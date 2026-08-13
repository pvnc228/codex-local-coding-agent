import json
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread

from local_coding_agent.service import DelegationRequest, DelegationService
from local_coding_agent.task import TaskEnvelope


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def chat(self, messages, *, tools=None):
        self.calls += 1
        return self.response


class BlockingFakeModel(FakeModel):
    def __init__(self, response, entered, release):
        super().__init__(response)
        self.entered = entered
        self.release = release

    def chat(self, messages, *, tools=None):
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=5)
        return self.response


class DelegationServiceTests(unittest.TestCase):
    def _request(self, *, request_id="request-1", goal="прочитать файл", profile="qwen2.5-1.5b"):
        return DelegationRequest(
            request_id=request_id,
            workspace_ref="fixture",
            model_profile=profile,
            task=TaskEnvelope(id="task-1", goal=goal, files=("allowed.py",)),
        )

    def _candidate(self, *, patch=""):
        return {
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "candidate",
                        "summary": "готово",
                        "patch": patch,
                        "checks": [],
                        "risks": [],
                        "audit": [{"event": "forged"}],
                        "applied": True,
                    },
                    ensure_ascii=False,
                ),
            }
        }

    def test_delegates_registered_workspace_proposal_only_and_caches_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            target = workspace / "allowed.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            patch = (
                "diff --git a/allowed.py b/allowed.py\n"
                "--- a/allowed.py\n"
                "+++ b/allowed.py\n"
                "@@ -1 +1 @@\n"
                "-VALUE = 1\n"
                "+VALUE = 2\n"
            )
            model = FakeModel(self._candidate(patch=patch))
            service = DelegationService(
                {"fixture": workspace},
                model_factory=lambda profile: model,
            )

            first = service.delegate("caller-a", self._request())
            second = service.delegate("caller-a", self._request())
            unchanged = target.read_text(encoding="utf-8")

        self.assertEqual(first["status"], "accepted")
        self.assertFalse(first.get("applied", False))
        self.assertNotIn({"event": "forged"}, first["audit"])
        self.assertEqual(unchanged, "VALUE = 1\n")
        self.assertEqual(model.calls, 1)
        self.assertEqual(first, second)

    def test_rejects_unregistered_workspace_and_unknown_profile_without_model_call(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            service = DelegationService(
                {"fixture": temp_dir},
                model_factory=lambda profile: calls.append(profile),
            )
            unknown_workspace = service.delegate(
                "caller-a",
                DelegationRequest(
                    request_id="request-1",
                    workspace_ref="unknown",
                    model_profile="qwen2.5-1.5b",
                    task=TaskEnvelope(id="task-1", goal="read", files=("allowed.py",)),
                ),
            )
            unknown_profile = service.delegate(
                "caller-a",
                self._request(request_id="request-2", profile="http://untrusted.invalid"),
            )

        self.assertEqual(unknown_workspace["error"]["kind"], "unknown_workspace")
        self.assertEqual(unknown_profile["error"]["kind"], "unknown_model_profile")
        self.assertEqual(calls, [])

    def test_rejects_reused_request_id_with_a_different_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = FakeModel(self._candidate())
            service = DelegationService(
                {"fixture": workspace},
                model_factory=lambda profile: model,
            )

            service.delegate("caller-a", self._request())
            conflict = service.delegate("caller-a", self._request(goal="другая задача"))

        self.assertEqual(conflict["status"], "failed")
        self.assertEqual(conflict["error"]["kind"], "idempotency_conflict")
        self.assertEqual(model.calls, 1)

    def test_normalizes_controller_policy_errors_into_terminal_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for index in range(6):
                (workspace / f"allowed-{index}.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = FakeModel(self._candidate())
            service = DelegationService(
                {"fixture": workspace},
                model_factory=lambda profile: model,
            )
            request = DelegationRequest(
                request_id="too-many-files",
                workspace_ref="fixture",
                model_profile="qwen2.5-1.5b",
                task=TaskEnvelope(
                    id="wide-task",
                    goal="read",
                    files=tuple(f"allowed-{index}.py" for index in range(6)),
                ),
            )
            result = service.delegate("caller-a", request)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["kind"], "controller_policy")
        self.assertFalse(result["applied"])
        self.assertEqual(model.calls, 0)

    def test_unexpected_model_factory_error_completes_and_caches_terminal_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            factory_calls = []

            def broken_factory(profile):
                factory_calls.append(profile.name)
                raise RuntimeError("simulated infrastructure failure")

            service = DelegationService({"fixture": workspace}, model_factory=broken_factory)
            first = service.delegate("caller-a", self._request())
            second = service.delegate("caller-a", self._request())

        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["error"]["kind"], "controller_error")
        self.assertEqual(first, second)
        self.assertEqual(factory_calls, ["qwen2.5-1.5b"])

    def test_concurrent_duplicate_requests_share_one_controller_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            entered, release = Event(), Event()
            model = BlockingFakeModel(self._candidate(), entered, release)
            service = DelegationService(
                {"fixture": workspace},
                model_factory=lambda profile: model,
            )
            results = []
            first = Thread(target=lambda: results.append(service.delegate("caller-a", self._request())))
            second = Thread(target=lambda: results.append(service.delegate("caller-a", self._request())))
            first.start()
            self.assertTrue(entered.wait(timeout=2))
            second.start()
            release.set()
            first.join(timeout=3)
            second.join(timeout=3)

        self.assertEqual(model.calls, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])

    def test_completed_idempotency_results_are_bounded_and_evictable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = FakeModel(self._candidate())
            service = DelegationService(
                {"fixture": workspace},
                model_factory=lambda profile: model,
                max_cached_results=1,
            )
            service.delegate("caller-a", self._request(request_id="one"))
            service.delegate("caller-a", self._request(request_id="two"))
            service.delegate("caller-a", self._request(request_id="one"))

        self.assertEqual(model.calls, 3)

    def test_request_rejects_blank_transport_identifiers(self):
        task = TaskEnvelope(id="task-1", goal="read", files=("allowed.py",))
        with self.assertRaises(ValueError):
            DelegationRequest("", "fixture", "qwen2.5-1.5b", task)
        with self.assertRaises(ValueError):
            DelegationRequest("request-1", "", "qwen2.5-1.5b", task)
        with self.assertRaises(ValueError):
            DelegationRequest("request-1", "fixture", "", task)


if __name__ == "__main__":
    unittest.main()
