"""Universal Agent Client Protocol (ACP) Server & Interop Gateway (R29).

Adapted from DeepSeek Harness @deepseek-ai/dsh-acp.
Implements the standard JSON-RPC 2.0 Agent Client Protocol over stdio with
both Content-Length header and newline-delimited JSONL framing support.
Exposes session lifecycle, prompting, cancellation, and repo tools to
external AI-native editors (Zed, Cursor, VS Code, JetBrains, OpenCode).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence, TextIO

from .ast_compactor import skeletonize_file
from .controller import Controller
from .lsp import LspManager
from .ollama_adapter import ModelProfile, OllamaError, build_client
from .profiles import get_profile
from .ripgrep import ripgrep_search
from .semantic_linter import lint_patch_in_memory
from .spill import read_spill
from .task import TaskEnvelope
from .validators import check_patch_applies


# ============================================================================
# Protocol Constants & Error Codes
# ============================================================================

PROTOCOL_VERSION: str = "2026-08-20"
SERVER_NAME: str = "local-coding-agent-acp"
SERVER_VERSION: str = "0.8.0"

JSONRPC_PARSE_ERROR: int = -32700
JSONRPC_INVALID_REQUEST: int = -32600
JSONRPC_METHOD_NOT_FOUND: int = -32601
JSONRPC_INVALID_PARAMS: int = -32602
JSONRPC_INTERNAL_ERROR: int = -32603


# ============================================================================
# Tool Catalog Schemas
# ============================================================================

ACP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "spill_read",
        "description": "Read or paginate a spilled tool output artifact (R24).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "locator": {"type": "string", "description": "Spill locator token (e.g. locator:spill:... or path)"},
                "offset": {"type": "integer", "description": "0-based line offset", "default": 0},
                "limit": {"type": "integer", "description": "Maximum number of lines to read", "default": 1000},
            },
            "required": ["locator"],
        },
    },
    {
        "name": "grep",
        "description": "Fast ripgrep / regex code search across workspace (R24).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or regex pattern"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Optional glob filters or paths"},
                "regex": {"type": "boolean", "description": "Treat query as regular expression", "default": False},
                "case_sensitive": {"type": "boolean", "description": "Perform case-sensitive matching", "default": False},
                "max_results": {"type": "integer", "description": "Maximum match results", "default": 100},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lsp",
        "description": "Run LSP code intelligence query (definition, references, hover, symbols) (R25).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["definition", "references", "hover", "symbols"],
                    "description": "LSP operation",
                },
                "file": {"type": "string", "description": "Target source file path"},
                "line": {"type": "integer", "description": "0-based line number", "default": 0},
                "char": {"type": "integer", "description": "0-based character/column offset", "default": 0},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
            "required": ["operation", "file"],
        },
    },
    {
        "name": "skeletonize",
        "description": "Parse and skeletonize code symbols using AST compactor (R17).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Target source file path"},
                "symbols": {"type": "array", "items": {"type": "string"}, "description": "Target symbols to retain in full"},
            },
            "required": ["file"],
        },
    },
    {
        "name": "lint_patch",
        "description": "Fast pre-test semantic linter checking patch in memory (R18).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Unified diff or SEARCH/REPLACE patch to check"},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
            "required": ["patch"],
        },
    },
    {
        "name": "read_file",
        "description": "Read one UTF-8 file from workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files below workspace directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path relative to workspace", "default": "."},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
        },
    },
    {
        "name": "run_tests",
        "description": "Run test or shell check command in workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
                "timeout": {"type": "number", "description": "Timeout in seconds", "default": 60},
            },
            "required": ["command"],
        },
    },
    {
        "name": "propose_patch",
        "description": "Validate whether a patch applies cleanly to the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Patch content to validate"},
                "workspace": {"type": "string", "description": "Workspace root directory override"},
            },
            "required": ["patch"],
        },
    },
]


# ============================================================================
# Stdio Framing Codec (Content-Length / JSONL)
# ============================================================================

class AcpCodec:
    """Header & line framing codec for JSON-RPC 2.0 stdio."""

    @staticmethod
    def read_message(stream: Any, max_bytes: int = 10 * 1024 * 1024) -> tuple[dict[str, Any] | None, str]:
        """Read a single JSON-RPC message from a binary or text stream.

        Returns:
            (message_dict, framing_type) where framing_type is "content-length" or "jsonl".
            Returns (None, "") on EOF.
        """
        while True:
            line = stream.readline()
            if not line:
                return None, ""
            if isinstance(line, bytes):
                line_str = line.decode("utf-8", errors="replace").strip()
            else:
                line_str = str(line).strip()
            if line_str:
                break

        # Check for Content-Length header
        if line_str.lower().startswith("content-length:"):
            try:
                parts = line_str.split(":", 1)
                if len(parts) < 2:
                    raise ValueError(f"Invalid Content-Length header: {line_str}")
                content_length = int(parts[1].strip())
            except ValueError:
                raise ValueError(f"Invalid Content-Length header: {line_str}")

            if content_length < 0:
                raise ValueError(f"Content-Length must be non-negative: {content_length}")
            if content_length > max_bytes:
                raise ValueError(f"Content-Length {content_length} exceeds max allowed {max_bytes} bytes")

            # Read remaining headers until empty line (bounded against header floods)
            header_count = 0
            while True:
                header_line = stream.readline()
                if not header_line:
                    break
                header_count += 1
                if header_count > 50:
                    raise ValueError("Too many header lines in request (max 50)")
                if isinstance(header_line, bytes):
                    h_str = header_line.decode("utf-8", errors="replace").strip()
                else:
                    h_str = str(header_line).strip()
                if not h_str:
                    break

            # Read exact content_length bytes
            body = stream.read(content_length)
            if isinstance(body, bytes):
                if len(body) < content_length:
                    raise ValueError(f"Unexpected EOF reading message body: expected {content_length} bytes, got {len(body)}")
                body_str = body.decode("utf-8", errors="replace")
            else:
                body_str = str(body)
                if len(body_str.encode("utf-8")) < content_length and len(body_str) < content_length:
                    raise ValueError(f"Unexpected EOF reading message body: expected {content_length} bytes")

            parsed = json.loads(body_str)
            if not isinstance(parsed, dict):
                raise ValueError("JSON-RPC message must be an object")
            return parsed, "content-length"
        else:
            # JSONL framing
            if len(line_str.encode("utf-8")) > max_bytes:
                raise ValueError(f"JSONL line exceeds max allowed {max_bytes} bytes")
            parsed = json.loads(line_str)
            if not isinstance(parsed, dict):
                raise ValueError("JSON-RPC message must be an object")
            return parsed, "jsonl"

    @staticmethod
    def format_message(message: dict[str, Any], framing: str = "jsonl") -> bytes:
        """Format a JSON-RPC message dictionary into framed bytes."""
        raw_json = json.dumps(message, ensure_ascii=False)
        encoded = raw_json.encode("utf-8")
        if framing == "content-length":
            header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
            return header + encoded
        else:
            return encoded + b"\n"


# ============================================================================
# Session Model
# ============================================================================

@dataclass
class AcpSession:
    """An active Agent Client Protocol session."""

    session_id: str
    workspace_path: Path
    profile: str
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    active_prompt: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ACP Server Implementation
# ============================================================================

class AcpServer:
    """Standard JSON-RPC 2.0 ACP Server & Interop Gateway."""

    def __init__(
        self,
        *,
        default_workspace: str | Path | None = None,
        default_profile: str = "qwen2.5-1.5b",
        model_factory: Callable[[Any], Any] | None = None,
        framing: str = "auto",
        max_request_bytes: int = 10 * 1024 * 1024,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
        protocol_version: str = PROTOCOL_VERSION,
    ) -> None:
        self.default_workspace = Path(default_workspace).resolve() if default_workspace else Path.cwd().resolve()
        self.default_profile = default_profile
        self.model_factory = model_factory
        self.framing = framing
        self.max_request_bytes = max_request_bytes
        self.server_name = server_name
        self.server_version = server_version
        self.protocol_version = protocol_version

        self._sessions: dict[str, AcpSession] = {}
        self._sessions_lock = threading.RLock()
        self._write_lock = threading.RLock()
        self._output_stream: Any | None = None
        self._closed = False
        self._detected_framing: str = "jsonl"

    # ------------------------------------------------------------------------
    # Core Stream Loop & Message Processing
    # ------------------------------------------------------------------------

    def serve(
        self,
        input_stream: BinaryIO | TextIO | None = None,
        output_stream: BinaryIO | TextIO | None = None,
    ) -> None:
        """Run the JSON-RPC stdio event loop until EOF or shutdown."""
        source = input_stream or getattr(sys.stdin, "buffer", sys.stdin)
        target = output_stream or getattr(sys.stdout, "buffer", sys.stdout)
        self._output_stream = target

        while not self._closed:
            try:
                msg, detected_framing = AcpCodec.read_message(source, max_bytes=self.max_request_bytes)
                if msg is None:
                    break  # EOF reached
                if detected_framing:
                    self._detected_framing = detected_framing

                response = self.process_request(msg)
                if response is not None:
                    self.write_message(response)
            except json.JSONDecodeError as error:
                err_resp = self._make_error(None, JSONRPC_PARSE_ERROR, f"Parse error: {error}")
                self.write_message(err_resp)
            except ValueError as error:
                err_msg = str(error)
                if "JSON-RPC message must be an object" in err_msg or "method" in err_msg:
                    err_resp = self._make_error(None, JSONRPC_INVALID_REQUEST, f"Invalid Request: {error}")
                else:
                    err_resp = self._make_error(None, JSONRPC_PARSE_ERROR, f"Parse error: {error}")
                self.write_message(err_resp)
            except Exception as error:
                err_resp = self._make_error(None, JSONRPC_INTERNAL_ERROR, f"Internal server error: {error}")
                self.write_message(err_resp)

    def write_message(self, message: dict[str, Any], framing: str | None = None) -> None:
        """Write a framed message to the active output stream in a thread-safe manner."""
        target = self._output_stream
        if target is None:
            return

        effective_framing = framing or (self._detected_framing if self.framing == "auto" else self.framing)
        data_bytes = AcpCodec.format_message(message, effective_framing)

        with self._write_lock:
            try:
                target.write(data_bytes)
            except TypeError:
                # If target is TextIO, write decoded string
                target.write(data_bytes.decode("utf-8", errors="replace"))
            target.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send an asynchronous JSON-RPC notification to the client."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self.write_message(notification)

    def process_request(self, raw_or_dict: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
        """Process a single JSON-RPC message and return the response dictionary."""
        if isinstance(raw_or_dict, (str, bytes)):
            try:
                text = raw_or_dict.decode("utf-8") if isinstance(raw_or_dict, bytes) else raw_or_dict
                msg = json.loads(text)
            except Exception as err:
                return self._make_error(None, JSONRPC_PARSE_ERROR, f"Parse error: {err}")
        elif isinstance(raw_or_dict, dict):
            msg = raw_or_dict
        else:
            return self._make_error(None, JSONRPC_INVALID_REQUEST, "Message must be an object")

        if not isinstance(msg, dict):
            return self._make_error(None, JSONRPC_INVALID_REQUEST, "Message must be an object")

        # JSON-RPC 2.0 version validation
        if "jsonrpc" in msg and msg.get("jsonrpc") != "2.0":
            return self._make_error(msg.get("id"), JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC protocol version; expected '2.0'")

        is_notification = "id" not in msg
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params")
        if params is None:
            params = {}

        if not isinstance(method, str) or not method.strip():
            if is_notification:
                return None
            return self._make_error(req_id, JSONRPC_INVALID_REQUEST, "Missing or invalid 'method' field")
        if not isinstance(params, (dict, list)):
            if is_notification:
                return None
            return self._make_error(req_id, JSONRPC_INVALID_PARAMS, "'params' must be an object or array")

        # Normalize method names
        normalized_method = self._normalize_method(method)
        handler = getattr(self, f"handle_{normalized_method}", None)
        if handler is None:
            if not is_notification:
                return self._make_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")
            return None

        try:
            result = handler(params if isinstance(params, dict) else {"_args": params})
            if not is_notification:
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            return None
        except ValueError as err:
            if not is_notification:
                return self._make_error(req_id, JSONRPC_INVALID_PARAMS, str(err))
            return None
        except Exception as err:
            if not is_notification:
                return self._make_error(req_id, JSONRPC_INTERNAL_ERROR, str(err))
            return None

    @staticmethod
    def _make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        err_obj: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err_obj["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": err_obj}

    @staticmethod
    def _normalize_method(method: str) -> str:
        mapping = {
            "initialize": "initialize",
            "init": "initialize",
            "session/new": "session_new",
            "session_new": "session_new",
            "new_session": "session_new",
            "newSession": "session_new",
            "session/load": "session_load",
            "session_load": "session_load",
            "load_session": "session_load",
            "loadSession": "session_load",
            "session/prompt": "session_prompt",
            "session_prompt": "session_prompt",
            "prompt": "session_prompt",
            "session/cancel": "session_cancel",
            "session_cancel": "session_cancel",
            "cancel": "session_cancel",
            "tools/list": "tools_list",
            "tools_list": "tools_list",
            "list_tools": "tools_list",
            "listTools": "tools_list",
            "tools/call": "tools_call",
            "tools_call": "tools_call",
            "call_tool": "tools_call",
            "callTool": "tools_call",
            "ping": "ping",
            "shutdown": "shutdown",
            "exit": "exit",
        }
        return mapping.get(method, method.replace("/", "_"))

    # ------------------------------------------------------------------------
    # Protocol Handlers
    # ------------------------------------------------------------------------

    def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize handshake."""
        return {
            "protocol_version": self.protocol_version,
            "protocolVersion": self.protocol_version,
            "server_info": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "serverInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "agentInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
            "capabilities": {
                "sessions": True,
                "streaming": True,
                "tools": True,
                "cancellation": True,
                "load_session": True,
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": True,
                },
            },
            "agentCapabilities": {
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": True,
                },
            },
            "authMethods": [],
        }

    def handle_session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new ACP session with workspace and profile configuration."""
        raw_ws = (
            params.get("workspace_path")
            or params.get("workspacePath")
            or params.get("cwd")
            or params.get("workspace")
            or str(self.default_workspace)
        )
        ws_path = Path(raw_ws).resolve()
        if not ws_path.is_dir():
            raise ValueError(f"Workspace path does not exist or is not a directory: {ws_path}")

        profile = (
            params.get("profile")
            or params.get("model_profile")
            or params.get("model")
            or self.default_profile
        )

        session_id = params.get("session_id") or params.get("sessionId") or f"session_{uuid.uuid4().hex[:12]}"

        session = AcpSession(
            session_id=session_id,
            workspace_path=ws_path,
            profile=profile,
            metadata={"created_via": "acp"},
        )

        with self._sessions_lock:
            self._sessions[session_id] = session

        return {
            "session_id": session_id,
            "sessionId": session_id,
            "workspace_path": str(ws_path),
            "profile": profile,
        }

    def handle_session_load(self, params: dict[str, Any]) -> dict[str, Any]:
        """Load an existing session's history and configuration."""
        session_id = params.get("session_id") or params.get("sessionId")
        if not session_id:
            raise ValueError("session_id parameter is required")

        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        return {
            "session_id": session.session_id,
            "sessionId": session.session_id,
            "workspace_path": str(session.workspace_path),
            "profile": session.profile,
            "history": list(session.history),
            "created_at": session.created_at,
        }

    def handle_session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a prompt turn in the given session."""
        session_id = params.get("session_id") or params.get("sessionId")
        if not session_id:
            raise ValueError("session_id parameter is required")

        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise ValueError(f"Session not found: {session_id}")

        raw_prompt = params.get("prompt") or params.get("message") or params.get("content")
        if raw_prompt is None:
            raise ValueError("prompt parameter is required")

        # Extract textual prompt
        if isinstance(raw_prompt, str):
            prompt_text = raw_prompt
        elif isinstance(raw_prompt, dict):
            prompt_text = raw_prompt.get("content") or raw_prompt.get("text") or json.dumps(raw_prompt, ensure_ascii=False)
        elif isinstance(raw_prompt, list):
            blocks = []
            for b in raw_prompt:
                if isinstance(b, dict) and "text" in b:
                    blocks.append(str(b["text"]))
                elif isinstance(b, str):
                    blocks.append(b)
            prompt_text = "\n".join(blocks)
        else:
            prompt_text = str(raw_prompt)

        stream = bool(params.get("stream", params.get("streaming", False)))

        with session.lock:
            session.cancel_event.clear()
            session.active_prompt = True
            session.history.append({"role": "user", "content": prompt_text})

            try:
                # Check for instant cancellation
                if session.cancel_event.is_set():
                    return self._cancel_turn_result(session)

                # Instantiate client
                client = self._get_model_client(session.profile)

                # If prompt is a TaskEnvelope representation, execute Controller
                if isinstance(raw_prompt, dict) and "goal" in raw_prompt and "files" in raw_prompt:
                    task = TaskEnvelope.from_mapping(raw_prompt)
                    controller = Controller(
                        client,
                        session.workspace_path,
                        cancel_event=session.cancel_event,
                    )
                    task_res = controller.run(task, apply=bool(params.get("apply", False)))
                    resp_text = json.dumps(task_res, ensure_ascii=False, indent=2)
                else:
                    # Interactive chat turn
                    resp = client.chat(session.history)
                    if session.cancel_event.is_set():
                        return self._cancel_turn_result(session)

                    msg_obj = resp.get("message", {}) if isinstance(resp, dict) else {}
                    resp_text = msg_obj.get("content", "")

                if stream and resp_text:
                    self.notify(
                        "session/update",
                        {
                            "sessionId": session.session_id,
                            "session_id": session.session_id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": [{"type": "text", "text": resp_text}],
                            },
                        },
                    )

                session.history.append({"role": "assistant", "content": resp_text})
                turn_idx = len(session.history) // 2

                return {
                    "session_id": session.session_id,
                    "sessionId": session.session_id,
                    "stop_reason": "end_turn",
                    "stopReason": "end_turn",
                    "content": resp_text,
                    "message": {"role": "assistant", "content": resp_text},
                    "turn": turn_idx,
                    "status": "completed",
                }
            except Exception as error:
                if session.cancel_event.is_set():
                    return self._cancel_turn_result(session)
                raise
            finally:
                session.active_prompt = False

    def _cancel_turn_result(self, session: AcpSession) -> dict[str, Any]:
        session.history.append({"role": "assistant", "content": "", "status": "cancelled"})
        return {
            "session_id": session.session_id,
            "sessionId": session.session_id,
            "stop_reason": "cancelled",
            "stopReason": "cancelled",
            "content": "",
            "message": {"role": "assistant", "content": ""},
            "status": "cancelled",
        }

    def handle_session_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel an in-flight prompt on the active session."""
        session_id = params.get("session_id") or params.get("sessionId")
        if not session_id:
            raise ValueError("session_id parameter is required")

        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if session is None:
            return {"session_id": session_id, "sessionId": session_id, "cancelled": False, "error": "session not found"}

        session.cancel_event.set()
        return {
            "session_id": session.session_id,
            "sessionId": session.session_id,
            "cancelled": True,
        }

    def handle_tools_list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """List available tools exposed to ACP clients."""
        return {"tools": ACP_TOOLS}

    def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific tool call over ACP."""
        name = params.get("name") or params.get("tool")
        if not name:
            raise ValueError("tool name parameter is required")

        args = params.get("arguments") or params.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be an object")

        ws_str = params.get("workspace") or args.get("workspace") or str(self.default_workspace)
        ws_path = Path(ws_str).resolve()

        try:
            if name == "spill_read":
                locator = args.get("locator", "")
                offset = int(args.get("offset", 0))
                limit = int(args.get("limit", 1000))
                content = read_spill(locator, offset_line=offset, limit_lines=limit)
                return self._tool_success(content, {"locator": locator, "offset": offset, "limit": limit, "content": content})

            elif name == "grep":
                query = args.get("query", "")
                paths = args.get("paths")
                if paths and isinstance(paths, list):
                    for p in paths:
                        if isinstance(p, str) and (".." in p or p.startswith("/") or (len(p) > 1 and p[1] == ":")):
                            raise ValueError(f"Grep path escapes workspace boundary: {p}")
                regex = bool(args.get("regex", args.get("is_regex", False)))
                case_sens = bool(args.get("case_sensitive", False))
                max_res = int(args.get("max_results", 100))
                matches = ripgrep_search(
                    query,
                    root=ws_path,
                    globs=paths,
                    is_regex=regex,
                    case_sensitive=case_sens,
                    max_results=max_res,
                )
                match_dicts = [
                    {"file": m.file, "line": m.line_number, "text": m.line_content}
                    for m in matches
                ]
                formatted = "\n".join(f"{m['file']}:{m['line']}: {m['text']}" for m in match_dicts)
                return self._tool_success(formatted, {"count": len(matches), "matches": match_dicts})

            elif name == "lsp":
                op = args.get("operation")
                file_rel = args.get("file", "")
                target_file = (ws_path / file_rel).resolve()
                if not self._is_safe_path(target_file, ws_path):
                    raise ValueError(f"Path escapes workspace boundary: {file_rel}")
                line = int(args.get("line", 0))
                char = int(args.get("char", args.get("character", 0)))
                lsp_mgr = LspManager(workspace_root=ws_path)

                if op == "definition":
                    res = lsp_mgr.go_to_definition(file_rel, line=line, character=char, workspace_root=ws_path)
                    data = [r.to_dict() for r in res]
                elif op == "references":
                    res = lsp_mgr.find_references(file_rel, line=line, character=char, workspace_root=ws_path)
                    data = [r.to_dict() for r in res]
                elif op == "hover":
                    h = lsp_mgr.hover(file_rel, line=line, character=char, workspace_root=ws_path)
                    data = h.to_dict() if h else None
                elif op == "symbols":
                    syms = lsp_mgr.document_symbols(file_rel, workspace_root=ws_path)
                    data = [s.to_dict() for s in syms]
                else:
                    raise ValueError(f"Unknown LSP operation: {op}")

                return self._tool_success(json.dumps(data, ensure_ascii=False, indent=2), data)

            elif name == "skeletonize":
                file_rel = args.get("file") or args.get("path", "")
                target_file = (ws_path / file_rel).resolve()
                if not self._is_safe_path(target_file, ws_path):
                    raise ValueError(f"Path escapes workspace boundary: {file_rel}")
                symbols = args.get("symbols")
                skeleton = skeletonize_file(str(target_file), target_symbols=symbols)
                return self._tool_success(skeleton, {"file": str(file_rel), "skeleton": skeleton})

            elif name == "lint_patch":
                patch = args.get("patch", "")
                report = lint_patch_in_memory(str(ws_path), patch)
                data = {
                    "valid": report.valid,
                    "diagnostics": [
                        {"file": d.file, "line": d.line, "message": d.message, "rule": d.rule}
                        for d in report.diagnostics
                    ],
                    "prescriptions": list(report.prescriptions),
                }
                text_out = "Valid patch" if report.valid else f"Lint issues: {list(report.prescriptions)}"
                return self._tool_success(text_out, data)

            elif name == "read_file":
                rel = args.get("path") or args.get("file", "")
                target = (ws_path / rel).resolve()
                if not self._is_safe_path(target, ws_path):
                    raise ValueError(f"Path escapes workspace boundary: {rel}")
                content = target.read_text(encoding="utf-8", errors="replace")
                return self._tool_success(content, {"path": rel, "content": content})

            elif name == "list_files":
                rel = args.get("path", ".")
                target = (ws_path / rel).resolve()
                if not self._is_safe_path(target, ws_path):
                    raise ValueError(f"Path escapes workspace boundary: {rel}")
                files = []
                for p in target.rglob("*"):
                    if p.is_file() and not any(part.startswith(".") or part in {"__pycache__", "node_modules", ".venv"} for part in p.parts):
                        files.append(p.relative_to(ws_path).as_posix())
                return self._tool_success("\n".join(files), {"files": files})

            elif name == "run_tests":
                cmd = args.get("command", "")
                timeout = float(args.get("timeout", 60))
                cp = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=ws_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                )
                passed = cp.returncode == 0
                out = (cp.stdout + cp.stderr).strip()
                return self._tool_success(out, {"command": cmd, "exit_code": cp.returncode, "passed": passed, "stdout": cp.stdout, "stderr": cp.stderr})

            elif name == "propose_patch":
                patch = args.get("patch", "")
                applies, err = check_patch_applies(ws_path, patch)
                return self._tool_success(
                    "Applies cleanly" if applies else f"Check failed: {err}",
                    {"applies": applies, "error": err if not applies else None},
                )

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as error:
            return self._tool_error(str(error))

    def handle_ping(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Health-check ping."""
        return {"status": "ok", "pong": True}

    def handle_shutdown(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Gracefully shutdown server."""
        self._closed = True
        return {"status": "shutdown_acknowledged"}

    def handle_exit(self, params: dict[str, Any] | None = None) -> None:
        """Exit server."""
        self._closed = True

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------

    def _get_model_client(self, profile_name: str) -> Any:
        if self.model_factory is not None:
            return self.model_factory(profile_name)
        profile = get_profile(profile_name)
        return build_client(profile)

    @staticmethod
    def _is_safe_path(target: Path, root: Path) -> bool:
        try:
            target.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _tool_success(text_out: str, data: Any = None) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": text_out}],
            "result": data,
            "is_error": False,
            "isError": False,
        }

    @staticmethod
    def _tool_error(err_msg: str) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": f"Error: {err_msg}"}],
            "result": None,
            "is_error": True,
            "isError": True,
            "error": err_msg,
        }
