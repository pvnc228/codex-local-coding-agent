"""Command-line entry point for codex-local-coding-agent."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .benchmark import run_benchmark, write_artifact
from .calibration import calibrate_for_model
from .controller import Controller
from .doctor import diagnose_environment
from .mcp_config import integrate_mcp_config
from .memory import ModelMemoryManager
from .ollama_adapter import OllamaClient, OllamaError
from .profiles import get_profile, list_profiles
from .smoke import run_smoke_test
from .task import TaskEnvelope


def load_task_file(path: str | Path) -> TaskEnvelope:
    raw = Path(path).read_bytes().decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("task JSON must be an object")
    return TaskEnvelope.from_mapping(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-agent",
        description="Codex Local Coding Agent: Bounded controller for atomic coding tasks.",
    )

    # Global options
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
    parser.add_argument(
        "--calibrate-workers",
        type=int,
        metavar="VRAM_BYTES",
        help="Derive a bounded worker count for the selected profile model within this VRAM budget",
    )
    parser.add_argument(
        "--parallel-context-bytes",
        type=int,
        help="Measured incremental VRAM estimate per concurrent request context/KV cache",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # doctor
    doc_p = subparsers.add_parser("doctor", help="Run system diagnostics and model recommendations")
    doc_p.add_argument("--endpoint", default="http://127.0.0.1:11434", help="Ollama endpoint to check")
    doc_p.add_argument("--json", action="store_true", help="Output diagnostic report in JSON format")
    doc_p.add_argument("--strict", action="store_true", help="Exit with code 1 if any check fails")


    # init-mcp
    mcp_p = subparsers.add_parser("init-mcp", help="Generate or configure MCP client integration")
    mcp_p.add_argument(
        "--client",
        choices=["claude", "cursor", "windsurf", "cline", "antigravity", "opencode", "chatgpt", "vscode", "auto", "all"],
        default="claude",
        help="Target MCP client (default: claude, or 'auto'/'all')",
    )
    mcp_p.add_argument("--claude", action="store_const", const="claude", dest="client", help="Configure for Claude Desktop & Claude Code")
    mcp_p.add_argument("--cursor", action="store_const", const="cursor", dest="client", help="Configure for Cursor")
    mcp_p.add_argument("--windsurf", action="store_const", const="windsurf", dest="client", help="Configure for Windsurf")
    mcp_p.add_argument("--cline", action="store_const", const="cline", dest="client", help="Configure for Cline Desktop / Extension")
    mcp_p.add_argument("--antigravity", action="store_const", const="antigravity", dest="client", help="Configure for Antigravity Desktop & agy CLI")
    mcp_p.add_argument("--opencode", action="store_const", const="opencode", dest="client", help="Configure for OpenCode Desktop & CLI")
    mcp_p.add_argument("--chatgpt", action="store_const", const="chatgpt", dest="client", help="Configure for ChatGPT Desktop & Codex CLI")
    mcp_p.add_argument("--vscode", action="store_const", const="cline", dest="client", help="Configure for VS Code / Cline")
    mcp_p.add_argument("--auto", action="store_const", const="auto", dest="client", help="Auto-detect IDEs in workspace and host environment")
    mcp_p.add_argument("--all", action="store_const", const="all", dest="client", help="Configure all detected IDE environments")
    mcp_p.add_argument("--workspace", default=".", help="Workspace path for the MCP server")
    mcp_p.add_argument("--profile", default="qwen3-8b-q6k", help="Default profile for MCP delegation")
    mcp_p.add_argument("--dry-run", action="store_true", help="Print config without writing to disk")
    mcp_p.add_argument("--write", action="store_true", help="Write/merge directly to client configuration file")
    mcp_p.add_argument("--path", type=Path, help="Explicit configuration file path")


    # test-run / smoke
    smoke_p = subparsers.add_parser("test-run", aliases=["smoke"], help="Run interactive end-to-end smoke test")
    smoke_p.add_argument("--profile", default="qwen2.5-coder", help="Model profile to use")
    smoke_p.add_argument("--mock", action="store_true", help="Use scripted mock model instead of live Ollama")
    smoke_p.add_argument("--no-fallback", action="store_true", help="Do not fallback to mock if Ollama is offline")

    # serve-mcp
    serve_mcp_p = subparsers.add_parser("serve-mcp", help="Run the MCP stdio server")
    serve_mcp_p.add_argument("--workspace-ref", default="workspace")
    serve_mcp_p.add_argument("--workspace", default=".")
    serve_mcp_p.add_argument("--enable-tasks", action="store_true", help="Mount Tasks extension and apply_proposal")
    serve_mcp_p.add_argument("--profile", help="Default model profile")
    serve_mcp_p.add_argument("--endpoint", help="Ollama API endpoint")

    # monitor
    mon_p = subparsers.add_parser("monitor", help="Start the live HTTP monitoring dashboard")
    mon_p.add_argument("--host", default="127.0.0.1")
    mon_p.add_argument("--port", type=int, default=8765)

    return parser


def handle_subcommand(args: argparse.Namespace) -> int:
    sub = args.subcommand
    if sub == "doctor":
        report = diagnose_environment(endpoint=args.endpoint)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(report.render_text())
        if getattr(args, "strict", False):
            return 0 if report.healthy else 1
        return 0


    if sub == "init-mcp":
        dry_run = not args.write or args.dry_run
        res = integrate_mcp_config(
            client=args.client,
            workspace=args.workspace,
            profile=args.profile,
            target_path=args.path,
            dry_run=dry_run,
        )
        if "results" in res:
            print(f"--- Multi-Client MCP Configuration ({'Preview' if dry_run else 'Applied'}) ---")
            for sub_res in res["results"]:
                status = "[DRY-RUN]" if dry_run else "[OK]"
                print(f"{status} {sub_res['client'].upper()}: {sub_res['path']}")
            if dry_run:
                print("\nUse --write to automatically merge these configs into the files.")
        else:
            if dry_run:
                print(f"--- MCP Configuration Preview ({args.client}) ---")
                print(f"Target Path: {res['path']}")
                print(json.dumps(res["config"], indent=2, ensure_ascii=False))
                print("\nUse --write to automatically merge this config into the file.")
            else:
                print(f"[OK] Successfully integrated MCP server into: {res['path']}")
        return 0


    if sub in ("test-run", "smoke"):
        res = run_smoke_test(
            profile_name=args.profile,
            use_mock=args.mock,
            fallback_to_mock=not args.no_fallback,
            verbose=True,
        )
        return 0 if res["success"] else 1

    if sub == "serve-mcp":
        from .mcp_server import build_server
        from .service import DelegationService

        ws_path = str(Path(args.workspace).resolve())
        service = DelegationService({args.workspace_ref: ws_path})
        server = build_server(service, enable_tasks=args.enable_tasks)
        server.run(transport="stdio")
        return 0

    if sub == "monitor":
        from .monitor import MonitorServer
        from .stats import DelegationStats

        stats = DelegationStats()
        server = MonitorServer(host=args.host, port=args.port, stats=stats)
        print(f"Starting Codex Monitor on {server.url}/dashboard (Press Ctrl+C to stop)...")
        server.start()
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            print("\nMonitor stopped.")
        return 0

    return -1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.subcommand:
        sub_code = handle_subcommand(args)
        if sub_code != -1:
            return sub_code

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
            if args.unload_all or args.unload_model or args.vram_limit_bytes is not None or args.calibrate_workers is not None:
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
        if args.calibrate_workers is not None:
            report = calibrate_for_model(
                client,
                profile.model,
                vram_budget_bytes=args.calibrate_workers,
                per_worker_context_bytes=args.parallel_context_bytes,
            )
            print(json.dumps({"status": "calibrated", "report": report}, ensure_ascii=False, indent=2))
            return 0
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
