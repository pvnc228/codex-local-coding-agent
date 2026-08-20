"""External agent hook bridges and protocol adapters (R30).

Provides lifecycle hook interception points (on_pre_tool_call, on_post_tool_call,
on_turn_start, on_turn_end, on_session_finish) and wire-protocol adapters compatible
with Codex and Claude Code hook standards.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


@dataclass
class HookDecision:
    """Consolidated outcome of hook execution at an interception point."""

    decision: str = "allow"  # "allow", "deny", "ask", "approve", "block"
    allowed: bool = True
    reason: str | None = None
    additional_context: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)
    system_messages: list[str] = field(default_factory=list)
    updated_input: dict[str, Any] | None = None
    stop: bool = False
    stop_reason: str | None = None
    raw_outputs: list[dict[str, Any]] = field(default_factory=list)

    def is_blocking(self) -> bool:
        """True if the hook explicitly denied or blocked the operation."""
        return not self.allowed or self.decision in ("deny", "block")


@dataclass
class _HookRegistration:
    hook_id: str
    point: str
    handler: Callable[..., Any]
    matcher: str | None
    priority: int = 0


class HookBridge:
    """Central registry and dispatcher for lifecycle hooks."""

    POINT_PRE_TOOL_CALL = "on_pre_tool_call"
    POINT_POST_TOOL_CALL = "on_post_tool_call"
    POINT_TURN_START = "on_turn_start"
    POINT_TURN_END = "on_turn_end"
    POINT_SESSION_FINISH = "on_session_finish"

    _POINT_ALIASES = {
        "PreToolUse": POINT_PRE_TOOL_CALL,
        "pre_tool_call": POINT_PRE_TOOL_CALL,
        "on_pre_tool_call": POINT_PRE_TOOL_CALL,
        "PostToolUse": POINT_POST_TOOL_CALL,
        "post_tool_call": POINT_POST_TOOL_CALL,
        "on_post_tool_call": POINT_POST_TOOL_CALL,
        "UserPromptSubmit": POINT_TURN_START,
        "turn_start": POINT_TURN_START,
        "on_turn_start": POINT_TURN_START,
        "TurnEnd": POINT_TURN_END,
        "turn_end": POINT_TURN_END,
        "on_turn_end": POINT_TURN_END,
        "SessionStart": "on_session_start",
        "session_start": "on_session_start",
        "on_session_start": "on_session_start",
        "Stop": POINT_SESSION_FINISH,
        "session_finish": POINT_SESSION_FINISH,
        "on_session_finish": POINT_SESSION_FINISH,
        "SubagentStart": "on_subagent_start",
        "SubagentStop": "on_subagent_stop",
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hooks: dict[str, list[_HookRegistration]] = {}

    def _normalize_point(self, point: str) -> str:
        return self._POINT_ALIASES.get(point, point)

    def register(
        self,
        point: str,
        handler: Callable[..., Any],
        *,
        matcher: str | None = None,
        priority: int = 0,
    ) -> str:
        """Register a hook handler for a lifecycle point."""
        norm_point = self._normalize_point(point)
        hook_id = f"hook-{uuid.uuid4().hex[:8]}"
        reg = _HookRegistration(
            hook_id=hook_id,
            point=norm_point,
            handler=handler,
            matcher=matcher,
            priority=priority,
        )
        with self._lock:
            if norm_point not in self._hooks:
                self._hooks[norm_point] = []
            self._hooks[norm_point].append(reg)
            self._hooks[norm_point].sort(key=lambda h: h.priority, reverse=True)
        return hook_id

    def unregister(self, hook_id: str) -> bool:
        """Unregister a hook handler by its ID."""
        with self._lock:
            for point, reg_list in self._hooks.items():
                for idx, reg in enumerate(reg_list):
                    if reg.hook_id == hook_id:
                        reg_list.pop(idx)
                        return True
        return False

    def on_pre_tool_call(self, matcher: str | None = None, priority: int = 0) -> Callable:
        """Decorator for registering pre-tool-call hooks."""
        def decorator(fn: Callable) -> Callable:
            self.register(self.POINT_PRE_TOOL_CALL, fn, matcher=matcher, priority=priority)
            return fn
        return decorator

    def on_post_tool_call(self, matcher: str | None = None, priority: int = 0) -> Callable:
        """Decorator for registering post-tool-call hooks."""
        def decorator(fn: Callable) -> Callable:
            self.register(self.POINT_POST_TOOL_CALL, fn, matcher=matcher, priority=priority)
            return fn
        return decorator

    def on_turn_start(self, matcher: str | None = None, priority: int = 0) -> Callable:
        """Decorator for registering turn-start hooks."""
        def decorator(fn: Callable) -> Callable:
            self.register(self.POINT_TURN_START, fn, matcher=matcher, priority=priority)
            return fn
        return decorator

    def on_turn_end(self, matcher: str | None = None, priority: int = 0) -> Callable:
        """Decorator for registering turn-end hooks."""
        def decorator(fn: Callable) -> Callable:
            self.register(self.POINT_TURN_END, fn, matcher=matcher, priority=priority)
            return fn
        return decorator

    def on_session_finish(self, priority: int = 0) -> Callable:
        """Decorator for registering session-finish hooks."""
        def decorator(fn: Callable) -> Callable:
            self.register(self.POINT_SESSION_FINISH, fn, priority=priority)
            return fn
        return decorator

    def _matches(self, pattern: str | None, query: str) -> bool:
        if pattern is None or pattern == "" or pattern == "*":
            return True
        try:
            return bool(re.search(pattern, query))
        except re.error:
            return pattern == query

    def trigger(
        self,
        point: str,
        match_target: str = "",
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> HookDecision:
        """Execute all matching hooks for a given point and combine decisions."""
        norm_point = self._normalize_point(point)
        with self._lock:
            candidates = list(self._hooks.get(norm_point, []))

        decision = HookDecision()
        merged_payload = dict(payload or {})
        merged_payload.update(kwargs)

        for reg in candidates:
            if not self._matches(reg.matcher, match_target):
                continue

            try:
                import inspect
                sig = inspect.signature(reg.handler)
                param_count = len([
                    p for p in sig.parameters.values()
                    if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                ])
                var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
                if var_pos or param_count >= 2:
                    out = reg.handler(match_target, merged_payload)
                elif param_count == 1:
                    out = reg.handler(merged_payload)
                else:
                    out = reg.handler()
            except Exception as exc:
                out = {"decision": "error", "reason": f"hook handler error: {exc}"}

            self._fold_outcome(decision, out)
            if decision.is_blocking():
                # Short-circuit on blocking decision
                break

        return decision

    def trigger_pre_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> HookDecision:
        """Convenience method for on_pre_tool_call point."""
        payload = {
            "tool_name": tool_name,
            "tool_input": arguments,
            "context": context or {},
        }
        return self.trigger(self.POINT_PRE_TOOL_CALL, match_target=tool_name, payload=payload)

    def trigger_post_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> HookDecision:
        """Convenience method for on_post_tool_call point."""
        payload = {
            "tool_name": tool_name,
            "tool_input": arguments,
            "tool_output": result,
            "context": context or {},
        }
        return self.trigger(self.POINT_POST_TOOL_CALL, match_target=tool_name, payload=payload)

    def trigger_turn_start(
        self,
        turn: int,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> HookDecision:
        """Convenience method for on_turn_start point."""
        payload = {
            "turn": turn,
            "turn_id": str(turn),
            "prompt": prompt,
            "context": context or {},
        }
        return self.trigger(self.POINT_TURN_START, match_target="", payload=payload)

    def trigger_turn_end(
        self,
        turn: int,
        response: Any,
        context: dict[str, Any] | None = None,
    ) -> HookDecision:
        """Convenience method for on_turn_end point."""
        payload = {
            "turn": turn,
            "turn_id": str(turn),
            "response": response,
            "context": context or {},
        }
        return self.trigger(self.POINT_TURN_END, match_target="", payload=payload)

    def trigger_session_finish(
        self,
        session_id: str,
        summary: str = "",
        status: str = "completed",
        context: dict[str, Any] | None = None,
    ) -> HookDecision:
        """Convenience method for on_session_finish point."""
        payload = {
            "session_id": session_id,
            "summary": summary,
            "status": status,
            "context": context or {},
        }
        return self.trigger(self.POINT_SESSION_FINISH, match_target="", payload=payload)

    def _fold_outcome(self, decision: HookDecision, outcome: Any) -> None:
        """Fold an individual hook outcome into the aggregate HookDecision."""
        if outcome is None:
            return

        if isinstance(outcome, HookDecision):
            raw = asdict(outcome) if hasattr(outcome, "__dataclass_fields__") else {}
            if outcome.is_blocking():
                decision.decision = outcome.decision
                decision.allowed = False
                decision.reason = outcome.reason or decision.reason
            if outcome.additional_context:
                decision.additional_context.extend(outcome.additional_context)
            if outcome.feedback:
                decision.feedback.extend(outcome.feedback)
            if outcome.system_messages:
                decision.system_messages.extend(outcome.system_messages)
            if outcome.updated_input:
                decision.updated_input = outcome.updated_input
            if outcome.stop:
                decision.stop = True
                decision.stop_reason = outcome.stop_reason or decision.stop_reason
            decision.raw_outputs.append(raw)
            return

        if isinstance(outcome, dict):
            decision.raw_outputs.append(outcome)
            # Permission / blocking decision check
            dec = outcome.get("decision")
            perm_dec = (
                outcome.get("hookSpecificOutput", {}).get("permissionDecision")
                if isinstance(outcome.get("hookSpecificOutput"), dict)
                else None
            )
            selected_dec = perm_dec or dec

            if selected_dec in ("deny", "block", "error"):
                decision.decision = selected_dec
                decision.allowed = False
                reason = outcome.get("reason") or (
                    outcome.get("hookSpecificOutput", {}).get("reason")
                    if isinstance(outcome.get("hookSpecificOutput"), dict)
                    else None
                )
                if reason:
                    decision.reason = str(reason)
            elif selected_dec in ("allow", "approve", "ask"):
                if not decision.is_blocking():
                    decision.decision = selected_dec

            # Additional context
            ctx = outcome.get("additionalContext") or outcome.get("additional_context")
            if not ctx and isinstance(outcome.get("hookSpecificOutput"), dict):
                ctx = outcome.get("hookSpecificOutput", {}).get("additionalContext")
            if isinstance(ctx, str) and ctx.strip():
                decision.additional_context.append(ctx.strip())
            elif isinstance(ctx, list):
                decision.additional_context.extend([str(c) for c in ctx if c])

            # Feedback
            fb = outcome.get("feedback")
            if not fb and isinstance(outcome.get("hookSpecificOutput"), dict):
                fb = outcome.get("hookSpecificOutput", {}).get("feedback")
            if isinstance(fb, str) and fb.strip():
                decision.feedback.append(fb.strip())
            elif isinstance(fb, list):
                decision.feedback.extend([str(f) for f in fb if f])

            # System message
            sys_msg = outcome.get("systemMessage") or outcome.get("system_message")
            if not sys_msg and isinstance(outcome.get("hookSpecificOutput"), dict):
                sys_msg = outcome.get("hookSpecificOutput", {}).get("systemMessage")
            if isinstance(sys_msg, str) and sys_msg.strip():
                decision.system_messages.append(sys_msg.strip())

            # Updated input
            updated = outcome.get("updatedInput") or outcome.get("updated_input")
            if not updated and isinstance(outcome.get("hookSpecificOutput"), dict):
                updated = outcome.get("hookSpecificOutput", {}).get("updatedInput")
            if isinstance(updated, dict):
                decision.updated_input = updated

            # Stop
            cont = outcome.get("continue")
            if cont is False:
                decision.stop = True
                decision.stop_reason = outcome.get("stopReason") or outcome.get("stop_reason")


class CodexHookAdapter:
    """Wire-protocol adapter and command runner for Codex hooks."""

    DIALECT = "codex"

    def __init__(self, bridge: HookBridge | None = None, *, model: str = "") -> None:
        self.bridge = bridge or HookBridge()
        self.model = model

    def format_session_start(
        self, session_id: str, cwd: str, model: str | None = None, source: str = "user"
    ) -> dict[str, Any]:
        """Format SessionStart event into Codex wire protocol."""
        return {
            "event": "SessionStart",
            "session_id": session_id,
            "cwd": cwd,
            "model": model or self.model,
            "source": source,
        }

    def format_user_prompt_submit(
        self, turn_id: str | int, prompt: str, cwd: str = "", model: str | None = None
    ) -> dict[str, Any]:
        """Format UserPromptSubmit event into Codex wire protocol."""
        return {
            "event": "UserPromptSubmit",
            "turn_id": str(turn_id),
            "prompt": prompt,
            "cwd": cwd,
            "model": model or self.model,
        }

    def format_pre_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        turn_id: str | int = "",
        cwd: str = "",
        model: str | None = None,
    ) -> dict[str, Any]:
        """Format PreToolUse event into Codex wire protocol."""
        return {
            "event": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "turn_id": str(turn_id),
            "cwd": cwd,
            "model": model or self.model,
        }

    def format_post_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any],
        turn_id: str | int = "",
        cwd: str = "",
        model: str | None = None,
    ) -> dict[str, Any]:
        """Format PostToolUse event into Codex wire protocol."""
        return {
            "event": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            "turn_id": str(turn_id),
            "cwd": cwd,
            "model": model or self.model,
        }

    def format_stop(
        self, session_id: str, reason: str = "", cwd: str = "", model: str | None = None
    ) -> dict[str, Any]:
        """Format Stop event into Codex wire protocol."""
        return {
            "event": "Stop",
            "session_id": session_id,
            "reason": reason,
            "cwd": cwd,
            "model": model or self.model,
        }

    def parse_hook_output(self, exit_code: int, stdout: str, stderr: str) -> HookDecision:
        """Parse raw process output into a normalized HookDecision."""
        trimmed_stdout = stdout.strip()
        trimmed_stderr = stderr.strip()

        # In Codex spec, non-zero exit codes indicate failure / blocking
        if exit_code != 0:
            reason = trimmed_stderr or trimmed_stdout or f"blocked by hook (exit code {exit_code})"
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=reason,
                raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}],
            )

        if not trimmed_stdout:
            return HookDecision(raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}])

        try:
            parsed = json.loads(trimmed_stdout)
            if isinstance(parsed, dict):
                decision = HookDecision()
                self.bridge._fold_outcome(decision, parsed)
                decision.raw_outputs.append({"exit_code": exit_code, "stdout": stdout, "stderr": stderr})
                return decision
        except json.JSONDecodeError:
            pass

        # Plain text stdout on exit code 0 is treated as additional context
        if exit_code == 0 and trimmed_stdout:
            return HookDecision(
                additional_context=[trimmed_stdout],
                raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}],
            )

        if exit_code != 0:
            err_msg = stderr.strip() or f"hook exited with code {exit_code}"
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=err_msg,
                raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}],
            )

        return HookDecision(raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}])

    def run_command_hook(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        timeout: float = 30.0,
        cwd: str | None = None,
    ) -> HookDecision:
        """Run an external command hook sending JSON to stdin and return HookDecision."""
        try:
            # Codex sends payload without trailing newline
            input_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            proc = subprocess.run(
                command,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                cwd=cwd,
                shell=True,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace")
            stderr = proc.stderr.decode("utf-8", errors="replace")
            return self.parse_hook_output(proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=f"hook command timed out after {timeout}s",
                raw_outputs=[{"error": "timeout", "command": command}],
            )
        except Exception as exc:
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=f"hook command execution error: {exc}",
                raw_outputs=[{"error": str(exc), "command": command}],
            )

    def load_config(
        self, config_data: dict[str, Any] | str | Path, cwd: str | None = None
    ) -> HookBridge:
        """Load a Codex hooks.json config and register command handlers onto the bridge."""
        if isinstance(config_data, (str, Path)):
            with open(config_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = dict(config_data)

        for event_name, groups in data.items():
            if not isinstance(groups, list):
                continue
            for grp in groups:
                if not isinstance(grp, dict):
                    continue
                matcher = grp.get("matcher", "")
                hooks = grp.get("hooks", [])
                for h in hooks:
                    cmd = h.get("command")
                    timeout = float(h.get("timeoutSec", 30))
                    if not cmd:
                        continue

                    def make_handler(command: str, timeout_sec: float):
                        def handler(match_target: str, payload: dict[str, Any]) -> HookDecision:
                            return self.run_command_hook(command, payload, timeout=timeout_sec, cwd=cwd)
                        return handler

                    self.bridge.register(
                        event_name,
                        make_handler(cmd, timeout),
                        matcher=matcher,
                    )
        return self.bridge


class ClaudeCodeHookAdapter:
    """Wire-protocol adapter and command runner for Claude Code hooks."""

    DIALECT = "claude-code"

    def __init__(
        self,
        bridge: HookBridge | None = None,
        *,
        plugin_root: str = "",
        project_dir: str = "",
    ) -> None:
        self.bridge = bridge or HookBridge()
        self.plugin_root = plugin_root
        self.project_dir = project_dir

    def format_session_start(
        self, session_id: str, project_dir: str = "", source: str = "startup"
    ) -> dict[str, Any]:
        """Format SessionStart event into Claude Code wire protocol."""
        return {
            "hookEventName": "SessionStart",
            "sessionId": session_id,
            "projectDir": project_dir or self.project_dir,
            "source": source,
        }

    def format_user_prompt_submit(
        self, turn: int, prompt: str, session_id: str = ""
    ) -> dict[str, Any]:
        """Format UserPromptSubmit event into Claude Code wire protocol."""
        return {
            "hookEventName": "UserPromptSubmit",
            "turn": turn,
            "prompt": prompt,
            "sessionId": session_id,
        }

    def format_pre_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        turn: int = 1,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Format PreToolUse event into Claude Code wire protocol."""
        return {
            "hookEventName": "PreToolUse",
            "tool": tool_name,
            "toolInput": tool_input,
            "turn": turn,
            "sessionId": session_id,
        }

    def format_post_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any],
        turn: int = 1,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Format PostToolUse event into Claude Code wire protocol."""
        return {
            "hookEventName": "PostToolUse",
            "tool": tool_name,
            "toolInput": tool_input,
            "toolOutput": tool_output,
            "turn": turn,
            "sessionId": session_id,
        }

    def format_stop(self, session_id: str, stop_reason: str = "") -> dict[str, Any]:
        """Format Stop event into Claude Code wire protocol."""
        return {
            "hookEventName": "Stop",
            "sessionId": session_id,
            "stopReason": stop_reason,
        }

    def format_subagent_start(
        self, subagent_id: str, role: str, session_id: str = ""
    ) -> dict[str, Any]:
        """Format SubagentStart event into Claude Code wire protocol."""
        return {
            "hookEventName": "SubagentStart",
            "subagentId": subagent_id,
            "role": role,
            "sessionId": session_id,
        }

    def format_subagent_stop(
        self, subagent_id: str, session_id: str = "", status: str = "completed"
    ) -> dict[str, Any]:
        """Format SubagentStop event into Claude Code wire protocol."""
        return {
            "hookEventName": "SubagentStop",
            "subagentId": subagent_id,
            "sessionId": session_id,
            "status": status,
        }

    def parse_hook_output(self, exit_code: int, stdout: str, stderr: str) -> HookDecision:
        """Parse Claude Code hook command output into a normalized HookDecision."""
        trimmed_stdout = stdout.strip()
        trimmed_stderr = stderr.strip()

        if exit_code != 0 and not trimmed_stdout:
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=trimmed_stderr or f"hook failed with exit code {exit_code}",
                raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}],
            )

        if not trimmed_stdout:
            return HookDecision(raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}])

        try:
            parsed = json.loads(trimmed_stdout)
            if isinstance(parsed, dict):
                decision = HookDecision()
                self.bridge._fold_outcome(decision, parsed)
                decision.raw_outputs.append({"exit_code": exit_code, "stdout": stdout, "stderr": stderr})
                return decision
        except json.JSONDecodeError:
            pass

        return HookDecision(
            additional_context=[trimmed_stdout] if exit_code == 0 and trimmed_stdout else [],
            raw_outputs=[{"exit_code": exit_code, "stdout": stdout, "stderr": stderr}],
        )

    def _substitute_vars(self, command: str, plugin_root: str, project_dir: str) -> str:
        res = command.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root)
        res = res.replace("$CLAUDE_PLUGIN_ROOT", plugin_root)
        res = res.replace("${CLAUDE_PROJECT_DIR}", project_dir)
        res = res.replace("$CLAUDE_PROJECT_DIR", project_dir)
        return res

    def run_command_hook(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        timeout: float = 30.0,
        cwd: str | None = None,
    ) -> HookDecision:
        """Run a Claude Code command hook with JSON input and variable substitutions."""
        plugin_root = self.plugin_root or (cwd or os.getcwd())
        project_dir = self.project_dir or (cwd or os.getcwd())
        substituted_cmd = self._substitute_vars(command, plugin_root, project_dir)

        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = project_dir
        if self.plugin_root:
            env["CLAUDE_PLUGIN_ROOT"] = self.plugin_root

        try:
            input_bytes = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            proc = subprocess.run(
                substituted_cmd,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                cwd=cwd or project_dir,
                shell=True,
                env=env,
            )
            stdout = proc.stdout.decode("utf-8", errors="replace")
            stderr = proc.stderr.decode("utf-8", errors="replace")
            return self.parse_hook_output(proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=f"hook command timed out after {timeout}s",
                raw_outputs=[{"error": "timeout", "command": command}],
            )
        except Exception as exc:
            return HookDecision(
                decision="deny",
                allowed=False,
                reason=f"hook execution error: {exc}",
                raw_outputs=[{"error": str(exc), "command": command}],
            )

    def load_config(
        self,
        config_data: dict[str, Any] | str | Path,
        cwd: str | None = None,
        plugin_root: str | None = None,
        project_dir: str | None = None,
    ) -> HookBridge:
        """Load Claude Code hooks.json / settings.json config and register onto bridge."""
        if plugin_root:
            self.plugin_root = plugin_root
        if project_dir:
            self.project_dir = project_dir

        if isinstance(config_data, (str, Path)):
            with open(config_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = dict(config_data)

        # Handle top-level 'hooks' wrapper if present
        hooks_dict = data.get("hooks", data)
        if not isinstance(hooks_dict, dict):
            return self.bridge

        for event_name, groups in hooks_dict.items():
            if not isinstance(groups, list):
                continue
            for grp in groups:
                if not isinstance(grp, dict):
                    continue
                matcher = grp.get("matcher", "")
                hooks = grp.get("hooks", [])
                for h in hooks:
                    # Claude code supports {type: "command", command: ...}
                    if isinstance(h, dict) and h.get("type", "command") == "command":
                        cmd = h.get("command")
                        timeout = float(h.get("timeoutSec", h.get("timeout", 30)))
                        if not cmd:
                            continue

                        def make_handler(command: str, timeout_sec: float):
                            def handler(match_target: str, payload: dict[str, Any]) -> HookDecision:
                                return self.run_command_hook(
                                    command, payload, timeout=timeout_sec, cwd=cwd
                                )
                            return handler

                        self.bridge.register(
                            event_name,
                            make_handler(cmd, timeout),
                            matcher=matcher,
                        )
        return self.bridge
