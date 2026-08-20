"""Persistent PTY Terminal Seam & Interactive Process Control (R26).

Adapted from DeepSeek Harness @deepseek-ai/dsh-terminal and @deepseek-ai/dsh-tool-terminal.
Provides persistent background interactive shell / process sessions, non-blocking I/O drainers,
circular scrollback buffers, cross-platform signal propagation, and robust process tree cleanup.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence


# ============================================================================
# Exceptions
# ============================================================================

class TerminalError(RuntimeError):
    """Base exception for terminal failures."""


class TerminalSessionNotFoundError(TerminalError):
    """Raised when a requested terminal session does not exist."""


class TerminalSessionExistsError(TerminalError):
    """Raised when creating a session with an ID that is already active."""


class TerminalProcessExitedError(TerminalError):
    """Raised when attempting to interact with a terminal process that has exited."""


class TerminalTimeoutError(TerminalError):
    """Raised when a terminal operation times out."""


# ============================================================================
# Data Models
# ============================================================================

@dataclass(frozen=True)
class TerminalSessionInfo:
    """Snapshot metadata describing a persistent terminal session."""

    session_id: str
    pid: int
    alive: bool
    exit_code: int | None
    cwd: str
    shell: str
    buffer_size: int
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "alive": self.alive,
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "shell": self.shell,
            "buffer_size": self.buffer_size,
            "created_at": self.created_at,
        }


# ============================================================================
# Process Tree Termination Helpers
# ============================================================================

def _windows_descendants(root_pid: int) -> tuple[list[int], str | None]:
    if os.name != "nt":
        return [root_pid], None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    invalid_handle = ctypes.c_void_p(-1).value
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == invalid_handle:
        return [], f"process snapshot failed: {ctypes.get_last_error()}"
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        parents: dict[int, int] = {}
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        children: dict[int, list[int]] = {}
        for pid, parent in parents.items():
            children.setdefault(parent, []).append(pid)
        descendants: list[int] = []
        pending = list(children.get(root_pid, []))
        while pending:
            pid = pending.pop()
            descendants.append(pid)
            pending.extend(children.get(pid, []))
        return descendants, None
    finally:
        kernel32.CloseHandle(snapshot)


def _terminate_windows_pid(pid: int) -> tuple[bool, str | None]:
    if os.name != "nt":
        return True, None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {2, 3, 87, 1168}:
            return True, None
        return False, f"OpenProcess({pid}) failed: {error}"
    try:
        if kernel32.TerminateProcess(handle, 1):
            return True, None
        return False, f"TerminateProcess({pid}) failed: {ctypes.get_last_error()}"
    finally:
        kernel32.CloseHandle(handle)


def kill_process_tree(pid: int, timeout: float = 3.0) -> tuple[bool, str | None]:
    """Force-terminate a process and all its descendants cross-platform."""
    if pid <= 0 or (os.name != "nt" and pid == os.getpid()):
        return True, None

    if os.name == "nt":
        if pid == os.getpid():
            return True, None
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        taskkill = str(Path(system_root) / "System32" / "taskkill.exe")
        if not Path(taskkill).is_file():
            taskkill = "taskkill"
        try:
            completed = subprocess.run(
                [taskkill, "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
            if completed.returncode == 0:
                return True, None
        except (OSError, subprocess.TimeoutExpired):
            pass

        tree, _ = _windows_descendants(pid)
        # Kill descendants first (bottom-up), then root pid
        all_pids = list(dict.fromkeys([*tree, pid]))
        for p in all_pids:
            if p != os.getpid():
                _terminate_windows_pid(p)
        return True, None
    else:
        try:
            my_pgid = os.getpgid(0)
            pgid = os.getpgid(pid)
            if pgid != my_pgid and pgid > 1:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        return True, None


def _parse_command(cmd_str: str) -> list[str]:
    if os.name == "nt":
        try:
            tokens = shlex.split(cmd_str, posix=False)
            cleaned: list[str] = []
            for token in tokens:
                if len(token) >= 2 and (
                    (token.startswith('"') and token.endswith('"'))
                    or (token.startswith("'") and token.endswith("'"))
                ):
                    token = token[1:-1]
                cleaned.append(token)
            return cleaned or cmd_str.split()
        except Exception:
            return cmd_str.split()
    try:
        return shlex.split(cmd_str, posix=True)
    except Exception:
        return cmd_str.split()


# ============================================================================
# TerminalSession
# ============================================================================

class TerminalSession:
    """Persistent interactive background shell / process wrapper with non-blocking I/O drainer."""

    def __init__(
        self,
        session_id: str,
        cwd: str | Path,
        shell: str | Sequence[str] | None = None,
        *,
        max_buffer_bytes: int = 1_048_576,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.cwd = Path(cwd).resolve()
        if not self.cwd.is_dir():
            raise TerminalError(f"Working directory does not exist: {self.cwd}")

        self.max_buffer_bytes = max_buffer_bytes
        self.created_at = time.time()
        self._buffer = ""
        self._total_chars_written = 0
        self._buffer_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._output_event = threading.Event()
        self._last_output_time = time.monotonic()
        self._closed = False
        self._master_fd: int | None = None
        self._slave_fd: int | None = None

        # Resolve shell command
        if shell is None:
            if os.name == "nt":
                default_shell = os.environ.get("COMSPEC", "cmd.exe")
                self.shell_cmd = default_shell
                cmd_args: list[str] = [default_shell]
            else:
                default_shell = os.environ.get("SHELL", "/bin/bash")
                if not Path(default_shell).exists():
                    default_shell = "/bin/sh"
                self.shell_cmd = default_shell
                cmd_args = [default_shell]
        elif isinstance(shell, str):
            self.shell_cmd = shell
            cmd_args = _parse_command(shell)
        else:
            cmd_args = list(shell)
            self.shell_cmd = " ".join(cmd_args)

        # Environment
        spawn_env = dict(os.environ)
        if env:
            spawn_env.update(env)
        # Ensure interactive Python doesn't buffer and UTF-8 is forced
        spawn_env["PYTHONUNBUFFERED"] = "1"
        spawn_env["PYTHONIOENCODING"] = "utf-8"

        # Platform PTY or Pipe Subprocess
        self.use_pty = False
        if os.name != "nt":
            try:
                import pty
                import termios
                import tty

                master, slave = pty.openpty()
                self._master_fd = master
                self._slave_fd = slave
                self.use_pty = True

                self.process = subprocess.Popen(
                    cmd_args,
                    cwd=str(self.cwd),
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    env=spawn_env,
                    start_new_session=True,
                    close_fds=True,
                )
                os.close(slave)
                self._slave_fd = None
            except Exception:
                # Fallback to standard pipes on failure
                self.use_pty = False
                if self._master_fd is not None:
                    try:
                        os.close(self._master_fd)
                    except OSError:
                        pass
                    self._master_fd = None
                if self._slave_fd is not None:
                    try:
                        os.close(self._slave_fd)
                    except OSError:
                        pass
                    self._slave_fd = None

        if not self.use_pty:
            kwargs: dict[str, Any] = {
                "cwd": str(self.cwd),
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "env": spawn_env,
                "bufsize": 0,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True

            self.process = subprocess.Popen(cmd_args, **kwargs)

        self.pid = self.process.pid

        # Start drainer thread
        self._reader_thread = threading.Thread(
            target=self._drain_loop,
            name=f"terminal-drainer-{self.session_id}",
            daemon=True,
        )
        self._reader_thread.start()

        # Brief warmup sleep to capture initial prompt/motd
        time.sleep(0.05)

    def _drain_loop(self) -> None:
        """Continuously drain child output and append to bounded buffer."""
        if self.use_pty and self._master_fd is not None:
            fd = self._master_fd
            while not self._closed:
                try:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    self._append_bytes(chunk)
                except (OSError, ValueError):
                    break
        else:
            assert self.process.stdout is not None
            read_fn = getattr(self.process.stdout, "read1", self.process.stdout.read)
            while not self._closed:
                try:
                    chunk = read_fn(4096)
                    if not chunk:
                        break
                    self._append_bytes(chunk)
                except (OSError, ValueError):
                    break

        self._output_event.set()

    def _append_bytes(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        with self._buffer_lock:
            self._total_chars_written += len(text)
            self._buffer += text
            if len(self._buffer) > self.max_buffer_bytes:
                drop_len = len(self._buffer) - self.max_buffer_bytes
                self._buffer = self._buffer[drop_len:]
            self._last_output_time = time.monotonic()
        self._output_event.set()

    def is_alive(self) -> bool:
        """Return True if the wrapped terminal process is currently running."""
        if self._closed:
            return False
        return self.process.poll() is None

    @property
    def exit_code(self) -> int | None:
        """Return process exit code if terminated, or None if still running."""
        return self.process.poll()

    @property
    def buffer(self) -> str:
        """Return entire current retained buffer."""
        with self._buffer_lock:
            return self._buffer

    def read_buffer(self, offset: int = 0, limit: int = 4096) -> str:
        """Read a slice of retained terminal output.

        If offset is negative, reads relative to the end of the buffer.
        """
        limit = max(0, limit)
        with self._buffer_lock:
            buf_len = len(self._buffer)
            if offset < 0:
                start = max(0, buf_len + offset)
                return self._buffer[start : start + limit]
            if offset >= buf_len:
                return ""
            return self._buffer[offset : offset + limit]

    def send_input(
        self,
        text: str,
        wait_ms: int = 500,
        submit: bool = True,
    ) -> str:
        """Send text input to the terminal and wait up to wait_ms to collect output delta."""
        with self._io_lock:
            if not self.is_alive():
                raise TerminalProcessExitedError(
                    f"Terminal session '{self.session_id}' (PID {self.pid}) has exited with code {self.exit_code}"
                )

            with self._buffer_lock:
                start_pos = self._total_chars_written

            data = str(text)
            if submit and not data.endswith(("\n", "\r\n")):
                data += "\r\n" if (os.name == "nt" and not self.use_pty) else "\n"

            encoded = data.encode("utf-8")
            try:
                if self.use_pty and self._master_fd is not None:
                    os.write(self._master_fd, encoded)
                else:
                    assert self.process.stdin is not None
                    self.process.stdin.write(encoded)
                    self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                if not self.is_alive():
                    raise TerminalProcessExitedError(
                        f"Terminal session '{self.session_id}' exited during write"
                    ) from e
                raise TerminalError(f"Failed to write to terminal stdin: {e}") from e

            if wait_ms <= 0:
                with self._buffer_lock:
                    buf_len = len(self._buffer)
                    buffer_start_pos = self._total_chars_written - buf_len
                    if start_pos <= buffer_start_pos:
                        return self._buffer
                    return self._buffer[start_pos - buffer_start_pos :]

            # Wait loop for output settling
            deadline = time.monotonic() + (wait_ms / 1000.0)
            last_pos = start_pos
            last_change = time.monotonic()

            while time.monotonic() < deadline:
                self._output_event.wait(timeout=0.03)
                self._output_event.clear()
                with self._buffer_lock:
                    curr_pos = self._total_chars_written
                if curr_pos != last_pos:
                    last_pos = curr_pos
                    last_change = time.monotonic()
                elif curr_pos > start_pos and (time.monotonic() - last_change) >= 0.15:
                    # Output has settled for 150ms after receiving new bytes
                    break

                if not self.is_alive():
                    # Allow drainer to finish reading remaining stream
                    time.sleep(0.05)
                    break

            with self._buffer_lock:
                buf_len = len(self._buffer)
                buffer_start_pos = self._total_chars_written - buf_len
                if start_pos <= buffer_start_pos:
                    return self._buffer
                return self._buffer[start_pos - buffer_start_pos :]

    def send_signal(self, sig: str) -> bool:
        """Deliver a signal (e.g. SIGINT, SIGTERM, SIGKILL, CTRL_C) to the terminal process."""
        if not self.is_alive():
            return False

        sig_upper = sig.strip().upper()

        if sig_upper in {"SIGINT", "CTRL_C", "INT", "2"}:
            # Send Ctrl+C
            try:
                if self.use_pty and self._master_fd is not None:
                    os.write(self._master_fd, b"\x03")
                elif self.process.stdin is not None:
                    self.process.stdin.write(b"\x03")
                    self.process.stdin.flush()
            except OSError:
                pass

            if os.name == "nt":
                try:
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                except (OSError, ValueError):
                    try:
                        self.process.send_signal(signal.CTRL_C_EVENT)
                    except (OSError, ValueError):
                        pass
            else:
                my_pgid = os.getpgid(0)
                try:
                    pgid = os.getpgid(self.process.pid)
                    if pgid != my_pgid and pgid > 1:
                        os.killpg(pgid, signal.SIGINT)
                    else:
                        self.process.send_signal(signal.SIGINT)
                except (OSError, ProcessLookupError):
                    try:
                        self.process.send_signal(signal.SIGINT)
                    except OSError:
                        pass
            return True

        elif sig_upper in {"SIGTERM", "TERM", "15"}:
            if os.name == "nt":
                kill_process_tree(self.process.pid, timeout=1.0)
            else:
                my_pgid = os.getpgid(0)
                try:
                    pgid = os.getpgid(self.process.pid)
                    if pgid != my_pgid and pgid > 1:
                        os.killpg(pgid, signal.SIGTERM)
                    else:
                        self.process.terminate()
                except (OSError, ProcessLookupError):
                    self.process.terminate()
            return True

        elif sig_upper in {"SIGKILL", "KILL", "9"}:
            kill_process_tree(self.process.pid, timeout=1.0)
            return True

        elif sig_upper in {"SIGBREAK", "BREAK"}:
            if os.name == "nt":
                try:
                    self.process.send_signal(signal.CTRL_BREAK_EVENT)
                    return True
                except (OSError, ValueError):
                    pass
            return False

        else:
            if hasattr(signal, sig_upper):
                sig_num = getattr(signal, sig_upper)
                try:
                    if os.name == "nt":
                        self.process.send_signal(sig_num)
                    else:
                        my_pgid = os.getpgid(0)
                        pgid = os.getpgid(self.process.pid)
                        if pgid != my_pgid and pgid > 1:
                            os.killpg(pgid, sig_num)
                        else:
                            self.process.send_signal(sig_num)
                    return True
                except (OSError, ValueError):
                    return False
            return False

    def close(self, timeout: float = 2.0) -> None:
        """Gracefully shut down and terminate the process tree and reader resources."""
        if self._closed:
            return
        self._closed = True

        # Close stdin to signal EOF
        if not self.use_pty and self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except (OSError, ValueError):
                pass

        # Terminate process if still running
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except Exception:
                kill_process_tree(self.process.pid, timeout=timeout)
                try:
                    self.process.wait(timeout=0.5)
                except Exception:
                    pass

        # Close pty master fd
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None

        # Close stdout pipe
        if not self.use_pty and self.process.stdout is not None:
            try:
                self.process.stdout.close()
            except (OSError, ValueError):
                pass

        if self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

    def snapshot(self) -> TerminalSessionInfo:
        """Return an immutable snapshot of session state."""
        return TerminalSessionInfo(
            session_id=self.session_id,
            pid=self.pid,
            alive=self.is_alive(),
            exit_code=self.exit_code,
            cwd=str(self.cwd),
            shell=self.shell_cmd,
            buffer_size=len(self.buffer),
            created_at=self.created_at,
        )

    def __enter__(self) -> TerminalSession:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close(timeout=0.5)
        except Exception:
            pass


# ============================================================================
# TerminalManager
# ============================================================================

class TerminalManager:
    """Registry and lifecycle manager for multiple persistent terminal sessions."""

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        *,
        default_max_buffer: int = 1_048_576,
        strict_workspace: bool = False,
    ) -> None:
        self.workspace_root = (
            Path(workspace_root).resolve() if workspace_root else Path.cwd()
        )
        self.default_max_buffer = default_max_buffer
        self.strict_workspace = strict_workspace
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        session_id: str,
        cwd: str | Path | None = None,
        shell: str | Sequence[str] | None = None,
        *,
        max_buffer_bytes: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> TerminalSession:
        """Create and start a new interactive persistent terminal session."""
        session_id = str(session_id).strip()
        if not session_id:
            raise TerminalError("session_id must be a non-empty string")

        if cwd is not None:
            raw_cwd = Path(cwd)
            if raw_cwd.is_absolute():
                target_cwd = raw_cwd.resolve()
            else:
                target_cwd = (self.workspace_root / raw_cwd).resolve()
        else:
            target_cwd = self.workspace_root

        if self.strict_workspace:
            try:
                target_cwd.relative_to(self.workspace_root)
            except ValueError as e:
                raise TerminalError(
                    f"Path traversal denied: working directory '{target_cwd}' is outside workspace root '{self.workspace_root}'"
                ) from e

        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                if existing.is_alive():
                    raise TerminalSessionExistsError(
                        f"Terminal session '{session_id}' already exists and is active"
                    )
                # Cleanup dead session before replacing
                existing.close()
                del self._sessions[session_id]

            buf_limit = max_buffer_bytes or self.default_max_buffer

            session = TerminalSession(
                session_id=session_id,
                cwd=target_cwd,
                shell=shell,
                max_buffer_bytes=buf_limit,
                env=env,
            )
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> TerminalSession:
        """Retrieve an existing terminal session by ID."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise TerminalSessionNotFoundError(
                    f"Terminal session '{session_id}' not found"
                )
            return session

    def send_input(
        self,
        session_id: str,
        text: str,
        wait_ms: int = 500,
        submit: bool = True,
    ) -> str:
        """Send input to an identified session and collect response output slice."""
        session = self.get_session(session_id)
        return session.send_input(text, wait_ms=wait_ms, submit=submit)

    def read_buffer(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 4096,
    ) -> str:
        """Read a slice from the session's retained output buffer."""
        session = self.get_session(session_id)
        return session.read_buffer(offset=offset, limit=limit)

    def send_signal(self, session_id: str, sig: str) -> bool:
        """Deliver a signal to the identified session."""
        session = self.get_session(session_id)
        return session.send_signal(sig)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List summary info for all tracked terminal sessions."""
        with self._lock:
            return [s.snapshot().to_dict() for s in self._sessions.values()]

    def close_session(self, session_id: str) -> None:
        """Shut down and unregister a terminal session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def close_all(self) -> None:
        """Shut down and clean up all active terminal sessions."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass

    def __enter__(self) -> TerminalManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close_all()


# ============================================================================
# Model-Facing Tool Schemas and Handlers
# ============================================================================

def get_terminal_tool_schemas() -> list[dict[str, Any]]:
    """Return JSON schemas for the 6 persistent terminal tools."""
    return [
        {
            "name": "terminal_open",
            "description": "Create a persistent interactive terminal session (e.g. bash, cmd, REPL) that survives across tool calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Unique identifier for this terminal session (e.g. 'main', 'build', 'gdb').",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Initial working directory. Defaults to workspace root.",
                    },
                    "shell": {
                        "type": "string",
                        "description": "Shell or interactive command to launch (e.g. 'bash', 'powershell', 'python -i'). Defaults to system shell.",
                    },
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "terminal_send",
            "description": "Send text or commands to a persistent terminal and receive the resulting output delta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID returned by terminal_open.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Input text or command line to send.",
                    },
                    "wait_ms": {
                        "type": "integer",
                        "description": "Milliseconds to wait for output after sending (default 500).",
                        "default": 500,
                    },
                    "submit": {
                        "type": "boolean",
                        "description": "Whether to append a newline (Enter) after text (default true).",
                        "default": True,
                    },
                },
                "required": ["session_id", "text"],
            },
        },
        {
            "name": "terminal_read",
            "description": "Read a bounded window from a terminal session's retained output buffer without sending input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to read from.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset to start reading from (default 0; negative offsets count from end).",
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of characters to return (default 4096).",
                        "default": 4096,
                    },
                },
                "required": ["session_id"],
            },
        },
        {
            "name": "terminal_signal",
            "description": "Deliver a control signal to the terminal (e.g. SIGINT/Ctrl+C, SIGTERM, SIGKILL).",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Target terminal session ID.",
                    },
                    "signal": {
                        "type": "string",
                        "description": "Signal to deliver ('SIGINT', 'SIGTERM', 'SIGKILL', etc.).",
                        "enum": ["SIGINT", "SIGTERM", "SIGKILL", "CTRL_C", "SIGBREAK"],
                    },
                },
                "required": ["session_id", "signal"],
            },
        },
        {
            "name": "terminal_list",
            "description": "List all active persistent terminal sessions and their current status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "terminal_close",
            "description": "Close a persistent terminal session and terminate its entire child process tree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to terminate and close.",
                    },
                },
                "required": ["session_id"],
            },
        },
    ]


def execute_terminal_tool(
    manager: TerminalManager,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a model-facing terminal tool by name with arguments."""
    if name == "terminal_open":
        session_id = arguments.get("session_id")
        if not session_id:
            return {"ok": False, "error": "session_id is required"}
        cwd = arguments.get("cwd")
        shell = arguments.get("shell")
        try:
            session = manager.create_session(session_id, cwd=cwd, shell=shell)
            return {
                "ok": True,
                "session_id": session.session_id,
                "pid": session.pid,
                "cwd": str(session.cwd),
                "shell": session.shell_cmd,
                "status": "running",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif name == "terminal_send":
        session_id = arguments.get("session_id")
        text = arguments.get("text")
        if not session_id or text is None:
            return {"ok": False, "error": "session_id and text are required"}
        wait_ms = int(arguments.get("wait_ms", 500))
        submit = bool(arguments.get("submit", True))
        try:
            output = manager.send_input(session_id, str(text), wait_ms=wait_ms, submit=submit)
            session = manager.get_session(session_id)
            return {
                "ok": True,
                "session_id": session_id,
                "output": output,
                "alive": session.is_alive(),
                "exit_code": session.exit_code,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif name == "terminal_read":
        session_id = arguments.get("session_id")
        if not session_id:
            return {"ok": False, "error": "session_id is required"}
        offset = int(arguments.get("offset", 0))
        limit = max(0, int(arguments.get("limit", 4096)))
        try:
            output = manager.read_buffer(session_id, offset=offset, limit=limit)
            session = manager.get_session(session_id)
            return {
                "ok": True,
                "session_id": session_id,
                "output": output,
                "total_buffer_bytes": len(session.buffer.encode("utf-8")),
                "offset": offset,
                "limit": limit,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif name == "terminal_signal":
        session_id = arguments.get("session_id")
        sig = arguments.get("signal")
        if not session_id or not sig:
            return {"ok": False, "error": "session_id and signal are required"}
        try:
            delivered = manager.send_signal(session_id, str(sig))
            return {
                "ok": delivered,
                "session_id": session_id,
                "signal": sig,
                "delivered": delivered,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif name == "terminal_list":
        try:
            sessions = manager.list_sessions()
            return {"ok": True, "sessions": sessions}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif name == "terminal_close":
        session_id = arguments.get("session_id")
        if not session_id:
            return {"ok": False, "error": "session_id is required"}
        try:
            manager.close_session(session_id)
            return {"ok": True, "session_id": session_id, "closed": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"Unknown tool: {name}"}
