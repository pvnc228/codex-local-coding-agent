import json
import tempfile
import unittest
from pathlib import Path

from local_coding_agent import (
    DirectCodingAdapter,
    ServiceError,
    ServiceRequest,
    WorkspaceRegistry,
)
from local_coding_agent.task import TaskEnvelope


class CountingModel:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or {
            "status": "candidate",
            "summary": "готово",
            "patch": "",
            "checks": [],
            "risks": [],
        }

    def chat(self, messages, *, tools):
        self.calls += 1
        return {
            "message": {
                "role": "assistant",
                "content": json.dumps(
                    self.result,
                    ensure_ascii=False,
                ),
            }
        }


class DirectCodingAdapterTests(unittest.TestCase):
    def test_duplicate_request_is_idempotent_and_does_not_call_model_twice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = CountingModel()
            adapter = DirectCodingAdapter(
                WorkspaceRegistry({"repo": workspace}),
                model_factory=lambda profile: model,
            )
            request = ServiceRequest(
                request_id="request-1",
                workspace_ref="repo",
                task=TaskEnvelope(
                    id="service-read",
                    goal="вернуть результат",
                    files=("value.py",),
                ),
                model_profile="qwen2.5-1.5b",
            )

            first = adapter.submit(request)
            second = adapter.submit(request)

        self.assertEqual(first.status, "accepted")
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(model.calls, 1)

    def test_workspace_and_profile_policy_errors_are_machine_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            adapter = DirectCodingAdapter(WorkspaceRegistry({"repo": workspace}))
            task = TaskEnvelope(
                id="service-policy",
                goal="вернуть результат",
                files=("value.py",),
            )

            with self.assertRaises(ServiceError) as missing:
                adapter.submit(
                    ServiceRequest(
                        request_id="missing-workspace",
                        workspace_ref="missing",
                        task=task,
                        model_profile="qwen2.5-1.5b",
                    )
                )
            with self.assertRaises(ServiceError) as unknown:
                adapter.submit(
                    ServiceRequest(
                        request_id="unknown-profile",
                        workspace_ref="repo",
                        task=task,
                        model_profile="not-allowlisted",
                    )
                )

        self.assertEqual(missing.exception.kind, "workspace_not_registered")
        self.assertEqual(unknown.exception.kind, "unknown_model_profile")

    def test_reused_request_id_with_changed_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = CountingModel()
            adapter = DirectCodingAdapter(
                WorkspaceRegistry({"repo": workspace}),
                model_factory=lambda profile: model,
            )
            base = dict(
                request_id="request-conflict",
                workspace_ref="repo",
                task=TaskEnvelope(
                    id="service-conflict",
                    goal="вернуть результат",
                    files=("value.py",),
                ),
                model_profile="qwen2.5-1.5b",
            )
            adapter.submit(ServiceRequest(**base))

            with self.assertRaises(ServiceError) as conflict:
                adapter.submit(
                    ServiceRequest(
                        **{**base, "model_profile": "qwen2.5-coder"}
                    )
                )

        self.assertEqual(conflict.exception.kind, "idempotency_conflict")
        self.assertEqual(model.calls, 1)

    def test_mapping_round_trip_preserves_utf8_and_enforces_attempt_budget(self):
        request = ServiceRequest.from_mapping(
            {
                "request_id": "utf8-request",
                "workspace_ref": "repo",
                "task": {
                    "id": "utf8-task",
                    "goal": "сохранить русский текст",
                    "files": ["value.py"],
                    "context": "контекст",
                    "constraints": ["не менять API"],
                    "checks": [],
                    "acceptance": ["UTF-8"],
                },
                "model_profile": "qwen2.5-1.5b",
                "attempt_budget": 3,
            }
        )

        self.assertEqual(request.as_dict()["task"]["goal"], "сохранить русский текст")
        self.assertEqual(ServiceRequest.from_mapping(request.as_dict()), request)
        with self.assertRaises(ValueError):
            ServiceRequest(
                request_id="too-many",
                workspace_ref="repo",
                task=request.task,
                model_profile="qwen2.5-1.5b",
                attempt_budget=11,
            )

    def test_service_keeps_controller_owned_fields_out_of_model_control(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            model = CountingModel(
                {
                    "status": "candidate",
                    "summary": "подделано",
                    "patch": "",
                    "checks": [],
                    "risks": [],
                    "audit": [{"event": "forged"}],
                    "applied": True,
                }
            )
            adapter = DirectCodingAdapter(
                WorkspaceRegistry({"repo": workspace}),
                model_factory=lambda profile: model,
            )
            result = adapter.submit(
                ServiceRequest(
                    request_id="controller-fields",
                    workspace_ref="repo",
                    task=TaskEnvelope(
                        id="controller-fields-task",
                        goal="вернуть результат",
                        files=("value.py",),
                    ),
                    model_profile="qwen2.5-1.5b",
                )
            )

        self.assertEqual(result.status, "accepted")
        self.assertNotIn("applied", result.as_dict())
        self.assertNotIn("forged", json.dumps(result.as_dict(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
