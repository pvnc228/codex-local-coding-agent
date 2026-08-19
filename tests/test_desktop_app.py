"""Unit tests for Desktop AI Coding Harness (R23)."""

import json
import urllib.request
import pytest
from pathlib import Path

from local_coding_agent.desktop.server import DesktopServer
from local_coding_agent.cli import build_parser


def test_desktop_server_html_endpoint():
    with DesktopServer() as server:
        req = urllib.request.Request(f"{server.url}/app")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "Local AI Coding Harness" in content
            assert "Geist" in content
            assert "Interactive Chat" in content
            assert "Delegated Tasks" in content


def test_desktop_server_status_api():
    with DesktopServer() as server:
        req = urllib.request.Request(f"{server.url}/api/status")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "healthy"
            assert "workspace" in data
            assert "git_branch" in data
            assert "vram" in data


def test_desktop_server_sessions_api():
    with DesktopServer() as server:
        req = urllib.request.Request(f"{server.url}/api/sessions")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "sessions" in data
            assert len(data["sessions"]) >= 2
            types = {s["type"] for s in data["sessions"]}
            assert "user" in types
            assert "agent" in types


def test_desktop_server_chat_api():
    with DesktopServer() as server:
        payload = json.dumps({"prompt": "Fix bug in window.py", "profile": "qwen2.5-coder"}).encode("utf-8")
        req = urllib.request.Request(
            f"{server.url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "accepted"
            assert "thinking" in data
            assert "testResult" in data


def test_desktop_server_rollback_api(tmp_path):
    with DesktopServer(workspace=tmp_path) as server:
        req = urllib.request.Request(
            f"{server.url}/api/rollback",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "status" in data


def test_cli_desktop_parser():
    parser = build_parser()
    args = parser.parse_args(["desktop", "--port", "9876", "--browser", "--profile", "qwen3-8b-q6k"])
    assert args.subcommand == "desktop"
    assert args.port == 9876
    assert args.browser is True
    assert args.profile == "qwen3-8b-q6k"
