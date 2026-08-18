"""Skill configuration and installer for AI coding agents.

Integrates SKILL.md into Codex, Antigravity, Claude, and workspace skill directories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


_EMBEDDED_SKILL_MD = """---
name: local-coding-agent
description: Offload and delegate atomic coding tasks, bug fixes, refactoring, and unit test implementations to local Ollama LLMs via MCP (delegate_code, apply_proposal) or direct CLI.
---

# Local Coding Agent — AI Agent Delegation Skill

## Overview

The `local-coding-agent` is a bounded, proposal-only controller designed to offload small, deterministic coding tasks to local LLMs (such as Qwen 2.5 Coder, Qwen3, Devstral, and Gemma) running via Ollama or OpenAI-compatible local endpoints.

### Core Security & Architecture Invariants
- **Proposal-Only by Default**: The local model never directly writes to disk or executes arbitrary shell commands. It only generates structured diffs (`patch`) or search/replace blocks (`edits`).
- **External Test Verification**: Test results are never self-reported by the model; they are executed and verified strictly by the external runner.
- **Bounded Scope**: Context and files are strictly allowlisted. Tasks exceeding budget limits must be decomposed into atomic child subtasks.
- **Mediated Apply with Auto-Rollback**: Applying patches (`apply_proposal` or `--apply`) verifies the diff, applies it, re-runs all targeted test checks, and automatically rolls back if any test fails.
- **100% CLI Parity**: Every feature available via MCP is equally accessible via CLI subcommands for non-MCP agents and terminal workflows.

---

## Delegation Decision Matrix

| Task Type | Delegate? | Reason / Action |
|---|---|---|
| Single-function bug fix | **YES** | Perfect fit. Provide targeted test check and allowlist 1 file. |
| Writing unit tests | **YES** | Provide the target implementation file + test file in `files`. |
| Localized refactor | **YES** | Clear acceptance criteria and targeted test runner command. |
| Edge-case handling | **YES** | Explicit constraints and expected inputs/outputs in `context`. |
| Cross-repo architecture | **NO** | Solve yourself. Too broad for bounded local model context. |
| Unknown / exploratory debugging | **NO** | First inspect and isolate the issue, then delegate the isolated fix. |
| Task with no test / verification check | **NO** | Provide a check command or solve directly. |

---

## MCP Tools Reference

### 1. `delegate_code`
Delegates one atomic, proposal-only coding task to a local Ollama model.

Parameters:
- `request_id` (string, required): Unique caller-generated idempotency key (e.g. `req-fix-01`).
- `workspace_ref` (string, required): Registered workspace identifier (usually `"workspace"`).
- `model_profile` (string, required): Named profile (e.g. `"qwen2.5-coder"`, `"qwen3-8b-q6k"`).
- `task` (object, required): Structured task envelope:
  - `id` (string): Short descriptive identifier.
  - `goal` (string): 1 concise sentence describing the goal.
  - `files` (array of strings): List of allowlisted relative file paths (1 to 5 files, ideally 1-2).
  - `context` (string): Compact relevant context (types, signatures, traces).
  - `constraints` (array of strings): Guardrails.
  - `checks` (array of strings): Targeted test commands.
  - `acceptance` (array of strings): Acceptance criteria.

### 2. `apply_proposal`
Safely applies a previously accepted proposal to the workspace after verifying confirmation.

---

## Model Profile Selection & Multi-Runtime Support

The controller is runtime-agnostic and natively supports two local inference backends:
1. **Ollama Runtime** (`provider="ollama"`, default: `http://127.0.0.1:11434`): Standard native Ollama API with VRAM introspection and dynamic model loading/unloading.
2. **llama.cpp / llama-server & OpenAI-Compatible** (`provider="openai"`, default: `http://127.0.0.1:8080`): Standalone `llama-server`, vLLM, or LM Studio endpoints providing `/v1/chat/completions` with exact timing measurements (`prompt_ms`, `predicted_ms`) and tool-calling support.

| Model Tier / Class | Memory / VRAM | Example Profiles / Runtimes | When to Choose |
|---|---|---|---|
| **Ultra-Lightweight (1B–3B)** | 2–4 GB VRAM / CPU | `qwen2.5-1.5b`, `gemma4-e2b-q4`, `ling-3.0-tiny-q6k` (llama-server) | Trivial fixes, single-line edits, docstrings, type annotations, ultra-fast response (<2s). |
| **Standard Workhorse (7B–14B)** | 6–12 GB VRAM | `qwen2.5-coder`, `qwen3-8b-q6k`, `qwen2.5-coder-7b-q4` | **Default choice.** Standard functions, bug fixes, localized refactoring, unit test generation. |
| **Advanced Reasoning (24B–32B)** | 16–24 GB VRAM | `devstral-small-2-24b`, `qwen3.8-27b-q4`, `qwen3-coder-30b` | Complex algorithms, subtle edge cases, multi-step logic, difficult refactors. |
| **llama-server / Custom OpenAI** | Any GGUF / GPU | `ling-3.0-tiny-q6k` (llama-server:8080), custom vLLM | Standalone `llama-server` instances or custom OpenAI-compatible proxies. |

- **Dynamic Discovery**: Run `local-agent profiles list --check-ollama --json` or `local-agent doctor --json` to inspect installed models on the host machine.
- **Targeting llama-server**: Specify `--endpoint http://127.0.0.1:8080` or use an OpenAI-provider profile.
- **Default Profile**: If unspecified, use `qwen2.5-coder` or the MCP server default profile.

---

## CLI Console Control (Fool-Proof Fallback for Any Agent / Shell)


- **Delegate a Task**: `local-agent delegate --task task.json --json`
- **Apply with Verification**: `local-agent delegate --task task.json --apply --json`
- **Decompose a Broad Task**: `local-agent decompose --task wide.json --json`
- **Manage Profiles**: `local-agent profiles list --json`
- **Manage VRAM & Memory**: `local-agent memory status --json`
- **Check Health**: `local-agent doctor --json`
- **Install Skill**: `local-agent init-skill --write`
"""



def get_skill_content(workspace: str | Path = ".") -> str:
    """Retrieve skill markdown content from file or embedded fallback."""
    candidate_paths = [
        Path(workspace) / "skills" / "local-coding-agent" / "SKILL.md",
        Path(__file__).resolve().parent.parent / "skills" / "local-coding-agent" / "SKILL.md",
    ]
    for path in candidate_paths:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass
    return _EMBEDDED_SKILL_MD.strip() + "\n"


def _get_skill_target_path(client: str, workspace: str | Path = ".") -> Path:
    home = Path.home()
    c = client.lower().strip()
    if c in ("codex", "chatgpt"):
        return home / ".codex" / "skills" / "local-coding-agent" / "SKILL.md"
    if c in ("antigravity", "agy", "gemini"):
        return home / ".gemini" / "antigravity" / "skills" / "local-coding-agent" / "SKILL.md"
    if c == "claude":
        return home / ".claude" / "skills" / "local-coding-agent" / "SKILL.md"
    if c == "workspace":
        return Path(workspace).resolve() / "skills" / "local-coding-agent" / "SKILL.md"
    return home / ".codex" / "skills" / "local-coding-agent" / "SKILL.md"


def _detect_installed_agent_dirs(workspace: str | Path = ".") -> list[tuple[str, Path]]:
    home = Path.home()
    detected = []
    
    # Codex
    codex_dir = home / ".codex"
    if codex_dir.is_dir() or (home / ".codex" / "skills").is_dir():
        detected.append(("codex", codex_dir / "skills" / "local-coding-agent" / "SKILL.md"))
        
    # Antigravity
    agy_dir = home / ".gemini" / "antigravity"
    if agy_dir.is_dir() or (agy_dir / "skills").is_dir():
        detected.append(("antigravity", agy_dir / "skills" / "local-coding-agent" / "SKILL.md"))
        
    # Claude
    claude_dir = home / ".claude"
    if claude_dir.is_dir():
        detected.append(("claude", claude_dir / "skills" / "local-coding-agent" / "SKILL.md"))
        
    # Always include workspace target
    ws_target = Path(workspace).resolve() / "skills" / "local-coding-agent" / "SKILL.md"
    detected.append(("workspace", ws_target))
    
    return detected


def integrate_skill_config(
    client: str = "auto",
    workspace: str | Path = ".",
    target_path: str | Path | None = None,
    dry_run: bool = False,
    print_content: bool = False,
) -> dict[str, Any]:
    """Export or install the Agent Skill to agent skill directories."""
    content = get_skill_content(workspace)
    
    if print_content:
        return {"action": "print", "content": content}
        
    client_norm = client.lower().strip()
    
    if target_path:
        dest_path = Path(target_path).resolve()
        if dest_path.is_dir():
            dest_path = dest_path / "SKILL.md"
        targets = [(client_norm or "custom", dest_path)]
    elif client_norm in ("auto", "all"):
        targets = _detect_installed_agent_dirs(workspace)
    else:
        targets = [(client_norm, _get_skill_target_path(client_norm, workspace))]
        
    results = []
    for client_name, path in targets:
        written = False
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written = True
        results.append({
            "client": client_name,
            "path": str(path),
            "written": written,
            "status": "installed" if written else "dry_run_preview",
        })
        
    if target_path or (len(results) == 1 and client_norm not in ("auto", "all")):
        return results[0]
        
    return {
        "action": "install_skill",
        "results": results,
        "dry_run": dry_run,
    }

