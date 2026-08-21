"""Command-line entry point for local-coding-agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .atomizer import TaskBudget, decompose, preflight
from .benchmark import run_benchmark, write_artifact
from .calibration import calibrate_for_model
from .controller import Controller
from .delegator import BY_FILES, PER_FILE
from .doctor import diagnose_environment
from .mcp_config import integrate_mcp_config
from .memory import ModelMemoryManager
from .ollama_adapter import OllamaError, build_client
from .profiles import get_profile, list_profiles
from .skill_config import integrate_skill_config
from .smoke import run_smoke_test
from .task import TaskEnvelope
from .validators import apply_patch, check_patch_applies


def load_task_file(path: str | Path) -> TaskEnvelope:
    raw = Path(path).read_bytes().decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("task JSON must be an object")
    return TaskEnvelope.from_mapping(value)


def load_task_input(
    task_value: str | Path | None = None,
    task_file: str | Path | None = None,
) -> TaskEnvelope:
    if task_file is not None:
        return load_task_file(task_file)
    if task_value is not None:
        val_str = str(task_value).strip()
        if (val_str.startswith("'") and val_str.endswith("'")) or (val_str.startswith('"') and val_str.endswith('"')):
            stripped = val_str[1:-1].strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                val_str = stripped
        if val_str.startswith("{") and val_str.endswith("}"):
            try:
                parsed = json.loads(val_str)
                if not isinstance(parsed, dict):
                    raise ValueError("task JSON must be an object")
                return TaskEnvelope.from_mapping(parsed)
            except json.JSONDecodeError:
                # Try replacing single quotes with double quotes if standard JSON failed
                try:
                    import ast
                    parsed_ast = ast.literal_eval(val_str)
                    if isinstance(parsed_ast, dict):
                        return TaskEnvelope.from_mapping(parsed_ast)
                except Exception:
                    pass
                raise ValueError(f"malformed inline task JSON: {val_str}")
        try:
            path = Path(task_value)
            if path.is_file():
                return load_task_file(path)
        except (OSError, ValueError):
            pass
        try:
            parsed = json.loads(val_str)
            if isinstance(parsed, dict):
                return TaskEnvelope.from_mapping(parsed)
        except Exception:
            pass
        return load_task_file(task_value)
    raise ValueError("--task or --task-file is required")



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent",
        description="Local Coding Agent: Bounded controller for atomic coding tasks.",
    )

    # Root options (backward compatibility)
    parser.add_argument("--task", help="UTF-8 JSON task envelope (inline JSON string or file path)")
    parser.add_argument("--task-file", type=Path, dest="task_file", help="Path to UTF-8 JSON task envelope file")
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
        default=Path(".local-run") / "benchmarks" / "latest.json",
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

    # 1. delegate (run)
    del_p = subparsers.add_parser("delegate", aliases=["run"], help="Delegate an atomic task to local model")
    del_p.add_argument("--task", help="UTF-8 JSON task envelope (inline string or file path)")
    del_p.add_argument("--task-file", type=Path, help="Path to task JSON envelope file")
    del_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace directory")
    del_p.add_argument("--profile", choices=list_profiles(), default="qwen2.5-1.5b", help="Model profile to use")
    del_p.add_argument("--endpoint", help="Override Ollama/OpenAI endpoint")
    del_p.add_argument("--max-turns", type=int, default=4, help="Maximum conversation turns")
    del_p.add_argument("--num-ctx", type=int, help="Override context window in tokens")
    del_p.add_argument("--speculative-drafts", type=int, default=1, help="Number of concurrent speculative drafts to race")
    del_p.add_argument("--apply", action="store_true", help="Apply accepted patch directly with auto-rollback")
    del_p.add_argument("--json", action="store_true", help="Ensure JSON output")

    # 2. decompose (atomize)
    dec_p = subparsers.add_parser("decompose", aliases=["atomize"], help="Preflight and decompose wide tasks into atomic envelopes")
    dec_p.add_argument("--task", help="UTF-8 JSON task envelope (inline string or file path)")
    dec_p.add_argument("--task-file", type=Path, help="Path to task JSON envelope file")
    dec_p.add_argument("--strategy", choices=["by_files", "per_file"], default="by_files", help="Decomposition strategy")
    dec_p.add_argument("--budget-files", type=int, default=5, help="Maximum allowed files per subtask envelope")
    dec_p.add_argument("--budget-bytes", type=int, default=32000, help="Maximum context bytes")
    dec_p.add_argument("--budget-checks", type=int, default=3, help="Maximum test checks per envelope")
    dec_p.add_argument("--json", action="store_true", help="Output decomposition result in JSON format")

    # 3. profiles
    prof_p = subparsers.add_parser("profiles", help="List and inspect model profiles")
    prof_p.add_argument("profile_action", nargs="?", choices=["list", "get"], default="list", help="Action: list or get")
    prof_p.add_argument("name", nargs="?", help="Profile name (for 'get')")
    prof_p.add_argument("--check-ollama", action="store_true", help="Query Ollama /api/tags to show local install status")
    prof_p.add_argument("--endpoint", default="http://127.0.0.1:11434", help="Ollama endpoint")
    prof_p.add_argument("--json", action="store_true", help="Output profiles in JSON format")

    # 4. memory
    mem_p = subparsers.add_parser("memory", help="Inspect and manage Ollama VRAM allocation")
    mem_p.add_argument("memory_action", choices=["status", "unload", "unload-all", "enforce"], help="Memory action")
    mem_p.add_argument("model", nargs="?", help="Model name to unload (for 'unload')")
    mem_p.add_argument("--limit", type=int, dest="limit", help="VRAM limit in bytes (for 'enforce')")
    mem_p.add_argument("--keep", action="append", default=[], help="Model name to protect from eviction")
    mem_p.add_argument("--profile", default="qwen2.5-1.5b", help="Profile to derive client settings")
    mem_p.add_argument("--endpoint", default="http://127.0.0.1:11434", help="Ollama endpoint")
    mem_p.add_argument("--json", action="store_true", help="Output memory status in JSON")

    # 5. calibrate
    cal_p = subparsers.add_parser("calibrate", help="Calculate worker capacity from VRAM budget")
    cal_p.add_argument("--vram-bytes", type=int, required=True, help="Target VRAM budget in bytes")
    cal_p.add_argument("--profile", choices=list_profiles(), default="qwen3-8b-q6k", help="Model profile")
    cal_p.add_argument("--parallel-context-bytes", type=int, help="Context VRAM delta per worker")
    cal_p.add_argument("--endpoint", help="Ollama endpoint")
    cal_p.add_argument("--json", action="store_true", help="Output report in JSON format")

    # 6. benchmark
    bench_p = subparsers.add_parser("benchmark", help="Run benchmark across model profiles")
    bench_p.add_argument("--model", action="append", choices=list_profiles(), dest="benchmark_models", help="Model profile to benchmark")
    bench_p.add_argument("--repeats", type=int, default=1, dest="benchmark_repeats", help="Benchmark repeats")
    bench_p.add_argument("--timeout-seconds", type=float, default=300, dest="benchmark_timeout_seconds", help="Timeout per model run")
    bench_p.add_argument("--output", type=Path, default=Path(".local-run") / "benchmarks" / "latest.json", dest="benchmark_output", help="Output artifact path")
    bench_p.add_argument("--max-turns", type=int, default=4, help="Max turns per task")
    bench_p.add_argument("--json", action="store_true", help="Output benchmark results in JSON format")
    bench_p.add_argument("--ladder", action="store_true", help="Run adaptive capability ladder benchmark")


    # 7. apply
    app_p = subparsers.add_parser("apply", help="Safely apply patch to workspace with verification and auto-rollback")
    app_p.add_argument("--patch-file", type=Path, help="Path to unified diff patch file")
    app_p.add_argument("--patch", help="Unified diff patch string")
    app_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Target workspace path")
    app_p.add_argument("--check", action="append", dest="checks", default=[], help="Targeted check command(s) to verify")
    app_p.add_argument("--json", action="store_true", help="Output result in JSON format")

    # 8. doctor
    doc_p = subparsers.add_parser("doctor", help="Run system diagnostics and model recommendations")
    doc_p.add_argument("--endpoint", default="http://127.0.0.1:11434", help="Ollama endpoint to check")
    doc_p.add_argument("--fix", action="store_true", help="Auto-remediate missing MCP configs, Agent Skills, and setup")
    doc_p.add_argument("--dry-run", action="store_true", help="Preview remediation actions without writing")
    doc_p.add_argument("--json", action="store_true", help="Output diagnostic report in JSON format")
    doc_p.add_argument("--strict", action="store_true", help="Exit with code 1 if any check fails")

    # 9. init-mcp
    mcp_p = subparsers.add_parser("init-mcp", help="Generate or configure MCP client integration")
    mcp_p.add_argument(
        "--client",
        choices=["claude", "cursor", "windsurf", "cline", "antigravity", "opencode", "codex", "chatgpt", "vscode", "auto", "all"],
        default="claude",
        help="Target MCP client (default: claude, or 'auto'/'all')",
    )
    mcp_p.add_argument("--claude", action="store_const", const="claude", dest="client", help="Configure for Claude Desktop & Claude Code")
    mcp_p.add_argument("--cursor", action="store_const", const="cursor", dest="client", help="Configure for Cursor")
    mcp_p.add_argument("--windsurf", action="store_const", const="windsurf", dest="client", help="Configure for Windsurf")
    mcp_p.add_argument("--cline", action="store_const", const="cline", dest="client", help="Configure for Cline Desktop / Extension")
    mcp_p.add_argument("--antigravity", action="store_const", const="antigravity", dest="client", help="Configure for Antigravity Desktop & agy CLI")
    mcp_p.add_argument("--opencode", action="store_const", const="opencode", dest="client", help="Configure for OpenCode Desktop & CLI")
    mcp_p.add_argument("--codex", action="store_const", const="codex", dest="client", help="Configure Codex Desktop & Codex CLI (~/.codex/config.toml)")
    mcp_p.add_argument("--chatgpt", action="store_const", const="codex", dest="client", help="Legacy alias for --codex")
    mcp_p.add_argument("--vscode", action="store_const", const="cline", dest="client", help="Configure for VS Code / Cline")
    mcp_p.add_argument("--auto", action="store_const", const="auto", dest="client", help="Auto-detect IDEs in workspace and host environment")
    mcp_p.add_argument("--all", action="store_const", const="all", dest="client", help="Configure all detected IDE environments")
    mcp_p.add_argument("--workspace", default=".", help="Workspace path for the MCP server")
    mcp_p.add_argument("--profile", default="qwen3-8b-q6k", help="Default profile for MCP delegation")
    mcp_p.add_argument("--dry-run", action="store_true", help="Print config without writing to disk")
    mcp_p.add_argument("--write", action="store_true", help="Write/merge directly to client configuration file")
    mcp_p.add_argument("--path", type=Path, help="Explicit configuration file path")

    # 10. init-skill (skill)
    skill_p = subparsers.add_parser("init-skill", aliases=["skill"], help="Export or install Agent Skill to agent directories")
    skill_p.add_argument(
        "--client",
        choices=["codex", "antigravity", "claude", "workspace", "auto", "all"],
        default="auto",
        help="Target agent ecosystem (default: auto)",
    )
    skill_p.add_argument("--workspace", default=".", help="Workspace path")
    skill_p.add_argument("--target-dir", type=Path, dest="path", help="Explicit target directory or file path")
    skill_p.add_argument("--dry-run", action="store_true", help="Preview target paths without writing")
    skill_p.add_argument("--write", action="store_true", help="Write SKILL.md to target directories")
    skill_p.add_argument("--print", action="store_true", dest="print_content", help="Print SKILL.md to stdout")
    skill_p.add_argument("--json", action="store_true", help="Output result in JSON format")

    # 11. test-run / smoke
    smoke_p = subparsers.add_parser("test-run", aliases=["smoke"], help="Run interactive end-to-end smoke test")
    smoke_p.add_argument("--profile", default="qwen2.5-coder", help="Model profile to use")
    smoke_p.add_argument("--mock", action="store_true", help="Use scripted mock model instead of live Ollama")
    smoke_p.add_argument("--no-fallback", action="store_true", help="Do not fallback to mock if Ollama is offline")

    # 12. serve-mcp
    serve_mcp_p = subparsers.add_parser("serve-mcp", help="Run the MCP stdio server")
    serve_mcp_p.add_argument("--workspace-ref", default="workspace")
    serve_mcp_p.add_argument("--workspace", default=".")
    serve_mcp_p.add_argument("--enable-tasks", action="store_true", help="Mount Tasks extension and apply_proposal")
    serve_mcp_p.add_argument("--profile", help="Default model profile")
    serve_mcp_p.add_argument("--endpoint", help="Ollama API endpoint")

    # 13. monitor
    mon_p = subparsers.add_parser("monitor", help="Start the live HTTP monitoring dashboard")
    mon_p.add_argument("--host", default="127.0.0.1")
    mon_p.add_argument("--port", type=int, default=8765)

    # 14. skeletonize
    skel_p = subparsers.add_parser("skeletonize", help="Skeletonize source file by collapsing non-target structures")
    skel_p.add_argument("file", type=Path, help="Path to source file")
    skel_p.add_argument("--symbol", action="append", dest="symbols", default=[], help="Symbol name to keep expanded")
    skel_p.add_argument("--json", action="store_true", help="Output skeleton in JSON format")

    # 15. lint-patch
    lint_p = subparsers.add_parser("lint-patch", help="Run sub-50ms fast static linter pre-gates on a patch")
    lint_p.add_argument("--patch-file", type=Path, help="Path to unified diff patch file")
    lint_p.add_argument("--patch", help="Unified diff patch string")
    lint_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Target workspace path")
    lint_p.add_argument("--json", action="store_true", help="Output linter report in JSON format")

    # 16. ui (app)
    ui_p = subparsers.add_parser("ui", aliases=["app"], help="[Experimental Preview] Start the standalone Web Workbench & Coding Arena")
    ui_p.add_argument("--host", default="127.0.0.1")
    ui_p.add_argument("--port", type=int, default=8765)
    ui_p.add_argument("--experimental", action="store_true", help="Acknowledge running the experimental web workbench preview")

    # 17. desktop
    desk_p = subparsers.add_parser("desktop", help="Start the Standalone Desktop AI Coding Harness (R23)")
    desk_p.add_argument("--host", default="127.0.0.1", help="Host address to bind")
    desk_p.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765)")
    desk_p.add_argument("--browser", action="store_true", help="Force open in system browser instead of native window")
    desk_p.add_argument("--workspace", default=".", help="Target workspace path")
    desk_p.add_argument("--profile", default="qwen2.5-coder", help="Default model profile")

    # 18. spill-read (R24)
    spill_p = subparsers.add_parser("spill-read", help="Read or paginate a spilled tool output artifact (R24)")
    spill_p.add_argument("locator", nargs="?", default=None, help="Spill locator token (e.g. locator:spill:... or path)")
    spill_p.add_argument("--locator", dest="opt_locator", help="Explicit spill locator")
    spill_p.add_argument("--offset", type=int, default=0, help="0-based line offset")
    spill_p.add_argument("--limit", type=int, default=1000, help="Maximum number of lines to read")
    spill_p.add_argument("--json", action="store_true", help="Output result in JSON format")

    # 19. grep (R24)
    grep_p = subparsers.add_parser("grep", help="Fast ripgrep / regex code search across workspace (R24)")
    grep_p.add_argument("query", help="Search query string or regex pattern")
    grep_p.add_argument("paths", nargs="*", default=[], help="Glob filters or file paths (e.g. *.py)")
    grep_p.add_argument("--regex", action="store_true", help="Treat query as regular expression")
    grep_p.add_argument("--case-sensitive", action="store_true", help="Perform case-sensitive matching")
    grep_p.add_argument("--max-results", type=int, default=100, help="Maximum number of matching lines")
    grep_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace root directory")
    grep_p.add_argument("--json", action="store_true", help="Output matches in JSON format")

    # 20. lsp (R25)
    lsp_p = subparsers.add_parser("lsp", help="Run LSP code intelligence query (R25)")
    lsp_p.add_argument("--operation", choices=["definition", "references", "hover", "symbols"], required=True, help="LSP query operation")
    lsp_p.add_argument("--file", type=Path, required=True, help="Target source file path")
    lsp_p.add_argument("--line", type=int, default=0, help="0-based cursor line number")
    lsp_p.add_argument("--char", type=int, default=0, help="0-based cursor column offset")
    lsp_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace root directory")
    lsp_p.add_argument("--json", action="store_true", help="Output result in JSON format")

    # 21. serve-acp (R29)
    acp_p = subparsers.add_parser("serve-acp", help="Start Agent Client Protocol (ACP) JSON-RPC stdio server (R29)")
    acp_p.add_argument("--workspace", type=Path, default=Path.cwd(), help="Default workspace directory")
    acp_p.add_argument("--profile", default="qwen2.5-1.5b", help="Default model profile")
    acp_p.add_argument("--framing", choices=["auto", "jsonl", "content-length"], default="auto", help="Framing mode")

    # 22. scan-models
    scan_p = subparsers.add_parser("scan-models", help="Discover and index local GGUF models across drives")
    scan_p.add_argument("--deep", action="store_true", help="Perform deep filesystem scan across all system drives")
    scan_p.add_argument("--drives", help="Comma-separated drive letters to target (e.g. C,D,Q)")
    scan_p.add_argument("--add-dir", dest="add_dir", help="Add custom directory to persistent model registry")
    scan_p.add_argument("--remove-dir", dest="remove_dir", help="Remove custom directory from registry")
    scan_p.add_argument("--list-dirs", action="store_true", help="List all registered custom model directories")
    scan_p.add_argument("--json", action="store_true", help="Output discovered models in JSON format")

    return parser


def handle_subcommand(args: argparse.Namespace) -> int:
    sub = args.subcommand
    if sub in ("delegate", "run"):
        try:
            task = load_task_input(args.task, getattr(args, "task_file", None))
            if getattr(args, "speculative_drafts", 1) > 1:
                from threading import Event
                from .speculative_racing import SpeculativeRacer

                def _make_runner(draft_idx: int):
                    def _run(cancel_ev: Event) -> dict[str, Any]:
                        overrides: dict[str, Any] = {}
                        if args.endpoint:
                            overrides["endpoint"] = args.endpoint
                        if args.num_ctx is not None:
                            overrides["num_ctx"] = args.num_ctx
                        temp = 0.0 if draft_idx == 0 else min(0.15 * draft_idx, 0.7)
                        overrides["temperature"] = temp
                        prof = get_profile(args.profile, **overrides)
                        cl = build_client(prof)
                        return Controller(
                            cl,
                            args.workspace,
                            max_turns=args.max_turns,
                            cancel_event=cancel_ev,
                        ).run(task, apply=args.apply)

                    return _run

                runners = [_make_runner(i) for i in range(args.speculative_drafts)]
                racer = SpeculativeRacer()
                result = racer.run(runners)
            else:
                overrides = {}
                if args.endpoint:
                    overrides["endpoint"] = args.endpoint
                if args.num_ctx is not None:
                    overrides["num_ctx"] = args.num_ctx
                profile = get_profile(args.profile, **overrides)
                client = build_client(profile)
                result = Controller(
                    client,
                    args.workspace,
                    max_turns=args.max_turns,
                ).run(task, apply=args.apply)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, OllamaError) as error:
            print(json.dumps({"status": "failed", "error": {"kind": "input", "message": str(error)}}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "accepted" else 1

    if sub in ("decompose", "atomize"):
        try:
            task = load_task_input(args.task, getattr(args, "task_file", None))
            budget = TaskBudget(
                max_files=args.budget_files,
                max_context_bytes=args.budget_bytes,
                max_checks=args.budget_checks,
            )
            pre = preflight(task, budget)
            if args.strategy == "per_file":
                children = PER_FILE.split(task, budget)
            else:
                children = BY_FILES.split(task, budget)
            payload = {
                "task_id": task.id,
                "preflight": {
                    "accepted": pre.accepted,
                    "reason": pre.reason,
                    "issues": list(pre.issues),
                },
                "strategy": args.strategy,
                "count": len(children),
                "children": [c.as_dict() for c in children],
            }
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            print(json.dumps({"status": "failed", "error": {"kind": "input", "message": str(error)}}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["children"] else 1

    if sub == "profiles":
        action = getattr(args, "profile_action", "list") or "list"
        if action == "get":
            if not args.name:
                print(json.dumps({"error": "profile name required for 'get'"}, ensure_ascii=False))
                return 2
            try:
                prof = get_profile(args.name)
                print(json.dumps(prof.__dict__, ensure_ascii=False, indent=2))
                return 0
            except ValueError as error:
                print(json.dumps({"error": str(error)}, ensure_ascii=False))
                return 1

        # list
        profile_names = list_profiles()
        installed_map: dict[str, bool] = {}
        if args.check_ollama:
            try:
                c = build_client(get_profile("qwen2.5-1.5b", endpoint=args.endpoint))
                tags = c.available_models().get("models", [])
                tag_names = {t.get("name") for t in tags if isinstance(t, dict) and "name" in t}
                for p_name in profile_names:
                    p_obj = get_profile(p_name)
                    installed_map[p_name] = p_obj.model in tag_names
            except Exception:
                pass

        items = []
        for p_name in profile_names:
            p_obj = get_profile(p_name)
            item = {
                "name": p_name,
                "model": p_obj.model,
                "provider": getattr(p_obj, "provider", "ollama"),
                "num_ctx": p_obj.num_ctx,
                "num_predict": p_obj.num_predict,
                "max_context_length": p_obj.max_context_length,
                "think": p_obj.think,
            }
            if args.check_ollama:
                item["installed_locally"] = installed_map.get(p_name, False)
            items.append(item)

        if args.json:
            print(json.dumps({"profiles": items}, ensure_ascii=False, indent=2))
        else:
            print(f"{'PROFILE':<25} {'MODEL':<35} {'CTX':<8} {'THINK':<6}")
            print("-" * 76)
            for it in items:
                print(f"{it['name']:<25} {it['model']:<35} {it['num_ctx']:<8} {str(it['think']):<6}")
        return 0

    if sub == "memory":
        action = getattr(args, "memory_action", "status")
        try:
            profile = get_profile(args.profile, endpoint=args.endpoint)
            client = build_client(profile)
            manager = ModelMemoryManager(client)
            if action == "unload":
                if not args.model:
                    print(json.dumps({"error": "model name required for 'unload'"}, ensure_ascii=False))
                    return 2
                snapshot = manager.unload_model(args.model)
            elif action == "unload-all":
                snapshot = manager.unload_all()
            elif action == "enforce":
                if args.limit is None:
                    print(json.dumps({"error": "--limit required for 'enforce'"}, ensure_ascii=False))
                    return 2
                snapshot = manager.enforce_limit(args.limit, keep=tuple(args.keep or []))
            else:
                snapshot = manager.snapshot()
            res = {"status": "memory_reconciled", "action": action, "memory": snapshot.as_dict()}
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        except Exception as error:
            print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            return 1

    if sub == "calibrate":
        try:
            overrides = {}
            if args.endpoint:
                overrides["endpoint"] = args.endpoint
            profile = get_profile(args.profile, **overrides)
            client = build_client(profile)
            report = calibrate_for_model(
                client,
                profile.model,
                vram_budget_bytes=args.vram_bytes,
                per_worker_context_bytes=args.parallel_context_bytes,
            )
            print(json.dumps({"status": "calibrated", "report": report}, ensure_ascii=False, indent=2))
            return 0
        except Exception as error:
            print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            return 1

    if sub == "apply":
        try:
            if args.patch_file:
                patch = Path(args.patch_file).read_text(encoding="utf-8")
            elif args.patch:
                patch = args.patch
            else:
                print(json.dumps({"error": "--patch or --patch-file is required"}, ensure_ascii=False))
                return 2

            ws_root = Path(args.workspace).resolve()
            applies, apply_err = check_patch_applies(ws_root, patch)
            if not applies:
                res = {"status": "rejected", "error": {"kind": "patch_check_failed", "message": apply_err}, "applied": False}
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 1

            applied, detail = apply_patch(ws_root, patch)
            if not applied:
                res = {"status": "rejected", "error": {"kind": "apply_failed", "message": detail}, "applied": False}
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 1

            check_results = []
            checks_passed = True
            for cmd in args.checks:
                cp = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=ws_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=60,
                )
                passed = cp.returncode == 0
                check_results.append({
                    "command": cmd,
                    "passed": passed,
                    "evidence": (cp.stdout + cp.stderr).strip()[:500],
                })
                if not passed:
                    checks_passed = False
                    break

            if not checks_passed:
                # Rollback
                rollback_ok, rollback_detail = apply_patch(ws_root, patch, reverse=True)
                res = {
                    "status": "rejected",
                    "error": {"kind": "post_apply_check_failed", "message": "one or more checks failed; patch rolled back"},
                    "checks": check_results,
                    "applied": False,
                    "rollback_ok": rollback_ok,
                }
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 1

            res = {"status": "accepted", "applied": True, "checks": check_results}
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        except Exception as error:
            print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            return 1

    if sub in ("init-skill", "skill"):
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

    if sub == "doctor":
        if getattr(args, "fix", False):
            from .doctor import remediate_environment

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
                config = res["config"]
                print(config if isinstance(config, str) else json.dumps(config, indent=2, ensure_ascii=False))
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

    if sub == "serve-acp":
        from .acp_server import AcpServer

        server = AcpServer(
            default_workspace=args.workspace,
            default_profile=args.profile,
            framing=args.framing,
        )
        server.serve()
        return 0

    if sub in ("monitor", "ui", "app"):
        from .monitor import MonitorServer
        from .stats import DelegationStats

        if sub in ("ui", "app"):
            print("=" * 72)
            print(" [EXPERIMENTAL PREVIEW] Web Workbench UI is experimental incubation.")
            print(" Full standalone Desktop Harness redesign is currently in progress.")
            print("=" * 72)

        stats = DelegationStats()
        server = MonitorServer(host=args.host, port=args.port, stats=stats)
        path_name = "workbench" if sub in ("ui", "app") else "dashboard"
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

    if sub == "desktop":
        from .desktop import launch_desktop_app

        return launch_desktop_app(
            host=args.host,
            port=args.port,
            workspace=args.workspace,
            default_profile=args.profile,
            browser=getattr(args, "browser", False),
        )

    if sub == "scan-models":
        from .model_scanner import get_model_registry

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

    if sub == "benchmark":
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
                    from .capability import CapabilityLadder
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

    if sub == "skeletonize":
        from .ast_compactor import skeletonize_file

        try:
            skeleton = skeletonize_file(str(args.file), target_symbols=args.symbols)
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"file": str(args.file), "symbols": args.symbols, "skeleton": skeleton},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                try:
                    print(skeleton)
                except UnicodeEncodeError:
                    if hasattr(sys.stdout, "buffer"):
                        sys.stdout.buffer.write(skeleton.encode("utf-8", errors="replace"))
                        sys.stdout.buffer.write(b"\n")
                        sys.stdout.buffer.flush()
                    else:
                        print(skeleton.encode("ascii", errors="replace").decode("ascii"))
            return 0
        except Exception as error:
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"status": "failed", "error": str(error)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(f"Error skeletonizing file: {error}", file=sys.stderr)
            return 1

    if sub == "lint-patch":
        from .semantic_linter import lint_patch_in_memory

        patch_str = args.patch
        if args.patch_file:
            patch_str = Path(args.patch_file).read_text(encoding="utf-8", errors="replace")
        if not patch_str:
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"valid": False, "error": "No patch specified"},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print("Error: No patch specified via --patch or --patch-file", file=sys.stderr)
            return 2
        report = lint_patch_in_memory(str(args.workspace), patch_str)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "valid": report.valid,
                        "diagnostics": [
                            {"file": d.file, "line": d.line, "message": d.message, "rule": d.rule}
                            for d in report.diagnostics
                        ],
                        "prescriptions": list(report.prescriptions),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            if report.valid:
                print("[OK] Patch passed fast static linter gates without issues.")
            else:
                print("[FAIL] Patch failed static linter gates:")
                for p in report.prescriptions:
                    print(f"  - {p}")
        return 0 if report.valid else 1

    if sub == "spill-read":
        from .spill import read_spill

        loc = args.opt_locator or args.locator
        if not loc:
            if getattr(args, "json", False):
                print(json.dumps({"status": "failed", "error": "Spill locator is required"}, ensure_ascii=False, indent=2))
            else:
                print("Error: spill locator is required", file=sys.stderr)
            return 2
        try:
            content = read_spill(loc, offset_line=args.offset, limit_lines=args.limit)
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"locator": loc, "offset": args.offset, "limit": args.limit, "content": content},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
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
        except Exception as error:
            if getattr(args, "json", False):
                print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            else:
                print(f"Error reading spill: {error}", file=sys.stderr)
            return 1

    if sub == "grep":
        from .ripgrep import ripgrep_search

        try:
            globs = args.paths if args.paths else None
            matches = ripgrep_search(
                args.query,
                root=args.workspace,
                globs=globs,
                is_regex=args.regex,
                case_sensitive=args.case_sensitive,
                max_results=args.max_results,
            )
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "query": args.query,
                            "count": len(matches),
                            "matches": [
                                {"file": m.file, "line": m.line_number, "text": m.line_content}
                                for m in matches
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for m in matches:
                    print(f"{m.file}:{m.line_number}: {m.line_content}")
            return 0
        except Exception as error:
            if getattr(args, "json", False):
                print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            else:
                print(f"Error during grep: {error}", file=sys.stderr)
            return 1

    if sub == "lsp":
        from .lsp import LspManager, LspPosition

        try:
            manager = LspManager(workspace_root=args.workspace)
            if args.operation == "definition":
                res = manager.go_to_definition(args.file, line=args.line, character=args.char, workspace_root=args.workspace)
                data = [r.to_dict() for r in res]
            elif args.operation == "references":
                res = manager.find_references(args.file, line=args.line, character=args.char, workspace_root=args.workspace)
                data = [r.to_dict() for r in res]
            elif args.operation == "hover":
                h_res = manager.hover(args.file, line=args.line, character=args.char, workspace_root=args.workspace)
                data = h_res.to_dict() if h_res else None
            elif args.operation == "symbols":
                syms = manager.document_symbols(args.file, workspace_root=args.workspace)
                data = [s.to_dict() for s in syms]
            else:
                data = None

            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"operation": args.operation, "file": str(args.file), "result": data},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        except Exception as error:
            if getattr(args, "json", False):
                print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2))
            else:
                print(f"Error during LSP query: {error}", file=sys.stderr)
            return 1

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
        client = build_client(profile)
        if args.benchmark:
            if args.task is not None or getattr(args, "task_file", None) is not None:
                raise ValueError("--benchmark cannot be combined with --task or --task-file")
            if args.unload_all or args.unload_model or args.vram_limit_bytes is not None or args.calibrate_workers is not None:
                raise ValueError("--benchmark cannot be combined with memory controls")
            if args.benchmark_repeats <= 0:
                raise ValueError("--benchmark-repeats must be positive")
            if args.benchmark_timeout_seconds <= 0:
                raise ValueError("--benchmark-timeout-seconds must be positive")
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
        if args.task is None and getattr(args, "task_file", None) is None:
            raise ValueError("--task or --task-file is required unless memory controls are used")
        task = load_task_input(args.task, getattr(args, "task_file", None))
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
