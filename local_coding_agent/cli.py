"""Command-line entry point for one proposal-only local coding task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .controller import Controller
from .memory import ModelMemoryManager
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
    parser.add_argument("--task", type=Path, help="UTF-8 JSON task envelope")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=list_profiles(), default="qwen2.5-1.5b")
    parser.add_argument("--endpoint", help="Override the profile Ollama endpoint")
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--num-ctx", type=int, help="Override model context window in tokens")
    memory_group = parser.add_mutually_exclusive_group()
    memory_group.add_argument("--unload-model", metavar="MODEL", help="Unload one model from Ollama VRAM")
    memory_group.add_argument("--unload-all", action="store_true", help="Unload every model currently held by Ollama")
    parser.add_argument("--vram-limit-bytes", type=int, help="Evict unprotected models until this VRAM budget fits")
    parser.add_argument("--keep-model", action="append", default=[], help="Model name to protect during VRAM eviction")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        overrides = {}
        if args.endpoint:
            overrides["endpoint"] = args.endpoint
        if args.num_ctx is not None:
            overrides["num_ctx"] = args.num_ctx
        profile = get_profile(args.profile, **overrides)
        client = OllamaClient(profile)
        if args.keep_model and args.vram_limit_bytes is None:
            raise ValueError("--keep-model requires --vram-limit-bytes")
        if args.unload_all or args.unload_model or args.vram_limit_bytes is not None:
            manager = ModelMemoryManager(client)
            if args.unload_all:
                snapshot = manager.unload_all()
            elif args.unload_model:
                snapshot = manager.unload_model(args.unload_model)
            else:
                snapshot = manager.snapshot()
            if args.vram_limit_bytes is not None:
                snapshot = manager.enforce_limit(args.vram_limit_bytes, keep=tuple(args.keep_model))
            print(json.dumps({"status": "memory_reconciled", "memory": snapshot.as_dict()}, ensure_ascii=False, indent=2))
            return 0
        if args.task is None:
            raise ValueError("--task is required unless --unload-model or --unload-all is used")
        task = load_task_file(args.task)
        result = Controller(
            client,
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
