"""Subcommand dispatch for the local-coding-agent CLI (part 2)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..benchmark import run_benchmark, write_artifact
from ..doctor import diagnose_environment
from ..mcp_config import integrate_mcp_config
from ..memory import ModelMemoryManager
from ..ollama_adapter import OllamaError, build_client
from ..profiles import get_profile
from ..skill_config import integrate_skill_config
from ..smoke import run_smoke_test


def _handle_skill(args: argparse.Namespace) -> int:
    dry_run = not args.write or args.dry_run
    res = integrate_skill_config(
        client=args.client,
        workspace=args.workspace,
        target_path=args.path,
        dry_run=dry_run,
        print_content=args.print_content,
    )
    if args.print_content:
        content = res.get("content", "")
        try:
            print(content)
        except UnicodeEncodeError:
            if hasattr(sys.stdout, "buffer"):
                sys.stdout.buffer.write(content.encode("utf-8", errors="replace"))
                sys.stdout.buffer.write(b"\n")
                sys.stdout.buffer.flush()
            else:
                print(content.encode("ascii", errors="replace").decode("ascii"))
        return 0

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        if "results" in res:
            print(f"--- Multi-Agent Skill Installation ({'Preview' if dry_run else 'Installed'}) ---")
            for sub_res in res["results"]:
                status = "[DRY-RUN]" if dry_run else "[OK]"
                print(f"{status} {sub_res['client'].upper()}: {sub_res['path']}")
            if dry_run:
                print("\nUse --write to write SKILL.md into these directories.")
        else:
            status = "[DRY-RUN]" if dry_run else "[OK]"
            print(f"{status} {res.get('client', 'custom').upper()}: {res.get('path')}")
            if dry_run:
                print("\nUse --write to write SKILL.md into this path.")
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    if getattr(args, "fix", False):
        from ..doctor import remediate_environment

        write = not getattr(args, "dry_run", False)
        fix_rep = remediate_environment(endpoint=args.endpoint, write=write)
        if args.json:
            print(json.dumps(fix_rep.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(fix_rep.render_text())
        return 0 if fix_rep.success else 1

    report = diagnose_environment(endpoint=args.endpoint)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.render_text())
    if getattr(args, "strict", False):
        return 0 if report.healthy else 1
    return 0


def _handle_init_mcp(args: argparse.Namespace) -> int:
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
            config = res["config"]
            print(config if isinstance(config, str) else json.dumps(config, indent=2, ensure_ascii=False))
            print("\nUse --write to automatically merge this config into the file.")
        else:
            print(f"[OK] Successfully integrated MCP server into: {res['path']}")
    return 0


def _handle_smoke(args: argparse.Namespace) -> int:
    res = run_smoke_test(
        profile_name=args.profile,
        use_mock=args.mock,
        fallback_to_mock=not args.no_fallback,
        verbose=True,
    )
    return 0 if res["success"] else 1


def _handle_serve_mcp(args: argparse.Namespace) -> int:
    from ..mcp_server import build_server
    from ..service import DelegationService

    ws_path = str(Path(args.workspace).resolve())
    service = DelegationService({args.workspace_ref: ws_path})
    server = build_server(service, enable_tasks=args.enable_tasks)
    server.run(transport="stdio")
    return 0


def _handle_serve_acp(args: argparse.Namespace) -> int:
    from ..acp_server import AcpServer

    server = AcpServer(
        default_workspace=args.workspace,
        default_profile=args.profile,
        framing=args.framing,
    )
    server.serve()
    return 0


def _handle_monitor(args: argparse.Namespace) -> int:
    from ..monitor import MonitorServer
    from ..stats import DelegationStats

    if args.subcommand in ("ui", "app"):
        print("=" * 72)
        print(" [EXPERIMENTAL PREVIEW] Web Workbench UI is experimental incubation.")
        print(" Full standalone Desktop Harness redesign is currently in progress.")
        print("=" * 72)

    stats = DelegationStats()
    server = MonitorServer(host=args.host, port=args.port, stats=stats)
    path_name = "workbench" if args.subcommand in ("ui", "app") else "dashboard"
    print(f"Starting server on {server.url}/{path_name} (Press Ctrl+C to stop)...")
    server.start()
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        print("\nServer stopped.")
    return 0


def _handle_desktop(args: argparse.Namespace) -> int:
    from ..desktop import launch_desktop_app

    return launch_desktop_app(
        host=args.host,
        port=args.port,
        workspace=args.workspace,
        default_profile=args.profile,
        browser=getattr(args, "browser", False),
    )


def _handle_scan_models(args: argparse.Namespace) -> int:
    from ..model_scanner import get_model_registry

    registry = get_model_registry()
    if getattr(args, "add_dir", None):
        added = registry.add_custom_directory(args.add_dir)
        res = {"status": "added" if added else "already_present", "directory": args.add_dir}
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if getattr(args, "remove_dir", None):
        removed = registry.remove_custom_directory(args.remove_dir)
        res = {"status": "removed" if removed else "not_found", "directory": args.remove_dir}
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if getattr(args, "list_dirs", False):
        dirs = registry.list_custom_directories()
        res = {"custom_directories": dirs}
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    target_drives = [d.strip() for d in args.drives.split(",") if d.strip()] if getattr(args, "drives", None) else None
    discovered = registry.scan(deep=getattr(args, "deep", False), target_drives=target_drives)
    models_data = [m.to_dict() for m in discovered]
    if getattr(args, "json", False):
        print(json.dumps({"total_models": len(models_data), "models": models_data}, indent=2, ensure_ascii=False))
    else:
        print(f"--- Discovered Local GGUF Models ({len(models_data)}) ---")
        for m in models_data:
            print(f"[{m['backend'].upper()}] {m['name']} ({m['size_gb']} GB) -> {m['path']}")
    return 0


def _handle_benchmark(args: argparse.Namespace) -> int:
    overrides = {}
    if args.endpoint:
        overrides["endpoint"] = args.endpoint
    names = tuple(args.benchmark_models or (
        "qwen3-8b-q6k",
        "qwen3.8-27b-q4",
        "qwen2.5-coder",
        "ornith-9b",
        "qwen3-coder-30b",
        "devstral-small-2-24b",
    ))
    artifact = {
        "schema": "local-coding-agent/benchmark-v1",
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
        benchmark_client = build_client(benchmark_profile)
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
            if getattr(args, "ladder", False):
                from ..capability import CapabilityLadder
                ladder = CapabilityLadder()
                ladder_vec = ladder.evaluate(name, benchmark_client, max_turns=args.max_turns)
                run = {
                    "profile": benchmark_profile.__dict__,
                    "status": "completed",
                    "capability_ladder": ladder_vec.as_dict(),
                }
            else:
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
    if getattr(args, "ladder", False) and not getattr(args, "json", False):
        for m in artifact["models"]:
            if m.get("status") == "completed" and "capability_ladder" in m:
                lad = m["capability_ladder"]
                print("\n" + "=" * 64)
                print(f"  Capability Ladder — {lad['model']}")
                print(f"  Overall Tier {lad['overall_tier']}: {lad['tier_label']}")
                print("=" * 64)
                print(f"  Granularity: {lad['granularity_tolerance']} | Gen Speed: {lad['tps_generation']} tok/s")
                print(f"  Confidence CI95: {lad['confidence_95_ci']} | Correctness: {lad['correctness_percent']}%")
                print("-" * 64)
                for t_idx, t_data in sorted(lad.get("tested_tiers", {}).items()):
                    mark = "[PASS]" if t_data.get("status") == "passed" else "[FAIL]"
                    print(f"  Tier {t_idx} ({t_data.get('label')}): {mark} {t_data.get('passed_cases')}/{t_data.get('total_cases')} ({t_data.get('score_percent')}%)")
                print("=" * 64 + "\n")
    else:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0 if artifact["models"] and all(item["status"] == "completed" for item in artifact["models"]) else 1
