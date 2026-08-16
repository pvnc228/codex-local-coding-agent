import json
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

    def test_cli_parser_accepts_task_file(self):
        args = build_parser().parse_args(["--task-file", "my_task.json"])
        self.assertEqual(args.task_file, Path("my_task.json"))
        self.assertIsNone(args.task)


if __name__ == "__main__":
    unittest.main()
