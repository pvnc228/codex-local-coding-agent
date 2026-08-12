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
                "bonsai-64k:latest",
            ]
        )

        self.assertEqual(args.num_ctx, 16_384)
        self.assertTrue(args.unload_all)
        self.assertEqual(args.vram_limit_bytes, 1_000_000)
        self.assertEqual(args.keep_model, ["bonsai-64k:latest"])

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
                ".codex-run/bench.json",
            ]
        )

        self.assertTrue(args.benchmark)
        self.assertEqual(args.benchmark_models, ["ornith-9b"])
        self.assertEqual(args.benchmark_repeats, 2)
        self.assertEqual(args.benchmark_timeout_seconds, 120)
        self.assertEqual(str(args.benchmark_output), ".codex-run\\bench.json")


if __name__ == "__main__":
    unittest.main()
