"""Bounded tool loop between a task envelope and an Ollama-compatible model."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from typing import Any, Protocol

from .repository_tools import BoundedRepositoryTools, ToolCancelled, ToolPolicyError
from .task import TaskEnvelope
from .validators import apply_patch, validate_candidate


SYSTEM_CONTRACT = """Ты локальный coding-subagent для одной атомарной задачи.
Работай только в пределах task envelope.
Не выдумывай отсутствующий контекст.
Не утверждай, что запускал тесты или менял файлы без результата инструмента.
Используй только предоставленные инструменты.
Для файлов используй только относительные пути из task allowlist; абсолютные пути и '..' запрещены.
Если данных не хватает, задай один точный вопрос.
Патч должен быть минимальным и затрагивать только разрешённые файлы.
Для propose_patch предпочтителен формат SEARCH/REPLACE: список edits, каждый с полями file, search (точная копия текущего кода) и replace (новый код); номера строк не нужны. Либо верните полный unified diff с реальными переводами строк и корректными hunk headers. Применимость и структура diff проверяются controller-owned validator и git; не используй placeholders, абсолютные пути или literal \\n в качестве перевода строки.
После завершения верни только структурированный JSON-результат."""


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List bounded files below a workspace-relative directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one UTF-8 file from the task allowlist.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text in bounded allowlisted files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_patch",
            "description": (
                "Return a complete change proposal without writing files. "
                "Prefer SEARCH/REPLACE: provide a list of edits, each copying the "
                "current code exactly (search) and the new code (replace); no line "
                "numbers needed. Alternatively provide one complete unified diff "
                "with diff --git, ---, +++ and valid hunk headers. Use real newlines "
                "and relative allowlisted paths. Applicability is checked by the "
                "controller-owned validator and git."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string"},
                                "search": {"type": "string"},
                                "replace": {"type": "string"},
                            },
                            "required": ["file", "search", "replace"],
                        },
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run exactly one command from the task checks allowlist.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]


class ModelClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]]) -> dict[str, Any]: ...


class Controller:
    def __init__(
        self,
        model: ModelClient,
        workspace_root: str,
        *,
        max_turns: int = 4,
        max_same_call: int = 1,
        max_tool_result_bytes: int = 32_000,
        max_files: int = 5,
        max_patch_bytes: int = 32_000,
        max_patch_files: int = 2,
        max_context_bytes: int = 32_000,
        max_retries: int = 1,
        cancel_event: Event | None = None,
    ) -> None:
        if max_turns <= 0 or max_same_call <= 0 or max_retries < 0:
            raise ValueError("controller limits are invalid")
        if max_retries > 10:
            raise ValueError("max_retries exceeds hard cap of 10")
        self.model = model
        self.workspace_root = workspace_root
        self.max_turns = max_turns
        self.max_same_call = max_same_call
        self.max_tool_result_bytes = max_tool_result_bytes
        self.max_files = max_files
        self.max_patch_bytes = max_patch_bytes
        self.max_patch_files = max_patch_files
        self.max_context_bytes = max_context_bytes
        self.max_retries = max_retries
        self.cancel_event = cancel_event

    def run(
        self,
        task: TaskEnvelope,
        *,
        cancel_event: Event | None = None,
        completion_event: Event | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        audit: list[dict[str, Any]] = [{"event": "task_received", "task_id": task.id}]
        try:
            messages = self._initial_messages(task)
        except ValueError as error:
            if completion_event is not None:
                completion_event.set()
            return self._failure("needs_context", "context_limit", str(error), audit)

        executor: ThreadPoolExecutor | None = None
        try:
            active_cancel = cancel_event or self.cancel_event
            tools = BoundedRepositoryTools(
                self.workspace_root,
                task,
                max_tool_result_bytes=self.max_tool_result_bytes,
                max_files=self.max_files,
                max_patch_bytes=self.max_patch_bytes,
                max_patch_files=self.max_patch_files,
                cancel_event=active_cancel,
            )
            seen_calls: dict[str, int] = {}
            observed_checks: dict[str, dict[str, Any]] = {}
            attempts: list[dict[str, Any]] = []
            viewed_files: set[str] = set()
            last_patch: list[str] = []
            retries = 0
            executor = ThreadPoolExecutor(max_workers=1)
            return self._run_turns(
                task,
                messages,
                tools,
                active_cancel,
                seen_calls,
                observed_checks,
                attempts,
                viewed_files,
                last_patch,
                retries,
                executor,
                audit,
                apply=apply,
            )
        finally:
            if executor is None:
                if completion_event is not None:
                    completion_event.set()
            else:
                executor.shutdown(wait=False, cancel_futures=True)
                if completion_event is not None:
                    Thread(
                        target=self._wait_for_executor,
                        args=(executor, completion_event),
                        daemon=True,
                    ).start()

    @staticmethod
    def _wait_for_executor(executor: ThreadPoolExecutor, completion_event: Event) -> None:
        try:
            executor.shutdown(wait=True)
        finally:
            completion_event.set()

    def _run_turns(
        self,
        task: TaskEnvelope,
        messages: list[dict[str, Any]],
        tools: BoundedRepositoryTools,
        active_cancel: Event | None,
        seen_calls: dict[str, int],
        observed_checks: dict[str, dict[str, Any]],
        attempts: list[dict[str, Any]],
        viewed_files: set[str],
        last_patch: list[str],
        retries: int,
        executor: ThreadPoolExecutor,
        audit: list[dict[str, Any]],
        *,
        apply: bool = False,
    ) -> dict[str, Any]:
        for turn in range(1, self.max_turns + 1):
            if active_cancel is not None and active_cancel.is_set():
                return self._failure("failed", "cancelled", "task was cancelled", audit)
            if self._messages_size(messages) > self.max_context_bytes:
                return self._failure(
                    "failed",
                    "context_limit",
                    f"cumulative context exceeds max_context_bytes={self.max_context_bytes}",
                    audit,
                )
            audit.append({"event": "model_request", "turn": turn, "message_count": len(messages)})
            try:
                future = executor.submit(
                    self.model.chat, messages, tools=self._tools_for_task(task)
                )
                while True:
                    try:
                        response = future.result(timeout=0.05)
                        break
                    except TimeoutError:
                        if active_cancel is not None and active_cancel.is_set():
                            # ponytail: the abandoned chat thread keeps running
                            # until its own ~30s HTTP timeout.
                            return self._failure("failed", "cancelled", "task was cancelled", audit)
            except Exception as error:  # model boundary: normalize executor failures
                return self._failure("failed", "model_error", str(error), audit)
            audit.append({"event": "model_response", "turn": turn})
            message = response.get("message") if isinstance(response, dict) else None
            if not isinstance(message, dict):
                if retries < self.max_retries:
                    retries += 1
                    attempts.append({"attempt": retries, "reason": "invalid_response"})
                    messages.append({"role": "user", "content": "Верни только объект JSON результата задачи."})
                    audit.append({"event": "retry", "reason": "invalid_response"})
                    continue
                attempts.append({"attempt": retries + 1, "reason": "invalid_response"})
                return self._escalation(
                    task,
                    reason="invalid_response",
                    attempts=attempts,
                    viewed_files=viewed_files,
                    last_patch=last_patch,
                    observed_checks=observed_checks,
                    audit=audit,
                )

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                compatible_call = self._decode_content_tool_call(message.get("content"))
                if compatible_call is not None:
                    message = dict(message)
                    message["tool_calls"] = [compatible_call]
                    message["content"] = ""
                    tool_calls = message["tool_calls"]
                    audit.append({"event": "content_tool_call_compatibility", "turn": turn})
            if tool_calls:
                messages.append(message)
                for call in tool_calls:
                    try:
                        name, arguments, call_id = self._decode_tool_call(call)
                        signature_arguments = arguments
                        if name == "list_files" and "path" not in signature_arguments:
                            signature_arguments = {**arguments, "path": "."}
                        signature = json.dumps(
                            {"name": name, "arguments": signature_arguments},
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        seen_calls[signature] = seen_calls.get(signature, 0) + 1
                        if seen_calls[signature] > self.max_same_call:
                            return self._failure(
                                "failed",
                                "duplicate_tool_call",
                                f"repeated tool call: {name}",
                                audit,
                            )
                        audit.append({"event": "tool_call", "name": name, "arguments": arguments, "turn": turn})
                        result = tools.execute(name, arguments)
                        if name == "read_file":
                            path = arguments.get("path")
                            if isinstance(path, str):
                                viewed_files.add(path)
                        elif name == "search_text":
                            for path in (arguments.get("paths") or list(task.files)):
                                if isinstance(path, str):
                                    viewed_files.add(path)
                        elif name == "list_files":
                            for path in result.get("files", []):
                                if isinstance(path, str):
                                    viewed_files.add(path)
                        elif name == "propose_patch":
                            patch = result.get("patch")
                            if isinstance(patch, str):
                                last_patch[:] = [patch]
                        if name == "run_tests":
                            observed_checks[arguments["command"]] = {
                                "passed": result["passed"],
                                "evidence": result["evidence"],
                            }
                        tool_message: dict[str, Any] = {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                        if call_id is not None:
                            tool_message["tool_call_id"] = call_id
                        messages.append(tool_message)
                        audit.append({"event": "tool_result", "name": name, "turn": turn})
                    except (ToolPolicyError, ValueError, TypeError, json.JSONDecodeError) as error:
                        return self._failure("failed", "policy", str(error), audit)
                    except ToolCancelled:
                        return self._failure("failed", "cancelled", "task was cancelled", audit)
                continue

            content = message.get("content")
            try:
                result = self._parse_final_result(content)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                if retries < self.max_retries:
                    retries += 1
                    attempts.append({"attempt": retries, "reason": "invalid_json"})
                    messages.append(message)
                    messages.append({"role": "user", "content": "Предыдущий ответ невалиден. Верни только JSON-объект без markdown."})
                    audit.append({"event": "retry", "reason": "invalid_json"})
                    continue
                attempts.append({"attempt": retries + 1, "reason": "invalid_json"})
                return self._escalation(
                    task,
                    reason="invalid_json",
                    attempts=attempts,
                    viewed_files=viewed_files,
                    last_patch=last_patch,
                    observed_checks=observed_checks,
                    audit=audit,
                )
            result = dict(result)
            for controller_field in (
                "audit",
                "applied",
                "error",
                "post_apply_checks",
                "validation",
            ):
                result.pop(controller_field, None)
            report = validate_candidate(
                result,
                task,
                max_patch_bytes=self.max_patch_bytes,
                max_patch_files=self.max_patch_files,
                observed_checks=observed_checks,
                workspace_root=self.workspace_root,
            )
            result["validation"] = {
                "valid": report.valid,
                "changed_files": list(report.changed_files),
                "issues": list(report.issues),
            }
            if report.resolved_patch:
                result["patch"] = report.resolved_patch
                result.pop("edits", None)
            result["status"] = "accepted" if report.valid else "rejected"
            audit.append({"event": "candidate_validated", "valid": report.valid})
            if report.valid and apply:
                patch = report.resolved_patch or result.get("patch")
                if not isinstance(patch, str) or not patch.strip():
                    audit.append({"event": "apply_skipped", "reason": "candidate has no patch"})
                else:
                    applied, apply_detail = apply_patch(self.workspace_root, patch)
                    if not applied:
                        result["status"] = "rejected"
                        self._add_risk(
                            result,
                            "apply_failed",
                            f"patch could not be applied: {apply_detail}",
                        )
                        audit.append({"event": "apply_failed", "detail": apply_detail})
                    else:
                        audit.append({"event": "patch_applied"})
                        try:
                            post_checks, post_checks_passed = self._run_post_apply_checks(
                                task, tools, active_cancel, audit
                            )
                        except ToolCancelled:
                            rollback_ok, rollback_detail = apply_patch(
                                self.workspace_root, patch, reverse=True
                            )
                            result["status"] = "failed"
                            self._add_risk(result, "cancelled", "post-apply checks were cancelled")
                            audit.append({"event": "post_apply_cancelled"})
                            if rollback_ok:
                                audit.append({"event": "patch_rolled_back"})
                            else:
                                self._add_risk(
                                    result,
                                    "rollback_failed",
                                    f"patch rollback failed: {rollback_detail}",
                                )
                                audit.append(
                                    {"event": "rollback_failed", "detail": rollback_detail}
                                )
                        except ToolPolicyError as error:
                            rollback_ok, rollback_detail = apply_patch(
                                self.workspace_root, patch, reverse=True
                            )
                            result["status"] = "rejected"
                            self._add_risk(
                                result,
                                "post_apply_check_failed",
                                f"post-apply check could not complete: {error}",
                            )
                            audit.append({"event": "post_apply_check_error", "detail": str(error)})
                            if rollback_ok:
                                audit.append({"event": "patch_rolled_back"})
                            else:
                                self._add_risk(
                                    result,
                                    "rollback_failed",
                                    f"patch rollback failed: {rollback_detail}",
                                )
                                audit.append(
                                    {"event": "rollback_failed", "detail": rollback_detail}
                                )
                        else:
                            result["post_apply_checks"] = post_checks
                            if post_checks_passed:
                                result["checks"] = post_checks
                                result["applied"] = True
                                audit.append({"event": "post_apply_checks_passed"})
                            else:
                                rollback_ok, rollback_detail = apply_patch(
                                    self.workspace_root, patch, reverse=True
                                )
                                result["status"] = "rejected"
                                self._add_risk(
                                    result,
                                    "post_apply_check_failed",
                                    "a targeted check failed after applying the patch",
                                )
                                if rollback_ok:
                                    audit.append({"event": "patch_rolled_back"})
                                else:
                                    self._add_risk(
                                        result,
                                        "rollback_failed",
                                        f"patch rollback failed: {rollback_detail}",
                                    )
                                    audit.append(
                                        {"event": "rollback_failed", "detail": rollback_detail}
                                    )
            elif apply:
                audit.append({"event": "apply_skipped", "reason": "candidate rejected"})
            if not report.valid:
                self._add_risk(result, "validation", "; ".join(report.issues))
            result["audit"] = audit
            return result

        if attempts:
            return self._escalation(
                task,
                reason="max_turns",
                attempts=attempts,
                viewed_files=viewed_files,
                last_patch=last_patch,
                observed_checks=observed_checks,
                audit=audit,
            )
        return self._failure("failed", "max_turns", f"max_turns={self.max_turns} exceeded", audit)

    def _run_post_apply_checks(
        self,
        task: TaskEnvelope,
        tools: BoundedRepositoryTools,
        active_cancel: Event | None,
        audit: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        checks: list[dict[str, Any]] = []
        for command in task.checks:
            if active_cancel is not None and active_cancel.is_set():
                raise ToolCancelled("task was cancelled")
            check = tools.execute("run_tests", {"command": command})
            observed = {
                "command": command,
                "passed": check["passed"],
                "evidence": check["evidence"],
            }
            checks.append(observed)
            audit.append(
                {
                    "event": "post_apply_check",
                    "command": command,
                    "passed": check["passed"],
                }
            )
        return checks, all(check["passed"] for check in checks)

    @staticmethod
    def _add_risk(result: dict[str, Any], kind: str, message: str) -> None:
        risks = result.get("risks")
        if not isinstance(risks, list):
            risks = []
            result["risks"] = risks
        risks.append({"kind": kind, "message": message})

    def _messages_size(self, messages) -> int:
        return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))

    def _initial_messages(self, task: TaskEnvelope) -> list[dict[str, Any]]:
        payload = {
            "id": task.id,
            "goal": task.goal,
            "files": list(task.files),
            "context": task.context,
            "constraints": list(task.constraints),
            "checks": list(task.checks),
            "acceptance": list(task.acceptance),
            "limits": {
                "max_turns": self.max_turns,
                "max_same_call": self.max_same_call,
                "max_tool_result_bytes": self.max_tool_result_bytes,
                "max_files": self.max_files,
                "max_patch_files": self.max_patch_files,
            },
        }
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(content.encode("utf-8")) > self.max_context_bytes:
            raise ValueError(f"task context exceeds max_context_bytes={self.max_context_bytes}")
        return [
            {"role": "system", "content": SYSTEM_CONTRACT},
            {"role": "user", "content": content},
        ]

    @staticmethod
    def _decode_tool_call(call: Any) -> tuple[str, dict[str, Any], str | None]:
        if not isinstance(call, dict):
            raise ValueError("tool call must be an object")
        function = call.get("function")
        if not isinstance(function, dict):
            raise ValueError("tool call has no function object")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tool call has no function name")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        call_id = call.get("id")
        if call_id is not None and not isinstance(call_id, str):
            raise ValueError("tool call id must be a string")
        return name, arguments, call_id

    @staticmethod
    def _decode_content_tool_call(content: Any) -> dict[str, Any] | None:
        if not isinstance(content, str) or not content.strip():
            return None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        name = payload.get("name")
        arguments = payload.get("arguments")
        if not isinstance(name, str) or not name or not isinstance(arguments, (dict, str)):
            return None
        return {"function": {"name": name, "arguments": arguments}}

    @staticmethod
    def _tools_for_task(task: TaskEnvelope) -> list[dict[str, Any]]:
        if task.checks:
            return TOOL_DEFINITIONS
        return [
            definition
            for definition in TOOL_DEFINITIONS
            if definition["function"]["name"] != "run_tests"
        ]

    @staticmethod
    def _parse_final_result(content: Any) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("final model response has no JSON content")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("final model response must be a JSON object")
        return result

    @staticmethod
    def _failure(status: str, kind: str, message: str, audit: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": status,
            "summary": message,
            "patch": "",
            "checks": [],
            "risks": [{"kind": kind, "message": message}],
            "error": {"kind": kind, "message": message},
            "audit": audit,
        }

    def _escalation(
        self,
        task: TaskEnvelope,
        *,
        reason: str,
        attempts: list[dict[str, Any]],
        viewed_files: set[str],
        last_patch: list[str],
        observed_checks: dict[str, dict[str, Any]],
        audit: list[dict[str, Any]],
    ) -> dict[str, Any]:
        audit.append({"event": "escalation", "reason": reason, "attempts": len(attempts)})
        return {
            "status": "failed",
            "summary": f"retry budget exhausted: {reason}",
            "patch": "",
            "checks": [],
            "risks": [],
            "error": {"kind": "retry_budget_exhausted", "message": reason},
            "escalation": {
                "reason": reason,
                "task": {
                    "id": task.id,
                    "goal": task.goal,
                    "files": list(task.files),
                    "context": task.context,
                    "constraints": list(task.constraints),
                    "checks": list(task.checks),
                    "acceptance": list(task.acceptance),
                },
                "attempts": list(attempts),
                "viewed_files": sorted(viewed_files),
                "last_patch": last_patch[0] if last_patch else "",
                "validation_issues": [],
                "external_evidence": dict(observed_checks),
                "risks": [],
            },
            "audit": audit,
        }
