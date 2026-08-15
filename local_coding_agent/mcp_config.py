"""MCP client configuration generator and integrator."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def get_client_config_path(client: str) -> Path:
    client_norm = client.lower().strip()
    home = Path.home()

    if client_norm in ("claude", "claude-desktop", "claudedesktop"):
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
        # Cursor workspace-level .cursor/mcp.json or user config
        return Path.cwd() / ".cursor" / "mcp.json"

    if client_norm in ("windsurf", "codeium"):
        return home / ".codeium" / "windsurf" / "mcp_config.json"

    if client_norm in ("vscode", "roo", "cline"):
        return Path.cwd() / ".vscode" / "mcp.json"

    raise ValueError(f"Unsupported MCP client: {client}. Supported: claude, cursor, windsurf, vscode")


def generate_mcp_config_dict(
    workspace: str | Path,
    profile: str = "qwen3-8b-q6k",
    endpoint: str | None = None,
    command: str | None = None,
    server_name: str = "codex-local-agent",
) -> dict[str, Any]:
    cmd = command or sys.executable
    args = ["-m", "local_coding_agent", "serve-mcp", "--workspace", str(Path(workspace).resolve()), "--profile", profile]
    if endpoint:
        args.extend(["--endpoint", endpoint])

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
    server_name: str = "codex-local-agent",
) -> dict[str, Any]:
    resolved_path = target_path if target_path is not None else get_client_config_path(client)
    snippet = generate_mcp_config_dict(
        workspace=workspace,
        profile=profile,
        endpoint=endpoint,
        server_name=server_name,
    )

    merged_data: dict[str, Any] = {"mcpServers": {}}

    if resolved_path.exists():
        try:
            raw = resolved_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                merged_data = loaded
                if "mcpServers" not in merged_data or not isinstance(merged_data["mcpServers"], dict):
                    merged_data["mcpServers"] = {}
        except Exception:
            merged_data = {"mcpServers": {}}

    # Merge our server definition
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
