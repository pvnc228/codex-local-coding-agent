import json
import tempfile
import unittest
from pathlib import Path

from local_coding_agent.stats import (
    DelegationStats,
    JsonlStatsSink,
    TimedDelegationStats,
)


def _accepted():
    return {"status": "accepted", "audit": [{"event": "model_request"}, {"event": "tool_call"}]}


def _failed(kind):
    return {"status": "failed", "error": {"kind": kind}, "audit": []}


class DelegationStatsTests(unittest.TestCase):
    def test_record_accumulates_statuses_and_audit_counts(self):
        stats = DelegationStats()
        stats.record(_accepted(), model="a", latency_ns=1_000_000)
        stats.record(_failed("context_limit"), model="a", latency_ns=2_000_000)

        snapshot = stats.snapshot()

        self.assertEqual(snapshot["total"], 2)
        self.assertEqual(snapshot["by_status"], {"accepted": 1, "failed": 1})
        self.assertEqual(snapshot["by_model"], {"a": 2})
        self.assertEqual(snapshot["by_error_kind"], {"context_limit": 1})
        self.assertEqual(snapshot["model_calls"], 1)
        self.assertEqual(snapshot["tool_calls"], 1)
        self.assertEqual(snapshot["latency"]["count"], 2)
        self.assertEqual(snapshot["latency"]["avg_ms"], 1.5)
        self.assertEqual(snapshot["latency"]["min_ms"], 1.0)
        self.assertEqual(snapshot["latency"]["max_ms"], 2.0)

    def test_snapshot_without_latency_leaves_none(self):
        stats = DelegationStats()
        stats.record(_accepted())

        self.assertIsNone(stats.snapshot()["latency"]["avg_ms"])

    def test_timed_stats_records_and_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sink = JsonlStatsSink(Path(temp_dir) / "stats.jsonl")
            stats = DelegationStats()
            timed = TimedDelegationStats(stats, sink=sink)

            def delegate(caller_id, request):
                return _accepted()

            result = timed(delegate, "caller", type("R", (), {"request_id": "r1"})(), model="m")

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(stats.snapshot()["total"], 1)
            lines = (Path(temp_dir) / "stats.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["request_id"], "r1")
            self.assertEqual(record["model"], "m")
            self.assertEqual(record["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
