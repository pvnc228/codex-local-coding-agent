import json
import tempfile
import unittest
from threading import Event
import sys
from pathlib import Path

from local_coding_agent.controller import Controller
from local_coding_agent.task import TaskEnvelope


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat(self, messages, *, tools=None):
        self.requests.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


class ControllerTests(unittest.TestCase):
    def test_controller_correlates_tool_result_and_returns_structured_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(
                id="controller-read",
                goal="проверить значение",
                files=("allowed.py",),
            )
            model = FakeModel(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": {"path": "allowed.py"},
                                    },
                                }
                            ],
                        }
                    },
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "status": "candidate",
                                    "summary": "прочитан файл",
                                    "patch": "",
                                    "checks": [],
                                    "risks": [],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    },
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["summary"], "прочитан файл")
        self.assertEqual(len(model.requests), 2)
        second_messages = model.requests[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_name"], "read_file")
        self.assertIn("VALUE = 42", second_messages[-1]["content"])

    def test_controller_fails_on_repeated_identical_tool_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="duplicate", goal="прочитать файл", files=("allowed.py",))
            call = {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "allowed.py"}}}],
                }
            }
            model = FakeModel([call, call])

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["kind"], "duplicate_tool_call")
        self.assertEqual(len(model.requests), 2)

    def test_controller_retries_invalid_json_with_changed_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="retry-json", goal="вернуть результат", files=("allowed.py",))
            valid = json.dumps(
                {"status": "candidate", "summary": "ok", "patch": "", "checks": [], "risks": []}
            )
            model = FakeModel(
                [
                    {"message": {"role": "assistant", "content": "not json"}},
                    {"message": {"role": "assistant", "content": valid}},
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(model.requests[1]["messages"][-1]["role"], "user")

    def test_controller_stops_before_model_call_when_cancelled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="cancel", goal="не запускать", files=("allowed.py",))
            model = FakeModel([])
            cancelled = Event()
            cancelled.set()

            result = Controller(model, workspace).run(task, cancel_event=cancelled)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["kind"], "cancelled")
        self.assertEqual(model.requests, [])

    def test_controller_accepts_check_only_with_external_runner_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            command = f'"{sys.executable}" -B -c "pass"'
            task = TaskEnvelope(
                id="check-evidence",
                goal="подтвердить проверку",
                files=("allowed.py",),
                checks=(command,),
            )
            model = FakeModel(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "run_tests",
                                        "arguments": {"command": command},
                                    }
                                }
                            ],
                        }
                    },
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "status": "candidate",
                                    "summary": "проверка прошла",
                                    "patch": "",
                                    "checks": [
                                        {
                                            "command": command,
                                            "passed": True,
                                            "evidence": "exit_code=0; passed=True; stdout_bytes=0; stderr_bytes=0; truncated=False",
                                        }
                                    ],
                                    "risks": [],
                                }
                            ),
                        }
                    },
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["validation"]["valid"])

    def test_controller_rejects_invalid_schema_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="bad-schema", goal="вернуть плохой результат", files=("allowed.py",))
            model = FakeModel(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "status": "candidate",
                                    "summary": "bad",
                                    "patch": "",
                                    "checks": [],
                                    "risks": "not-a-list",
                                }
                            ),
                        }
                    }
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "rejected")
        self.assertTrue(result["risks"])


if __name__ == "__main__":
    unittest.main()
