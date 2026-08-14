"""MCP server exposing proposal-only ``delegate_code`` via the official SDK.

Built on ``mcp>=2.0.0``, which speaks the 2026-07-28 stateless protocol
(per-request ``_meta``, ``server/discover``, ``resultType``) and auto-falls
back to the legacy ``initialize`` handshake for older clients through
``serve_dual_era_loop``. Policy, validation, idempotency and result ownership
stay in :class:`DelegationService`; this server is only a wire adapter.

With ``enable_tasks``, the server also mounts the ``io.modelcontextprotocol/tasks``
extension over a bounded worker pool (async lifecycle) and an ``apply_proposal``
tool whose confirmation is a Multi Round-Trip Request elicitation.

Single-tenant: the stdio server serves one direct client process, so every
request shares the fixed caller id ``"mcp-stdio"`` (idempotency + task pool
namespace). Multi-tenant caller scoping belongs to a remote HTTP gate.
"""

from __future__ import annotations

import argparse
from typing import Annotated, Any

from .service import DelegationService

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - pydantic comes with mcp
    BaseModel = None  # type: ignore[assignment]

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

try:
    from mcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
        ElicitationResult,
    )
    from mcp.server.mcpserver import Context, Elicit, Resolve
except ImportError:  # pragma: no cover - mcp is an optional dependency
    AcceptedElicitation = None  # type: ignore[assignment]
    CancelledElicitation = None  # type: ignore[assignment]
    DeclinedElicitation = None  # type: ignore[assignment]
    ElicitationResult = None  # type: ignore[assignment]
    Context = None  # type: ignore[assignment]
    Elicit = None  # type: ignore[assignment]
    Resolve = None  # type: ignore[assignment]


def _require_mcp() -> None:
    if not _MCP_AVAILABLE:
        raise ImportError(
            "the MCP server requires the 'mcp' package; install it with `pip install mcp>=2.0.0`"
        )


def _delegate_request(request_id: Any, workspace_ref: Any, model_profile: Any, task: Any):
    from .service import DelegationRequest
    from .task import TaskEnvelope

    return DelegationRequest(
        request_id=request_id,
        workspace_ref=workspace_ref,
        model_profile=model_profile,
        task=TaskEnvelope.from_mapping(task),
    )


# Module-level apply confirmation model and resolver so the official SDK can
# evaluate the ``apply_proposal`` tool's annotations via ``inspect.signature``.
# Defined only when pydantic/mcp are present; they are referenced solely at
# tool-registration time, after ``_require_mcp`` has already succeeded.
if BaseModel is not None:
    class ApplyConfirmation(BaseModel):
        confirm: bool

    def _resolve_apply(ctx: Context) -> Elicit[ApplyConfirmation]:
        del ctx
        return Elicit(
            "Подтвердите применение предложенного патча к рабочей области.",
            ApplyConfirmation,
        )


def build_server(service: DelegationService, *, enable_tasks: bool = False, max_workers: int = 1, max_queue: int = 16):
    """Build an official-SDK MCP server exposing proposal-only ``delegate_code``.

    Args:
        service: The transport-neutral delegation service.
        enable_tasks: When True, mount the Tasks extension (async lifecycle) and
            ``apply_proposal``. When False (default), keep the pure synchronous
            proposal-only path.
        max_workers: Worker slots for the task backend when ``enable_tasks``.
        max_queue: Queue bound for the task backend when ``enable_tasks``.
    """

    _require_mcp()

    extensions: list[Any] = []
    if enable_tasks:
        from .tasks import TasksExtension
        from .worker_pool import BoundedWorkerPool

        pool = BoundedWorkerPool(service, max_workers=max_workers, max_queue=max_queue)
        extensions.append(TasksExtension(pool, caller_id=_CALLER_ID))

    server = MCPServer(
        name=_SERVER_NAME,
        version=_SERVER_VERSION,
        instructions=(
            "Delegates one atomic, proposal-only coding task to a local Ollama "
            "model. Returns a controller-owned result (status, patch, checks, "
            "risks, validation, audit); never applies changes to the workspace."
        ),
        extensions=extensions or None,
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
        request = _delegate_request(request_id, workspace_ref, model_profile, task)
        result = service.delegate(_CALLER_ID, request)
        text = _json(result)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=result,
            is_error=result.get("status") == "failed",
        )

    if enable_tasks:
        _register_apply_proposal(server, service)

    return server


def _register_apply_proposal(server, service: DelegationService) -> None:
    @server.tool(
        name="apply_proposal",
        description=(
            "Apply a previously accepted proposal to its workspace after explicit "
            "confirmation. Revalidates the patch, applies it, runs allowlisted "
            "checks and rolls back on failure."
        ),
    )
    async def apply_proposal(
        request_id: str,
        workspace_ref: str,
        confirmation: Annotated[ElicitationResult[ApplyConfirmation], Resolve(_resolve_apply)],
    ) -> CallToolResult:
        if isinstance(confirmation, DeclinedElicitation):
            result = {"status": "rejected", "error": {"kind": "apply_declined", "message": "apply was declined"}}
        elif isinstance(confirmation, CancelledElicitation):
            result = {"status": "rejected", "error": {"kind": "apply_cancelled", "message": "apply was cancelled"}}
        elif isinstance(confirmation, AcceptedElicitation) and confirmation.data.confirm is True:
            result = service.apply(_CALLER_ID, workspace_ref, request_id)
        else:
            result = {"status": "rejected", "error": {"kind": "apply_declined", "message": "apply was not confirmed"}}
        text = _json(result)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=result,
            is_error=result.get("status") == "failed",
        )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the proposal-only MCP stdio server")
    parser.add_argument("--workspace-ref", default="workspace")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--enable-tasks", action="store_true", help="Mount the Tasks extension and apply_proposal")
    args = parser.parse_args(argv)
    service = DelegationService({args.workspace_ref: args.workspace})
    build_server(service, enable_tasks=args.enable_tasks).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
