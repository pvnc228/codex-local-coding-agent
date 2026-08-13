"""Independent validation of the model's structured candidate result."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .task import TaskEnvelope


def _fold_path(path: str) -> str:
    # ponytail: treat only Windows as case-insensitive; macOS default is
    # case-insensitive but this keeps the common Linux case strict.
    return path.casefold() if os.name == "nt" else path


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    changed_files: tuple[str, ...]
    issues: tuple[str, ...]


def _evidence_facts(evidence: str | None) -> dict[str, str | None]:
    """Extract security-relevant facts from an evidence string.

    The evidence is a `key=value; ` segment list produced by
    `_process_evidence` (e.g. `exit_code=0; passed=True; stdout_bytes=...`).
    Only `exit_code` and `passed` matter for anti-fabrication; the byte-count
    metadata may be rephrased by the model. Missing keys are parsed as None.

    Fallback: if neither side parses an `exit_code`, the comparison falls back
    to `passed` equality (already enforced separately as the core gate), so a
    model that rephrases evidence without structural values is not falsely
    rejected as long as `passed` matches.
    """

    facts: dict[str, str | None] = {"exit_code": None, "passed": None}
    if not evidence:
        return facts
    for segment in evidence.split(";"):
        if "=" not in segment:
            continue
        key, _, value = segment.partition("=")
        key = key.strip()
        value = value.strip()
        if key in facts and value:
            facts[key] = value
    return facts


def validate_candidate(
    candidate: Mapping[str, Any],
    task: TaskEnvelope,
    *,
    max_patch_bytes: int = 32_000,
    max_patch_files: int = 2,
    observed_checks: Mapping[str, Mapping[str, Any]] | None = None,
    workspace_root: str | Path | None = None,
) -> ValidationReport:
    issues: list[str] = []
    changed_files: tuple[str, ...] = ()
    if not isinstance(candidate, Mapping):
        return ValidationReport(False, (), ("candidate must be a JSON object",))

    if candidate.get("status") != "candidate":
        issues.append("status must be 'candidate'")
    if not isinstance(candidate.get("summary"), str) or not candidate["summary"].strip():
        issues.append("summary must be a non-empty string")
    patch = candidate.get("patch")
    if not isinstance(patch, str):
        issues.append("patch must be a string")
        patch = ""
    checks = candidate.get("checks")
    if not isinstance(checks, list):
        issues.append("checks must be a list")
        checks = []
    if not isinstance(candidate.get("risks"), list):
        issues.append("risks must be a list")

    if patch:
        if max_patch_bytes <= 0 or len(patch.encode("utf-8")) > max_patch_bytes:
            issues.append(f"patch exceeds max_patch_bytes={max_patch_bytes}")
        changed_files, diff_issues = parse_unified_diff(patch)
        issues.extend(diff_issues)
        if len(changed_files) > max_patch_files:
            issues.append(f"patch exceeds max_patch_files={max_patch_files}")
        allowed = {_normalize_task_path(path) for path in task.files}
        for path in changed_files:
            if _fold_path(path) not in allowed:
                issues.append(f"patch file is outside task allowlist: {path}")
        if workspace_root is not None and not issues:
            applies, detail = check_patch_applies(workspace_root, patch)
            if not applies:
                issues.append(f"patch does not apply cleanly: {detail}")

    expected_checks = set(task.checks)
    seen_checks: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping):
            issues.append("each check must be an object")
            continue
        command = check.get("command")
        if not isinstance(command, str) or not command:
            issues.append("check command must be a non-empty string")
            continue
        if command not in expected_checks:
            issues.append(f"check command is not allowlisted: {command}")
        if command in seen_checks:
            issues.append(f"duplicate check command: {command}")
        seen_checks.add(command)
        if not isinstance(check.get("passed"), bool):
            issues.append(f"check passed must be boolean: {command}")
        elif check["passed"] is False:
            issues.append(f"check failed: {command}")
        evidence = check.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            issues.append(f"check evidence is required: {command}")
        if observed_checks is None or command not in observed_checks:
            issues.append(f"check has no external runner evidence: {command}")
        else:
            observed = observed_checks[command]
            if check.get("passed") != observed.get("passed"):
                issues.append(f"check result disagrees with external runner: {command}")
            candidate_facts = _evidence_facts(check.get("evidence"))
            observed_facts = _evidence_facts(observed.get("evidence"))
            if (
                candidate_facts.get("exit_code") is not None
                and candidate_facts.get("exit_code") != observed_facts.get("exit_code")
            ):
                issues.append(f"check evidence disagrees with external runner: {command}")
            elif (
                candidate_facts.get("passed") is not None
                and candidate_facts.get("passed") != observed_facts.get("passed")
            ):
                issues.append(f"check evidence disagrees with external runner: {command}")

    missing_checks = expected_checks - seen_checks
    for command in sorted(missing_checks):
        issues.append(f"missing check evidence: {command}")
        if observed_checks is None or command not in observed_checks:
            issues.append(f"check has no external runner evidence: {command}")

    return ValidationReport(not issues, changed_files, tuple(issues))


def check_patch_applies(
    workspace_root: str | Path,
    patch: str,
    *,
    timeout_seconds: float = 10,
) -> tuple[bool, str]:
    """Check a patch with git without modifying the workspace."""

    return _run_git_apply(workspace_root, patch, check=True, timeout_seconds=timeout_seconds)


def apply_patch(
    workspace_root: str | Path,
    patch: str,
    *,
    timeout_seconds: float = 10,
    reverse: bool = False,
) -> tuple[bool, str]:
    """Apply an already-validated patch to the workspace.

    This is the controller-only mediated-apply seam. The local model never
    reaches it directly: it has no `apply_patch` tool, and the controller only
    calls this after `validate_candidate` has accepted the proposal.
    """

    return _run_git_apply(
        workspace_root,
        patch,
        check=False,
        reverse=reverse,
        timeout_seconds=timeout_seconds,
    )


def _run_git_apply(
    workspace_root: str | Path,
    patch: str,
    *,
    check: bool,
    reverse: bool = False,
    timeout_seconds: float,
) -> tuple[bool, str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    executable = shutil.which("git")
    if executable is None:
        return False, "git executable is unavailable"
    root = Path(workspace_root).resolve()
    if not root.is_dir():
        return False, f"workspace directory does not exist: {root}"
    command = [executable, "apply", "--whitespace=nowarn"]
    if check:
        command.append("--check")
    if reverse:
        command.append("--reverse")
    command.append("-")
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            input=patch.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"git apply{' check' if check else ''} failed: {error}"
    if completed.returncode == 0:
        return True, ""
    detail = completed.stderr.decode("utf-8", errors="replace").strip()
    return False, detail or f"git apply exited with code {completed.returncode}"


def parse_unified_diff(patch: str) -> tuple[tuple[str, ...], list[str]]:
    paths: list[str] = []
    issues: list[str] = []
    saw_old = False
    saw_new = False
    saw_hunk = False
    hunk: dict[str, int] | None = None

    def finish_hunk() -> None:
        nonlocal hunk
        if hunk is None:
            return
        # ponytail: hunk line-count mismatch is intentionally NOT flagged here.
        # git apply --check already rejects malformed hunks as "corrupt patch",
        # so a stricter parser-side count check is a duplicate gate that rejects
        # otherwise-valid patches (real models miscount hunk headers ~19%).
        hunk = None

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            finish_hunk()
            match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
            if not match:
                issues.append("patch has invalid diff header")
                continue
            for raw_path in match.groups():
                normalized, path_issue = _normalize_diff_path(raw_path)
                if path_issue:
                    issues.append(path_issue)
                elif normalized is not None and normalized not in paths:
                    paths.append(normalized)
        elif line.startswith("@@ "):
            finish_hunk()
            saw_hunk = True
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", line)
            if not match:
                issues.append("patch has invalid hunk header")
                continue
            hunk = {
                "old_expected": int(match.group(2) or "1"),
                "new_expected": int(match.group(4) or "1"),
                "old_seen": 0,
                "new_seen": 0,
            }
        elif hunk is not None:
            if line.startswith("\\"):
                continue
            if line.startswith(" "):
                hunk["old_seen"] += 1
                hunk["new_seen"] += 1
            elif line.startswith("-"):
                hunk["old_seen"] += 1
            elif line.startswith("+"):
                hunk["new_seen"] += 1
            else:
                issues.append("patch has invalid hunk line")
        elif line.startswith("--- "):
            saw_old = True
            normalized, path_issue = _normalize_diff_path(line[4:].split("\t", 1)[0].strip())
            if path_issue:
                issues.append(path_issue)
            elif normalized is not None and normalized not in paths:
                paths.append(normalized)
        elif line.startswith("+++ "):
            saw_new = True
            normalized, path_issue = _normalize_diff_path(line[4:].split("\t", 1)[0].strip())
            if path_issue:
                issues.append(path_issue)
            elif normalized is not None and normalized not in paths:
                paths.append(normalized)
    finish_hunk()
    if not paths or not saw_old or not saw_new or not saw_hunk:
        issues.append("patch is not a unified diff")
    return tuple(sorted(paths)), issues


def _normalize_diff_path(raw_path: str) -> tuple[str | None, str | None]:
    if raw_path == "/dev/null":
        return None, None
    path = raw_path[2:] if raw_path[:2] in {"a/", "b/"} else raw_path
    path = path.replace("\\", "/")
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return None, f"patch path is absolute or empty: {raw_path}"
    parts = [part for part in path.split("/") if part not in {"", "."}]
    if ".." in parts:
        return None, f"patch path escapes workspace: {raw_path}"
    return "/".join(parts), None


def _normalize_task_path(path: str) -> str:
    return _fold_path(path.replace("\\", "/").strip("/"))
