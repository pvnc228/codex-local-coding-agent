import tempfile
import unittest
import json
import sys
from pathlib import Path

from local_coding_agent.repository_tools import BoundedRepositoryTools, ToolPolicyError
from local_coding_agent.task import TaskEnvelope


class RepositoryToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "allowed.py").write_text("VALUE = 42\n", encoding="utf-8")
        (self.workspace / "secret.txt").write_text("do not expose\n", encoding="utf-8")
        self.task = TaskEnvelope(
            id="read-one",
            goal="прочитать разрешённый файл",
            files=("src/allowed.py",),
            checks=(),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_read_file_returns_only_allowlisted_content(self):
        tools = BoundedRepositoryTools(self.workspace, self.task)

        result = tools.execute("read_file", {"path": "src/allowed.py"})

        self.assertEqual(
            result,
            {"path": "src/allowed.py", "content": "VALUE = 42\n", "truncated": False},
        )
        with self.assertRaisesRegex(ToolPolicyError, "allowlist"):
            tools.execute("read_file", {"path": "secret.txt"})
        with self.assertRaises(ToolPolicyError):
            tools.execute("read_file", {"path": "../secret.txt"})
        with self.assertRaises(ToolPolicyError):
            tools.execute("read_file", {"path": str((self.workspace / "src" / "allowed.py").resolve())})

    def test_read_file_bounds_utf8_tool_result_without_splitting_text(self):
        long_content = "Привет мир! " * 40
        (self.workspace / "src" / "allowed.py").write_text(long_content, encoding="utf-8")
        tools = BoundedRepositoryTools(self.workspace, self.task, max_tool_result_bytes=96)

        result = tools.execute("read_file", {"path": "src/allowed.py"})

        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), 96)
        result["content"].encode("utf-8").decode("utf-8")

    def test_search_text_returns_bounded_matches_from_allowlisted_files(self):
        (self.workspace / "src" / "allowed.py").write_text(
            "VALUE = 42\nother = VALUE\n", encoding="utf-8"
        )
        tools = BoundedRepositoryTools(self.workspace, self.task)

        result = tools.execute(
            "search_text",
            {"query": "VALUE", "paths": ["src/allowed.py"]},
        )

        self.assertEqual(
            result,
            {
                "matches": [
                    {"path": "src/allowed.py", "line": 1, "text": "VALUE = 42"},
                    {"path": "src/allowed.py", "line": 2, "text": "other = VALUE"},
                ],
                "truncated": False,
            },
        )

    def test_list_files_stays_inside_requested_workspace_directory(self):
        result = BoundedRepositoryTools(self.workspace, self.task).execute(
            "list_files",
            {"path": "src"},
        )

        self.assertEqual(result, {"files": ["src/allowed.py"], "truncated": False})

    def test_propose_patch_returns_valid_diff_without_writing_files(self):
        patch = (
            "diff --git a/src/allowed.py b/src/allowed.py\n"
            "--- a/src/allowed.py\n"
            "+++ b/src/allowed.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 42\n"
            "+VALUE = 43\n"
        )
        tools = BoundedRepositoryTools(self.workspace, self.task)

        result = tools.execute("propose_patch", {"patch": patch})

        self.assertEqual(result, {"patch": patch, "files": ["src/allowed.py"]})
        self.assertEqual(
            (self.workspace / "src" / "allowed.py").read_text(encoding="utf-8"),
            "VALUE = 42\n",
        )
        outside_patch = patch.replace("src/allowed.py", "secret.txt")
        with self.assertRaisesRegex(ToolPolicyError, "allowlist"):
            tools.execute("propose_patch", {"patch": outside_patch})

    def test_run_tests_executes_only_an_exactly_allowlisted_command(self):
        command = f'"{sys.executable}" -B -c "print(\'check ok\')"'
        task = TaskEnvelope(
            id="run-check",
            goal="запустить проверку",
            files=("src/allowed.py",),
            checks=(command,),
        )
        tools = BoundedRepositoryTools(self.workspace, task)

        result = tools.execute("run_tests", {"command": command})

        self.assertTrue(result["passed"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("check ok", result["stdout"])
        with self.assertRaisesRegex(ToolPolicyError, "allowlisted"):
            tools.execute("run_tests", {"command": "python -c \"print(1)\""})

    def test_run_tests_keeps_external_evidence_inside_result_limit(self):
        task = TaskEnvelope(
            id="bounded-check",
            goal="запустить короткую проверку",
            files=("src/allowed.py",),
            checks=("exit 0",),
        )
        tools = BoundedRepositoryTools(self.workspace, task, max_tool_result_bytes=200)

        result = tools.execute("run_tests", {"command": "exit 0"})

        self.assertIn("evidence", result)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), 200)

    def test_tool_calls_are_recorded_as_audit_events(self):
        tools = BoundedRepositoryTools(self.workspace, self.task)
        tools.execute("read_file", {"path": "src/allowed.py"})
        with self.assertRaises(ToolPolicyError):
            tools.execute("read_file", {"path": "secret.txt"})

        self.assertEqual([event["name"] for event in tools.audit_events], ["read_file", "read_file"])
        self.assertTrue(tools.audit_events[0]["success"])
        self.assertFalse(tools.audit_events[1]["success"])


if __name__ == "__main__":
    unittest.main()
