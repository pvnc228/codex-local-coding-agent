import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from local_coding_agent.mcp_server import McpStdioServer
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


class McpStdioServerTests(unittest.TestCase):
    def _service(self, workspace: Path) -> DelegationService:
        return DelegationService({"fixture": workspace}, model_factory=lambda profile: FakeModel())

    def _delegate_params(self):
        return {
            "name": "delegate_code",
            "arguments": {
                "request_id": "mcp-request-1",
                "workspace_ref": "fixture",
                "model_profile": "qwen2.5-1.5b",
                "task": {
                    "id": "mcp-task-1",
                    "goal": "прочитать файл",
                    "files": ["allowed.py"],
                },
            },
        }

    def test_initialize_negotiates_protocol_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = McpStdioServer(self._service(Path(temp_dir)))
            response = server.handle_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"},
                    }
                )
            )

        payload = json.loads(response)
        self.assertEqual(payload["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(payload["result"]["serverInfo"]["name"], "codex-local-coding-agent")

    def test_tools_list_exposes_only_delegate_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = McpStdioServer(self._service(Path(temp_dir)))
            response = server.handle_message(
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            )

        tools = json.loads(response)["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["delegate_code"])

    def test_tools_call_delegates_and_returns_proposal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            server = McpStdioServer(self._service(workspace))
            response = server.handle_message(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": self._delegate_params()}
                )
            )

        payload = json.loads(response)
        content = payload["result"]["content"][0]
        self.assertEqual(content["type"], "text")
        result = json.loads(content["text"])
        self.assertEqual(result["status"], "accepted")
        self.assertFalse(result["applied"])
        self.assertIs(payload["result"]["isError"], False)

    def test_tools_call_rejects_unknown_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = McpStdioServer(self._service(Path(temp_dir)))
            params = self._delegate_params()
            params["arguments"]["workspace_ref"] = "missing"
            response = server.handle_message(
                json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": params})
            )

        payload = json.loads(response)
        self.assertIs(payload["result"]["isError"], True)
        result = json.loads(payload["result"]["content"][0]["text"])
        self.assertEqual(result["error"]["kind"], "unknown_workspace")

    def test_unknown_method_returns_rpc_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = McpStdioServer(self._service(Path(temp_dir)))
            response = server.handle_message(
                json.dumps({"jsonrpc": "2.0", "id": 5, "method": "nope"})
            )

        payload = json.loads(response)
        self.assertEqual(payload["error"]["code"], -32601)

    def test_notification_returns_no_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            server = McpStdioServer(self._service(Path(temp_dir)))
            response = server.handle_message(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            )

        self.assertIsNone(response)

    def test_process_bound_mcp_handshake_and_call(self):
        helper = r'''
import json
import sys
from local_coding_agent.mcp_server import McpStdioServer
from local_coding_agent.service import DelegationService

class FakeModel:
    def chat(self, messages, *, tools=None):
        return {"message": {"role": "assistant", "content": json.dumps({
            "status": "candidate", "summary": "ok", "patch": "",
            "checks": [], "risks": [],
        }, ensure_ascii=False)}}

service = DelegationService({"fixture": sys.argv[1]}, model_factory=lambda p: FakeModel())
McpStdioServer(service).serve()
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            lines = "\n".join(
                [
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": self._delegate_params()}),
                ]
            )
            completed = subprocess.run(
                [sys.executable, "-c", helper, str(workspace)],
                cwd=Path(__file__).parents[1],
                input=(lines + "\n").encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8"))
        responses = [json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "codex-local-coding-agent")
        result = json.loads(responses[1]["result"]["content"][0]["text"])
        self.assertEqual(result["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
