---
name: local-delegate
description: Use when delegating a small, atomic coding task to a local Ollama model, or when wiring this repo's controller into a host agent (MCP server or direct Python API). Triggers on "delegate", "локальная модель", "delegate_code", "codex-local-coding-agent".
---

# Local coding delegation

This repo exposes a bounded, proposal-only controller that delegates atomic
coding tasks to a local Ollama model. It is harness-agnostic: the same core is
reachable through a direct Python API, a JSONL stdio adapter, and an MCP stdio
server.

## When to use

- The task is small and atomic: one goal, a short allowlist of files, a
  targeted check command, and clear acceptance criteria.
- A local model can do the work; the calling agent stays the owner of the task
  statement, review, and any decision to apply or escalate.

## Contracts

Task envelope (`TaskEnvelope`):

```json
{
  "id": "unique-preserve-order",
  "goal": "убрать сортировку и сохранить порядок первого появления",
  "files": ["src/unique.py"],
  "context": "минимальный контекст",
  "constraints": ["не менять публичную сигнатуру"],
  "checks": ["py -m unittest tests.test_unique -v"],
  "acceptance": ["diff меняет только src/unique.py"]
}
```

Controller-owned result fields (`status`, `validation`, `audit`, `applied`)
cannot be forged by the model.

## Direct Python API

```python
from local_coding_agent import DelegationRequest, DelegationService, TaskEnvelope

service = DelegationService({"repo": "."})
request = DelegationRequest(
    request_id="idempotency-key",
    workspace_ref="repo",
    model_profile="qwen2.5-1.5b",
    task=TaskEnvelope(id="read-one", goal="прочитать файл", files=("src/example.py",)),
)
result = service.delegate("trusted-host", request)  # always proposal-only
```

## MCP server

```powershell
pip install "mcp>=2.0.0"
py -m local_coding_agent.mcp_server --workspace-ref repo --workspace .
```

Exposes one tool, `delegate_code`, over stdio using the official SDK. It
speaks the 2026-07-28 stateless protocol (`server/discover`, per-request
`_meta`, `resultType`) and auto-falls back to the legacy `initialize`
handshake for older clients. It is always proposal-only; it never applies
changes.

## Decomposing wide tasks

```python
from local_coding_agent import DelegatingAgent, TaskBudget

agent = DelegatingAgent(
    service.delegate,
    workspace_ref="repo",
    model_profile="qwen2.5-1.5b",
    budget=TaskBudget(max_files=5),
)
summary = agent.run("caller", wide_task)  # decompose -> delegate -> decompose further
```

## Monitoring

```python
from local_coding_agent import DelegationStats, TimedDelegationStats

stats = DelegationStats()
timed = TimedDelegationStats(stats)
result = timed(service.delegate, "caller", request, model="qwen2.5-1.5b")
print(stats.snapshot())
```

## Safety invariants

- Proposal-only is the default; mediated apply is opt-in via `--apply` only.
- The model never gets arbitrary shell access; check commands come from the
  task envelope.
- Every patch is validated (allowlist, size, `git apply --check`) before it is
  accepted.
- Duplicate tool calls and `max_turns` terminate the loop.
