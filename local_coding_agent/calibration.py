"""VRAM-based worker-pool calibration for one Ollama model runtime.

The worker pool cannot promise physical parallelism that a single machine does
not have. This module answers one question: given a model and a VRAM budget,
how many concurrent worker slots can we run without over-subscribing memory?
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class OllamaRuntime(Protocol):
    def loaded_models(self) -> Mapping[str, Any]: ...

    def available_models(self) -> Mapping[str, Any]: ...


def calibrate_workers(
    model_vram_bytes: int,
    *,
    vram_budget_bytes: int,
    hard_max: int = 4,
) -> int:
    """Return a bounded worker count for one model given a VRAM budget.

    Concurrency is capped by the hard maximum and by how many copies of the
    model's VRAM footprint fit in the budget. A non-positive or unknown
    footprint yields a single worker rather than an unsafe guess.
    """

    if vram_budget_bytes <= 0:
        raise ValueError("vram_budget_bytes must be positive")
    if hard_max <= 0:
        raise ValueError("hard_max must be positive")
    if model_vram_bytes <= 0:
        return 1
    by_budget = vram_budget_bytes // model_vram_bytes
    return max(1, min(hard_max, by_budget))


def model_vram_bytes(client: OllamaRuntime, model_name: str) -> tuple[int, str]:
    """Estimate the VRAM footprint of ``model_name``.

    Prefer the runtime-reported ``size_vram`` from ``/api/ps`` when the model is
    loaded; otherwise fall back to the model file ``size`` from ``/api/tags`` as
    an upper-bound estimate. Returns ``(bytes, source)``.
    """

    loaded = client.loaded_models()
    raw_models = loaded.get("models") if isinstance(loaded, Mapping) else None
    if isinstance(raw_models, list):
        for model in raw_models:
            if not isinstance(model, Mapping):
                continue
            name = model.get("name") or model.get("model")
            if name == model_name and isinstance(model.get("size_vram"), int) and model["size_vram"] > 0:
                return model["size_vram"], "ps.size_vram"

    available = client.available_models()
    raw_tags = available.get("models") if isinstance(available, Mapping) else None
    if isinstance(raw_tags, list):
        for model in raw_tags:
            if not isinstance(model, Mapping):
                continue
            if model.get("name") == model_name and isinstance(model.get("size"), int) and model["size"] > 0:
                return model["size"], "tags.size"

    return 0, "unknown"


def calibrate_for_model(
    client: OllamaRuntime,
    model_name: str,
    *,
    vram_budget_bytes: int,
    hard_max: int = 4,
) -> dict[str, Any]:
    """Resolve a model's VRAM footprint and derive a worker count."""

    footprint, source = model_vram_bytes(client, model_name)
    workers = calibrate_workers(
        footprint,
        vram_budget_bytes=vram_budget_bytes,
        hard_max=hard_max,
    )
    return {
        "model": model_name,
        "model_vram_bytes": footprint,
        "source": source,
        "vram_budget_bytes": vram_budget_bytes,
        "max_workers": workers,
    }
