import json
import tempfile
import unittest
from threading import Event, Timer
import sys
from pathlib import Path

from local_coding_agent.controller import Controller, TOOL_DEFINITIONS
from local_coding_agent.task import TaskEnvelope


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def chat(self, messages, *, tools=None):
        self.requests.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


class BlockingFakeModel:
    def __init__(self, block_event, release_event):
        self.requests = []
        self._block = block_event
        self._release = release_event

    def chat(self, messages, *, tools=None):
        self.requests.append({"messages": messages, "tools": tools})
        try:
            self._block.wait(timeout=10)
        finally:
            self._release.set()
        return {"message": {"role": "assistant", "content": "{}"}}


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

    def test_controller_does_not_advertise_run_tests_without_allowlisted_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="no-check-tool", goal="прочитать файл", files=("allowed.py",))
            model = FakeModel(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "status": "candidate",
                                    "summary": "готово",
                                    "patch": "",
                                    "checks": [],
                                    "risks": [],
                                }
                            ),
                        }
                    }
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "accepted")
        advertised = {
            definition["function"]["name"]
            for definition in model.requests[0]["tools"]
        }
        self.assertNotIn("run_tests", advertised)

    def test_propose_patch_tool_contract_requires_counted_complete_diff(self):
        definition = next(
            definition
            for definition in TOOL_DEFINITIONS
            if definition["function"]["name"] == "propose_patch"
        )
        description = definition["function"]["description"]

        self.assertIn("hunk", description)
        self.assertIn("counts", description)
        self.assertIn("real newlines", description)
        self.assertIn("literal \\n", description)

    def test_controller_converts_json_tool_call_in_content_to_bounded_tool_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="content-tool", goal="прочитать файл", files=("allowed.py",))
            model = FakeModel(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "name": "read_file",
                                    "arguments": {"path": "allowed.py"},
                                }
                            ),
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
                                }
                            ),
                        }
                    },
                ]
            )

            result = Controller(model, workspace).run(task)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(model.requests[1]["messages"][-1]["tool_name"], "read_file")
        self.assertIn("VALUE = 42", model.requests[1]["messages"][-1]["content"])

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

    def test_controller_fails_on_repeated_list_files_with_default_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="duplicate-list-files", goal="прочитать файлы", files=("allowed.py",))
            call = {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "list_files", "arguments": {"path": "."}}}
                    ],
                }
            }
            default_call = {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{"function": {"name": "list_files", "arguments": {}}}],
                }
            }
            model = FakeModel([default_call, call])

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

    def test_controller_cancels_during_blocking_model_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
            task = TaskEnvelope(id="cancel-block", goal="не ждать", files=("allowed.py",))
            block_event = Event()
            release_event = Event()
            model = BlockingFakeModel(block_event, release_event)
            cancelled = Event()
            timer = Timer(0.2, cancelled.set)
            timer.start()

            result = Controller(model, workspace).run(task, cancel_event=cancelled)

            timer.cancel()
            release_event.set()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["kind"], "cancelled")
        self.assertEqual(len(model.requests), 1)

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

    def test_controller_fails_when_cumulative_context_exceeds_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("x" * 500, encoding="utf-8")
            task = TaskEnvelope(id="cumulative-context", goal="прочитать файл", files=("allowed.py",))
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
                                    "summary": "готово",
                                    "patch": "",
                                    "checks": [],
                                    "risks": [],
                                }
                            ),
                        }
                    },
                ]
            )

            result = Controller(model, workspace, max_context_bytes=2000).run(task)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["kind"], "context_limit")
        self.assertEqual(len(model.requests), 1)

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
