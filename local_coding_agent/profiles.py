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
        max_context_length=262_144,
    ),
    "qwen2.5-1.5b": ModelProfile(
        name="qwen2.5-1.5b",
        model="qwen2.5:1.5b",
        think=False,
        temperature=0,
        num_ctx=4096,
        num_predict=256,
        keep_alive="10m",
        max_context_length=32_768,
    ),
    "qwen2.5-coder": ModelProfile(
        name="qwen2.5-coder",
        model="qwen2.5-coder:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=32_768,
    ),
    "ornith-9b": ModelProfile(
        name="ornith-9b",
        model="codex-ornith-9b:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen3-coder-30b": ModelProfile(
        name="qwen3-coder-30b",
        model="codex-qwen3-coder-30b:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "devstral-small-2-24b": ModelProfile(
        name="devstral-small-2-24b",
        model="codex-devstral-small-2-24b:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=393_216,
    ),
    "ternary-bonsai-27b": ModelProfile(
        name="ternary-bonsai-27b",
        model="codex-ternary-bonsai-27b:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen3-8b-q6k": ModelProfile(
        name="qwen3-8b-q6k",
        model="codex-qwen3-8b-q6k:latest",
        think=False,
        temperature=0.7,
        top_p=0.80,
        presence_penalty=1.5,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=32_768,
    ),
    "qwen3-coder-30b-iq2": ModelProfile(
        name="qwen3-coder-30b-iq2",
        model="codex-qwen3-coder-30b-ud-iq2:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen3-coder-30b-q4": ModelProfile(
        name="qwen3-coder-30b-q4",
        model="codex-qwen3-coder-30b-ud-q4:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen2.5-coder-14b-q6k": ModelProfile(
        name="qwen2.5-coder-14b-q6k",
        model="codex-qwen2.5-coder-14b-q6k:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=32_768,
    ),
    "nemotron-30b-mxfp4": ModelProfile(
        name="nemotron-30b-mxfp4",
        model="codex-nemotron-30b-mxfp4:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=131_072,
    ),
    "qwen3.8-27b-q4": ModelProfile(
        name="qwen3.8-27b-q4",
        model="codex-qwen3.8-27b-q4:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen3.8-27b-q5": ModelProfile(
        name="qwen3.8-27b-q5",
        model="codex-qwen3.8-27b-q5:latest",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        keep_alive="10m",
        max_context_length=262_144,
    ),
    "qwen3.8-27b-think": ModelProfile(
        name="qwen3.8-27b-think",
        model="codex-qwen3.8-27b-q4:latest",
        think=True,
        temperature=1.0,
        num_ctx=8192,
        num_predict=1024,
        keep_alive="10m",
        max_context_length=262_144,
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
