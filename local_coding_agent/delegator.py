"""Harness-agnostic delegating agent: decompose, delegate, decompose further.

The delegating agent owns the outer "expensive agent" loop: it breaks a wide
task into bounded children using decomposition templates, delegates each child
through the transport-neutral ``delegate`` seam, and on a decomposable failure
re-splits that child at finer granularity. It does not know about MCP, stdio or
the CLI, and never talks to the model directly.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .atomizer import TaskBudget, decompose
from .service import DelegationRequest
from .task import TaskEnvelope


Delegate = Callable[[str, DelegationRequest], Mapping[str, Any]]


@dataclass(frozen=True)
class DecompositionTemplate:
    """A named strategy that turns one task envelope into bounded children."""

    name: str
    split: Callable[[TaskEnvelope, TaskBudget], tuple[TaskEnvelope, ...]]


def _split_by_files(task: TaskEnvelope, budget: TaskBudget) -> tuple[TaskEnvelope, ...]:
    # ponytail: reuse atomizer.decompose; a context/checks-over-budget task is
    # not file-splittable, so fall back to the unchanged envelope and let the
    # delegate reject it with a machine-readable reason.
    try:
        return decompose(task, budget).children
    except ValueError:
        return (task,)


def _split_per_file(task: TaskEnvelope, budget: TaskBudget) -> tuple[TaskEnvelope, ...]:
    del budget
    return tuple(
        TaskEnvelope(
            id=f"{task.id}#{index + 1}",
            goal=task.goal,
            files=(file,),
            context=task.context,
            constraints=task.constraints,
            checks=task.checks,
            acceptance=task.acceptance,
        )
        for index, file in enumerate(task.files)
    )


BY_FILES = DecompositionTemplate("by_files", _split_by_files)
PER_FILE = DecompositionTemplate("per_file", _split_per_file)
DEFAULT_TEMPLATES = (BY_FILES, PER_FILE)

_DECOMPOSABLE_KINDS = frozenset(
    {
        "preflight_rejected",
        "context_limit",
        "max_turns",
        "retry_budget_exhausted",
        "too_many_files",
        "too_many_checks",
    }
)


def is_decomposable_failure(result: Mapping[str, Any]) -> bool:
    """True when a child failure can be retried at finer granularity."""

    error = result.get("error")
    if not isinstance(error, Mapping):
        return False
    kind = error.get("kind")
    if kind in _DECOMPOSABLE_KINDS:
        return True
    if kind == "controller_policy":
        message = str(error.get("message", ""))
        return "max_files" in message or "context" in message
    return False


class DelegatingAgent:
    """Decompose a task into bounded children and delegate each one.

    ``delegate`` is the harness-agnostic seam (e.g. ``DelegationService.delegate``)
    with signature ``(caller_id, request) -> result``. ``workspace_ref`` and
    ``model_profile`` are deployment configuration, not part of the task.
    """

    def __init__(
        self,
        delegate: Delegate,
        *,
        workspace_ref: str,
        model_profile: str,
        budget: TaskBudget | None = None,
        templates: Sequence[DecompositionTemplate] = DEFAULT_TEMPLATES,
        max_depth: int = 3,
        max_parallel_children: int = 1,
    ) -> None:
        if max_depth <= 0:
            raise ValueError("max_depth must be positive")
        if not templates:
            raise ValueError("templates must not be empty")
        if max_parallel_children <= 0:
            raise ValueError("max_parallel_children must be positive")
        self.delegate = delegate
        self.workspace_ref = workspace_ref
        self.model_profile = model_profile
        self.budget = budget or TaskBudget()
        self.templates = tuple(templates)
        self.max_depth = max_depth
        self.max_parallel_children = max_parallel_children

    def run(self, caller_id: str, task: TaskEnvelope) -> dict[str, Any]:
        if not isinstance(caller_id, str) or not caller_id.strip():
            raise ValueError("caller_id must be a non-empty string")
        splits = [0]
        leaves = self._dispatch(caller_id, task, 0, splits)
        accepted = sum(1 for leaf in leaves if leaf["result"].get("status") == "accepted")
        if accepted == len(leaves):
            status = "accepted"
        elif accepted:
            status = "partial"
        else:
            status = "failed"
        return {
            "status": status,
            "task_id": task.id,
            "splits": splits[0],
            "children": leaves,
        }

    def _dispatch(
        self,
        caller_id: str,
        task: TaskEnvelope,
        depth: int,
        splits: list[int],
    ) -> list[dict[str, Any]]:
        template = self.templates[min(depth, len(self.templates) - 1)]
        children = template.split(task, self.budget)
        leaves: list[dict[str, Any]] = []

        def run_child(child: TaskEnvelope, index: int) -> tuple[dict[str, Any], bool]:
            request = DelegationRequest(
                request_id=f"{task.id}@{depth}.{index}",
                workspace_ref=self.workspace_ref,
                model_profile=self.model_profile,
                task=child,
            )
            result = self.delegate(caller_id, request)
            return dict(result), is_decomposable_failure(result) and self._can_split_further(child, depth)

        if self.max_parallel_children > 1 and len(children) > 1:
            with ThreadPoolExecutor(max_workers=self.max_parallel_children) as pool:
                outcomes = list(pool.map(lambda item: run_child(item[1], item[0]), enumerate(children)))
        else:
            outcomes = [run_child(child, index) for index, child in enumerate(children)]

        for child, (result, decomposable) in zip(children, outcomes):
            if decomposable:
                splits[0] += 1
                leaves.extend(self._dispatch(caller_id, child, depth + 1, splits))
            else:
                leaves.append({"task_id": child.id, "depth": depth, "result": result})
        return leaves

    def _can_split_further(self, task: TaskEnvelope, depth: int) -> bool:
        if depth + 1 >= self.max_depth:
            return False
        next_template = self.templates[min(depth + 1, len(self.templates) - 1)]
        return len(next_template.split(task, self.budget)) > 1
