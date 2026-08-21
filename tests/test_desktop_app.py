"""Unit tests for Desktop AI Coding Harness (R23)."""

import json
import urllib.request
import pytest
from pathlib import Path
from unittest.mock import patch

from local_coding_agent.desktop.server import (
    DesktopServer,
    _classify_backend_error,
    profile_model_is_available,
    resolve_model_profile,
    select_available_profile,
)
from local_coding_agent.cli import build_parser
from local_coding_agent.ollama_adapter import OllamaError


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


def test_desktop_server_models_api():
    with DesktopServer() as server:
        req = urllib.request.Request(f"{server.url}/api/models")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "profiles" in data
            assert len(data["profiles"]) > 0
            assert "backends" in data
            assert "ollama" in data["backends"]
            assert "llama_server" in data["backends"]


def test_desktop_server_sessions_api():
    with DesktopServer() as server:
        # POST new user session
        new_sess_payload = json.dumps({
            "id": "test-sess-1",
            "type": "user",
            "title": "Test new session",
            "file": "calc.py",
            "patch": "diff --git a/calc.py b/calc.py\n+def add(): pass",
            "checks": ["pytest tests/"],
        }).encode("utf-8")
        req_post = urllib.request.Request(
            f"{server.url}/api/sessions",
            data=new_sess_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_post, timeout=3.0) as resp_post:
            assert resp_post.status == 200
            post_data = json.loads(resp_post.read().decode("utf-8"))
            assert post_data["status"] == "created"
            assert post_data["session"]["title"] == "Test new session"

        # POST new agent session
        agent_sess_payload = json.dumps({
            "id": "test-sess-2",
            "type": "agent",
            "title": "Agent delegated task",
            "file": "calc.py",
            "patch": "",
            "checks": ["pytest tests/"],
        }).encode("utf-8")
        req_post_agent = urllib.request.Request(
            f"{server.url}/api/sessions",
            data=agent_sess_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_post_agent, timeout=3.0) as resp_agent:
            assert resp_agent.status == 200

        # GET sessions
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
            assert data["status"] in ("accepted", "failed", "completed")
            assert "thinking" in data


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


def test_desktop_server_apply_no_patch(tmp_path):
    with DesktopServer(workspace=tmp_path) as server:
        req = urllib.request.Request(
            f"{server.url}/api/apply",
            data=json.dumps({"patch": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "failed"
            assert "No patch content" in data["error"]


def test_cli_desktop_parser():
    parser = build_parser()
    args = parser.parse_args(["desktop", "--port", "9876", "--browser", "--profile", "qwen3-8b-q6k"])
    assert args.subcommand == "desktop"
    assert args.port == 9876
    assert args.browser is True
    assert args.profile == "qwen3-8b-q6k"


def test_desktop_server_model_scanner_endpoints(tmp_path):
    with DesktopServer() as server:
        # 1. Test POST /api/models/add_dir
        add_req = urllib.request.Request(
            f"{server.url}/api/models/add_dir",
            data=json.dumps({"path": str(tmp_path)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(add_req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] in ("added", "already_present")

        # 2. Test POST /api/models/scan
        scan_req = urllib.request.Request(
            f"{server.url}/api/models/scan",
            data=json.dumps({"deep": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(scan_req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert "models" in data

        # 3. Test POST /api/models/remove_dir
        remove_req = urllib.request.Request(
            f"{server.url}/api/models/remove_dir",
            data=json.dumps({"path": str(tmp_path)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(remove_req, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] in ("removed", "not_found")


def test_resolve_model_profile_gguf_gives_openai_endpoint_without_v1():
    """A discovered GGUF/display name resolves to an openai profile on :8080 (no /v1)."""
    fake = {
        "name": "custom-llama-9b-q4.gguf",
        "display_name": "custom-llama-9b-q4",
        "path": "/tmp/custom-llama.gguf",
        "size_gb": 2.5,
        "backend": "gguf",
        "source": "custom",
    }

    class FakeRegistry:
        def get_models(self, auto_scan=True):
            from local_coding_agent.model_scanner import DiscoveredModel
            return [DiscoveredModel.from_dict(fake)]

    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=[]):
        prof = resolve_model_profile("custom-llama-9b-q4", registry=FakeRegistry())

    assert prof.provider == "openai"
    assert prof.endpoint == "http://127.0.0.1:8080"
    assert not prof.endpoint.endswith("/v1")
    assert prof.model == "custom-llama-9b-q4.gguf"


def test_resolve_model_profile_known_profile_returns_get_profile():
    """A known profile name still resolves exactly via get_profile (ling is openai :8080)."""
    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=[]):
        prof = resolve_model_profile("ling-3.0-tiny-q6k")
    assert prof.provider == "openai"
    assert prof.endpoint == "http://127.0.0.1:8080"
    assert not prof.endpoint.endswith("/v1")
    assert prof.model == "ling-3.0-tiny-q6k"


def test_resolve_model_profile_ollama_tag():
    """An installed Ollama tag resolves to an ollama profile on :11434."""
    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=["qwen2.5:1.5b"]):
        prof = resolve_model_profile("qwen2.5")
    assert prof.provider == "ollama"
    assert prof.endpoint == "http://127.0.0.1:11434"
    assert prof.model == "qwen2.5"


def test_classify_backend_error_by_kind():
    assert _classify_backend_error(OllamaError("boom", kind="transport")) == "offline"
    assert _classify_backend_error(OllamaError("boom", kind="http")) == "server_error"
    assert _classify_backend_error(OllamaError("boom", kind="invalid_json")) is None
    assert _classify_backend_error(RuntimeError("Connection refused")) is None


def test_profile_model_is_available_ollama():
    from local_coding_agent.ollama_adapter import ModelProfile
    prof = ModelProfile(name="x", model="qwen2.5:1.5b")
    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=["qwen2.5:1.5b"]):
        assert profile_model_is_available(prof) is True
    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=[]):
        assert profile_model_is_available(prof) is False


def test_select_available_profile_falls_back_to_ollama():
    with patch("local_coding_agent.desktop.server.discover_local_ollama_models", return_value=["qwen2.5:1.5b"]):
        with patch("local_coding_agent.desktop.server.profile_model_is_available", return_value=False):
            assert select_available_profile("qwen2.5-coder") == "qwen2.5:1.5b"
