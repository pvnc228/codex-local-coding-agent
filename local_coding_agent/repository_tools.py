"""Policy-bound repository operations exposed to a local model."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .task import TaskEnvelope
from .validators import check_patch_applies, parse_unified_diff


class ToolPolicyError(RuntimeError):
    """A tool call rejected by the repository policy."""


class BoundedRepositoryTools:
    def __init__(
        self,
        workspace_root: str | Path,
        task: TaskEnvelope,
        *,
        max_tool_result_bytes: int = 32_000,
        max_files: int = 5,
        max_matches: int = 100,
        max_patch_bytes: int = 32_000,
        max_patch_files: int = 2,
        test_timeout_seconds: float = 60,
    ) -> None:
        if max_tool_result_bytes <= 0:
            raise ValueError("max_tool_result_bytes must be positive")
        if (
            max_files <= 0
            or max_matches <= 0
            or max_patch_bytes <= 0
            or max_patch_files <= 0
            or test_timeout_seconds <= 0
        ):
            raise ValueError("all repository tool limits must be positive")
        self.workspace_root = Path(workspace_root).resolve()
        self.task = task
        self.max_tool_result_bytes = max_tool_result_bytes
        self.max_files = max_files
        self.max_matches = max_matches
        self.max_patch_bytes = max_patch_bytes
        self.max_patch_files = max_patch_files
        self.test_timeout_seconds = test_timeout_seconds
        self._allowlist = {self._normalize_declared_path(path) for path in task.files}
        if len(self._allowlist) > max_files:
            raise ToolPolicyError(f"task exceeds max_files={max_files}")
        self._audit_events: list[dict[str, Any]] = []

    @property
    def audit_events(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(event) for event in self._audit_events)

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in {"list_files", "read_file", "search_text", "propose_patch", "run_tests"}:
            self._record(name, arguments, False, "unknown tool")
            raise ToolPolicyError(f"unknown tool: {name}")
        try:
            if name == "list_files":
                result = self._list_files(arguments)
            elif name == "read_file":
                result = self._read_file(arguments)
            elif name == "propose_patch":
                result = self._propose_patch(arguments)
            elif name == "run_tests":
                result = self._run_tests(arguments)
            else:
                result = self._search_text(arguments)
        except ToolPolicyError as error:
            self._record(name, arguments, False, str(error))
            raise
        self._record(name, arguments, True, None)
        return result

    def _run_tests(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolPolicyError("command must be a non-empty string")
        if command not in self.task.checks:
            raise ToolPolicyError("command is not allowlisted")
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace_root,
                shell=True,
                capture_output=True,
                timeout=self.test_timeout_seconds,
                check=False,
                close_fds=True,
                env=self._isolated_environment(),
                **self._process_group_options(),
            )
            result = {
                "command": command,
                "passed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout.decode("utf-8", errors="replace"),
                "stderr": completed.stderr.decode("utf-8", errors="replace"),
                "truncated": False,
                "isolated": True,
            }
        except subprocess.TimeoutExpired as error:
            result = {
                "command": command,
                "passed": False,
                "exit_code": None,
                "stdout": self._decode_process_output(error.output),
                "stderr": self._decode_process_output(error.stderr),
                "truncated": False,
                "timeout": True,
                "isolated": True,
            }
        result = self._bounded_process_result(result)
        result["evidence"] = self._process_evidence(result)
        if self._result_size(result) > self.max_tool_result_bytes and result.get("isolated") is True:
            result.pop("isolated")
        while self._result_size(result) > self.max_tool_result_bytes and (
            result.get("stdout") or result.get("stderr")
        ):
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            if len(stdout) >= len(stderr) and stdout:
                result["stdout"] = stdout[:-1]
            elif stderr:
                result["stderr"] = stderr[:-1]
            result["truncated"] = True
            result["evidence"] = self._process_evidence(result)
        if self._result_size(result) > self.max_tool_result_bytes:
            raise ToolPolicyError("max_tool_result_bytes is too small for run_tests evidence")
        return result

    @staticmethod
    def _isolated_environment() -> dict[str, str]:
        allowed = {
            "COMSPEC",
            "LANG",
            "LC_ALL",
            "PATH",
            "PATHEXT",
            "PYTHONIOENCODING",
            "PYTHONUTF8",
            "SystemRoot",
            "TEMP",
            "TMP",
            "TMPDIR",
            "WINDIR",
        }
        return {key: value for key, value in os.environ.items() if key in allowed}

    @staticmethod
    def _process_group_options() -> dict[str, Any]:
        if os.name == "nt":
            return {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            }
        return {"start_new_session": True}

    def _bounded_process_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if self._result_size(result) <= self.max_tool_result_bytes:
            return result
        # Keep the externally useful process evidence available even for very
        # small result caps.  Isolation is a provenance flag, not test output,
        # so it is the first optional field we may omit when metadata itself
        # would otherwise exceed the configured limit.
        if result.get("isolated") is True:
            result = {key: value for key, value in result.items() if key != "isolated"}
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        while self._result_size(result) > self.max_tool_result_bytes and (stdout or stderr):
            if len(stdout) >= len(stderr) and stdout:
                stdout = stdout[:-1]
            elif stderr:
                stderr = stderr[:-1]
        result = {**result, "stdout": stdout, "stderr": stderr, "truncated": True}
        if self._result_size(result) > self.max_tool_result_bytes:
            raise ToolPolicyError("max_tool_result_bytes is too small for run_tests metadata")
        return result

    @staticmethod
    def _decode_process_output(output: bytes | str | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return output

    @staticmethod
    def _process_evidence(result: dict[str, Any]) -> str:
        return (
            f"exit_code={result['exit_code']}; passed={result['passed']}; "
            f"stdout_bytes={len(result.get('stdout', '').encode('utf-8'))}; "
            f"stderr_bytes={len(result.get('stderr', '').encode('utf-8'))}; "
            f"truncated={result.get('truncated', False)}"
        )

    def _propose_patch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        patch = arguments.get("patch")
        if not isinstance(patch, str) or not patch.strip():
            raise ToolPolicyError("patch must be a non-empty string")
        if len(patch.encode("utf-8")) > self.max_patch_bytes:
            raise ToolPolicyError(f"patch exceeds max_patch_bytes={self.max_patch_bytes}")
        _, diff_issues = parse_unified_diff(patch)
        if diff_issues:
            raise ToolPolicyError("; ".join(diff_issues))

        paths: list[str] = []
        has_hunk = False
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
                if not match:
                    raise ToolPolicyError("patch has invalid diff header")
                for raw_path in match.groups():
                    normalized = self._patch_path(raw_path, prefix=None)
                    if normalized is not None and normalized not in paths:
                        paths.append(normalized)
            elif line.startswith("--- ") or line.startswith("+++ "):
                raw_path = line[4:].split("\t", 1)[0].strip()
                normalized = self._patch_path(raw_path, prefix=None)
                if normalized is not None and normalized not in paths:
                    paths.append(normalized)
            elif line.startswith("@@ "):
                has_hunk = True
        if not paths or not has_hunk:
            raise ToolPolicyError("patch is not a unified diff")
        if len(paths) > self.max_patch_files:
            raise ToolPolicyError(f"patch exceeds max_patch_files={self.max_patch_files}")
        applies, detail = check_patch_applies(self.workspace_root, patch)
        if not applies:
            raise ToolPolicyError(f"patch does not apply cleanly: {detail}")
        return {"patch": patch, "files": sorted(paths)}

    def _patch_path(self, raw_path: str, *, prefix: str | None) -> str | None:
        del prefix
        if raw_path == "/dev/null":
            return None
        candidate = raw_path[2:] if raw_path[:2] in {"a/", "b/"} else raw_path
        _, relative = self._resolve_allowlisted(candidate)
        return relative

    def _list_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = arguments.get("path", ".")
        directory, relative_root = self._resolve_workspace_path(raw_path)
        if not directory.is_dir():
            raise ToolPolicyError(f"directory does not exist: {relative_root}")
        ignored_parts = {".git", "__pycache__", ".venv", "venv", "node_modules"}
        files = sorted(
            path.relative_to(self.workspace_root).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and not ignored_parts.intersection(path.relative_to(self.workspace_root).parts)
        )
        truncated = len(files) > self.max_files
        result = {"files": files[: self.max_files], "truncated": truncated}
        if self._result_size(result) <= self.max_tool_result_bytes:
            return result
        bounded = list(result["files"])
        while bounded and self._result_size({"files": bounded, "truncated": True}) > self.max_tool_result_bytes:
            bounded.pop()
        result = {"files": bounded, "truncated": True}
        if self._result_size(result) > self.max_tool_result_bytes:
            raise ToolPolicyError("max_tool_result_bytes is too small for list_files metadata")
        return result

    def _search_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise ToolPolicyError("query must be a non-empty string")
        if len(query) > 256:
            raise ToolPolicyError("query exceeds 256 characters")
        raw_paths = arguments.get("paths", self.task.files)
        if isinstance(raw_paths, str) or not isinstance(raw_paths, (list, tuple)):
            raise ToolPolicyError("paths must be a list of strings")
        if not raw_paths or len(raw_paths) > self.max_files:
            raise ToolPolicyError(f"paths must contain 1..{self.max_files} files")

        matches: list[dict[str, Any]] = []
        for raw_path in raw_paths:
            path, relative = self._resolve_allowlisted(raw_path)
            if not path.is_file():
                raise ToolPolicyError(f"file does not exist: {relative}")
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ToolPolicyError(f"file is not UTF-8 text: {relative}") from error
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query in line:
                    matches.append({"path": relative, "line": line_number, "text": line})
                    if len(matches) >= self.max_matches:
                        return self._bounded_matches(matches, truncated=True)
        return self._bounded_matches(matches, truncated=False)

    def _bounded_matches(self, matches: list[dict[str, Any]], *, truncated: bool) -> dict[str, Any]:
        result = {"matches": matches, "truncated": truncated}
        if self._result_size(result) <= self.max_tool_result_bytes:
            return result
        bounded = list(matches)
        while bounded and self._result_size({"matches": bounded, "truncated": True}) > self.max_tool_result_bytes:
            bounded.pop()
        result = {"matches": bounded, "truncated": True}
        if self._result_size(result) > self.max_tool_result_bytes:
            raise ToolPolicyError("max_tool_result_bytes is too small for search_text metadata")
        return result

    def _read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = arguments.get("path")
        path, relative = self._resolve_allowlisted(raw_path)
        if not path.is_file():
            raise ToolPolicyError(f"file does not exist: {relative}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ToolPolicyError(f"file is not UTF-8 text: {relative}") from error
        result = {"path": relative, "content": content, "truncated": False}
        if self._result_size(result) <= self.max_tool_result_bytes:
            return result
        low = 0
        high = len(content)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = {"path": relative, "content": content[:middle], "truncated": True}
            if self._result_size(candidate) <= self.max_tool_result_bytes:
                best = candidate["content"]
                low = middle + 1
            else:
                high = middle - 1
        bounded = {"path": relative, "content": best, "truncated": True}
        if self._result_size(bounded) > self.max_tool_result_bytes:
            raise ToolPolicyError("max_tool_result_bytes is too small for read_file metadata")
        return bounded

    @staticmethod
    def _result_size(result: dict[str, Any]) -> int:
        return len(json.dumps(result, ensure_ascii=False).encode("utf-8"))

    def _resolve_allowlisted(self, raw_path: Any) -> tuple[Path, str]:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolPolicyError("path must be a non-empty string")
        candidate_input = Path(raw_path)
        if candidate_input.is_absolute() or candidate_input.drive or candidate_input.root or "\x00" in raw_path:
            raise ToolPolicyError("absolute or invalid path is not allowed")
        candidate = (self.workspace_root / candidate_input).resolve()
        try:
            relative = candidate.relative_to(self.workspace_root).as_posix()
        except ValueError as error:
            raise ToolPolicyError("path escapes workspace") from error
        if relative.casefold() not in self._allowlist:
            raise ToolPolicyError(f"path is outside task allowlist: {relative}")
        return candidate, relative

    def _resolve_workspace_path(self, raw_path: Any) -> tuple[Path, str]:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolPolicyError("path must be a non-empty string")
        candidate_input = Path(raw_path)
        if candidate_input.is_absolute() or candidate_input.drive or candidate_input.root or "\x00" in raw_path:
            raise ToolPolicyError("absolute or invalid path is not allowed")
        candidate = (self.workspace_root / candidate_input).resolve()
        try:
            relative = candidate.relative_to(self.workspace_root).as_posix()
        except ValueError as error:
            raise ToolPolicyError("path escapes workspace") from error
        return candidate, relative or "."

    @staticmethod
    def _normalize_declared_path(raw_path: str) -> str:
        candidate = Path(raw_path)
        if candidate.is_absolute() or candidate.drive or candidate.root or "\x00" in raw_path:
            raise ValueError(f"task file must be a relative valid path: {raw_path!r}")
        return candidate.as_posix().casefold()

    def _record(
        self,
        name: str,
        arguments: dict[str, Any],
        success: bool,
        error: str | None,
    ) -> None:
        event: dict[str, Any] = {
            "event": "tool_call",
            "name": name,
            "arguments": dict(arguments),
            "success": success,
        }
        if error is not None:
            event["error"] = error
        self._audit_events.append(event)
