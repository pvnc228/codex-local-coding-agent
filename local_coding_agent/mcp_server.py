"""MCP server exposing proposal-only ``delegate_code`` via the official SDK.

Built on ``mcp>=2.0.0``, which speaks the 2026-07-28 stateless protocol
(per-request ``_meta``, ``server/discover``, ``resultType``) and auto-falls
back to the legacy ``initialize`` handshake for older clients through
``serve_dual_era_loop``. Policy, validation, idempotency and result ownership
stay in :class:`DelegationService`; this server is only a wire adapter.
"""

from __future__ import annotations

import argparse
from typing import Any

from .service import DelegationService

_CALLER_ID = "mcp-stdio"
_SERVER_NAME = "codex-local-coding-agent"
_SERVER_VERSION = "0.2.0"

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import CallToolResult, TextContent

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency is optional
    MCPServer = None  # type: ignore[assignment]
    CallToolResult = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False


def build_server(service: DelegationService):
    """Build an official-SDK MCP server exposing proposal-only ``delegate_code``.

    ``mcp`` is imported lazily so the stdlib-only core keeps importing without
    it; this function raises a clear error only when actually called.
    """

    if not _MCP_AVAILABLE:
        raise ImportError(
            "the MCP server requires the 'mcp' package; install it with `pip install mcp>=2.0.0`"
        )

    server = MCPServer(
        name=_SERVER_NAME,
        version=_SERVER_VERSION,
        instructions=(
            "Delegates one atomic, proposal-only coding task to a local Ollama "
            "model. Returns a controller-owned result (status, patch, checks, "
            "risks, validation, audit); never applies changes to the workspace."
        ),
    )

    @server.tool(
        name="delegate_code",
        description=(
            "Delegate one atomic, proposal-only coding task to a local Ollama "
            "model. The result is controller-owned and never applies changes."
        ),
    )
    async def delegate_code(
        request_id: str,
        workspace_ref: str,
        model_profile: str,
        task: dict[str, Any],
    ) -> CallToolResult:
        from .service import DelegationRequest
        from .task import TaskEnvelope

        request = DelegationRequest(
            request_id=request_id,
            workspace_ref=workspace_ref,
            model_profile=model_profile,
            task=TaskEnvelope.from_mapping(task),
        )
        result = service.delegate(_CALLER_ID, request)
        text = _json(result)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=result,
            is_error=result.get("status") == "failed",
        )

    return server


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the proposal-only MCP stdio server")
    parser.add_argument("--workspace-ref", default="workspace")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    service = DelegationService({args.workspace_ref: args.workspace})
    build_server(service).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
