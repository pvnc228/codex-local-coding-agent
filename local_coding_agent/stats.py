"""Minimal, stdlib-only statistics collector for delegation runs.

This is a lightweight observability seam: it counts outcomes and accumulates
latencies without any third-party dependency, and can optionally append one
JSONL record per terminal result. It is harness-agnostic — anything that
produces a controller/service result can feed it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping


class DelegationStats:
    """Thread-safe counters and latency aggregates over delegation results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_ns = time.monotonic_ns()
        self.total = 0
        self.by_status: dict[str, int] = {}
        self.by_model: dict[str, int] = {}
        self.by_error_kind: dict[str, int] = {}
        self.latency_count = 0
        self.latency_total_ns = 0
        self.latency_min_ns: int | None = None
        self.latency_max_ns: int | None = None
        self.tool_calls = 0
        self.model_calls = 0

    def record(
        self,
        result: Mapping[str, Any],
        *,
        model: str | None = None,
        latency_ns: int | None = None,
    ) -> None:
        with self._lock:
            self.total += 1
            status = str(result.get("status", "unknown"))
            self.by_status[status] = self.by_status.get(status, 0) + 1
            if model:
                self.by_model[model] = self.by_model.get(model, 0) + 1
            error = result.get("error")
            if isinstance(error, Mapping) and error.get("kind"):
                kind = str(error["kind"])
                self.by_error_kind[kind] = self.by_error_kind.get(kind, 0) + 1
            audit = result.get("audit")
            if isinstance(audit, (list, tuple)):
                for event in audit:
                    if isinstance(event, Mapping):
                        name = event.get("event")
                        if name == "tool_call":
                            self.tool_calls += 1
                        elif name == "model_request":
                            self.model_calls += 1
            if latency_ns is not None and latency_ns >= 0:
                self.latency_count += 1
                self.latency_total_ns += latency_ns
                self.latency_min_ns = (
                    latency_ns
                    if self.latency_min_ns is None
                    else min(self.latency_min_ns, latency_ns)
                )
                self.latency_max_ns = (
                    latency_ns
                    if self.latency_max_ns is None
                    else max(self.latency_max_ns, latency_ns)
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed_s = (time.monotonic_ns() - self._started_ns) / 1_000_000_000
            latency_avg_ns = (
                self.latency_total_ns / self.latency_count if self.latency_count else None
            )
            return {
                "elapsed_seconds": round(elapsed_s, 3),
                "total": self.total,
                "by_status": dict(self.by_status),
                "by_model": dict(self.by_model),
                "by_error_kind": dict(self.by_error_kind),
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "latency": {
                    "count": self.latency_count,
                    "avg_ms": (
                        round(latency_avg_ns / 1_000_000, 3)
                        if latency_avg_ns is not None
                        else None
                    ),
                    "min_ms": (
                        round(self.latency_min_ns / 1_000_000, 3)
                        if self.latency_min_ns is not None
                        else None
                    ),
                    "max_ms": (
                        round(self.latency_max_ns / 1_000_000, 3)
                        if self.latency_max_ns is not None
                        else None
                    ),
                },
            }


class JsonlStatsSink:
    """Append one JSON line per record to a UTF-8 file for later inspection."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")


class TimedDelegationStats:
    """Convenience wrapper that times a delegate call and records the result."""

    def __init__(
        self,
        stats: DelegationStats,
        *,
        sink: JsonlStatsSink | None = None,
    ) -> None:
        self.stats = stats
        self.sink = sink

    def __call__(
        self,
        delegate,
        caller_id: str,
        request,
        *,
        model: str | None = None,
    ) -> Mapping[str, Any]:
        started = time.monotonic_ns()
        result = delegate(caller_id, request)
        latency_ns = time.monotonic_ns() - started
        self.stats.record(result, model=model, latency_ns=latency_ns)
        if self.sink is not None:
            record = {
                "ts": time.time(),
                "caller_id": caller_id,
                "request_id": getattr(request, "request_id", None),
                "model": model,
                "status": result.get("status"),
                "error_kind": (
                    result.get("error", {}).get("kind")
                    if isinstance(result.get("error"), Mapping)
                    else None
                ),
                "latency_ms": round(latency_ns / 1_000_000, 3),
            }
            self.sink.write(record)
        return result
