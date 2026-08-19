"""Speculative Multi-Drafting & Model Racing Engine (R19).

Coordinates concurrent speculative drafts across model clients and worker pools,
accepting the first passing candidate and cancelling competing workers to boost
first-attempt success rates with low latency.
"""

from __future__ import annotations

import queue
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any, Callable, Sequence


class SpeculativeRacer:
    """Coordinates racing between multiple speculative task drafts."""

    def run(
        self,
        runners: Sequence[Callable[[Event], dict[str, Any]]],
        *,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        if not runners:
            return {"status": "failed", "error": "no runners provided"}

        if cancel_event is not None and cancel_event.is_set():
            return {"status": "failed", "error": "cancelled"}

        result_queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue()
        local_cancels: list[Event] = [Event() for _ in runners]

        def _worker_wrapper(idx: int, runner_fn: Callable[[Event], dict[str, Any]]) -> None:
            runner_cancel = local_cancels[idx]
            try:
                if cancel_event is not None and cancel_event.is_set():
                    runner_cancel.set()
                res = runner_fn(runner_cancel)
                result_queue.put((idx, res))
            except Exception as exc:
                result_queue.put((idx, {"status": "failed", "error": str(exc)}))

        executor = ThreadPoolExecutor(max_workers=len(runners))
        try:
            for i, runner in enumerate(runners):
                executor.submit(_worker_wrapper, i, runner)

            completed_count = 0
            fallback_result: dict[str, Any] | None = None

            while completed_count < len(runners):
                if cancel_event is not None and cancel_event.is_set():
                    for ev in local_cancels:
                        ev.set()
                    return {"status": "failed", "error": "cancelled"}

                try:
                    idx, result = result_queue.get(timeout=0.05)
                    completed_count += 1
                except queue.Empty:
                    continue

                if result.get("status") == "accepted":
                    # Winner found! Cancel all remaining racers
                    for j, ev in enumerate(local_cancels):
                        if j != idx:
                            ev.set()
                    audit = result.get("audit")
                    if isinstance(audit, list):
                        audit.append({
                            "event": "speculative_race_winner",
                            "draft_index": idx,
                            "total_drafts": len(runners),
                        })
                    return result

                if fallback_result is None:
                    fallback_result = result

            return fallback_result or {"status": "failed", "error": "no result"}
        finally:
            for ev in local_cancels:
                ev.set()
            executor.shutdown(wait=False, cancel_futures=True)
