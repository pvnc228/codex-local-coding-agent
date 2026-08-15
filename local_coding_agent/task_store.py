"""Durable storage abstraction for task delegation state and recovery."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class TaskRecord:
    """A durable record representing a delegated task and its terminal outcome."""

    task_id: str
    caller_id: str
    request_id: str
    workspace_ref: str
    model_profile: str
    state: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskRecord:
        return cls(
            task_id=str(data["task_id"]),
            caller_id=str(data["caller_id"]),
            request_id=str(data["request_id"]),
            workspace_ref=str(data["workspace_ref"]),
            model_profile=str(data["model_profile"]),
            state=str(data["state"]),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            result=dict(data["result"]) if isinstance(data.get("result"), Mapping) else None,
            error=dict(data["error"]) if isinstance(data.get("error"), Mapping) else None,
        )


class TaskStore(Protocol):
    """Protocol for persisting and recovering delegation tasks across restarts."""

    def save(self, record: TaskRecord) -> None: ...

    def get(self, task_id: str) -> TaskRecord | None: ...

    def list(
        self,
        caller_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]: ...

    def delete(self, task_id: str) -> bool: ...


class JsonFileTaskStore:
    """Thread-safe, filesystem-backed JSON task store with atomic writes."""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: dict[str, TaskRecord] = {}
        self._load_and_recover()

    def _load_and_recover(self) -> None:
        """Scan directory, recover existing task files, and mark interrupted tasks."""
        with self._lock:
            for path in self._dir.glob("*.json"):
                try:
                    content = path.read_text(encoding="utf-8")
                    data = json.loads(content)
                    record = TaskRecord.from_dict(data)
                    # If previous process crashed while task was running/queued
                    if record.state in {"queued", "working"}:
                        record = TaskRecord(
                            task_id=record.task_id,
                            caller_id=record.caller_id,
                            request_id=record.request_id,
                            workspace_ref=record.workspace_ref,
                            model_profile=record.model_profile,
                            state="interrupted",
                            created_at=record.created_at,
                            updated_at=record.updated_at,
                            result=record.result,
                            error={"kind": "process_interrupted", "message": "task was interrupted by server restart"},
                        )
                        self._write_file(record)
                    self._cache[record.task_id] = record
                except (json.JSONDecodeError, KeyError, OSError):
                    continue

    def _write_file(self, record: TaskRecord) -> None:
        target = self._dir / f"{record.task_id}.json"
        temp = self._dir / f"{record.task_id}.tmp"
        data = json.dumps(record.as_dict(), ensure_ascii=False, indent=2)
        temp.write_text(data, encoding="utf-8")
        temp.replace(target)

    def save(self, record: TaskRecord) -> None:
        with self._lock:
            self._write_file(record)
            self._cache[record.task_id] = record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._cache.get(task_id)

    def list(
        self,
        caller_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        with self._lock:
            records = list(self._cache.values())
            if caller_id is not None:
                records = [r for r in records if r.caller_id == caller_id]
            if status is not None:
                records = [r for r in records if r.state == status]
            return records[:limit]

    def delete(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._cache:
                del self._cache[task_id]
                target = self._dir / f"{task_id}.json"
                if target.exists():
                    target.unlink()
                return True
            return False
