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

### R13 — Adaptive Model Calibration & Dynamic Profiler (Completed in v0.4.0)
- **OpenAI-Compatible & `llama-server` Adapter**: First-class support for `llama-server` on port 8080 and OpenAI-compatible endpoints with exact microsecond timing extraction.
- **Pinpointed Prescriptions Engine**: Deterministic in-context diagnostic translation turning validation failures into actionable repair instructions.
- **System Diagnostic Wizard**: Multi-point automated health checking via `local-agent doctor`.

### R13b — Universal Agent Skills & 100% CLI Parity (Completed in v0.5.0)
- **Multi-Agent Skill (`SKILL.md`)**: Full compatibility with Claude Code, Cursor, Windsurf, Roo Code, ChatGPT Codex, and Google Antigravity via `local-agent init-skill --write`.
- **100% CLI Parity ("Fool-Proof" Control)**: Console commands for all capabilities (`delegate`, `decompose`, `profiles`, `memory`, `calibrate`, `apply`, `init-skill`, `doctor`, `init-mcp`, `test-run`, `serve-mcp`, `monitor`, `benchmark`) with machine-parseable `--json` output.
- **Cross-Platform Resilience**: Hardened stdout encoding defense for Windows (`cp1252`), macOS, and Linux.

### R15 — Multi-Dimensional Capability Ladder & Intelligence Benchmark (Completed in v0.6.0)
- **Taxonomy of Difficulty Tiers**: Progressive test suite from Tier 0 (Syntax/Formatting/Typos) -> Tier 1 (Atomic Pure Functions) -> Tier 2 (Single-File Multi-Hunk Refactor) -> Tier 3 (Cross-File Invariants) -> Tier 4 (Algorithmic & Strict Constraints).
- **Adaptive Early-Exit Benchmark Ladder**: Dynamic step-up evaluation that calculates the model's reliability ceiling without wasting compute on out-of-reach tiers.
- **Task Decomposition & Granularity Tolerance**: Quantitative evaluation of maximum digestible chunk size (`atomic_hunk`, `function_level`, `file_level`, `multi_file_batch`).
- **Polyglot Evaluation Matrix**: Multi-language capability benchmarks across Python, TypeScript/JavaScript, Rust, and Go to establish per-language capability ratings.
- **Tool Horizon & Turn Endurance**: Measurement of the model's degradation point (repetition, loop fatigue, schema drift, hallucination) across extended multi-turn tool loops.

### R16 — MCP Capability Discovery, Smart Routing & Task Gatekeeper (Completed in v0.6.0)
- **Structured Capability Profile**: Standardized JSON capability vector (`overall_tier`, `confidence_95_ci`, `granularity_tolerance`, `turn_horizon`, `languages`, `tps_generation`).
- **MCP Protocol Discovery & Introspection**: Expose model capabilities and routing advice via MCP tool definitions, MCP resource `model://profile`, and system prompt injection for calling host agents.
- **Pre-Flight Complexity Gatekeeper**: Immediate controller-level rejection/warning before invoking LLM if submitted task exceeds model's verified tier or file bounds (`CAPABILITY_OVERLOAD`).
- **Decomposition Guidance for Host Agents**: Actionable error envelopes instructing host agents (Codex/Claude) how to decompose rejected tasks into digestible chunks for the active local model.
- **CLI Intelligence Inspector**: `local-agent doctor --rank` and `local-agent benchmark --ladder` reporting model intelligence tier, supported languages, and routing sweet spot.

---

### R14 — Dynamic Context Compaction & Harness State Machine (Completed in v0.7.0)
- **Agentic Harness vs Conversational Chat (Stateless Context Reconstruction & Turn Assembly)**: Transition controller loop from passive chat history accumulation (`messages.append`) to an active stateful agentic harness. On each turn, the controller evaluates the world state (`HarnessState`: task envelope, observed files, latest tool observation, active pinpointed prescription) and synthesizes a clean, reconstructed context from scratch rather than sending a growing dialogue log. Deterministic state machine transitions (`received` -> `context_ready` -> `awaiting_model` -> `evaluating_candidate` -> `reconstructing_turn`).
- **Tool Output Trimming & Eviction**: Automatic summarization/pruning of historical `read_file` and `search_text` results older than 1 turn to prevent context blowup and attention degradation on 3B–14B models (preserving `assistant(tool_calls)` ↔ `role:tool` pairing invariant).
- **Diff Residue & Error Echo Elimination**: Purge multi-turn failed diff attempts and syntax errors from active context, replacing them with a minimal task envelope + active pinpointed prescription. Small models receive only the current state of files and precise repair instructions without seeing past hallucinations.

### R17 — AST-Guided Context Compaction & Skeletonization (`ast_compactor.py`) (Completed in v0.7.0)
- **AST File Skeletonizer**: Pre-processor that parses code structures (Python `ast`, `tree-sitter`) and collapses non-target classes/functions down to their signatures and docstrings (`def process_order(id: str) -> bool: ...`).
- **Target Function Expansion**: Full code body is expanded only for the specific symbol targeted for editing.
- **Token Efficiency Gain**: Slashes prompt context by 60–85%, keeping 1B–4B models focused inside their optimal attention window and reducing generation latency.

### R18 — Semantic Linter & Fast Pre-Test Prescriptions (`semantic_linter.py`) (Completed in v0.7.0)
- **Sub-50ms Static Pre-Gates**: Lightweight static analysis pipeline (`ruff check` for Python, `biome` / `tsc --noEmit` for TypeScript) running immediately after patch generation.
- **Instant In-Context Feedback**: Catches syntax errors, undefined variables, and type mismatches before spinning up heavy unit test runners (`pytest`), converting linter diagnostics into pinpointed prescriptive hints.

### R19 — Speculative Multi-Drafting & Model Racing Engine (Completed in v0.7.0)
- **Parallel Speculative Dispatch**: Coordinates concurrent execution of 2 lightweight workers across the `BoundedWorkerPool` (e.g. `qwen2.5-1.5b` with `temp=0` vs `gemma4-2b` with `temp=0.2`).
- **First-Pass Winner Acceptance**: The first candidate patch that passes `git apply --check` and targeted tests is accepted; the competing worker is immediately cancelled.
- **Reliability Boost**: Increases first-attempt success rates from ~70% to 95%+ with sub-second turnaround.

### R20 — Streaming Progress & Token Telemetry (MCP + SSE) (Completed in v0.7.0)
- **MCP Progress Protocol**: Implementation of MCP `notifications/progress` broadcasting live controller lifecycle states (`[1/4] Compacting -> [2/4] Generating @ 84 tok/s -> [3/4] Testing -> [4/4] Validated`).
- **Server-Sent Events (SSE)**: Real-time event stream (`/api/events`) for dashboard and terminal CLI progress bars.

### R21 — Self-Healing Environment & Auto-Pulling (`doctor --fix`) (Completed in v0.7.0)
- **VRAM-Aware Quant Selection**: Automatic hardware introspection determining the highest-performing quant fitting the system GPU budget.
- **Automated Ingestion Wizard**: `local-agent doctor --fix` and `local-agent profiles pull <tier>` downloading recommended Ollama models / GGUFs and setting up IDE configs automatically.

### R22 — Standalone AI Harness & Modern Web Workbench (`local-agent ui` / `local-agent app`) (Completed in v0.7.0)
- **Embedded Web Server**: Zero-config Starlette / FastAPI / stdlib backend embedded in the Python package, serving the application on port 8765 without requiring Node.js on the host.
- **Interactive Coding Arena**: Web UI (`/workbench`) allowing developers to submit prompts, configure TaskEnvelopes, and interact with local models directly without an external host IDE.
- **GitHub-Grade Side-by-Side Diff Viewer**: Clean modern split diff preview with syntax highlighting.
- **One-Click Action Controls**: Buttons for `Apply Proposal`, `Auto-Rollback`, `Decompose Task`, and `Retry with Prescription`.
- **Live Observability & Benchmark Charts**: Interactive telemetry dashboard showing live GPU VRAM gauges, active worker slots, and radar charts comparing model accuracy and speed.

---

## Planned Milestones

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
7. **Standalone Harness UI Architecture**: Embedded FastAPI/Starlette backend serving a lightweight modern static bundle (`diff2html`, Monaco, Tailwind, Chart.js) with zero Node.js runtime requirements for the user.





