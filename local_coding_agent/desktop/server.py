"""Desktop API and Webview HTTP Server for Local AI Coding Harness.

Provides real hardware GPU telemetry directly from nvidia-smi, multi-backend probing
(Ollama & llama-server), live model discovery, server process controls, model load/unload
VRAM management, real workspace file introspection, and mediated execution with auto-rollback.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..doctor import diagnose_environment
from ..memory import ModelMemoryManager
from ..model_scanner import discover_llama_server_binary, get_live_system_path, get_model_registry
from ..ollama_adapter import OllamaError, OpenAICompatibleClient, build_client
from ..profiles import ModelProfile, get_profile, list_profiles
from ..stats import DelegationStats
from ..task import TaskEnvelope
from ..validators import apply_patch, check_patch_applies
from .ui import DESKTOP_HTML_TEMPLATE


def get_nvidia_gpu_telemetry() -> dict[str, Any] | None:
    """Query live GPU hardware metrics directly from nvidia-smi."""
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu,name,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.5,
        )
        if res.returncode == 0 and res.stdout.strip():
            first_line = res.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first_line.split(",")]
            if len(parts) >= 4:
                used_mb = float(parts[0])
                total_mb = float(parts[1])
                util_gpu = float(parts[2])
                name = parts[3]
                temp_c = float(parts[4]) if len(parts) > 4 else None
                used_gb = round(used_mb / 1024, 1)
                total_gb = round(total_mb / 1024, 1)
                percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
                return {
                    "gpu_name": name,
                    "used_mb": round(used_mb, 1),
                    "total_mb": round(total_mb, 1),
                    "used_gb": used_gb,
                    "total_gb": total_gb,
                    "percent": percent,
                    "utilization_pct": util_gpu,
                    "temp_c": temp_c,
                    "source": "nvidia-smi",
                }
    except Exception:
        pass
    return None


def discover_local_ollama_models() -> list[str]:
    """Query live Ollama API and scan local disk manifests for installed models."""
    models: list[str] = []
    # 1. Probe live endpoint
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=0.3) as resp:
            if resp.status == 200:
                tags_data = json.loads(resp.read().decode("utf-8"))
                for m in tags_data.get("models", []):
                    if isinstance(m, dict) and "name" in m:
                        models.append(m["name"])
                if models:
                    return sorted(list(set(models)))
    except Exception:
        pass

    # 2. Disk manifests inspection in ~/.ollama/models/manifests
    manifest_root = Path.home() / ".ollama" / "models" / "manifests"
    if manifest_root.exists():
        try:
            for reg in manifest_root.iterdir():
                if reg.is_dir():
                    for user_or_lib in reg.iterdir():
                        if user_or_lib.is_dir():
                            for model_dir in user_or_lib.iterdir():
                                if model_dir.is_dir():
                                    for tag_file in model_dir.iterdir():
                                        if tag_file.is_file():
                                            prefix = "" if user_or_lib.name == "library" else f"{user_or_lib.name}/"
                                            models.append(f"{prefix}{model_dir.name}:{tag_file.name}")
        except Exception:
            pass

    return sorted(list(set(models)))


def resolve_model_profile(name: str, registry: Any = None) -> ModelProfile:
    """Resolve a profile by known profile name, installed Ollama tag, or discovered GGUF model."""
    if registry is None:
        registry = get_model_registry()
    clean_name = name.strip()

    # 1. Exact known profile (carries correct provider/endpoint)
    try:
        return get_profile(clean_name)
    except ValueError:
        pass

    # 2. Installed Ollama tag
    ollama_models = discover_local_ollama_models()
    base = clean_name.split(":", 1)[0].split("/", 1)[0]
    if clean_name in ollama_models or base in ollama_models:
        matched = clean_name if clean_name in ollama_models else base
        return ModelProfile(
            name=clean_name,
            model=matched,
            provider="ollama",
            endpoint="http://127.0.0.1:11434",
            num_ctx=8192,
        )

    # 3. Discovered GGUF model
    for discovered in registry.get_models(auto_scan=True):
        if clean_name.lower() in (discovered.name.lower(), discovered.display_name.lower()):
            return ModelProfile(
                name=clean_name,
                model=discovered.name,
                provider="openai",
                endpoint="http://127.0.0.1:8080",
                num_ctx=8192,
            )

    # 4. Fallback to Ollama profile using name as model
    return ModelProfile(
        name=clean_name,
        model=clean_name,
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        num_ctx=8192,
    )


def _classify_backend_error(error: Exception) -> str | None:
    """Classify a backend error by normalized kind instead of OS-specific text."""
    if isinstance(error, OllamaError):
        if error.kind == "transport":
            return "offline"
        if error.kind == "http":
            return "server_error"
    return None


def profile_model_is_available(profile: ModelProfile) -> bool:
    """Return True if the profile's model is actually installed/available on a live backend."""
    try:
        if profile.provider == "ollama":
            ollama_models = discover_local_ollama_models()
            target = profile.model
            if target in ollama_models:
                return True
            return target.split(":", 1)[0] in ollama_models
        if profile.provider == "openai":
            try:
                avail = OpenAICompatibleClient(profile).available_models()
                live_names = {m["name"] for m in avail.get("models", []) if isinstance(m, dict) and "name" in m}
                if profile.model in live_names:
                    return True
            except Exception:
                pass
            gguf_names = {m.display_name for m in get_model_registry().get_models(auto_scan=True)}
            gguf_names.update(m.name for m in get_model_registry().get_models(auto_scan=True))
            return profile.model in gguf_names
        return False
    except Exception:
        return False


def select_available_profile(preferred: str) -> str:
    """Return a profile name whose model is actually installed, falling back to discovered models."""
    try:
        if _is_known_profile(preferred) and profile_model_is_available(resolve_model_profile(preferred)):
            return preferred
    except Exception:
        pass
    try:
        ollama_models = discover_local_ollama_models()
        if ollama_models:
            return ollama_models[0]
    except Exception:
        pass
    try:
        discovered = get_model_registry().get_models(auto_scan=True)
        if discovered:
            return discovered[0].display_name
    except Exception:
        pass
    return preferred


def _is_known_profile(name: str) -> bool:
    try:
        get_profile(name)
        return True
    except ValueError:
        return False


class DesktopRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler serving the Desktop UI and REST endpoints."""

    @property
    def server_inst(self) -> Any:
        return getattr(self.server, "desktop_server", self.server)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in {"", "/app", "/index.html"}:
            self._send_response(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                DESKTOP_HTML_TEMPLATE.encode("utf-8"),
            )
        elif path in {"/api/status", "/status"}:
            self._handle_status()
        elif path in {"/api/gpu", "/gpu", "/api/gpu/telemetry"}:
            self._handle_gpu_telemetry()
        elif path in {"/api/models", "/models", "/api/profiles"}:
            self._handle_models()
        elif path in {"/api/sessions", "/sessions"}:
            self._handle_sessions()
        elif path in {"/api/workspace/files", "/workspace/files"}:
            self._handle_workspace_files()
        elif path in {"/api/health", "/health"}:
            self._send_json({"status": "ok", "uptime": round(time.monotonic() - self.server_inst.started_at, 2)})
        else:
            self._send_response(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"404 Not Found\n")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in {"/api/chat", "/chat"}:
            self._handle_chat()
        elif path in {"/api/delegate", "/delegate"}:
            self._handle_delegate()
        elif path in {"/api/apply", "/apply"}:
            self._handle_apply()
        elif path in {"/api/rollback", "/rollback"}:
            self._handle_rollback()
        elif path in {"/api/server/start", "/server/start"}:
            self._handle_server_start()
        elif path in {"/api/server/stop", "/server/stop"}:
            self._handle_server_stop()
        elif path in {"/api/model/load", "/model/load"}:
            self._handle_model_load()
        elif path in {"/api/model/unload", "/model/unload"}:
            self._handle_model_unload()
        elif path in {"/api/model/unload_all", "/model/unload_all"}:
            self._handle_model_unload_all()
        elif path in {"/api/doctor/fix", "/doctor/fix"}:
            self._handle_doctor_fix()
        elif path in {"/api/sessions", "/sessions"}:
            self._handle_create_session()
        elif path in {"/api/models/scan", "/models/scan"}:
            self._handle_model_scan()
        elif path in {"/api/models/add_dir", "/models/add_dir"}:
            self._handle_model_add_dir()
        elif path in {"/api/models/remove_dir", "/models/remove_dir"}:
            self._handle_model_remove_dir()
        else:
            self._send_response(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"404 Not Found\n")

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}

    def _handle_status(self) -> None:
        workspace = self.server_inst.workspace
        branch = "main"
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                branch = res.stdout.strip()
        except Exception:
            pass

        # Check server endpoints with loading / ready distinction
        ollama_online, ollama_status = self._probe_server_status("http://127.0.0.1:11434/api/tags")
        llama_online, llama_status = self._probe_server_status("http://127.0.0.1:8080/v1/models")

        # 1. First priority: Real Hardware readings from nvidia-smi
        gpu_telemetry = get_nvidia_gpu_telemetry()

        # 2. Fallback: Ollama memory manager if nvidia-smi is unavailable
        if gpu_telemetry:
            vram_info = gpu_telemetry
        else:
            vram_info = {"used_gb": 0.0, "total_gb": 16.0, "percent": 0.0, "gpu_name": "System GPU"}
            if ollama_online:
                try:
                    client = build_client(get_profile(self.server_inst.default_profile))
                    manager = ModelMemoryManager(client)
                    snap = manager.snapshot()
                    if snap.is_supported:
                        used_gb = round(snap.total_vram_bytes / (1024**3), 2)
                        vram_info = {
                            "used_gb": used_gb,
                            "total_gb": 16.0,
                            "percent": min(100.0, round((used_gb / 16.0) * 100, 1)),
                            "gpu_name": "Ollama VRAM Manager",
                            "loaded_models": [m.to_dict() for m in snap.models],
                        }
                except Exception:
                    pass

        payload = {
            "status": "healthy",
            "uptime_seconds": round(time.monotonic() - self.server_inst.started_at, 2),
            "workspace": str(Path(workspace).resolve()),
            "workspace_name": Path(workspace).resolve().name,
            "git_branch": branch,
            "profile": self.server_inst.default_profile,
            "servers": {
                "ollama": {"online": ollama_online, "status": ollama_status, "endpoint": "http://127.0.0.1:11434"},
                "llama_server": {"online": llama_online, "status": llama_status, "endpoint": "http://127.0.0.1:8080"},
            },
            "vram": vram_info,
            "stats": self.server_inst.stats.snapshot() if self.server_inst.stats else {},
        }
        self._send_json(payload)

    def _handle_gpu_telemetry(self) -> None:
        gpu = get_nvidia_gpu_telemetry()
        if gpu:
            self._send_json({"status": "ok", "gpu": gpu})
        else:
            self._send_json({"status": "unavailable", "message": "nvidia-smi telemetry not available on this host"})

    def _handle_models(self) -> None:
        profiles_data = []
        for name in list_profiles():
            prof = get_profile(name)
            profiles_data.append({
                "name": name,
                "model": prof.model,
                "provider": prof.provider,
                "endpoint": prof.endpoint,
                "num_ctx": prof.num_ctx,
            })

        ollama_online, _ = self._probe_server_status("http://127.0.0.1:11434/api/tags")
        ollama_models = discover_local_ollama_models()

        llama_online, _ = self._probe_server_status("http://127.0.0.1:8080/v1/models")
        llama_models: list[str] = []
        if llama_online:
            try:
                req = urllib.request.Request("http://127.0.0.1:8080/v1/models")
                with urllib.request.urlopen(req, timeout=0.3) as resp:
                    if resp.status == 200:
                        models_data = json.loads(resp.read().decode("utf-8"))
                        raw_list = models_data.get("data") or models_data.get("models") or []
                        for m in raw_list:
                            if isinstance(m, dict) and "id" in m:
                                llama_models.append(m["id"])
                            elif isinstance(m, dict) and "name" in m:
                                llama_models.append(m["name"])
            except Exception:
                pass

        from ..model_scanner import get_model_registry
        discovered_ggufs = [m.to_dict() for m in get_model_registry().get_models(auto_scan=True)]

        self._send_json({
            "profiles": profiles_data,
            "active_profile": self.server_inst.default_profile,
            "backends": {
                "ollama": {"online": ollama_online, "endpoint": "http://127.0.0.1:11434", "models": ollama_models},
                "llama_server": {"online": llama_online, "endpoint": "http://127.0.0.1:8080", "models": llama_models},
                "local_gguf": {"models": discovered_ggufs},
            },
        })

    def _handle_model_scan(self) -> None:
        from ..model_scanner import get_model_registry
        data = self._read_json_body()
        deep = bool(data.get("deep", False))
        registry = get_model_registry()
        models = registry.scan(deep=deep)
        self._send_json({"status": "ok", "total_models": len(models), "models": [m.to_dict() for m in models]})

    def _handle_model_add_dir(self) -> None:
        from ..model_scanner import get_model_registry
        data = self._read_json_body()
        path_val = data.get("path", "").strip()
        if not path_val or not Path(path_val).is_dir():
            self._send_json({"status": "failed", "error": f"Directory does not exist: {path_val}"})
            return
        added = get_model_registry().add_custom_directory(path_val)
        self._send_json({"status": "added" if added else "already_present", "path": path_val})

    def _handle_model_remove_dir(self) -> None:
        from ..model_scanner import get_model_registry
        data = self._read_json_body()
        path_val = data.get("path", "").strip()
        removed = get_model_registry().remove_custom_directory(path_val)
        self._send_json({"status": "removed" if removed else "not_found", "path": path_val})

    def _handle_workspace_files(self) -> None:
        workspace = Path(self.server_inst.workspace)
        files = []
        for p in workspace.rglob("*"):
            if p.is_file() and not any(part.startswith(".") or part in ("__pycache__", "venv", ".git", "build", "dist", "node_modules") for part in p.parts):
                rel = str(p.relative_to(workspace).as_posix())
                files.append({
                    "path": rel,
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "is_code": p.suffix in (".py", ".ts", ".js", ".go", ".rs", ".json", ".md"),
                })
        files.sort(key=lambda x: (not x["is_code"], x["path"]))
        self._send_json({"workspace": str(workspace), "files": files[:80]})

    def _handle_sessions(self) -> None:
        self._send_json({"sessions": self.server_inst.load_sessions()})

    def _handle_create_session(self) -> None:
        data = self._read_json_body()
        session_id = data.get("id") or f"sess-{int(time.time())}"
        session_type = data.get("type", "user")
        title = data.get("title", "New Task Session")
        file_path = data.get("file", "src/main.py")
        patch = data.get("patch", "")
        checks = data.get("checks", [])

        session = {
            "id": session_id,
            "type": session_type,
            "title": title,
            "file": file_path,
            "patch": patch,
            "checks": checks,
            "status": data.get("status", "Active"),
            "time": "Just now",
        }
        self.server_inst.save_session(session)
        self._send_json({"status": "created", "session": session})

    def _server_log_file(self, backend: str) -> Path:
        log_dir = Path(self.server_inst.workspace) / ".local_agent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{backend}.log"

    def _read_log_tail(self, backend: str, n: int = 40) -> str:
        log_file = self._server_log_file(backend)
        if not log_file.exists():
            return ""
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            return "".join(lines[-n:])
        except Exception:
            return ""

    def _wait_for_ready(self, url: str, proc: subprocess.Popen, backend: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            online, status = self._probe_server_status(url)
            if online:
                return {"ok": True, "status": "started"}
            if proc.poll() is not None:
                return {
                    "ok": False,
                    "status": "failed",
                    "error": f"Server exited during startup (code {proc.returncode}). Log tail:\n{self._read_log_tail(backend)}",
                }
            time.sleep(0.5)

        if proc.poll() is not None:
            return {
                "ok": False,
                "status": "failed",
                "error": f"Server exited during startup (code {proc.returncode}). Log tail:\n{self._read_log_tail(backend)}",
            }
        return {
            "ok": False,
            "status": "loading",
            "message": "server started but not ready yet",
        }

    def _handle_server_start(self) -> None:
        data = self._read_json_body()
        backend = data.get("backend", "ollama")
        custom_path = data.get("custom_path")
        model_path = data.get("model_path")

        if backend == "ollama":
            # Search possible Windows locations for Ollama
            live_path = get_live_system_path()
            ollama_bin = shutil.which("ollama", path=live_path) or shutil.which("ollama.exe", path=live_path)
            if not ollama_bin:
                appdata_ollama = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"))
                if appdata_ollama.exists():
                    ollama_bin = str(appdata_ollama)

            if not ollama_bin:
                self._send_json({"status": "failed", "error": "Ollama executable not found. Please install Ollama from ollama.com"})
                return
            try:
                log_handle = open(self._server_log_file("ollama"), "ab")
                proc = subprocess.Popen(
                    [ollama_bin, "serve"],
                    stdout=log_handle,
                    stderr=log_handle,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.server_inst.spawned_processes["ollama"] = proc
                result = self._wait_for_ready("http://127.0.0.1:11434/api/tags", proc, "ollama")
                if result.get("status") == "started":
                    self._send_json({"status": "started", "backend": "ollama", "pid": proc.pid})
                else:
                    self._send_json(result)
            except Exception as error:
                self._send_json({"status": "failed", "error": f"{error}\nLog tail:\n{self._read_log_tail('ollama')}"})

        elif backend in ("llama_server", "llama.cpp"):
            llama_online, _ = self._probe_server_status("http://127.0.0.1:8080/v1/models")
            if llama_online:
                self._send_json({
                    "status": "already_running",
                    "backend": "llama_server",
                    "endpoint": "http://127.0.0.1:8080",
                })
                return

            llama_bin = self._find_llama_server_bin(custom_path)
            if not llama_bin:
                self._send_json({
                    "status": "failed",
                    "error": (
                        "llama-server executable not found in system PATH. "
                        "Add your llama-server directory to PATH or set LLAMA_SERVER_PATH."
                    ),
                })
                return

            cmd = [llama_bin, "--port", "8080"]
            gguf_path = self._find_gguf_model(model_path)
            if gguf_path:
                cmd.extend(["-m", gguf_path, "-c", "8192", "-ngl", "99"])

            try:
                log_handle = open(self._server_log_file("llama_server"), "ab")
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_handle,
                    stderr=log_handle,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.server_inst.spawned_processes["llama_server"] = proc
                result = self._wait_for_ready("http://127.0.0.1:8080/v1/models", proc, "llama_server")
                if result.get("status") == "started":
                    self._send_json({
                        "status": "started",
                        "backend": "llama_server",
                        "pid": proc.pid,
                        "bin": llama_bin,
                        "model": gguf_path or "unspecified",
                    })
                else:
                    self._send_json(result)
            except Exception as error:
                self._send_json({"status": "failed", "error": f"{error}\nLog tail:\n{self._read_log_tail('llama_server')}"})
        else:
            self._send_json({"status": "failed", "error": f"Unknown backend: {backend}"})

    def _find_llama_server_bin(self, custom: str | None = None) -> str | None:
        return discover_llama_server_binary(custom)

    def _find_gguf_model(self, custom: str | None = None) -> str | None:
        if custom and custom.strip() and Path(custom.strip()).is_file():
            return str(Path(custom.strip()).resolve())

        env_model = os.environ.get("LLAMA_MODEL_PATH") or os.environ.get("GGUF_MODEL_PATH")
        if env_model and Path(env_model.strip()).is_file():
            return str(Path(env_model.strip()).resolve())

        return None

    def _handle_server_stop(self) -> None:
        data = self._read_json_body()
        backend = data.get("backend", "all")
        stopped = []

        for name, proc in list(self.server_inst.spawned_processes.items()):
            if backend in (name, "all"):
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                            capture_output=True,
                            check=False,
                        )
                    else:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                    stopped.append(name)
                    del self.server_inst.spawned_processes[name]
                except Exception:
                    pass

        self._send_json({"status": "stopped", "backends": stopped})

    def _handle_model_load(self) -> None:
        data = self._read_json_body()
        model_name = data.get("model") or self.server_inst.default_profile
        try:
            prof = resolve_model_profile(model_name)
            client = build_client(prof)
            if prof.provider == "ollama":
                if hasattr(client, "_request_json"):
                    try:
                        client._request_json("POST", "/api/generate", {"model": prof.model, "prompt": "", "keep_alive": "10m"})
                    except OllamaError as oe:
                        if "not found" in str(oe).lower():
                            base = prof.model.split(":", 1)[0]
                            candidates = [prof.model, f"{base}:latest", base]
                            avail = set()
                            try:
                                for m in client.available_models().get("models", []):
                                    if isinstance(m, dict) and "name" in m:
                                        avail.add(m["name"])
                            except Exception:
                                avail = set(discover_local_ollama_models())
                            alt = next((c for c in candidates if c in avail), None)
                            if alt is None:
                                raise
                            client._request_json("POST", "/api/generate", {"model": alt, "prompt": "", "keep_alive": "10m"})
                        else:
                            raise
                else:
                    client.complete("warmup", system="warmup", max_tokens=1)
            elif prof.provider == "openai":
                if hasattr(client, "complete"):
                    client.complete("warmup", system="warmup", max_tokens=1)
                elif hasattr(client, "chat"):
                    client.chat([{"role": "user", "content": "warmup"}])
            else:
                if hasattr(client, "complete"):
                    client.complete("warmup", system="warmup", max_tokens=1)
            self._send_json({"status": "loaded", "model": model_name})
        except Exception as error:
            kind = _classify_backend_error(error)
            if kind == "offline":
                is_llama = prof.provider == "openai"
                backend_name = "llama-server (port 8080)" if is_llama else "Ollama (port 11434)"
                self._send_json({"status": "failed", "error": f"{backend_name} is OFFLINE. Start it in Local Inference Servers."})
            else:
                self._send_json({"status": "failed", "error": str(error)})

    def _handle_model_unload(self) -> None:
        data = self._read_json_body()
        model_name = data.get("model")
        if not model_name:
            self._send_json({"status": "failed", "error": "model name required"})
            return
        try:
            client = build_client(resolve_model_profile(self.server_inst.default_profile))
            manager = ModelMemoryManager(client)
            snap = manager.unload_model(model_name)
            self._send_json({"status": "unloaded", "model": model_name, "remaining": [m.name for m in snap.models]})
        except Exception as error:
            self._send_json({"status": "failed", "error": str(error)})

    def _handle_model_unload_all(self) -> None:
        try:
            client = build_client(resolve_model_profile(self.server_inst.default_profile))
            manager = ModelMemoryManager(client)
            snap = manager.unload_all()
            self._send_json({"status": "unloaded_all", "remaining_bytes": snap.total_vram_bytes})
        except Exception as error:
            self._send_json({"status": "failed", "error": str(error)})

    def _handle_chat(self) -> None:
        data = self._read_json_body()
        prompt = str(data.get("prompt", "")).strip()
        profile_name = data.get("profile", self.server_inst.default_profile)
        if profile_name == self.server_inst.default_profile:
            profile_name = select_available_profile(profile_name)
        files = data.get("files") or []
        checks = data.get("checks") or []

        if not prompt:
            self._send_json({"status": "failed", "error": "Prompt cannot be empty"})
            return

        # Friendly conversational greeting handling
        greetings = {"hi", "hello", "hey", "привет", "здравствуйте", "yo", "sup", "help", "test"}
        if prompt.lower().strip("!.,? ") in greetings:
            self._send_json({
                "status": "completed",
                "task_id": f"greet-{int(time.time())}",
                "prompt": prompt,
                "profile": profile_name,
                "file": "workspace",
                "patch": "",
                "thinking": "Conversational intent detected. Harness is ready for code instructions.",
                "testResult": "READY",
                "checks": [],
                "message": (
                    f"Hello! Connected to `{profile_name}`. "
                    "Please give me a specific coding task, bug fix, or refactoring goal (e.g. 'Fix off-by-one in sliding window' or 'Write unit tests for tax logic')."
                ),
            })
            return

        workspace = self.server_inst.workspace
        if not files:
            files = self._detect_relevant_files(workspace, prompt)
        if not checks:
            checks = self._detect_test_checks(workspace)

        task_id = f"task-{int(time.time())}"

        # Informational / Code Inquiry Handling (e.g. "read main.py and tell me what it does", "explain foo")
        info_prefixes = ("read ", "explain ", "what ", "how ", "tell me ", "show ", "опиши ", "прочитай ", "что делает ", "как ", "покажи ")
        if any(prompt.lower().startswith(p) for p in info_prefixes):
            try:
                profile = resolve_model_profile(profile_name)
                client = build_client(profile)
                target_file = files[0] if files else "src/main.py"
                target_path = Path(workspace) / target_file
                content_snippet = ""
                if target_path.is_file():
                    try:
                        content_snippet = target_path.read_text(encoding="utf-8", errors="replace")[:6000]
                    except Exception:
                        pass

                messages = [
                    {"role": "system", "content": f"You are a helpful coding assistant. Workspace target file: {target_file}\nFile content:\n```\n{content_snippet}\n```"},
                    {"role": "user", "content": prompt},
                ]
                resp = client.chat(messages)
                msg_content = (resp.get("message") or {}).get("content") or "No response received."

                session_record = {
                    "id": task_id,
                    "type": "user",
                    "title": prompt[:50] + ("..." if len(prompt) > 50 else ""),
                    "file": target_file,
                    "patch": "",
                    "checks": checks,
                    "status": "Verified",
                    "time": "Just now",
                }
                self.server_inst.save_session(session_record)

                self._send_json({
                    "status": "completed",
                    "task_id": task_id,
                    "prompt": prompt,
                    "profile": profile_name,
                    "file": target_file,
                    "patch": "",
                    "thinking": f"Read context from {target_file} and formulated code explanation.",
                    "testResult": "READY",
                    "checks": [],
                    "message": msg_content,
                })
                return
            except Exception as error:
                kind = _classify_backend_error(error)
                if kind == "offline":
                    is_llama = profile.provider == "openai"
                    server_name = "llama-server on port 8080" if is_llama else "Ollama on port 11434"
                    prescript = f"Local backend server ({server_name}) is currently OFFLINE. Click 'Start {('llama-server' if is_llama else 'Ollama')}' or launch your local engine."
                    self._send_json({"status": "failed", "error": prescript, "offline_server": "llama_server" if is_llama else "ollama"})
                    return
                else:
                    self._send_json({"status": "failed", "error": str(error)})
                    return

        task = TaskEnvelope(
            id=task_id,
            goal=prompt,
            files=tuple(files),
            checks=tuple(checks),
        )

        try:
            from ..controller import Controller
            profile = resolve_model_profile(profile_name)
            client = build_client(profile)
            controller = Controller(client, workspace)
            result = controller.run(task, apply=False)

            patch_content = result.get("patch", "")
            target_file = files[0] if files else "src/main.py"

            session_record = {
                "id": task_id,
                "type": "user",
                "title": prompt[:50] + ("..." if len(prompt) > 50 else ""),
                "file": target_file,
                "patch": patch_content,
                "checks": checks,
                "status": "Verified" if result.get("status") == "accepted" else "Needs Review",
                "time": "Just now",
            }
            self.server_inst.save_session(session_record)

            self._send_json({
                "status": result.get("status", "completed"),
                "task_id": task_id,
                "prompt": prompt,
                "profile": profile_name,
                "file": target_file,
                "patch": patch_content,
                "thinking": result.get("summary") or "AST context compacted, generated candidate patch, ran external tests.",
                "testResult": "PASSED" if result.get("status") == "accepted" else "FAILED",
                "checks": result.get("checks", []),
                "message": result.get("summary") or f"Task processed for '{prompt}'.",
            })
        except Exception as error:
            kind = _classify_backend_error(error)
            if kind == "offline":
                is_llama = profile.provider == "openai"
                server_name = "llama-server on port 8080" if is_llama else "Ollama on port 11434"
                prescript = f"Local backend server ({server_name}) is currently OFFLINE. Click 'Start {('llama-server' if is_llama else 'Ollama')}' or launch your local engine."
                self._send_json({"status": "failed", "error": prescript, "offline_server": "llama_server" if is_llama else "ollama"})
            else:
                self._send_json({"status": "failed", "error": str(error)})

    def _handle_delegate(self) -> None:
        data = self._read_json_body()
        raw_task = data.get("task", {})
        profile_name = data.get("profile", self.server_inst.default_profile)
        apply_flag = bool(data.get("apply", False))

        try:
            from ..controller import Controller
            task = TaskEnvelope.from_mapping(raw_task)
            profile = resolve_model_profile(profile_name)
            client = build_client(profile)
            controller = Controller(client, self.server_inst.workspace)
            result = controller.run(task, apply=apply_flag)
            self._send_json(result)
        except Exception as error:
            self._send_json({"status": "failed", "error": str(error)})

    def _handle_apply(self) -> None:
        data = self._read_json_body()
        patch_str = data.get("patch", "").strip()
        checks = data.get("checks", [])
        workspace = Path(self.server_inst.workspace)

        if not patch_str:
            self._send_json({"status": "failed", "error": "No patch content provided to apply"})
            return

        applies, err = check_patch_applies(workspace, patch_str)
        if not applies:
            self._send_json({"status": "rejected", "error": f"Patch cannot apply cleanly: {err}"})
            return

        applied, detail = apply_patch(workspace, patch_str)
        if not applied:
            self._send_json({"status": "failed", "error": f"Apply failed: {detail}"})
            return

        check_results = []
        checks_passed = True
        for cmd in checks:
            try:
                cp = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                passed = cp.returncode == 0
                check_results.append({
                    "command": cmd,
                    "passed": passed,
                    "evidence": (cp.stdout + cp.stderr).strip()[:400],
                })
                if not passed:
                    checks_passed = False
                    break
            except Exception as e:
                check_results.append({"command": cmd, "passed": False, "evidence": str(e)})
                checks_passed = False
                break

        if not checks_passed:
            apply_patch(workspace, patch_str, reverse=True)
            self._send_json({
                "status": "rejected",
                "error": "Targeted checks failed after applying patch. Changes were automatically rolled back.",
                "checks": check_results,
                "rolled_back": True,
            })
            return

        self._send_json({"status": "applied", "checks": check_results})

    def _handle_rollback(self) -> None:
        workspace = self.server_inst.workspace
        try:
            res = subprocess.run(
                ["git", "restore", "."],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            self._send_json({"status": "rolled_back", "code": res.returncode})
        except Exception as error:
            self._send_json({"status": "failed", "error": str(error)})

    def _handle_doctor_fix(self) -> None:
        report = diagnose_environment(fix=True)
        self._send_json({"status": "ok", "report": report})

    def _probe_port(self, url: str) -> bool:
        online, _ = self._probe_server_status(url)
        return online

    def _probe_server_status(self, url: str) -> tuple[bool, str]:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=0.3) as resp:
                if resp.status == 200:
                    return True, "ready"
                return True, "loading"
        except urllib.error.HTTPError as e:
            if e.code == 503:
                return True, "loading"
            return False, "offline"
        except Exception:
            return False, "offline"

    def _detect_relevant_files(self, workspace: str, prompt: str) -> list[str]:
        ws_path = Path(workspace)
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                dirty = [line.strip().split()[-1] for line in res.stdout.strip().splitlines() if line.strip()]
                if dirty:
                    return dirty[:3]
        except Exception:
            pass

        for p in (ws_path / "src").glob("*.py"):
            return [str(p.relative_to(ws_path).as_posix())]
        for p in ws_path.glob("*.py"):
            if not p.name.startswith("test_"):
                return [p.name]
        return ["src/main.py"]

    def _detect_test_checks(self, workspace: str) -> list[str]:
        ws_path = Path(workspace)
        if (ws_path / "tests").is_dir():
            return ["pytest tests/"]
        if (ws_path / "test").is_dir():
            return ["pytest test/"]
        return ["pytest"]

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_response(HTTPStatus.OK, "application/json; charset=utf-8", body)

    def _send_response(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class DesktopServer:
    """Desktop Harness embedded HTTP server with persistent storage and process orchestration."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        workspace: str | Path = ".",
        default_profile: str = "qwen2.5-coder",
        stats: DelegationStats | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.workspace = str(Path(workspace).resolve())
        self.default_profile = default_profile
        self.stats = stats or DelegationStats()
        self.started_at = time.monotonic()
        self.spawned_processes: dict[str, subprocess.Popen[Any]] = {}
        self.sessions_file = Path(self.workspace) / ".local_agent_sessions.json"
        self._httpd = ThreadingHTTPServer((host, port), DesktopRequestHandler)
        self._httpd.desktop_server = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def actual_port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.actual_port}"

    def load_sessions(self) -> list[dict[str, Any]]:
        if self.sessions_file.exists():
            try:
                data = json.loads(self.sessions_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def save_session(self, session: dict[str, Any]) -> None:
        sessions = self.load_sessions()
        sessions = [s for s in sessions if s.get("id") != session.get("id")]
        sessions.insert(0, session)
        try:
            self.sessions_file.write_text(json.dumps(sessions[:50], indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="local-agent-desktop-http",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        for name, proc in list(self.spawned_processes.items()):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
                else:
                    proc.terminate()
                    proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.spawned_processes.clear()

        if self._thread is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=3.0)
        self._thread = None

    def __enter__(self) -> DesktopServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
