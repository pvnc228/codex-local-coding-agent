# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.5.1] - 2026-08-18

### 🛡️ Resilience & Validation
- **Zero-Context Unified Diff Support**:
  - Added `--unidiff-zero` flag to `_run_git_apply` in `local_coding_agent.validators`.
  - Enables seamless `git apply` execution for compact atomic diffs generated without standard 3-line context windows.
- **Workflow & Invariants Synchronization**:
  - Updated `AGENTS.md` automated agent setup instructions and core invariant guidelines.
- **Repository Hygiene**:
  - Ignored experimental and scratch benchmarking run directories (`tests_experiment/`, `.local-run/`).

---

## [0.5.0] - 2026-08-18

### 🚀 Headline Features
- **Universal Agent Skill (`skills/local-coding-agent/SKILL.md`)**:
  - Full support for any AI coding harness (Claude Code, Cursor, Windsurf, Roo Code, ChatGPT Codex, Google Antigravity, OpenCode).
  - Built-in multi-agent installer: `local-agent init-skill --write`.
  - Comprehensive delegation decision matrix, envelope construction blueprint, and model tier recommendations.
- **100% CLI-First Console Parity ("Fool-Proof" Control)**:
  - First-class CLI subcommands with `--json` output and standard return codes for every feature:
    - `delegate` / `run`: Run atomic delegation directly via console.
    - `decompose` / `atomize`: Preflight and decompose wide task envelopes.
    - `profiles`: Query and inspect registered model profiles with Ollama availability checks.
    - `memory`: Manage Ollama VRAM, unload models, and enforce memory limits.
    - `calibrate`: Derive worker pool capacity for a given VRAM budget.
    - `apply`: Safely apply patches to workspace with test validation and auto-rollback.
    - `init-skill`: Export/install Agent Skills to agent directories.
- **Multi-Runtime Support: Native Ollama & llama.cpp (`llama-server`)**:
  - Direct support for `llama-server` and any OpenAI-compatible runtime (`/v1/chat/completions`) with precise timing extraction (`prompt_ms`, `predicted_ms`).
  - Runtime-agnostic profile dispatch via `OpenAICompatibleClient`.

### 🛡️ Safety & Architecture
- **CLI-First Invariant**: Formalized architectural rule that all future features must maintain 100% CLI parity with automated tests.
- **Verified Test Suite**: Full cross-platform test suite verifying CLI subcommands, skill installers, worker pools, and memory management.


---

## [0.4.0] - 2026-08-15

### Added
- **Pinpointed Prescriptions Engine (`local_coding_agent.prescriptions`)**:
  - Deterministic in-context diagnostic translation for small models (2B–4B).
  - Zero Distillation Guarantee: Rule-based translation without leaking host LLM reasoning.
- **Multi-Client MCP Configuration Generator (`init-mcp`)**:
  - Auto-detection and multi-client configuration merger for Claude, Cursor, Windsurf, Cline, Antigravity, OpenCode, Codex.
- **System Diagnostic Wizard (`doctor`)**:
  - Automated environment checks for Ollama API, Git CLI, RAM/VRAM, and model catalog.
- **Real-Time HTTP Monitoring & Dashboard (`monitor`)**:
  - Web dashboard showing worker load, queue latency, and live tokens per second.
