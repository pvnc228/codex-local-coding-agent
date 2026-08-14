import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from local_coding_agent.mcp_server import build_server
from local_coding_agent.service import DelegationService


class FakeModel:
    def chat(self, messages, *, tools=None):
        return {
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "candidate",
                        "summary": "готово",
                        "patch": "",
                        "checks": [],
                        "risks": [],
                    },
                    ensure_ascii=False,
                ),
            }
        }


class PatchModel:
    def chat(self, messages, *, tools=None):
        return {
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "candidate",
                        "summary": "изменено значение",
                        "patch": (
                            "diff --git a/value.py b/value.py\n"
                            "--- a/value.py\n"
                            "+++ b/value.py\n"
                            "@@ -1 +1 @@\n"
                            "-VALUE = 1\n"
                            "+VALUE = 2\n"
                        ),
                        "checks": [],
                        "risks": [],
                    },
                    ensure_ascii=False,
                ),
            }
        }


class CreateTaskClaimModel(BaseModel):
    result_type: Literal["task"] = Field(alias="resultType", default="task")
    task_id: str = Field(alias="taskId")
    status: str


class FlatTaskResult(BaseModel):
    result_type: str = Field(alias="resultType", default="complete")
    task_id: str = Field(alias="taskId")
    status: str
    created_at: str = Field(alias="createdAt")
    last_updated_at: str = Field(alias="lastUpdatedAt")
    ttl_ms: int | None = Field(alias="ttlMs", default=None)
    poll_interval_ms: int | None = Field(alias="pollIntervalMs", default=None)
    result: dict | None = None
    error: dict | None = None


def _arguments(request_id="r1"):
    return {
        "request_id": request_id,
        "workspace_ref": "fixture",
        "model_profile": "qwen2.5-1.5b",
        "task": {"id": "t1", "goal": "прочитать файл", "files": ["allowed.py"]},
    }


class TasksExtensionTests(unittest.TestCase):
    def _service(self, workspace: Path, model=None):
        return DelegationService({"fixture": workspace}, model_factory=lambda profile: model or FakeModel())

    def _build_tasks_client(self):
        from mcp.client import Client
        from mcp.client.extension import ClientExtension, ResultClaim
        from mcp.types import Result

        class ClaimModel(Result):
            result_type: Literal["task"] = "task"
            task_id: str = Field(alias="taskId")
            status: str

        class TasksClaimExtension(ClientExtension):
            identifier = "io.modelcontextprotocol/tasks"

            def claims(self):
                return [
                    ResultClaim(
                        result_type="task",
                        model=ClaimModel,
                        resolve=self._resolve,
                    )
                ]

            async def _resolve(self, task, ctx):
                from mcp.types import CallToolResult, TextContent

                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(task.model_dump(by_alias=True)))],
                    structured_content=task.model_dump(by_alias=True),
                )

        return Client, TasksClaimExtension

    def test_tasks_lifecycle_returns_working_then_completed(self):
        from mcp.types import GetTaskRequest, GetTaskRequestParams

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)
            Client, TasksClaimExtension = self._build_tasks_client()

            async def run():
                async with Client(server, extensions=[TasksClaimExtension()]) as client:
                    tools = await client.list_tools()
                    result = await client.call_tool("delegate_code", _arguments())
                    return [t.name for t in tools.tools], result

            names, result = asyncio.run(run())

        self.assertEqual(names, ["delegate_code", "apply_proposal"])
        task_id = result.structured_content["taskId"]
        self.assertEqual(result.result_type, "complete")
        self.assertEqual(result.structured_content["status"], "working")
        self.assertTrue(task_id)

    def test_tasks_get_reports_terminal_result(self):
        from mcp.types import GetTaskRequest, GetTaskRequestParams

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)
            Client, TasksClaimExtension = self._build_tasks_client()

            async def run():
                async with Client(server, extensions=[TasksClaimExtension()]) as client:
                    result = await client.call_tool("delegate_code", _arguments())
                    task_id = result.structured_content["taskId"]
                    for _ in range(50):
                        raw = await client.session.send_request(
                            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)),
                            FlatTaskResult,
                        )
                        if raw.status in {"completed", "failed", "cancelled"}:
                            return raw
                        await asyncio.sleep(0.02)
                    return raw

            raw = asyncio.run(run())

        self.assertEqual(raw.status, "completed")
        self.assertEqual(raw.result["status"], "accepted")
        self.assertFalse(raw.result.get("applied", False))

    def test_delegate_code_without_tasks_capability_stays_synchronous(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)

            async def run():
                from mcp.client import Client

                async with Client(server) as client:
                    result = await client.call_tool("delegate_code", _arguments())
                    return result

            result = asyncio.run(run())

        self.assertEqual(result.result_type, "complete")
        self.assertEqual(result.structured_content["status"], "accepted")


class ApplyProposalTests(unittest.TestCase):
    def _service(self, workspace: Path):
        return DelegationService({"fixture": workspace}, model_factory=lambda profile: PatchModel())

    def _apply_arguments(self):
        return {"request_id": "r1", "workspace_ref": "fixture"}

    @staticmethod
    async def _accept_callback(context, params):
        from mcp.types import ElicitResult

        return ElicitResult(action="accept", content={"confirm": True})

    @staticmethod
    async def _decline_callback(context, params):
        from mcp.types import ElicitResult

        return ElicitResult(action="decline")

    def test_apply_proposal_applies_after_confirmation(self):
        from mcp.client import Client

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)

            async def run():
                async with Client(server, elicitation_callback=self._accept_callback) as client:
                    delegated = await client.call_tool(
                        "delegate_code",
                        {
                            "request_id": "r1",
                            "workspace_ref": "fixture",
                            "model_profile": "qwen2.5-1.5b",
                            "task": {"id": "t1", "goal": "change", "files": ["value.py"]},
                        },
                    )
                    applied = await client.call_tool("apply_proposal", self._apply_arguments())
                    return delegated.structured_content, applied.structured_content

            delegated, applied = asyncio.run(run())
            content = (workspace / "value.py").read_text(encoding="utf-8")

        self.assertEqual(delegated["status"], "accepted")
        self.assertFalse(delegated.get("applied", False))
        self.assertEqual(applied["status"], "accepted")
        self.assertTrue(applied["applied"])
        self.assertEqual(content, "VALUE = 2\n")

    def test_apply_proposal_decline_leaves_workspace_untouched(self):
        from mcp.client import Client

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)

            async def run():
                async with Client(server, elicitation_callback=self._decline_callback) as client:
                    await client.call_tool(
                        "delegate_code",
                        {
                            "request_id": "r1",
                            "workspace_ref": "fixture",
                            "model_profile": "qwen2.5-1.5b",
                            "task": {"id": "t1", "goal": "change", "files": ["value.py"]},
                        },
                    )
                    applied = await client.call_tool("apply_proposal", self._apply_arguments())
                    return applied.structured_content

            applied = asyncio.run(run())
            content = (workspace / "value.py").read_text(encoding="utf-8")

        self.assertEqual(applied["status"], "rejected")
        self.assertEqual(applied["error"]["kind"], "apply_declined")
        self.assertEqual(content, "VALUE = 1\n")

    def test_apply_proposal_stale_workspace_rejected(self):
        from mcp.client import Client

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = build_server(self._service(workspace), enable_tasks=True)

            async def run():
                async with Client(server, elicitation_callback=self._accept_callback) as client:
                    await client.call_tool(
                        "delegate_code",
                        {
                            "request_id": "r1",
                            "workspace_ref": "fixture",
                            "model_profile": "qwen2.5-1.5b",
                            "task": {"id": "t1", "goal": "change", "files": ["value.py"]},
                        },
                    )
                    (workspace / "value.py").write_text("VALUE = 999\n", encoding="utf-8")
                    applied = await client.call_tool("apply_proposal", self._apply_arguments())
                    return applied.structured_content

            applied = asyncio.run(run())
            content = (workspace / "value.py").read_text(encoding="utf-8")

        self.assertEqual(applied["status"], "failed")
        self.assertEqual(applied["error"]["kind"], "stale_workspace")
        self.assertEqual(content, "VALUE = 999\n")


if __name__ == "__main__":
    unittest.main()
