"""Command-line entry point for one proposal-only local coding task."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .benchmark import run_benchmark, write_artifact
from .controller import Controller
from .memory import ModelMemoryManager
from .ollama_adapter import OllamaClient, OllamaError
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
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить принятый патч к рабочей области вместо proposal-only",
    )
    parser.add_argument("--num-ctx", type=int, help="Override model context window in tokens")
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run the fixed proposal-only benchmark instead of one task",
    )
    parser.add_argument(
        "--benchmark-model",
        action="append",
        choices=list_profiles(),
        dest="benchmark_models",
        help="Benchmark one named profile; repeat the option for multiple models",
    )
    parser.add_argument("--benchmark-repeats", type=int, default=1)
    parser.add_argument("--benchmark-timeout-seconds", type=float, default=300)
    parser.add_argument(
        "--benchmark-output",
        type=Path,
        default=Path(".codex-run") / "benchmarks" / "latest.json",
    )
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
        if args.benchmark:
            if args.task is not None:
                raise ValueError("--benchmark cannot be combined with --task")
            if args.unload_all or args.unload_model or args.vram_limit_bytes is not None:
                raise ValueError("--benchmark cannot be combined with memory controls")
            if args.benchmark_repeats <= 0:
                raise ValueError("--benchmark-repeats must be positive")
            if args.benchmark_timeout_seconds <= 0:
                raise ValueError("--benchmark-timeout-seconds must be positive")
            names = tuple(args.benchmark_models or (
                "bonsai-64k",
                "qwen2.5-coder",
                "ornith-9b",
                "qwen3-coder-30b",
                "devstral-small-2-24b",
                "ternary-bonsai-27b",
            ))
            artifact = {
                "schema": "codex-local-coding-agent/benchmark-v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repeats": args.benchmark_repeats,
                "models": [],
            }
            for name in names:
                benchmark_profile = get_profile(
                    name,
                    **overrides,
                    timeout_seconds=args.benchmark_timeout_seconds,
                )
                benchmark_client = OllamaClient(benchmark_profile)
                try:
                    available = benchmark_client.available_models()
                    available_names = {
                        item.get("name")
                        for item in available.get("models", [])
                        if isinstance(item, dict) and isinstance(item.get("name"), str)
                    }
                    if benchmark_profile.model not in available_names:
                        artifact["models"].append(
                            {
                                "profile": name,
                                "model": benchmark_profile.model,
                                "status": "unavailable",
                                "error": f"model is not present in Ollama /api/tags: {benchmark_profile.model}",
                            }
                        )
                        continue
                    model_info = next(
                        (
                            item
                            for item in available.get("models", [])
                            if isinstance(item, dict) and item.get("name") == benchmark_profile.model
                        ),
                        {},
                    )
                    memory = ModelMemoryManager(benchmark_client)
                    memory_before = memory.snapshot().as_dict()
                    if memory_before["models"]:
                        memory.unload_all()
                    run = run_benchmark(
                        name,
                        benchmark_client,
                        repeats=args.benchmark_repeats,
                        max_turns=args.max_turns,
                    )
                    run["profile"] = benchmark_profile.__dict__
                    run["status"] = "completed"
                    run["memory_before"] = memory_before
                    run["memory_after"] = memory.snapshot().as_dict()
                    run["ollama_model_info"] = {
                        key: model_info.get(key)
                        for key in ("name", "size", "digest", "details", "capabilities")
                        if key in model_info
                    }
                    artifact["models"].append(run)
                except OllamaError as error:
                    artifact["models"].append(
                        {
                            "profile": name,
                            "model": benchmark_profile.model,
                            "status": "unavailable",
                            "error": {"kind": error.kind, "message": str(error)},
                        }
                    )
            write_artifact(args.benchmark_output, artifact)
            print(json.dumps(artifact, ensure_ascii=False, indent=2))
            return 0 if artifact["models"] and all(item["status"] == "completed" for item in artifact["models"]) else 1
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
        ).run(task, apply=args.apply)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, OllamaError) as error:
        print(json.dumps({"status": "failed", "error": {"kind": "input", "message": str(error)}}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
