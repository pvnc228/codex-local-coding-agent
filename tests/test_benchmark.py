import json
import tempfile
import unittest
from pathlib import Path

from local_coding_agent.benchmark import (
    BenchmarkCase,
    InstrumentedModel,
    default_cases,
    run_case,
    summarize_results,
)
from local_coding_agent.task import TaskEnvelope


class FakeBenchmarkModel:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def chat(self, messages, *, tools=None):
        self.calls += 1
        return self.response


class SequenceBenchmarkModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, *, tools=None):
        return self.responses.pop(0)


def restricted_process_oracle(workspace):
    read = _load_function(workspace / "src/value.py", "read")
    return read() == "restricted", "oracle process allowed an unsafe import"


class BenchmarkTests(unittest.TestCase):
    def test_default_cases_are_comparable_and_have_unique_ids(self):
        cases = default_cases()

        self.assertGreaterEqual(len(cases), 3)
        self.assertEqual(len({case.id for case in cases}), len(cases))
        for case in cases:
            self.assertIsInstance(case, BenchmarkCase)
            self.assertEqual(set(case.task.files), set(case.fixture))
            self.assertTrue(case.expected_files)

    def test_run_case_applies_candidate_only_in_isolated_fixture_and_scores_metrics(self):
        case = BenchmarkCase(
            id="replace-value",
            task=TaskEnvelope(
                id="replace-value",
                goal="заменить значение",
                files=("src/value.py",),
            ),
            fixture={"src/value.py": "VALUE = 1\n"},
            expected_files={"src/value.py": "VALUE = 2\n"},
        )
        model = FakeBenchmarkModel(
            {
                "total_duration": 2_000_000,
                "load_duration": 500_000,
                "prompt_eval_count": 20,
                "prompt_eval_duration": 700_000,
                "eval_count": 8,
                "eval_duration": 800_000,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "candidate",
                            "summary": "значение заменено",
                            "patch": (
                                "diff --git a/src/value.py b/src/value.py\n"
                                "--- a/src/value.py\n"
                                "+++ b/src/value.py\n"
                                "@@ -1 +1 @@\n"
                                "-VALUE = 1\n"
                                "+VALUE = 2\n"
                            ),
                            "checks": [],
                            "risks": [],
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        )

        result = run_case(model, case)

        self.assertTrue(result.correct)
        self.assertTrue(result.loop_reliable)
        self.assertEqual(result.model_calls, 1)
        self.assertEqual(result.eval_count, 8)
        self.assertEqual(result.prompt_tokens, 20)
        self.assertGreaterEqual(result.wall_time_ms, 0)
        self.assertEqual(Path("src/value.py").exists(), False)

    def test_instrumented_model_preserves_response_and_accumulates_ollama_metrics(self):
        response = {
            "total_duration": 10,
            "prompt_eval_count": 3,
            "eval_count": 4,
            "message": {"role": "assistant", "content": "{}"},
        }
        model = InstrumentedModel(FakeBenchmarkModel(response))

        self.assertIs(model.chat([], tools=[]), response)
        self.assertEqual(model.model_calls, 1)
        self.assertEqual(model.prompt_tokens, 3)
        self.assertEqual(model.eval_count, 4)
        self.assertEqual(model.total_duration_ns, 10)

    def test_instrumented_model_keeps_compatible_content_tool_patch(self):
        patch = (
            "diff --git a/src/value.py b/src/value.py\n"
            "--- a/src/value.py\n"
            "+++ b/src/value.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        response = {
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {"name": "propose_patch", "arguments": {"patch": patch}}
                ),
            }
        }
        model = InstrumentedModel(FakeBenchmarkModel(response))

        model.chat([], tools=[])

        self.assertEqual(model.proposed_patches, [patch])

    def test_benchmark_oracle_runs_in_restricted_child_process(self):
        case = BenchmarkCase(
            id="restricted-oracle",
            task=TaskEnvelope(
                id="restricted-oracle",
                goal="проверить ограничение oracle",
                files=("src/value.py",),
            ),
            fixture={"src/value.py": "def read():\n    return 'original'\n"},
            expected_files={
                "src/value.py": (
                    "def read():\n"
                    "    try:\n"
                    "        import os\n"
                    "        return 'unsafe'\n"
                    "    except ImportError:\n"
                    "        return 'restricted'\n"
                )
            },
            oracle=restricted_process_oracle,
        )
        patch = (
            "diff --git a/src/value.py b/src/value.py\n"
            "--- a/src/value.py\n"
            "+++ b/src/value.py\n"
            "@@ -1,2 +1,6 @@\n"
            " def read():\n"
            "-    return 'original'\n"
            "+    try:\n"
            "+        import os\n"
            "+        return 'unsafe'\n"
            "+    except ImportError:\n"
            "+        return 'restricted'\n"
        )
        model = FakeBenchmarkModel(
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "candidate",
                            "summary": "ограничение oracle проверено",
                            "patch": patch,
                            "checks": [],
                            "risks": [],
                        }
                    ),
                }
            }
        )

        result = run_case(model, case)

        self.assertTrue(result.correct, result.patch_error)

    def test_benchmark_uses_content_tool_patch_as_fallback(self):
        patch = (
            "diff --git a/src/value.py b/src/value.py\n"
            "--- a/src/value.py\n"
            "+++ b/src/value.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        model = SequenceBenchmarkModel(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {"name": "propose_patch", "arguments": {"patch": patch}}
                        ),
                    }
                },
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "status": "candidate",
                                "summary": "proposal завершён",
                                "patch": "",
                                "checks": [],
                                "risks": [],
                            }
                        ),
                    }
                },
            ]
        )
        case = BenchmarkCase(
            id="content-tool-fallback",
            task=TaskEnvelope(
                id="content-tool-fallback",
                goal="заменить значение",
                files=("src/value.py",),
            ),
            fixture={"src/value.py": "VALUE = 1\n"},
            expected_files={"src/value.py": "VALUE = 2\n"},
        )

        result = run_case(model, case)

        self.assertTrue(result.correct)
        self.assertEqual(result.patch_source, "tool_proposal")

    def test_run_case_scores_search_replace_edits_proposal(self):
        case = BenchmarkCase(
            id="replace-value-edits",
            task=TaskEnvelope(
                id="replace-value-edits",
                goal="заменить значение",
                files=("src/value.py",),
            ),
            fixture={"src/value.py": "VALUE = 1\n"},
            expected_files={"src/value.py": "VALUE = 2\n"},
        )
        model = FakeBenchmarkModel(
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "candidate",
                            "summary": "значение заменено",
                            "edits": [
                                {"file": "src/value.py", "search": "VALUE = 1", "replace": "VALUE = 2"}
                            ],
                            "checks": [],
                            "risks": [],
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        )

        result = run_case(model, case)

        self.assertTrue(result.correct, result.patch_error)
        self.assertTrue(result.loop_reliable)
        self.assertEqual(result.model_calls, 1)

    def test_summarize_results_reports_correctness_and_reliability_rates(self):
        cases = default_cases()
        model = FakeBenchmarkModel(
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": "candidate",
                            "summary": "нет изменений",
                            "patch": "",
                            "checks": [],
                            "risks": [],
                        }
                    ),
                }
            }
        )
        results = [run_case(model, case) for case in cases[:2]]

        summary = summarize_results("fake", results)

        self.assertEqual(summary["model"], "fake")
        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["correctness_percent"], 0.0)
        self.assertEqual(summary["tool_loop_reliability_percent"], 100.0)
        self.assertEqual(summary["model_calls"], 2)


if __name__ == "__main__":
    unittest.main()
