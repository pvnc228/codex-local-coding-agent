"""Transport-neutral, proposal-only entry point for bounded delegations."""

from __future__ import annotations

import copy
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable, Mapping

from .controller import Controller, ModelClient
from .ollama_adapter import ModelProfile, OllamaClient
from .profiles import get_profile
from .repository_tools import ToolPolicyError
from .task import TaskEnvelope


@dataclass(frozen=True)
class DelegationRequest:
    """A host-approved request that is independent of any transport schema."""

    request_id: str
    workspace_ref: str
    model_profile: str
    task: TaskEnvelope

    def __post_init__(self) -> None:
        for name, value in (
            ("request_id", self.request_id),
            ("workspace_ref", self.workspace_ref),
            ("model_profile", self.model_profile),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"delegation field '{name}' must be a non-empty string")
        if not isinstance(self.task, TaskEnvelope):
            raise ValueError("delegation field 'task' must be a TaskEnvelope")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DelegationRequest":
        if not isinstance(value, Mapping):
            raise ValueError("delegation request must be an object")
        task = value.get("task")
        if not isinstance(task, Mapping):
            raise ValueError("delegation field 'task' must be an object")
        return cls(
            request_id=value.get("request_id"),
            workspace_ref=value.get("workspace_ref"),
            model_profile=value.get("model_profile"),
            task=TaskEnvelope.from_mapping(task),
        )


@dataclass
class _CachedResult:
    fingerprint: str
    completed: Event
    result: dict[str, Any] | None = None


class DelegationService:
    """Direct adapter that resolves only host-registered workspaces and profiles.

    The service deliberately does not expose ``apply`` or arbitrary paths.  It is
    the R5.1 core seam; transports may adapt their request formats to this API,
    but policy and result ownership remain in ``Controller``.
    """

    def __init__(
        self,
        workspaces: Mapping[str, str | Path],
        *,
        model_factory: Callable[[ModelProfile], ModelClient] = OllamaClient,
        max_turns: int = 4,
        max_cached_results: int = 256,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if max_cached_results <= 0:
            raise ValueError("max_cached_results must be positive")
        registered: dict[str, Path] = {}
        for reference, raw_path in workspaces.items():
            if not isinstance(reference, str) or not reference.strip():
                raise ValueError("workspace references must be non-empty strings")
            path = Path(raw_path).resolve()
            if not path.is_dir():
                raise ValueError(f"registered workspace is not a directory: {reference!r}")
            registered[reference] = path
        self._workspaces = registered
        self._model_factory = model_factory
        self._max_turns = max_turns
        self._max_cached_results = max_cached_results
        self._cache: OrderedDict[tuple[str, str, str], _CachedResult] = OrderedDict()
        self._cache_lock = RLock()

    def delegate(self, caller_id: str, request: DelegationRequest) -> dict[str, Any]:
        """Run one proposal-only delegation with caller-scoped idempotency."""

        if not isinstance(caller_id, str) or not caller_id.strip():
            return self._policy_failure("invalid_caller", "caller_id must be a non-empty string")
        if not isinstance(request, DelegationRequest):
            return self._policy_failure("invalid_request", "request must be a DelegationRequest")

        cache_key = (caller_id, request.workspace_ref, request.request_id)
        fingerprint = self._fingerprint(request)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is None:
                if len(self._cache) >= self._max_cached_results:
                    for stale_key, stale_record in self._cache.items():
                        if stale_record.completed.is_set():
                            self._cache.pop(stale_key)
                            break
                    else:
                        return self._policy_failure(
                            "idempotency_capacity",
                            "in-memory idempotency capacity is exhausted by active requests",
                        )
                cached = _CachedResult(fingerprint=fingerprint, completed=Event())
                self._cache[cache_key] = cached
                owner = True
            elif cached.fingerprint != fingerprint:
                return self._policy_failure(
                    "idempotency_conflict",
                    "request_id was already used with a different request payload",
                )
            else:
                self._cache.move_to_end(cache_key)
                owner = False

        if not owner:
            cached.completed.wait()
            assert cached.result is not None
            return copy.deepcopy(cached.result)

        try:
            result = self._execute(request)
        except (OSError, ToolPolicyError, ValueError) as error:
            result = self._policy_failure("controller_policy", str(error))
        except Exception:
            # This is the transport boundary: unexpected infrastructure errors
            # must still complete the reservation so duplicate callers cannot
            # wait forever on an in-flight idempotency key.
            result = self._policy_failure("controller_error", "controller execution failed")
        normalized = self._normalize_result(result)
        with self._cache_lock:
            cached.result = copy.deepcopy(normalized)
            cached.completed.set()
            self._evict_completed_results()
        return copy.deepcopy(normalized)

    def _execute(self, request: DelegationRequest) -> dict[str, Any]:
        workspace = self._workspaces.get(request.workspace_ref)
        if workspace is None:
            return self._policy_failure(
                "unknown_workspace",
                f"workspace_ref is not registered: {request.workspace_ref!r}",
            )
        try:
            profile = get_profile(request.model_profile)
        except ValueError:
            return self._policy_failure(
                "unknown_model_profile",
                f"model_profile is not allowlisted: {request.model_profile!r}",
            )
        model = self._model_factory(profile)
        # apply is intentionally absent: direct delegation always remains a proposal.
        return Controller(model, workspace, max_turns=self._max_turns).run(request.task)

    def _evict_completed_results(self) -> None:
        while len(self._cache) > self._max_cached_results:
            for key, record in self._cache.items():
                if record.completed.is_set():
                    self._cache.pop(key)
                    break
            else:
                # Active reservations must keep their idempotency boundary.
                return

    @staticmethod
    def _normalize_result(result: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(result)
        normalized["applied"] = False
        return normalized

    @staticmethod
    def _fingerprint(request: DelegationRequest) -> str:
        return json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _policy_failure(kind: str, message: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": {"kind": kind, "message": message},
            "audit": [{"event": "policy_rejected", "kind": kind}],
        }
