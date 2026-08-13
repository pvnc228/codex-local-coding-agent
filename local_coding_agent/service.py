"""Transport-neutral service seam for bounded coding requests."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from .controller import Controller
from .ollama_adapter import ModelProfile, OllamaClient
from .profiles import get_profile
from .task import TaskEnvelope


MAX_ATTEMPT_BUDGET = 10
_OPAQUE_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ServiceError(ValueError):
    """A machine-readable request or policy error at the service seam."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


def _validate_handle(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_HANDLE.fullmatch(value):
        raise ValueError(f"{field} must be a non-empty opaque handle")
    return value


@dataclass(frozen=True)
class ServiceRequest:
    """Validated transport-neutral request accepted by direct adapters."""

    request_id: str
    workspace_ref: str
    task: TaskEnvelope
    model_profile: str
    attempt_budget: int = 1

    def __post_init__(self) -> None:
        _validate_handle(self.request_id, "request_id")
        _validate_handle(self.workspace_ref, "workspace_ref")
        if not isinstance(self.task, TaskEnvelope):
            raise TypeError("task must be a TaskEnvelope")
        if not isinstance(self.model_profile, str) or not self.model_profile.strip():
            raise ValueError("model_profile must be a non-empty profile name")
        if (
            isinstance(self.attempt_budget, bool)
            or not isinstance(self.attempt_budget, int)
            or not 1 <= self.attempt_budget <= MAX_ATTEMPT_BUDGET
        ):
            raise ValueError(
                f"attempt_budget must be an integer between 1 and {MAX_ATTEMPT_BUDGET}"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ServiceRequest":
        if not isinstance(value, Mapping):
            raise ValueError("service request must be an object")
        task = value.get("task")
        if not isinstance(task, Mapping):
            raise ValueError("service request field 'task' must be an object")
        return cls(
            request_id=value.get("request_id"),
            workspace_ref=value.get("workspace_ref"),
            task=TaskEnvelope.from_mapping(task),
            model_profile=value.get("model_profile"),
            attempt_budget=value.get("attempt_budget", 1),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workspace_ref": self.workspace_ref,
            "task": {
                "id": self.task.id,
                "goal": self.task.goal,
                "files": list(self.task.files),
                "context": self.task.context,
                "constraints": list(self.task.constraints),
                "checks": list(self.task.checks),
                "acceptance": list(self.task.acceptance),
            },
            "model_profile": self.model_profile,
            "attempt_budget": self.attempt_budget,
        }


@dataclass(frozen=True)
class ServiceResult:
    """Immutable wrapper preserving the controller-owned result shape."""

    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("service result payload must be an object")
        if not isinstance(self.payload.get("status"), str):
            raise ValueError("service result must contain a string status")

    @property
    def status(self) -> str:
        return self.payload["status"]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


class WorkspaceRegistry:
    """Resolve configured opaque workspace handles without accepting paths."""

    def __init__(self, workspaces: Mapping[str, str | Path] | None = None) -> None:
        self._workspaces: dict[str, Path] = {}
        for workspace_ref, workspace in (workspaces or {}).items():
            self.register(workspace_ref, workspace)

    def register(self, workspace_ref: str, workspace: str | Path) -> None:
        _validate_handle(workspace_ref, "workspace_ref")
        root = Path(workspace).resolve()
        if not root.is_dir():
            raise ValueError(f"workspace directory does not exist: {root}")
        self._workspaces[workspace_ref] = root

    def resolve(self, workspace_ref: str) -> Path:
        _validate_handle(workspace_ref, "workspace_ref")
        try:
            return self._workspaces[workspace_ref]
        except KeyError as error:
            raise ServiceError(
                "workspace_not_registered",
                f"workspace_ref is not registered: {workspace_ref}",
            ) from error


ModelFactory = Callable[[ModelProfile], Any]


class DirectCodingAdapter:
    """In-process adapter that delegates exactly one bounded request to Controller."""

    def __init__(
        self,
        workspaces: WorkspaceRegistry,
        *,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._model_factory = model_factory or OllamaClient
        self._completed: dict[tuple[str, str], tuple[str, ServiceResult]] = {}
        self._lock = RLock()

    def submit(self, request: ServiceRequest) -> ServiceResult:
        if not isinstance(request, ServiceRequest):
            raise TypeError("request must be a ServiceRequest")
        fingerprint = self._fingerprint(request)
        key = (request.workspace_ref, request.request_id)

        with self._lock:
            previous = self._completed.get(key)
            if previous is not None:
                previous_fingerprint, previous_result = previous
                if previous_fingerprint != fingerprint:
                    raise ServiceError(
                        "idempotency_conflict",
                        "request_id was already used with a different request",
                    )
                return previous_result

            workspace = self._workspaces.resolve(request.workspace_ref)
            try:
                profile = get_profile(request.model_profile)
            except ValueError as error:
                raise ServiceError("unknown_model_profile", str(error)) from error

            model = self._model_factory(profile)
            result = Controller(
                model,
                workspace,
                max_retries=request.attempt_budget - 1,
            ).run(request.task)
            service_result = ServiceResult(result)
            self._completed[key] = (fingerprint, service_result)
            return service_result

    @staticmethod
    def _fingerprint(request: ServiceRequest) -> str:
        encoded = json.dumps(
            request.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return encoded.hex()
