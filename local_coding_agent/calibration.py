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
    per_worker_context_bytes: int | None = None,
    other_loaded_vram_bytes: int = 0,
    hard_max: int = 4,
) -> int:
    """Return a bounded worker count using one model residency plus KV budget.

    Ollama workers share the loaded model. ``model_vram_bytes`` is charged once;
    each additional worker is charged an explicit ``per_worker_context_bytes``
    estimate for its parallel context/KV cache, and already loaded other models
    are charged through ``other_loaded_vram_bytes``. Without a measured context
    estimate the safe answer is one worker rather than an invented copy count.
    """

    if vram_budget_bytes <= 0:
        raise ValueError("vram_budget_bytes must be positive")
    if hard_max <= 0:
        raise ValueError("hard_max must be positive")
    if other_loaded_vram_bytes < 0:
        raise ValueError("other_loaded_vram_bytes must be non-negative")
    if model_vram_bytes <= 0 or per_worker_context_bytes is None:
        return 1
    if per_worker_context_bytes <= 0:
        raise ValueError("per_worker_context_bytes must be positive")
    available = vram_budget_bytes - other_loaded_vram_bytes - model_vram_bytes
    if available <= 0:
        return 1
    by_context = 1 + available // per_worker_context_bytes
    return max(1, min(hard_max, by_context))


def model_vram_bytes(client: OllamaRuntime, model_name: str) -> tuple[int, str]:
    """Estimate the VRAM footprint of ``model_name``.

    Prefer the runtime-reported ``size_vram`` from ``/api/ps`` when the model is
    loaded; otherwise return the model file ``size`` from ``/api/tags`` as a
    diagnostic estimate only. Returns ``(bytes, source)``.
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
                return model["size"], "tags.size_estimate"

    return 0, "unknown"


def calibrate_for_model(
    client: OllamaRuntime,
    model_name: str,
    *,
    vram_budget_bytes: int,
    per_worker_context_bytes: int | None = None,
    hard_max: int = 4,
) -> dict[str, Any]:
    """Resolve runtime VRAM and derive a worker count conservatively.

    A model-file size from ``/api/tags`` is diagnostic only. It is not used to
    claim a multi-worker capacity because actual GPU residency depends on
    offload, compute buffers, and runtime configuration.
    """

    footprint, source = model_vram_bytes(client, model_name)
    loaded = client.loaded_models()
    raw_models = loaded.get("models") if isinstance(loaded, Mapping) else None
    other_loaded = 0
    if isinstance(raw_models, list):
        for model in raw_models:
            if not isinstance(model, Mapping):
                continue
            name = model.get("name") or model.get("model")
            size_vram = model.get("size_vram")
            if name != model_name and isinstance(size_vram, int) and size_vram > 0:
                other_loaded += size_vram

    if source != "ps.size_vram":
        workers = 1
        basis = "runtime_vram_unconfirmed"
    elif per_worker_context_bytes is None:
        workers = 1
        basis = "parallel_context_budget_missing"
    else:
        workers = calibrate_workers(
            footprint,
            vram_budget_bytes=vram_budget_bytes,
            per_worker_context_bytes=per_worker_context_bytes,
            other_loaded_vram_bytes=other_loaded,
            hard_max=hard_max,
        )
        basis = "runtime_model_plus_parallel_context"
    return {
        "model": model_name,
        "model_vram_bytes": footprint,
        "source": source,
        "other_loaded_vram_bytes": other_loaded,
        "per_worker_context_bytes": per_worker_context_bytes,
        "vram_budget_bytes": vram_budget_bytes,
        "max_workers": workers,
        "calibration_basis": basis,
    }
