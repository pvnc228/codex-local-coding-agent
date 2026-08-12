"""Named model profiles kept separate from controller logic."""

from __future__ import annotations

from dataclasses import replace

from .ollama_adapter import ModelProfile


_PROFILES = {
    "bonsai-64k": ModelProfile(
        name="bonsai-64k",
        model="bonsai-64k:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
    ),
    "qwen2.5-1.5b": ModelProfile(
        name="qwen2.5-1.5b",
        model="qwen2.5:1.5b",
        think=False,
        temperature=0,
        num_ctx=4096,
        num_predict=256,
        keep_alive="10m",
    ),
    "qwen2.5-coder": ModelProfile(
        name="qwen2.5-coder",
        model="qwen2.5-coder:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
    ),
}


def list_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))


def get_profile(name: str, **overrides: object) -> ModelProfile:
    try:
        profile = _PROFILES[name]
    except KeyError as error:
        available = ", ".join(list_profiles())
        raise ValueError(f"unknown model profile {name!r}; available: {available}") from error
    return replace(profile, **overrides)
