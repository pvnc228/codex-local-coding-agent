"""Command-line entry point for one proposal-only local coding task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .controller import Controller
from .ollama_adapter import OllamaClient
from .profiles import get_profile, list_profiles
from .task import TaskEnvelope


def load_task_file(path: str | Path) -> TaskEnvelope:
    raw = Path(path).read_bytes().decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("task JSON must be an object")
    return TaskEnvelope.from_mapping(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one bounded proposal-only Ollama coding task.")
    parser.add_argument("--task", type=Path, required=True, help="UTF-8 JSON task envelope")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=list_profiles(), default="qwen2.5-1.5b")
    parser.add_argument("--endpoint", help="Override the profile Ollama endpoint")
    parser.add_argument("--max-turns", type=int, default=4)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        task = load_task_file(args.task)
        profile = get_profile(args.profile, **({"endpoint": args.endpoint} if args.endpoint else {}))
        result = Controller(
            OllamaClient(profile),
            args.workspace,
            max_turns=args.max_turns,
        ).run(task)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": {"kind": "input", "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
