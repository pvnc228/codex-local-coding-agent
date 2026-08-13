"""Formal task budget and deterministic decomposition (R7 task atomization)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .task import TaskEnvelope


@dataclass(frozen=True)
class TaskBudget:
    max_files: int = 5
    max_context_bytes: int = 32_000
    max_checks: int = 3

    def __post_init__(self) -> None:
        if self.max_files <= 0:
            raise ValueError("max_files must be positive")
        if self.max_context_bytes <= 0:
            raise ValueError("max_context_bytes must be positive")
        if self.max_checks <= 0:
            raise ValueError("max_checks must be positive")


@dataclass(frozen=True)
class PreflightReport:
    accepted: bool
    reason: str | None
    issues: tuple[str, ...]


@dataclass(frozen=True)
class Decomposition:
    children: tuple[TaskEnvelope, ...]


def preflight(task: TaskEnvelope, budget: TaskBudget) -> PreflightReport:
    if len(task.files) > budget.max_files:
        return PreflightReport(False, "too_many_files", ("too_many_files",))
    if len(task.context.encode("utf-8")) > budget.max_context_bytes:
        return PreflightReport(False, "context_too_large", ("context_too_large",))
    if len(task.checks) > budget.max_checks:
        return PreflightReport(False, "too_many_checks", ("too_many_checks",))
    return PreflightReport(True, None, ())


def decompose(task: TaskEnvelope, budget: TaskBudget) -> Decomposition:
    if len(task.context.encode("utf-8")) > budget.max_context_bytes:
        raise ValueError("cannot decompose task: context_too_large")
    if len(task.checks) > budget.max_checks:
        raise ValueError("cannot decompose task: too_many_checks")

    report = preflight(task, budget)
    if not report.accepted and report.reason != "too_many_files":
        raise ValueError(f"cannot decompose task: {report.reason}")

    count = math.ceil(len(task.files) / budget.max_files)
    if count <= 1:
        return Decomposition((task,))

    children = []
    for index in range(count):
        start = index * budget.max_files
        files = task.files[start : start + budget.max_files]
        children.append(
            TaskEnvelope(
                id=f"{task.id}#{index + 1}",
                goal=task.goal,
                files=files,
                context=task.context,
                constraints=task.constraints,
                checks=task.checks,
                acceptance=task.acceptance,
            )
        )
    return Decomposition(tuple(children))
