"""MCP client configuration generator and integrator."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def get_client_config_path(client: str, workspace: str | Path = ".") -> Path:
    client_norm = client.lower().strip()
    home = Path.home()
    ws = Path(workspace).resolve()

    if client_norm in ("claude", "claude-desktop", "claudedesktop", "claude-code"):
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Roaming"
            return base / "Claude" / "claude_desktop_config.json"
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        # Linux
        config_home = os.environ.get("XDG_CONFIG_HOME")
        base = Path(config_home) if config_home else home / ".config"
        return base / "Claude" / "claude_desktop_config.json"

    if client_norm in ("cursor", "cursor-ide"):
        return ws / ".cursor" / "mcp.json"

    if client_norm in ("windsurf", "codeium"):
        return home / ".codeium" / "windsurf" / "mcp_config.json"

    if client_norm in ("cline", "cline-desktop", "roo", "roo-code", "vscode"):
        # Check workspace .vscode/mcp.json or user-level .cline/mcp.json
        if (ws / ".vscode").is_dir():
            return ws / ".vscode" / "mcp.json"
        return home / ".cline" / "mcp.json"

    if client_norm in ("antigravity", "antigravity-desktop", "agy"):
        return home / ".gemini" / "config" / "mcp_config.json"

    if client_norm in ("opencode", "opencode-desktop", "opencode-cli"):
        return home / ".config" / "opencode" / "opencode.jsonc"

    if client_norm in ("chatgpt", "chatgpt-desktop", "codex", "codex-cli", "openai"):
        return home / ".codex" / "config.json"

    raise ValueError(
        f"Unsupported MCP client: {client}. Supported: claude, cursor, windsurf, cline, antigravity, opencode, chatgpt, vscode"
    )


def detect_installed_clients(workspace: str | Path = ".") -> list[str]:
    """Detect available IDE / MCP clients in workspace and host environment."""
    ws = Path(workspace).resolve()
    home = Path.home()
    detected: list[str] = []

    # Check workspace directories
    if (ws / ".cursor").is_dir():
        detected.append("cursor")
    if (ws / ".vscode").is_dir():
        detected.append("cline")

    # Check user-level configurations
    try:
        claude_path = get_client_config_path("claude", ws)
        if claude_path.parent.is_dir() or claude_path.exists():
            detected.append("claude")
    except Exception:
        pass

    try:
        windsurf_path = get_client_config_path("windsurf", ws)
        if windsurf_path.parent.is_dir() or windsurf_path.exists():
            detected.append("windsurf")
    except Exception:
        pass

    try:
        if (home / ".gemini").is_dir():
            detected.append("antigravity")
    except Exception:
        pass

    try:
        if (home / ".config" / "opencode").is_dir() or (home / ".opencode").is_dir():
            detected.append("opencode")
    except Exception:
        pass

    try:
        if (home / ".codex").is_dir():
            detected.append("chatgpt")
    except Exception:
        pass

    if not detected:
        detected = ["claude", "cursor"]

    return detected



def generate_mcp_config_dict(
    workspace: str | Path,
    profile: str = "qwen3-8b-q6k",
    endpoint: str | None = None,
    command: str | None = None,
    server_name: str = "local-coding-agent",
    client: str = "generic",
) -> dict[str, Any]:
    cmd = command or sys.executable
    args = ["-m", "local_coding_agent", "serve-mcp", "--workspace", str(Path(workspace).resolve()), "--profile", profile]
    if endpoint:
        args.extend(["--endpoint", endpoint])

    client_norm = client.lower().strip()
    if client_norm in ("opencode", "opencode-desktop", "opencode-cli"):
        return {
            "mcp": {
                server_name: {
                    "type": "local",
                    "command": [cmd, *args],
                    "enabled": True,
                }
            }
        }

    return {
        "mcpServers": {
            server_name: {
                "command": cmd,
                "args": args,
            }
        }
    }


def integrate_mcp_config(
    client: str,
    workspace: str | Path = ".",
    profile: str = "qwen3-8b-q6k",
    target_path: Path | None = None,
    dry_run: bool = False,
    endpoint: str | None = None,
    server_name: str = "local-coding-agent",
) -> dict[str, Any]:
    client_norm = client.lower().strip()

    if client_norm in ("auto", "all", "*"):
        targets = detect_installed_clients(workspace)
        sub_results = []
        all_written = True
        for tgt in targets:
            sub_res = integrate_mcp_config(
                client=tgt,
                workspace=workspace,
                profile=profile,
                dry_run=dry_run,
                endpoint=endpoint,
                server_name=server_name,
            )
            sub_results.append(sub_res)
            if not sub_res.get("written", False):
                all_written = False
        return {
            "client": client,
            "detected_clients": targets,
            "results": sub_results,
            "dry_run": dry_run,
            "written": all_written if not dry_run else False,
        }

    resolved_path = target_path if target_path is not None else get_client_config_path(client, workspace)
    is_opencode = client_norm in ("opencode", "opencode-desktop", "opencode-cli") or resolved_path.name.startswith("opencode.")

    snippet = generate_mcp_config_dict(
        workspace=workspace,
        profile=profile,
        endpoint=endpoint,
        server_name=server_name,
        client="opencode" if is_opencode else client_norm,
    )

    merged_data: dict[str, Any] = {}

    if resolved_path.exists():
        try:
            raw = resolved_path.read_text(encoding="utf-8")
            cleaned_lines = []
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("#"):
                    continue
                cleaned_lines.append(line)
            loaded = json.loads("\n".join(cleaned_lines))
            if isinstance(loaded, dict):
                merged_data = loaded
        except Exception:
            merged_data = {}

    if is_opencode:
        if "mcp" not in merged_data or not isinstance(merged_data["mcp"], dict):
            merged_data["mcp"] = {}
        # Clean up any errant mcpServers key in opencode config which violates opencode.json schema
        if "mcpServers" in merged_data:
            del merged_data["mcpServers"]
        merged_data["mcp"][server_name] = snippet["mcp"][server_name]
    else:
        if "mcpServers" not in merged_data or not isinstance(merged_data["mcpServers"], dict):
            merged_data["mcpServers"] = {}
        merged_data["mcpServers"][server_name] = snippet["mcpServers"][server_name]

    if dry_run:
        return {
            "client": client,
            "path": str(resolved_path),
            "dry_run": True,
            "written": False,
            "config": merged_data,
            "snippet": snippet,
        }

    # Ensure parent directory exists
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(json.dumps(merged_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "client": client,
        "path": str(resolved_path),
        "dry_run": False,
        "written": True,
        "config": merged_data,
        "snippet": snippet,
    }
