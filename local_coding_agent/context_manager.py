"""Harness State Machine and Context Manager (R14).

Provides deterministic state tracking and stateless context assembly for local models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .task import TaskEnvelope


@dataclass
class HarnessState:
    """Explicit state representation of a delegation session."""

    task: TaskEnvelope
    turn: int = 1
    observed_files: dict[str, str] = field(default_factory=dict)
    latest_tool_name: str | None = None
    latest_tool_arguments: dict[str, Any] | None = None
    latest_tool_result: dict[str, Any] | None = None
    latest_tool_call_id: str | None = None
    active_prescription: str | None = None
    last_patch: str | None = None
    observed_checks: dict[str, dict[str, Any]] = field(default_factory=dict)


class ContextAssembler:
    """Assembles a clean, stateless prompt context envelope from current HarnessState."""

    def assemble(
        self,
        state: HarnessState,
        system_contract: str,
        *,
        limits: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        task = state.task
        envelope_payload: dict[str, Any] = {
            "id": task.id,
            "goal": task.goal,
            "files": list(task.files),
            "context": task.context,
            "constraints": list(task.constraints),
            "checks": list(task.checks),
            "acceptance": list(task.acceptance),
        }
        if limits:
            envelope_payload["limits"] = limits

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_contract},
            {
                "role": "user",
                "content": json.dumps(envelope_payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]

        if state.latest_tool_name and state.latest_tool_result is not None:
            # Synthetic pairing compliant with OpenAI / Ollama tool calling
            tool_args = state.latest_tool_arguments or {}
            assistant_tool_call = {
                "id": state.latest_tool_call_id or "call_0",
                "type": "function",
                "function": {
                    "name": state.latest_tool_name,
                    "arguments": json.dumps(tool_args, ensure_ascii=False),
                },
            }
            tool_res_message: dict[str, Any] = {
                "role": "tool",
                "tool_name": state.latest_tool_name,
                "content": json.dumps(state.latest_tool_result, ensure_ascii=False),
            }
            if state.latest_tool_call_id:
                tool_res_message["tool_call_id"] = state.latest_tool_call_id

            messages.append({"role": "assistant", "tool_calls": [assistant_tool_call]})
            messages.append(tool_res_message)

        if state.active_prescription:
            messages.append({
                "role": "user",
                "content": json.dumps(
                    {
                        "error": "CANDIDATE_VALIDATION_FAILED",
                        "instruction": f"ОШИБКА ВАЛИДАЦИИ: {state.active_prescription} Исправь эти поля и верни скорректированный JSON-объект.",
                    },
                    ensure_ascii=False,
                ),
            })

        return messages


def _message_bytes(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))


def compact_tool_exchanges(
    messages: list[dict[str, Any]], max_bytes: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compacts message list by evicting older tool-call pairs while respecting max_bytes."""
    current = list(messages)
    dropped_all: list[dict[str, Any]] = []

    while _message_bytes(current) > max_bytes:
        # Find tool exchange blocks [start, end)
        blocks: list[tuple[int, int]] = []
        i = 2
        n = len(current)
        while i < n:
            msg = current[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                start = i
                j = i + 1
                while j < n and current[j].get("role") == "tool":
                    j += 1
                blocks.append((start, j))
                i = j
            else:
                i += 1

        if len(blocks) <= 1:
            break

        # Evict oldest block
        start, end = blocks[0]
        dropped = current[start:end]
        dropped_all.extend(dropped)
        del current[start:end]

    return current, dropped_all


def purge_diff_residues(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Purge raw invalid patch strings from previous assistant messages in the history."""
    purged: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
            try:
                data = json.loads(msg["content"])
                if isinstance(data, dict) and data.get("patch"):
                    data["patch"] = "<invalid_patch_omitted>"
                    msg_copy = dict(msg)
                    msg_copy["content"] = json.dumps(data, ensure_ascii=False)
                    purged.append(msg_copy)
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
        purged.append(msg)
    return purged
