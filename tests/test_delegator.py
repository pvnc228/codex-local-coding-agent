import unittest

from local_coding_agent.atomizer import TaskBudget
from local_coding_agent.delegator import DelegatingAgent, is_decomposable_failure
from local_coding_agent.task import TaskEnvelope


def _envelope(task_id, files):
    return TaskEnvelope(id=task_id, goal="разобрать", files=files)


class DelegatingAgentTests(unittest.TestCase):
    def _agent(self, delegate, **kwargs):
        return DelegatingAgent(
            delegate,
            workspace_ref="repo",
            model_profile="qwen2.5-1.5b",
            budget=TaskBudget(max_files=2),
            **kwargs,
        )

    def test_is_decomposable_failure_detects_known_kinds(self):
        for kind in ("preflight_rejected", "context_limit", "max_turns", "too_many_files"):
            with self.subTest(kind=kind):
                self.assertTrue(is_decomposable_failure({"error": {"kind": kind}}))
        self.assertFalse(is_decomposable_failure({"error": {"kind": "cancelled"}}))
        self.assertFalse(is_decomposable_failure({"status": "accepted"}))

    def test_successful_child_is_not_redecomposed(self):
        calls = []

        def delegate(caller_id, request):
            calls.append(request.request_id)
            return {"status": "accepted", "summary": "ok"}

        result = self._agent(delegate).run(
            "caller", _envelope("wide", ("a.py", "b.py", "c.py"))
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["splits"], 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            {leaf["task_id"] for leaf in result["children"]}, {"wide#1", "wide#2"}
        )

    def test_decomposable_failure_splits_further_per_file(self):
        outcomes = {}

        def delegate(caller_id, request):
            outcomes[request.request_id] = request.task
            if request.task.id == "wide#1":
                return {"status": "failed", "error": {"kind": "context_limit"}}
            return {"status": "accepted", "summary": "ok"}

        result = self._agent(delegate, max_depth=3).run(
            "caller", _envelope("wide", ("a.py", "b.py", "c.py", "d.py"))
        )

        self.assertEqual(result["status"], "accepted")
        self.assertGreaterEqual(result["splits"], 1)
        self.assertIn("wide#1@1.0", outcomes)
        self.assertIn("wide#1@1.1", outcomes)

    def test_non_decomposable_failure_stops(self):
        calls = []

        def delegate(caller_id, request):
            calls.append(request.request_id)
            return {"status": "failed", "error": {"kind": "cancelled"}}

        result = self._agent(delegate).run("caller", _envelope("wide", ("a.py", "b.py")))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["splits"], 0)
        self.assertEqual(len(calls), 1)

    def test_depth_cap_stops_endless_redecomposition(self):
        def delegate(caller_id, request):
            return {"status": "failed", "error": {"kind": "preflight_rejected"}}

        result = self._agent(delegate, max_depth=2).run(
            "caller", _envelope("wide", ("a.py",))
        )

        self.assertLessEqual(result["splits"], 1)
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
