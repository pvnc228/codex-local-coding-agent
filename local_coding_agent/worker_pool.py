"""Bounded in-memory worker pool for proposal-only delegations."""

from __future__ import annotations

import copy
import json
import math
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Mapping

from .service import DelegationRequest


_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Job:
    job_id: str
    caller_id: str
    request_key: tuple[str, str, str]
    fingerprint: str
    request: DelegationRequest
    state: str = "queued"
    created_at: str = ""
    updated_at: str = ""
    result: dict[str, Any] | None = None
    cancel_event: threading.Event | None = None
    execution_complete: threading.Event | None = None
    completed: threading.Event | None = None


class BoundedWorkerPool:
    """Run service delegations with bounded queue and caller-scoped jobs.

    This is deliberately an in-memory execution primitive. It provides bounded
    overload behavior and cooperative cancellation for a future task adapter,
    but it does not claim durable persistence or MCP Tasks conformance.
    """

    def __init__(
        self,
        service: Any,
        *,
        max_workers: int = 1,
        max_queue: int = 16,
        max_completed_jobs: int = 256,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if max_queue < 0:
            raise ValueError("max_queue must be non-negative")
        if max_completed_jobs <= 0:
            raise ValueError("max_completed_jobs must be positive")
        self._service = service
        self._max_completed_jobs = max_completed_jobs
        self._condition = threading.Condition()
        self._queue: Deque[str] = deque()
        self._jobs: dict[str, _Job] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._max_workers = max_workers
        self._max_queue = max_queue
        self._active_workers = 0
        self._stopping = False
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"codex-worker-{index}",
                daemon=True,
            )
            for index in range(max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, caller_id: str, request: DelegationRequest) -> dict[str, Any]:
        """Queue one proposal-only request or return a bounded policy failure."""

        if not isinstance(caller_id, str) or not caller_id.strip():
            return self._failure("invalid_caller", "caller_id must be a non-empty string")
        if not isinstance(request, DelegationRequest):
            return self._failure("invalid_request", "request must be a DelegationRequest")

        request_key = (caller_id, request.workspace_ref, request.request_id)
        fingerprint = self._fingerprint(request)
        with self._condition:
            existing_id = self._idempotency.get(request_key)
            if existing_id is not None:
                existing = self._jobs.get(existing_id)
                if existing is not None:
                    if existing.fingerprint != fingerprint:
                        return self._failure(
                            "idempotency_conflict",
                            "request_id was already used with a different request payload",
                        )
                    return self._snapshot(existing)
                self._idempotency.pop(request_key, None)

            if self._stopping:
                return self._failure("pool_shutdown", "worker pool is shutting down")
            if self._active_workers + len(self._queue) >= self._max_workers + self._max_queue:
                return self._failure(
                    "queue_overload",
                    f"worker capacity is full at max_workers={self._max_workers}, "
                    f"max_queue={self._max_queue}",
                )

            job = _Job(
                job_id=uuid.uuid4().hex,
                caller_id=caller_id,
                request_key=request_key,
                fingerprint=fingerprint,
                request=request,
                created_at=_now_iso(),
                updated_at=_now_iso(),
                cancel_event=threading.Event(),
                execution_complete=threading.Event(),
                completed=threading.Event(),
            )
            self._jobs[job.job_id] = job
            self._idempotency[request_key] = job.job_id
            self._queue.append(job.job_id)
            self._condition.notify()
            return self._snapshot(job)

    def get(self, caller_id: str, job_id: str) -> dict[str, Any]:
        """Return a caller-scoped job snapshot without waiting."""

        with self._condition:
            job = self._owned_job(caller_id, job_id)
            if job is None:
                return self._failure("unknown_job", "job is unknown or belongs to another caller")
            return self._snapshot(job)

    def wait(self, caller_id: str, job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
        """Wait at most ``timeout`` seconds, then return the current snapshot."""

        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            return self._failure("invalid_timeout", "timeout must be a finite non-negative number")
        with self._condition:
            job = self._owned_job(caller_id, job_id)
            if job is None:
                return self._failure("unknown_job", "job is unknown or belongs to another caller")
            completed = job.completed
        assert completed is not None
        completed.wait(timeout)
        with self._condition:
            return self._snapshot(job)

    def cancel(self, caller_id: str, job_id: str) -> dict[str, Any]:
        """Request cooperative cancellation for a queued or running job."""

        with self._condition:
            job = self._owned_job(caller_id, job_id)
            if job is None:
                return self._failure("unknown_job", "job is unknown or belongs to another caller")
            assert job.cancel_event is not None
            if job.state == "queued":
                try:
                    self._queue.remove(job.job_id)
                except ValueError:
                    # A worker may have claimed the job between the state check
                    # and removal. The worker owns the running transition.
                    if job.state != "queued":
                        return self._snapshot(job)
                job.cancel_event.set()
                job.state = "cancelled"
                job.updated_at = _now_iso()
                self._complete_locked(job)
                self._condition.notify_all()
                return self._snapshot(job)
            if job.state == "working":
                job.cancel_event.set()
                snapshot = self._snapshot(job)
                snapshot["cancellation_requested"] = True
                return snapshot
            return self._snapshot(job)

    def shutdown(self, *, wait: bool = True, timeout: float = 5.0) -> bool:
        """Stop workers and cancel pending work with a bounded join."""

        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be a finite non-negative number")
        with self._condition:
            self._stopping = True
            while self._queue:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.state != "queued":
                    continue
                assert job.cancel_event is not None
                job.cancel_event.set()
                job.state = "cancelled"
                self._complete_locked(job)
            for job in self._jobs.values():
                if job.state == "working" and job.cancel_event is not None:
                    job.cancel_event.set()
            self._condition.notify_all()

        if not wait:
            return not any(worker.is_alive() for worker in self._workers)
        deadline = time.monotonic() + timeout
        for worker in self._workers:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(remaining)
        return not any(worker.is_alive() for worker in self._workers)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    self._condition.wait()
                if not self._queue and self._stopping:
                    return
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.state == "cancelled":
                    continue
                job.state = "working"
                job.updated_at = _now_iso()
                self._active_workers += 1

            try:
                assert job.cancel_event is not None
                assert job.execution_complete is not None
                result = self._service.delegate(
                    job.caller_id,
                    job.request,
                    cancel_event=job.cancel_event,
                    completion_event=job.execution_complete,
                )
                if not isinstance(result, Mapping):
                    raise TypeError("service returned a non-object result")
                result = dict(result)
            except Exception:  # noqa: BLE001 - worker boundary must terminate the job.
                result = self._failure("worker_error", "delegation worker failed")

            assert job.execution_complete is not None
            # A service may finish its public call before a cancellable model
            # thread has actually terminated. Keep the worker slot occupied
            # until the service reports that physical execution is complete.
            job.execution_complete.wait()

            with self._condition:
                self._active_workers -= 1
                if job.cancel_event is not None and job.cancel_event.is_set():
                    job.state = "cancelled"
                    job.result = None
                else:
                    job.result = copy.deepcopy(result)
                    job.state = "failed" if result.get("status") == "failed" else "completed"
                job.updated_at = _now_iso()
                self._complete_locked(job)
                self._condition.notify_all()

    def _complete_locked(self, job: _Job) -> None:
        assert job.completed is not None
        job.completed.set()
        self._evict_completed_locked()

    def _evict_completed_locked(self) -> None:
        terminal_jobs = sum(job.state in _TERMINAL_STATES for job in self._jobs.values())
        while terminal_jobs > self._max_completed_jobs:
            candidate_id = next(
                (job_id for job_id, job in self._jobs.items() if job.state in _TERMINAL_STATES),
                None,
            )
            if candidate_id is None:
                return
            candidate = self._jobs.pop(candidate_id)
            if self._idempotency.get(candidate.request_key) == candidate_id:
                self._idempotency.pop(candidate.request_key, None)
            terminal_jobs -= 1

    def _owned_job(self, caller_id: str, job_id: str) -> _Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.caller_id != caller_id:
            return None
        return job

    @staticmethod
    def _snapshot(job: _Job) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.state,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        if job.state in {"completed", "failed"} and job.result is not None:
            snapshot["result"] = copy.deepcopy(job.result)
        if job.state == "working" and job.cancel_event is not None and job.cancel_event.is_set():
            snapshot["cancellation_requested"] = True
        return snapshot

    @staticmethod
    def _fingerprint(request: DelegationRequest) -> str:
        return json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _failure(kind: str, message: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "error": {"kind": kind, "message": message},
            "applied": False,
        }
