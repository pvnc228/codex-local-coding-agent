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
