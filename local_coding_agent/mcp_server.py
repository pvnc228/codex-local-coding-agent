"""Lean stdlib MCP server exposing proposal-only ``delegate_code`` over stdio.

Implements the JSON-RPC 2.0 stdio subset that local MCP clients speak:
``initialize``, ``notifications/initialized``, ``tools/list``, ``tools/call``.
Policy, validation, idempotency and result ownership stay in
:class:`DelegationService`; this server is only a wire adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from .service import DelegationRequest, DelegationService

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
_SERVER_INFO = {"name": "codex-local-coding-agent", "version": "0.1.0"}
_CALLER_ID = "mcp-stdio"

_TOOLS = [
    {
        "name": "delegate_code",
        "description": (
            "Delegate one atomic, proposal-only coding task to a local Ollama "
            "model. Returns a controller-owned result (status, patch, checks, "
            "risks, validation, audit); never applies changes to the workspace."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "workspace_ref": {"type": "string"},
                "model_profile": {"type": "string"},
                "task": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "goal": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}},
                        "context": {"type": "string"},
                        "constraints": {"type": "array", "items": {"type": "string"}},
                        "checks": {"type": "array", "items": {"type": "string"}},
                        "acceptance": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "goal", "files"],
                },
            },
            "required": ["request_id", "workspace_ref", "model_profile", "task"],
        },
    }
]

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class McpStdioServer:
    """Serve one bounded ``delegate_code`` tool over newline-delimited JSON-RPC."""

    def __init__(self, service: DelegationService) -> None:
        self._service = service

    def handle_message(self, raw: str | bytes) -> str | None:
        """Process one JSON-RPC message; return the encoded response or None."""

        if not isinstance(raw, (str, bytes)):
            return self._encode_error(None, _INVALID_REQUEST, "message must be text or bytes")
        try:
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except UnicodeDecodeError:
            return self._encode_error(None, _PARSE_ERROR, "message is not valid UTF-8")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return self._encode_error(None, _PARSE_ERROR, "message is not valid JSON")
        if not isinstance(message, Mapping):
            return self._encode_error(None, _INVALID_REQUEST, "message must be an object")

        method = message.get("method")
        message_id = message.get("id")
        is_request = "id" in message

        if not isinstance(method, str) or not method:
            if is_request:
                return self._encode_error(message_id, _INVALID_REQUEST, "missing method")
            return None

        try:
            result = self._dispatch(method, message.get("params"), message_id)
        except McpError as error:
            return self._encode_error(message_id, error.code, error.message)
        except Exception:  # noqa: BLE001 - transport boundary must not crash the loop
            return self._encode_error(message_id, _INTERNAL_ERROR, "internal server error")
        if result is None or not is_request:
            return None
        return json.dumps({"jsonrpc": "2.0", "id": message_id, "result": result}, ensure_ascii=False)

    def _dispatch(self, method: str, params: Any, message_id: Any) -> dict[str, Any] | None:
        if method == "initialize":
            return {
                "protocolVersion": _negotiate_version(params),
                "capabilities": {"tools": {}},
                "serverInfo": _SERVER_INFO,
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return None
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": _TOOLS}
        if method == "tools/call":
            return self._call_tool(params)
        raise McpError(_METHOD_NOT_FOUND, f"unknown method: {method}")

    def _call_tool(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise McpError(_INVALID_PARAMS, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name != "delegate_code":
            raise McpError(_METHOD_NOT_FOUND, f"unknown tool: {name}")
        try:
            request = DelegationRequest.from_mapping(arguments)
        except (TypeError, ValueError) as error:
            raise McpError(_INVALID_PARAMS, str(error)) from error
        result = self._service.delegate(_CALLER_ID, request)
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}
            ],
            "isError": result.get("status") == "failed",
        }

    def serve(
        self,
        input_stream=None,
        output_stream=None,
    ) -> None:
        source = input_stream or getattr(sys.stdin, "buffer", sys.stdin)
        target = output_stream or getattr(sys.stdout, "buffer", sys.stdout)
        for raw_line in source:
            if isinstance(raw_line, bytes):
                if raw_line == b"":
                    break
            elif raw_line == "":
                break
            if isinstance(raw_line, (str, bytes)) and not raw_line.strip():
                continue
            response = self.handle_message(raw_line)
            if response is None:
                continue
            encoded = response.encode("utf-8")
            try:
                target.write(encoded + b"\n")
            except TypeError:
                target.write(response + "\n")
            target.flush()

    @staticmethod
    def _encode_error(message_id: Any, code: int, message: str) -> str:
        return json.dumps(
            {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )


def _negotiate_version(params: Any) -> str:
    if isinstance(params, Mapping) and params.get("protocolVersion") in SUPPORTED_PROTOCOL_VERSIONS:
        return params["protocolVersion"]
    return SUPPORTED_PROTOCOL_VERSIONS[-1]


class McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the proposal-only MCP stdio server")
    parser.add_argument("--workspace-ref", default="workspace")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    service = DelegationService({args.workspace_ref: args.workspace})
    McpStdioServer(service).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
