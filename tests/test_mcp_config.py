"""Tests for MCP config generator and integrator."""

import json
import tempfile
import unittest
from pathlib import Path

from local_coding_agent.mcp_config import (
    generate_mcp_config_dict,
    get_client_config_path,
    integrate_mcp_config,
)


class TestMcpConfig(unittest.TestCase):
    def test_generate_mcp_config_dict_defaults(self):
        conf = generate_mcp_config_dict(
            workspace="c:/workspace",
            profile="qwen3-8b-q6k",
        )
        self.assertIn("mcpServers", conf)
        self.assertIn("codex-local-agent", conf["mcpServers"])
        server = conf["mcpServers"]["codex-local-agent"]
        self.assertIn("command", server)
        self.assertIn("args", server)
        self.assertIn("serve-mcp", server["args"])
        self.assertIn("--profile", server["args"])
        self.assertIn("qwen3-8b-q6k", server["args"])

    def test_get_client_config_path_claude(self):
        path = get_client_config_path("claude")
        self.assertIsInstance(path, Path)
        self.assertTrue(path.name.endswith("claude_desktop_config.json"))

    def test_get_client_config_path_cursor(self):
        path = get_client_config_path("cursor")
        self.assertIsInstance(path, Path)
        self.assertTrue(str(path).endswith("mcp.json"))

    def test_integrate_mcp_config_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            res = integrate_mcp_config(
                client="claude",
                workspace=tmpdir,
                profile="qwen2.5-coder",
                target_path=cfg_file,
                dry_run=True,
            )
            self.assertFalse(cfg_file.exists())
            self.assertTrue(res["dry_run"])
            self.assertIn("mcpServers", res["config"])

    def test_integrate_mcp_config_write_and_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            # Create existing config with other server
            initial_data = {
                "mcpServers": {
                    "existing-server": {
                        "command": "node",
                        "args": ["server.js"]
                    }
                }
            }
            cfg_file.write_text(json.dumps(initial_data), encoding="utf-8")

            res = integrate_mcp_config(
                client="claude",
                workspace=tmpdir,
                profile="bonsai-64k",
                target_path=cfg_file,
                dry_run=False,
            )
            self.assertTrue(cfg_file.exists())
            self.assertFalse(res["dry_run"])
            self.assertTrue(res["written"])

            saved = json.loads(cfg_file.read_text(encoding="utf-8"))
            self.assertIn("existing-server", saved["mcpServers"])
            self.assertIn("codex-local-agent", saved["mcpServers"])


if __name__ == "__main__":
    unittest.main()
