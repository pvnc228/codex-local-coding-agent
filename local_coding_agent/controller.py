"""Bounded tool loop between a task envelope and an Ollama-compatible model."""

from __future__ import annotations

import json
from threading import Event
from typing import Any, Protocol

from .repository_tools import BoundedRepositoryTools, ToolPolicyError
from .task import TaskEnvelope
from .validators import validate_candidate


SYSTEM_CONTRACT = """Ты локальный coding-subagent для одной атомарной задачи.
Работай только в пределах task envelope.
Не выдумывай отсутствующий контекст.
Не утверждай, что запускал тесты или менял файлы без результата инструмента.
Используй только предоставленные инструменты.
Для файлов используй только относительные пути из task allowlist; абсолютные пути и '..' запрещены.
Если данных не хватает, задай один точный вопрос.
Патч должен быть минимальным и затрагивать только разрешённые файлы.
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
            "description": "Return a unified diff proposal without writing files.",
            "parameters": {
                "type": "object",
                "properties": {"patch": {"type": "string"}},
                "required": ["patch"],
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

    def run(self, task: TaskEnvelope, *, cancel_event: Event | None = None) -> dict[str, Any]:
        audit: list[dict[str, Any]] = [{"event": "task_received", "task_id": task.id}]
        try:
            messages = self._initial_messages(task)
        except ValueError as error:
            return self._failure("needs_context", "context_limit", str(error), audit)

        tools = BoundedRepositoryTools(
            self.workspace_root,
            task,
            max_tool_result_bytes=self.max_tool_result_bytes,
            max_files=self.max_files,
            max_patch_bytes=self.max_patch_bytes,
            max_patch_files=self.max_patch_files,
        )
        seen_calls: dict[str, int] = {}
        observed_checks: dict[str, dict[str, Any]] = {}
        retries = 0
        active_cancel = cancel_event or self.cancel_event

        for turn in range(1, self.max_turns + 1):
            if active_cancel is not None and active_cancel.is_set():
                return self._failure("failed", "cancelled", "task was cancelled", audit)
            audit.append({"event": "model_request", "turn": turn, "message_count": len(messages)})
            try:
                response = self.model.chat(messages, tools=TOOL_DEFINITIONS)
            except Exception as error:  # model boundary: normalize executor failures
                return self._failure("failed", "model_error", str(error), audit)
            audit.append({"event": "model_response", "turn": turn})
            message = response.get("message") if isinstance(response, dict) else None
            if not isinstance(message, dict):
                if retries < self.max_retries:
                    retries += 1
                    messages.append({"role": "user", "content": "Верни только объект JSON результата задачи."})
                    audit.append({"event": "retry", "reason": "invalid_response"})
                    continue
                return self._failure("failed", "invalid_response", "model response has no message object", audit)

            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append(message)
                for call in tool_calls:
                    try:
                        name, arguments, call_id = self._decode_tool_call(call)
                        signature = json.dumps(
                            {"name": name, "arguments": arguments},
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
                continue

            content = message.get("content")
            try:
                result = self._parse_final_result(content)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                if retries < self.max_retries:
                    retries += 1
                    messages.append(message)
                    messages.append({"role": "user", "content": "Предыдущий ответ невалиден. Верни только JSON-объект без markdown."})
                    audit.append({"event": "retry", "reason": "invalid_json"})
                    continue
                return self._failure("failed", "invalid_json", str(error), audit)
            result = dict(result)
            report = validate_candidate(
                result,
                task,
                max_patch_bytes=self.max_patch_bytes,
                max_patch_files=self.max_patch_files,
                observed_checks=observed_checks,
            )
            result["validation"] = {
                "valid": report.valid,
                "changed_files": list(report.changed_files),
                "issues": list(report.issues),
            }
            result["status"] = "accepted" if report.valid else "rejected"
            if not report.valid:
                risks = result.get("risks")
                if not isinstance(risks, list):
                    risks = []
                    result["risks"] = risks
                risks.append(
                    {"kind": "validation", "message": "; ".join(report.issues)}
                )
            audit.append({"event": "candidate_validated", "valid": report.valid})
            result.setdefault("audit", audit)
            return result

        return self._failure("failed", "max_turns", f"max_turns={self.max_turns} exceeded", audit)

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
