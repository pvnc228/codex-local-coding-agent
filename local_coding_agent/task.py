"""Task envelope shared by the controller and bounded repository tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from pathlib import Path


@dataclass(frozen=True)
class TaskEnvelope:
    id: str
    goal: str
    files: tuple[str, ...]
    context: str = ""
    constraints: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("task field 'id' must be a non-empty string")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("task field 'goal' must be a non-empty string")
        if isinstance(self.files, str) or not isinstance(self.files, (tuple, list)) or not self.files:
            raise ValueError("task field 'files' must not be empty")
        for raw_path in self.files:
            if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
                raise ValueError("task files must contain valid relative paths")
            if (
                raw_path.startswith("/")
                or raw_path.startswith("\\")
                or (len(raw_path) >= 2 and raw_path[1] == ":" and raw_path[0].isalpha())
            ):
                raise ValueError(f"task file must be relative and inside workspace: {raw_path!r}")
            path = Path(raw_path)
            if path.is_absolute() or path.drive or path.root or ".." in path.parts:
                raise ValueError(f"task file must be relative and inside workspace: {raw_path!r}")

        # A frozen dataclass does not make an incoming list immutable.  Keep the
        # envelope stable after validation so service-level fingerprints and the
        # controller always observe the same allowlist and checks.
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "acceptance", tuple(self.acceptance))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TaskEnvelope":
        def strings(name: str) -> tuple[str, ...]:
            raw = value.get(name, ())
            if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
                raise ValueError(f"task field '{name}' must be a list of strings")
            if not all(isinstance(item, str) and item for item in raw):
                raise ValueError(f"task field '{name}' must contain non-empty strings")
            return tuple(raw)

        identifier = value.get("id")
        goal = value.get("goal")
        context = value.get("context", "")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("task field 'id' must be a non-empty string")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("task field 'goal' must be a non-empty string")
        if not isinstance(context, str):
            raise ValueError("task field 'context' must be a string")
        files = strings("files")
        if not files:
            raise ValueError("task field 'files' must not be empty")
        return cls(
            id=identifier,
            goal=goal,
            files=files,
            context=context,
            constraints=strings("constraints"),
            checks=strings("checks"),
            acceptance=strings("acceptance"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "files": list(self.files),
            "context": self.context,
            "constraints": list(self.constraints),
            "checks": list(self.checks),
            "acceptance": list(self.acceptance),
        }

