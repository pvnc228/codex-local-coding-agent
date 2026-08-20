import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from local_coding_agent.cli import build_parser, load_task_file


class CliTests(unittest.TestCase):
    def test_task_file_is_decoded_as_utf8_and_keeps_russian_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "task.json"
            path.write_bytes(
                json.dumps(
                    {
                        "id": "russian-task",
                        "goal": "изменить текст",
                        "files": ["src/file.py"],
                        "checks": [],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
            )

            task = load_task_file(path)

        self.assertEqual(task.goal, "изменить текст")
        self.assertEqual(task.files, ("src/file.py",))

    def test_cli_exposes_context_window_and_memory_controls(self):
        args = build_parser().parse_args(
            [
                "--task",
                "task.json",
                "--num-ctx",
                "16384",
                "--unload-all",
                "--vram-limit-bytes",
                "1000000",
                "--keep-model",
                "qwen3-8b-q6k:latest",
            ]
        )

        self.assertEqual(args.num_ctx, 16_384)
        self.assertTrue(args.unload_all)
        self.assertEqual(args.vram_limit_bytes, 1_000_000)
        self.assertEqual(args.keep_model, ["qwen3-8b-q6k:latest"])

    def test_cli_exposes_benchmark_controls(self):
        args = build_parser().parse_args(
            [
                "--benchmark",
                "--benchmark-model",
                "ornith-9b",
                "--benchmark-repeats",
                "2",
                "--benchmark-timeout-seconds",
                "120",
                "--benchmark-output",
                ".local-run/bench.json",
            ]
        )

        self.assertTrue(args.benchmark)
        self.assertEqual(args.benchmark_models, ["ornith-9b"])
        self.assertEqual(args.benchmark_repeats, 2)
        self.assertEqual(args.benchmark_timeout_seconds, 120)
        self.assertEqual(str(args.benchmark_output), str(Path(".local-run/bench.json")))

    def test_cli_exposes_apply_flag(self):
        args = build_parser().parse_args(["--task", "task.json", "--apply"])
        self.assertIs(args.apply, True)

        args = build_parser().parse_args(["--task", "task.json"])
        self.assertIs(args.apply, False)

    def test_cli_subcommand_doctor(self):
        args = build_parser().parse_args(["doctor", "--endpoint", "http://127.0.0.1:11434", "--json"])
        self.assertEqual(args.subcommand, "doctor")
        self.assertEqual(args.endpoint, "http://127.0.0.1:11434")
        self.assertTrue(args.json)

    def test_cli_subcommand_init_mcp(self):
        args = build_parser().parse_args(["init-mcp", "--cursor", "--workspace", "c:/code", "--dry-run"])
        self.assertEqual(args.subcommand, "init-mcp")
        self.assertEqual(args.client, "cursor")
        self.assertEqual(args.workspace, "c:/code")
        self.assertTrue(args.dry_run)

    def test_cli_subcommand_codex_mcp(self):
        args = build_parser().parse_args(["init-mcp", "--codex", "--workspace", "c:/code", "--dry-run"])
        self.assertEqual(args.client, "codex")

    def test_cli_subcommand_test_run(self):
        args = build_parser().parse_args(["test-run", "--mock", "--profile", "qwen3-8b-q6k"])
        self.assertEqual(args.subcommand, "test-run")
        self.assertTrue(args.mock)
        self.assertEqual(args.profile, "qwen3-8b-q6k")

    def test_cli_subcommand_serve_mcp(self):
        args = build_parser().parse_args(["serve-mcp", "--workspace", "c:/code", "--enable-tasks"])
        self.assertEqual(args.subcommand, "serve-mcp")
        self.assertEqual(args.workspace, "c:/code")
        self.assertTrue(args.enable_tasks)

    def test_cli_subcommand_monitor(self):
        args = build_parser().parse_args(["monitor", "--port", "9000"])
        self.assertEqual(args.subcommand, "monitor")
        self.assertEqual(args.port, 9000)

    def test_load_task_input_inline_json_string(self):
        from local_coding_agent.cli import load_task_input

        inline = '{"id": "inline-1", "goal": "test inline", "files": ["a.py"]}'
        task = load_task_input(task_value=inline)
        self.assertEqual(task.id, "inline-1")
        self.assertEqual(task.goal, "test inline")
        self.assertEqual(task.files, ("a.py",))

    def test_load_task_input_task_file(self):
        from local_coding_agent.cli import load_task_input

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "envelope.json"
            file_path.write_text('{"id": "from-file", "goal": "file test", "files": ["b.py"]}', encoding="utf-8")
            task = load_task_input(task_file=file_path)
            self.assertEqual(task.id, "from-file")
            self.assertEqual(task.files, ("b.py",))

    def test_load_task_input_multiline_inline_json(self):
        from local_coding_agent.cli import load_task_input

        inline = '{\n  "id": "multiline-1",\n  "goal": "test multiline",\n  "files": ["a.py"]\n}'
        task = load_task_input(task_value=inline)
        self.assertEqual(task.id, "multiline-1")
        self.assertEqual(task.goal, "test multiline")

    def test_cli_parser_accepts_task_file(self):
        args = build_parser().parse_args(["--task-file", "my_task.json"])
        self.assertEqual(args.task_file, Path("my_task.json"))
        self.assertIsNone(args.task)

    def test_cli_subcommand_delegate_parsing(self):
        args = build_parser().parse_args(
            ["delegate", "--task", "task.json", "--profile", "qwen3-8b-q6k", "--apply", "--json"]
        )
        self.assertEqual(args.subcommand, "delegate")
        self.assertEqual(args.task, "task.json")
        self.assertEqual(args.profile, "qwen3-8b-q6k")
        self.assertTrue(args.apply)
        self.assertTrue(args.json)

    def test_cli_subcommand_decompose_parsing(self):
        args = build_parser().parse_args(
            [
                "decompose",
                "--task",
                '{"id": "wide", "goal": "split", "files": ["a.py", "b.py"]}',
                "--strategy",
                "per_file",
                "--budget-files",
                "1",
                "--json",
            ]
        )
        self.assertEqual(args.subcommand, "decompose")
        self.assertEqual(args.strategy, "per_file")
        self.assertEqual(args.budget_files, 1)
        self.assertTrue(args.json)

    def test_cli_subcommand_profiles_parsing(self):
        args = build_parser().parse_args(["profiles", "get", "qwen2.5-coder", "--json"])
        self.assertEqual(args.subcommand, "profiles")
        self.assertEqual(args.profile_action, "get")
        self.assertEqual(args.name, "qwen2.5-coder")
        self.assertTrue(args.json)

    def test_cli_subcommand_memory_parsing(self):
        args = build_parser().parse_args(
            ["memory", "enforce", "--limit", "8000000000", "--keep", "qwen3-8b-q6k:latest", "--json"]
        )
        self.assertEqual(args.subcommand, "memory")
        self.assertEqual(args.memory_action, "enforce")
        self.assertEqual(args.limit, 8_000_000_000)
        self.assertEqual(args.keep, ["qwen3-8b-q6k:latest"])
        self.assertTrue(args.json)

    def test_cli_subcommand_calibrate_parsing(self):
        args = build_parser().parse_args(
            ["calibrate", "--vram-bytes", "16000000000", "--profile", "qwen2.5-coder", "--json"]
        )
        self.assertEqual(args.subcommand, "calibrate")
        self.assertEqual(args.vram_bytes, 16_000_000_000)
        self.assertEqual(args.profile, "qwen2.5-coder")
        self.assertTrue(args.json)

    def test_cli_subcommand_benchmark_parsing(self):
        args = build_parser().parse_args(
            ["benchmark", "--model", "ornith-9b", "--repeats", "3", "--output", "out.json"]
        )
        self.assertEqual(args.subcommand, "benchmark")
        self.assertEqual(args.benchmark_models, ["ornith-9b"])
        self.assertEqual(args.benchmark_repeats, 3)

    def test_cli_subcommand_apply_parsing(self):
        args = build_parser().parse_args(
            ["apply", "--patch-file", "patch.diff", "--workspace", ".", "--check", "pytest tests/"]
        )
        self.assertEqual(args.subcommand, "apply")
        self.assertEqual(args.patch_file, Path("patch.diff"))
        self.assertEqual(args.workspace, Path("."))
        self.assertEqual(args.checks, ["pytest tests/"])

    def test_cli_subcommand_init_skill_parsing(self):
        args = build_parser().parse_args(
            ["init-skill", "--client", "codex", "--write", "--json"]
        )
        self.assertEqual(args.subcommand, "init-skill")
        self.assertEqual(args.client, "codex")
        self.assertTrue(args.write)
        self.assertTrue(args.json)

    def test_handle_subcommand_decompose_execution(self):
        from local_coding_agent.cli import handle_subcommand

        args = build_parser().parse_args(
            [
                "decompose",
                "--task",
                json.dumps(
                    {
                        "id": "split-task",
                        "goal": "decompose this task",
                        "files": ["f1.py", "f2.py", "f3.py", "f4.py", "f5.py", "f6.py"],
                        "checks": [],
                    }
                ),
                "--strategy",
                "by_files",
                "--budget-files",
                "3",
                "--json",
            ]
        )
        code = handle_subcommand(args)
        self.assertEqual(code, 0)

    def test_handle_subcommand_profiles_list_and_get(self):
        from local_coding_agent.cli import handle_subcommand

        # list
        args_list = build_parser().parse_args(["profiles", "list", "--json"])
        code_list = handle_subcommand(args_list)
        self.assertEqual(code_list, 0)

        # get
        args_get = build_parser().parse_args(["profiles", "get", "qwen2.5-coder", "--json"])
        code_get = handle_subcommand(args_get)
        self.assertEqual(code_get, 0)

    def test_handle_subcommand_init_skill_print_and_write(self):
        from local_coding_agent.cli import handle_subcommand

        # print
        args_print = build_parser().parse_args(["init-skill", "--print"])
        code_print = handle_subcommand(args_print)
        self.assertEqual(code_print, 0)

        # write to temp target
        with tempfile.TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / "skills" / "local-coding-agent" / "SKILL.md"
            args_write = build_parser().parse_args(
                ["init-skill", "--target-dir", str(target_file), "--write", "--json"]
            )
            code_write = handle_subcommand(args_write)
            self.assertEqual(code_write, 0)
            self.assertTrue(target_file.is_file())
            content = target_file.read_text(encoding="utf-8")
            self.assertIn("Local Coding Agent — AI Agent Delegation Skill", content)

    def test_handle_subcommand_apply_execution(self):
        from local_coding_agent.cli import handle_subcommand

        with tempfile.TemporaryDirectory() as temp_dir:
            ws = Path(temp_dir)
            # init git repo in temp_dir
            subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=ws, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=ws, check=True, capture_output=True)

            file_a = ws / "hello.py"
            file_a.write_text("def hello():\n    return 'old'\n", encoding="utf-8")
            subprocess.run(["git", "add", "hello.py"], cwd=ws, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=ws, check=True, capture_output=True)

            patch_content = (
                "--- a/hello.py\n"
                "+++ b/hello.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def hello():\n"
                "-    return 'old'\n"
                "+    return 'new'\n"
            )
            patch_file = ws / "patch.diff"
            patch_file.write_text(patch_content, encoding="utf-8")

            # test successful apply with check
            args = build_parser().parse_args(
                [
                    "apply",
                    "--patch-file",
                    str(patch_file),
                    "--workspace",
                    str(ws),
                    "--check",
                    f'python -c "import hello; assert hello.hello() == \'new\'"',
                    "--json",
                ]
            )
            code = handle_subcommand(args)
            self.assertEqual(code, 0)
            self.assertIn("return 'new'", file_a.read_text(encoding="utf-8"))

    def test_cli_subcommand_benchmark_ladder(self):
        args = build_parser().parse_args(["benchmark", "--model", "ling-3.0-tiny-q6k", "--ladder", "--json"])
        self.assertEqual(args.subcommand, "benchmark")
        self.assertEqual(args.benchmark_models, ["ling-3.0-tiny-q6k"])
        self.assertTrue(args.ladder)
        self.assertTrue(args.json)

    def test_cli_subcommand_skeletonize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_py = Path(temp_dir) / "sample.py"
            file_py.write_text(
                "def func_a():\n    return 1\n\ndef func_b():\n    return 2\n",
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                ["skeletonize", str(file_py), "--symbol", "func_b", "--json"]
            )
            from local_coding_agent.cli import handle_subcommand

            code = handle_subcommand(args)
            self.assertEqual(code, 0)

    def test_cli_subcommand_lint_patch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_py = Path(temp_dir) / "hello.py"
            file_py.write_text("def hello():\n    return 'old'\n", encoding="utf-8")
            patch = (
                "--- a/hello.py\n"
                "+++ b/hello.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def hello():\n"
                "-    return 'old'\n"
                "+    return 'new'\n"
            )
            args = build_parser().parse_args(
                ["lint-patch", "--workspace", temp_dir, "--patch", patch, "--json"]
            )
            from local_coding_agent.cli import handle_subcommand

            code = handle_subcommand(args)
            self.assertEqual(code, 0)

    def test_cli_speculative_drafts_flag(self):
        args = build_parser().parse_args(
            ["delegate", "--task", "{}", "--speculative-drafts", "2"]
        )
        self.assertEqual(args.subcommand, "delegate")
        self.assertEqual(args.speculative_drafts, 2)

    def test_cli_doctor_fix_flag(self):
        args = build_parser().parse_args(["doctor", "--fix", "--dry-run", "--json"])
        self.assertEqual(args.subcommand, "doctor")
        self.assertTrue(args.fix)
        self.assertTrue(args.dry_run)
        from local_coding_agent.cli import handle_subcommand

        code = handle_subcommand(args)
        self.assertEqual(code, 0)

    def test_cli_ui_subcommand(self):
        args = build_parser().parse_args(["ui", "--port", "9999"])
        self.assertEqual(args.subcommand, "ui")
        self.assertEqual(args.port, 9999)

    def test_cli_spill_read_subcommand(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from local_coding_agent.spill import SpillStore
            store = SpillStore(root_dir=temp_dir)
            ref = store.save_text("sess-cli", "hello\nworld\n", source_tool="test", suggested_name="data.txt")
            args = build_parser().parse_args(["spill-read", ref.locator, "--json"])
            self.assertEqual(args.subcommand, "spill-read")
            from local_coding_agent.cli import handle_subcommand
            code = handle_subcommand(args)
            self.assertEqual(code, 0)

    def test_cli_grep_subcommand(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            p = Path(temp_dir) / "sample.py"
            p.write_text("def find_me_symbol():\n    return 42\n", encoding="utf-8")
            args = build_parser().parse_args(["grep", "find_me_symbol", "--workspace", temp_dir, "--json"])
            self.assertEqual(args.subcommand, "grep")
            from local_coding_agent.cli import handle_subcommand
            code = handle_subcommand(args)
            self.assertEqual(code, 0)

    def test_cli_lsp_subcommand(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            p = Path(temp_dir) / "mod.py"
            p.write_text("class MyService:\n    def execute(self):\n        return True\n", encoding="utf-8")
            args = build_parser().parse_args(["lsp", "--operation", "symbols", "--file", str(p), "--workspace", temp_dir, "--json"])
            self.assertEqual(args.subcommand, "lsp")
            from local_coding_agent.cli import handle_subcommand
            code = handle_subcommand(args)
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()










