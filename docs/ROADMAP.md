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

### R22 — AI Harness & Modern Workbench Prototype (Experimental Web Preview)
- **Experimental Web Prototype**: Lightweight embedded stdlib web UI (`/workbench`) on port 8765 for rapid prototyping of TaskEnvelopes and local model execution. Marked experimental pending full desktop redesign.
- **Interactive Coding Arena**: Web UI allowing developers to submit prompts, configure TaskEnvelopes, and interact with local models directly.
- **Side-by-Side Diff Preview**: Split diff view with patch review and status feedback.
- **One-Click Action Controls**: Buttons for `Apply Proposal`, `Auto-Rollback`, and `Retry with Prescription`.

---

## Planned Milestones (DeepSeek Harness Borrowing & Evolution)

### R23 — Standalone Desktop AI Coding Harness (`local-agent desktop`)
- **Dedicated Desktop Architecture**: Transitioning from a browser sandbox to a first-class desktop application ([`local_coding_agent/desktop/app.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/desktop/app.py), [`local_coding_agent/desktop/server.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/desktop/server.py)).
- **Native Workspace & Git Integration**: Native folder picker, active git diff tree, character-exact SEARCH/REPLACE diff visualizer, and file-tree context picker.
- **Speculative Model Racing Arena**: Visual side-by-side execution split view between competing local model drafts.
- **Hardware & VRAM Telemetry Hub**: Real-time GPU VRAM (`nvidia-smi`), context window token meters, and live model process management.
- **AST Skeletonizer & Token Savings Studio**: Interactive preview of code compaction before LLM dispatch ([`local_coding_agent/ast_compactor.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/ast_compactor.py)).
- **Pinpointed Prescriptions Studio**: Visual repair assistant for model diff alignment errors ([`local_coding_agent/prescriptions.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/prescriptions.py)).
- **Conversation Node UI Framework**: Modular frontend cards for Diffs, Terminal output, Todo checklists, and Plan review dialogs ([`local_coding_agent/desktop/ui.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/desktop/ui.py)).

---

### R24 — Tool Output Spill Store, Ripgrep & FS Observation Policy (Safety & Context Resilience)
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-spill`, `@deepseek-ai/dsh-tool-fs-search`, and `@deepseek-ai/dsh-fs-observation-policy`*

- **Tool Output Spill Store**:
  - Implementation of [`local_coding_agent/spill.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/spill.py) managing private session-scoped directories under `.local_agent/spill/<session_id>/` (with strict 0700 permissions and path traversal neutralizers).
  - Hard byte/line thresholds (default: 30KB / 1,000 lines). Oversized tool outputs (large file reads, verbose test traces, huge grep results) are spilled to disk, returning a structured summary (head snippet + tail snippet + total line count + unique locator path).
  - Model can retrieve or query specific lines without blowing up prompt attention.
- **Packaged Ripgrep Discovery (`ripgrep.py`)**:
  - Implementation of [`local_coding_agent/ripgrep.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/ripgrep.py) executing direct `rg` binary invocations for `glob` and `grep` with structured JSON parsing.
  - Replaces fragile shell pipelines with direct subprocess spawns, eliminating Windows quoting/escaping vulnerabilities.
  - Integrated into [`local_coding_agent/repository_tools.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/repository_tools.py).
- **Filesystem Observation Policy Gate**:
  - Enforce strict **read-before-edit** and **read-before-write** invariant in [`local_coding_agent/validators.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/validators.py).
  - A model proposal modifying a file that was not observed (read or listed with hash) during the current session is immediately rejected before touching the workspace, preventing blind hallucinations.

---

### R25 — Generic LSP Stdio Code Intelligence Seam (Language Server Navigation)
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-lsp` & `@deepseek-ai/dsh-tool-lsp`*

- **Language Server Protocol Stdio Client**:
  - Implementation of [`local_coding_agent/lsp.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/lsp.py) providing async JSON-RPC stdio communication with active language servers (`pyright` / `basedpyright` for Python, `typescript-language-server` for TS/JS, `rust-analyzer` for Rust, `gopls` for Go).
  - Process lifecycle management, automatic initialize handshake, capabilities negotiation, and serialized query queue.
- **Model-Facing `lsp` Tool**:
  - Added to [`local_coding_agent/repository_tools.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/repository_tools.py):
    - `goToDefinition`: Navigate to exact symbol declaration across files.
    - `findReferences`: Find all callers/references without full-workspace grep.
    - `documentSymbol`: Extract file outline (classes, methods, functions).
    - `workspaceSymbol`: Fast fuzzy symbol lookup.
    - `hover`: Type signature and docstring preview.
    - `diagnostics`: Real-time compilation/type errors directly from the compiler.
- **High-Impact Value for Small Models**:
  - Empowers 1.5B–14B models to perform precise cross-file refactoring without loading large file bodies into prompt context.

---

### R26 — Persistent PTY Terminal Seam & Interactive Process Control
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-terminal` & `@deepseek-ai/dsh-tool-terminal`*

- **Cross-Platform PTY Process Manager**:
  - Implementation of [`local_coding_agent/terminal.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/terminal.py) providing persistent, stateful terminal sessions.
  - Windows support via `winpty` / `ConPTY` (`CreatePseudoConsole`); Linux/macOS support via standard `pty` / `termios`.
- **Terminal Tool Suite**:
  - `terminal_open(id, cwd, shell)`: Spawn long-running persistent shell (pwsh/bash).
  - `terminal_send(id, text, wait_ms)`: Send command/keystrokes and read resulting output stream.
  - `terminal_read(id, offset)`: Non-blocking incremental read of terminal buffer.
  - `terminal_signal(id, sig)`: Send signals (Ctrl+C / SIGINT, SIGTERM) to interrupt runaway commands.
  - `terminal_list()`: Introspect running background processes.
  - `terminal_close(id)`: Graceful teardown of entire process tree.
- **Use Cases**: Interactive REPLs (Python, Node), watch-mode testing, long builds, and live local development servers.

---

### R27 — Plan Mode Controller, Structured Questions & Dynamic Checklist
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-plan-mode`, `@deepseek-ai/dsh-tool-ask-user`, and `@deepseek-ai/dsh-tool-todo`*

- **Plan Mode State Machine**:
  - Implementation of [`local_coding_agent/plan_mode.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/plan_mode.py).
  - When Plan Mode is active, tool execution policy enforces **read-only exploration** (`read_file`, `lsp`, `grep`, `glob`). Mutation tools (`propose_patch`, `apply`) are disabled.
  - Model completes exploration and calls `exit_plan_mode(plan, steps, risks)` to present a formal design artifact.
  - Controller blocks execution until the user explicitly clicks "Approve & Execute" or provides steering feedback.
- **Structured Interactive `ask_user_question` Tool**:
  - Enables the model to clarify ambiguous requirements with structured multiple-choice questions, default write-in, and multi-select options.
- **Dynamic `todo_write` Checklist Tool**:
  - Model manages a session-scoped task checklist (`pending`, `in_progress`, `completed`).
  - Rendered dynamically in terminal CLI and Desktop UI.

---

### R28 — Event-Sourced Session Engine & SQLite FTS5 Search Index
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-session`, `@deepseek-ai/dsh-session-query`, and `@deepseek-ai/dsh-session-persistence-sqlite`*

- **Event-Sourced Session Architecture**:
  - Implementation of [`local_coding_agent/session_events.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/session_events.py).
  - Every turn, user prompt, tool call, tool result, and model response is recorded as an immutable typed event in an append-only log.
  - Enforces the invariant: **Model-Visible ⟺ Logged**. Any state seen by the model is deterministically reconstructable via `derive_messages()`.
- **Session Branching & Time-Travel Replay**:
  - Session forking (`fork(session_id, step_index)`): Branch a new session from any historical step to test alternative prompts or models.
- **SQLite FTS5 Full-Text Search**:
  - Implementation of [`local_coding_agent/session_query.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/session_query.py) maintaining a local SQLite database with full-text search across all historical session events.
  - Subcommands and MCP tools: `session_search`, `session_event_search`, `session_trace`.
- **Automatic Log-Backed Session Titles**:
  - Asynchronously generates descriptive session titles from the first prompt using local lightweight models.

---

### R29 — Universal Agent Client Protocol (ACP) Server & Interop Gateway
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-acp`*

- **Agent Client Protocol (ACP) stdio Server**:
  - Implementation of [`local_coding_agent/acp_server.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/acp_server.py) implementing the standard JSON-RPC ACP protocol over stdio.
  - Exposes our Python harness directly to modern AI-native editors and IDEs (Zed, Cursor, VS Code, JetBrains, OpenCode) without requiring custom extension plugins.
- **CLI Subcommand**:
  - `python -m local_coding_agent serve-acp` added to [`local_coding_agent/cli.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/cli.py).

---

### R30 — Continuable Background Subagents & External Agent Hook Bridges
*Adapted from DeepSeek Harness `@deepseek-ai/dsh-subagent`, `@deepseek-ai/dsh-hooks`, and `@deepseek-ai/dsh-hooks-codex`*

- **In-Process Continuable Subagents**:
  - Implementation of [`local_coding_agent/subagent.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/subagent.py).
  - Main agent can spawn child workers with restricted task envelopes, dedicated tool subsets, and separate context memory.
  - Inter-agent communication via structured mailboxes (`send_message`, `report`, `interrupt_agent`).
- **External CLI Subagent Adapters**:
  - Subprocess bridges allowing our local harness to delegate heavy multi-file architectural tasks to host Claude Code CLI or OpenAI Codex CLI when tasks exceed local model capacity tiers.
- **Claude Code & Codex Wire-Protocol Hooks**:
  - Implementation of [`local_coding_agent/hooks.py`](file:///c:/Users/mist8/Documents/Codex/2026-08-12/new-chat-2/codex-local-coding-agent/local_coding_agent/hooks.py) bridging tool execution hooks and session lifecycle events with external host tools.

---

## Security Invariants & Defensive Controls (OWASP / MITRE ATLAS AML.T0053)

To ensure bulletproof safety during autonomous tool execution, all planned capabilities adhere to strict security invariants:

1. **Deny-by-Default Tool Allowlisting**:
   - Every tool call is validated against strict Pydantic/dataclass JSON schemas before execution. Unknown tools or extra properties are immediately rejected.
2. **Read-Before-Write Observation Gate**:
   - No patch or write operation is accepted for files that were not previously observed in the session.
3. **Strict Path Normalization & Traversal Defense**:
   - All filesystem paths (`spill`, `fs`, `lsp`, `terminal`) are normalized against the registered workspace root. `../` and symlink escapes outside workspace boundaries trigger immediate `SECURITY_VIOLATION` errors.
4. **Isolated Process Boundaries & Non-Blocking Streams**:
   - All child processes (tests, LSP servers, persistent PTYs, ripgrep) run with bounded timeouts and continuous async pipe drainage to prevent deadlocks on full OS pipes.
5. **Human-in-the-Loop (HITL) for High-Impact Actions**:
   - Disk writes during mediated apply and Plan Mode exit require explicit human confirmation.

---

## Decisions & Architectural Rationale

1. **Backend adapter → ship it (Option B)**: The OpenAI-compatible `llama-server` adapter is a first-class milestone, sequenced *before* R13. It is the whole point of the feature: enabling non-Ollama GGUF architectures (`ling-3.0-tiny-q6k` and future BailingMoE/KDA/MLA) through the real controller path.
2. **Context budget → real token count (Option B)**: Replace `max_context_bytes` with an actual token budget mapped against `num_ctx`. Bytes were never the right unit; a byte-bounded task can silently exceed `num_ctx` and be truncated by the model. Use a per-model tokenizer or a tokens≈bytes/N approximation rather than raw bytes.
3. **Compaction → preserve pairing (recommended, Option A)**: R14 eviction may only drop whole `assistant(tool_calls)` ↔ `role:tool` pairs. Never orphan a tool result from its call. Summarization of past turns is a later step, not the MVP.
4. **Capability vector freshness → versioning + invalidation (Option B)**: The profile is keyed to `model` + quant + hash. A stale vector invalidates the profile and the gate refuses to route on it.
5. **Polyglot → do it now (Option B)**: Ship Python/TypeScript/Rust/Go evaluation. This requires building external oracles/verifiers for the non-Python tiers first — no language tier is reported without a working verifier.
6. **Gating evidence → gate only on verified tiers (recommended, Option A)**: `CAPABILITY_OVERLOAD` may only reject/warn on CI-confirmed tiers. Unverified tiers are reported as `unknown`, never used to cut a task.
7. **Standalone Harness UI Architecture**: Embedded FastAPI/Starlette backend serving a lightweight modern static bundle (`diff2html`, Monaco, Tailwind, Chart.js) with zero Node.js runtime requirements for the user.
8. **Spill Store vs Context Compression (Option A)**: Tool output spilling to `.local_agent/spill/` is strictly decoupled from LLM context summarization. The filesystem owns large blobs; the LLM receives only clean locators and summaries.
9. **LSP Stdio Isolation (Option B)**: Language servers run in dedicated child processes isolated per workspace and serialized through an async queue, preventing server crashes from killing the agent controller.
10. **Event-Sourced Monotonic Log (Option A)**: `SessionEvent` records are append-only. All UI views, telemetry, and message projections are derived views from this immutable event stream.






