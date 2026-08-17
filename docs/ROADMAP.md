# Project Roadmap

Historical milestones (M0–M6) are archived in [archive/ROADMAP_HISTORICAL.md](archive/ROADMAP_HISTORICAL.md).

---

## Completed Milestones

### R1 — Security, Budget & Resource Boundaries (Completed)
- Restricted `list_files` to the configured task allowlist.
- Added cumulative context token budgeting across multi-turn tool loops.
- Enforced graceful handling and diagnostics for Git CLI availability.
- Added cooperative task cancellation support to break blocking model and test calls.

### R2 — Protocol Robustness & Tool Loop Stability (Completed)
- Replaced rigid string matching with structured test runner evidence validation.
- Added pre-read byte limits for `search_text` to prevent memory exhaustion on large files.
- Optimized output truncation to eliminate O(n²) string slicing overhead.
- Fixed duplicate tool-call bypasses with normalized default arguments.

### R3 — Mediated Apply & Automatic Rollback (Completed)
- Added explicit opt-in `--apply` and `apply_proposal` execution seams.
- Ensured `apply_patch` is strictly controller-owned and never exposed to the local model.
- Kept proposal-only as the default operating mode.
- Added post-apply test re-execution with automatic workspace rollback upon check failures.

### R4 — Reproducible Benchmark Suite (Completed)
- Created an isolated benchmark runner with restricted Python child process oracles.
- Implemented automated calculation of 95% Wilson confidence intervals.

### R5 — Service Seam & Process Boundaries (Completed)
- Implemented transport-neutral `DelegationService` with caller-scoped idempotency.
- Implemented `StdioDelegationAdapter` for process-bound JSONL stdio communication.
- Built official `mcp==2.0.0` server compliant with the 2026-07-28 stateless era.

### R6 — Concurrency & Bounded Worker Pool (Completed)
- Implemented `BoundedWorkerPool` to enforce worker slot limits and request queue bounds.
- Added support for cooperative background task cancellation and `SharedExecutionGate`.

### R7 — Task Atomization & Decomposition (Completed)
- Added structured task envelope validation with fine-grained file allowlists.

### R8 — Retries & Escalation Policies (Completed)
- Implemented bounded retry budgets for recoverable model errors (`invalid_json`, `patch_parse_error`).

### R9 — SEARCH/REPLACE Edit Format (Completed)
- Replaced raw unified diff generation with strict character-exact SEARCH/REPLACE blocks (`edits`).
- Boosted patch validity and correctness from near-zero to 90%+ on quantized local models.

### R10 — Observability, Memory Management & Task Persistence (Completed)
- Integrated live VRAM calibration via Ollama `/api/ps`.
- Implemented `JsonFileTaskStore` for durable task recovery across process restarts.
- Added lightweight stdlib `MonitorServer` with real-time JSON endpoints (`/stats`, `/tasks`) and an interactive HTML web dashboard (`/dashboard`).

### R11 — Developer Experience & Packaging (Completed)
- Added `local-agent doctor` diagnostic wizard checking Python, Git, RAM/VRAM, and Ollama models.
- Added `local-agent init-mcp` for 1-click configuration generation (Claude Desktop, Cursor, Windsurf, VS Code).
- Added `local-agent test-run` for automated end-to-end smoke verification with live TPS tracking.
- Configured PyPI package metadata and console entry points (`local-agent`, `local-coding-agent`).

### R12 — Open-Source Showcase & Repository Readiness (Completed)
- Restructured user-facing documentation in English (`QUICKSTART.md`, `ARCHITECTURE.md`, `MCP_INTEGRATION.md`, `BENCHMARK.md`, `PROTOCOL.md`).
- Added open-source community standards: `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, and issue/PR templates.
- Configured GitHub Actions matrix CI (`.github/workflows/ci.yml`) for automated testing on Linux, macOS, and Windows.

### R13 — Adaptive Model Calibration & Dynamic Profiler (Planned)
- **Prerequisite (Decision #1)**: `llama-server` / OpenAI-compatible backend adapter — shipped as a first-class milestone *before* R13. Without it, non-Ollama models like `ling-3.0-tiny-q6k` cannot run through the real controller path.
- **Automated Failure Taxonomy**: Automated post-benchmark categorization distinguishing *Capability Failures* (logic/reasoning) from *Contract Friction* (JSON schema, line alignment, field redundancy).
- **Profile-Specific Prompt & Contract Synthesis**: Declarative adaptation per model family (custom stopping tokens, targeted system contracts, thinking-mode toggles).
- **Targeted Prescriptions (Dynamic Remediation)**: Context-aware single-turn retry prompts (e.g. precise line-alignment guides) preserving proposal-only invariants.
- **Teaser Prototype (scratch, not in controller path)**: `ling-3.0-tiny-q6k` was probed via a scratch OpenAI-style adapter against a local `llama-server` (port 8080), measuring **95% Correctness / 80% Loop Reliability at ~119 tok/s** on RTX 4060. This is *not* reproducible through the committed `Controller`/`OllamaClient` path: the built-in profile (`profiles.py`) points at port 8080, but `OllamaClient` only speaks Ollama `/api/chat`. The result lives in `scratch/` (gitignored) and the probe suite fails with `ConnectionRefusedError` when the server is down.

### R14 — Dynamic Context Compaction & Harness State Machine (Planned)
- **Agentic Harness vs Conversational Chat**: Transition controller loop from passive chat history accumulation to active agentic state management.
- **Tool Output Trimming & Eviction**: Automatic summarization/pruning of historical `read_file` and `search_text` results older than 1 turn to prevent context blowup and attention degradation on 3B–14B models.
- **Diff Residue Elimination**: Purge multi-turn failed diff attempts from active context, replacing them with a minimal task envelope + active pinpointed prescription.

### R15 — Multi-Dimensional Capability Ladder & Intelligence Benchmark (Planned)
- **Taxonomy of Difficulty Tiers**: Progressive test suite from Tier 0 (Syntax/Formatting/Typos) -> Tier 1 (Atomic Pure Functions) -> Tier 2 (Single-File Multi-Hunk Refactor) -> Tier 3 (Cross-File Invariants) -> Tier 4 (Algorithmic & Strict Constraints).
- **Adaptive Early-Exit Benchmark Ladder**: Dynamic step-up evaluation that calculates the model's reliability ceiling without wasting compute on out-of-reach tiers.
- **Task Decomposition & Granularity Tolerance**: Quantitative evaluation of maximum digestible chunk size (`atomic_hunk`, `function_level`, `file_level`, `multi_file_batch`).
- **Polyglot Evaluation Matrix**: Multi-language capability benchmarks across Python, TypeScript/JavaScript, Rust, and Go to establish per-language capability ratings.
- **Tool Horizon & Turn Endurance**: Measurement of the model's degradation point (repetition, loop fatigue, schema drift, hallucination) across extended multi-turn tool loops.

### R16 — MCP Capability Discovery, Smart Routing & Task Gatekeeper (Planned)
- **Structured Capability Profile**: Standardized JSON capability vector (`overall_tier`, `confidence_95_ci`, `granularity_tolerance`, `turn_horizon`, `languages`, `tps_generation`).
- **MCP Protocol Discovery & Introspection**: Expose model capabilities and routing advice via MCP tool definitions, MCP resource `model://profile`, and system prompt injection for calling host agents.
- **Pre-Flight Complexity Gatekeeper**: Immediate controller-level rejection/warning before invoking LLM if submitted task exceeds model's verified tier or file bounds (`CAPABILITY_OVERLOAD`).
- **Decomposition Guidance for Host Agents**: Actionable error envelopes instructing host agents (Codex/Claude) how to decompose rejected tasks into digestible chunks for the active local model.
- **CLI Intelligence Inspector**: `local-agent doctor --rank` and `local-agent benchmark --ladder` reporting model intelligence tier, supported languages, and routing sweet spot.

---

## Beyond Current Scope (Future Exploration)

- `content`-JSON fallback for legacy models lacking native tool-calling capabilities.
- Round-robin GPU queue scheduling across competing model profiles.
- Distributed worker clusters with remote Ollama instances.

---

## Decisions (2026-08-18)

1. **Backend adapter → ship it (Option B)**: The OpenAI-compatible `llama-server` adapter is a first-class milestone, sequenced *before* R13. It is the whole point of the feature: enabling non-Ollama GGUF architectures (`ling-3.0-tiny-q6k` and future BailingMoE/KDA/MLA) through the real controller path.
2. **Context budget → real token count (Option B)**: Replace `max_context_bytes` with an actual token budget mapped against `num_ctx`. Bytes were never the right unit; a byte-bounded task can silently exceed `num_ctx` and be truncated by the model. Use a per-model tokenizer or a tokens≈bytes/N approximation rather than raw bytes.
3. **Compaction → preserve pairing (recommended, Option A)**: R14 eviction may only drop whole `assistant(tool_calls)` ↔ `role:tool` pairs. Never orphan a tool result from its call. Summarization of past turns is a later step, not the MVP.
4. **Capability vector freshness → versioning + invalidation (Option B)**: The profile is keyed to `model` + quant + hash. A stale vector invalidates the profile and the gate refuses to route on it.
5. **Polyglot → do it now (Option B)**: Ship Python/TypeScript/Rust/Go evaluation. This requires building external oracles/verifiers for the non-Python tiers first — no language tier is reported without a working verifier.
6. **Gating evidence → gate only on verified tiers (recommended, Option A)**: `CAPABILITY_OVERLOAD` may only reject/warn on CI-confirmed tiers. Unverified tiers are reported as `unknown`, never used to cut a task.




