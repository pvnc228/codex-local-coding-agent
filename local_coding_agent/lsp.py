"""Generic LSP Stdio Code Intelligence Seam & Language Server Navigation (R25).

Adapted from DeepSeek Harness @deepseek-ai/dsh-lsp and @deepseek-ai/dsh-tool-lsp.
Provides standardized JSON-RPC stdio language server communication, process lifecycle,
protocol translation, mock servers, and AST/regex fallback intelligence.
"""

from __future__ import annotations

import ast
import concurrent.futures
from dataclasses import asdict, dataclass
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO, Mapping, Sequence
import urllib.parse
import urllib.request


# ============================================================================
# Constants & LSP Wire Enums
# ============================================================================

HEADER_SEPARATOR = b"\r\n\r\n"
MAX_HEADER_BYTES = 64 * 1024
MAX_MESSAGE_BYTES = 10 * 1024 * 1024

SYMBOL_KIND_NAMES: dict[int, str] = {
    1: "File",
    2: "Module",
    3: "Namespace",
    4: "Package",
    5: "Class",
    6: "Method",
    7: "Property",
    8: "Field",
    9: "Constructor",
    10: "Enum",
    11: "Interface",
    12: "Function",
    13: "Variable",
    14: "Constant",
    15: "String",
    16: "Number",
    17: "Boolean",
    18: "Array",
    19: "Object",
    20: "Key",
    21: "Null",
    22: "EnumMember",
    23: "Struct",
    24: "Event",
    25: "Operator",
    26: "TypeParameter",
}

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
}

DEFAULT_SERVER_CANDIDATES: dict[str, list[list[str]]] = {
    "python": [
        ["pyright-langserver", "--stdio"],
        ["pyright", "--stdio"],
        ["basedpyright-langserver", "--stdio"],
        ["pylsp"],
    ],
    "typescript": [
        ["typescript-language-server", "--stdio"],
    ],
    "javascript": [
        ["typescript-language-server", "--stdio"],
    ],
    "rust": [
        ["rust-analyzer"],
    ],
    "go": [
        ["gopls"],
    ],
}


# ============================================================================
# Exceptions
# ============================================================================

class LspError(RuntimeError):
    """Base exception for LSP errors."""


class LspTimeoutError(LspError):
    """An LSP request timed out waiting for server response."""


class LspConnectionError(LspError):
    """LSP server process failed to start or crashed."""


class LspResponseError(LspError):
    """Server returned an LSP JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"LSP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


# ============================================================================
# Data Models
# ============================================================================

@dataclass(frozen=True)
class LspPosition:
    """A zero-based line and character cursor coordinate."""

    line: int
    character: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LspPosition:
        return cls(line=int(data["line"]), character=int(data["character"]))


@dataclass(frozen=True)
class LspRange:
    """A half-open range `[start, end)` within a document."""

    start: LspPosition
    end: LspPosition

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LspRange:
        return cls(
            start=LspPosition.from_dict(data["start"]),
            end=LspPosition.from_dict(data["end"]),
        )


@dataclass(frozen=True)
class LspLocation:
    """A document URI, range within it, and local filesystem path."""

    uri: str
    range: LspRange
    file_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "range": self.range.to_dict(),
            "file_path": self.file_path,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LspLocation:
        uri = str(data["uri"])
        file_path = str(data.get("file_path") or uri_to_path(uri))
        return cls(
            uri=uri,
            range=LspRange.from_dict(data["range"]),
            file_path=file_path,
        )

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> LspLocation:
        # Handles Location (uri, range) and LocationLink (targetUri, targetSelectionRange/targetRange)
        if "targetUri" in data:
            uri = str(data["targetUri"])
            raw_range = data.get("targetSelectionRange") or data.get("targetRange") or {}
            range_obj = LspRange.from_dict(raw_range)
        else:
            uri = str(data["uri"])
            range_obj = LspRange.from_dict(data["range"])
        return cls(uri=uri, range=range_obj, file_path=uri_to_path(uri))


@dataclass(frozen=True)
class LspHoverResult:
    """Hover documentation or signature information."""

    contents: str
    range: LspRange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contents": self.contents,
            "range": self.range.to_dict() if self.range is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LspHoverResult:
        raw_range = data.get("range")
        range_obj = LspRange.from_dict(raw_range) if raw_range is not None else None
        return cls(contents=str(data.get("contents", "")), range=range_obj)

    @classmethod
    def from_wire(cls, data: Any) -> LspHoverResult | None:
        if not data or not isinstance(data, Mapping):
            return None
        raw_contents = data.get("contents")
        contents = _render_hover_contents(raw_contents)
        if not contents.strip():
            return None
        raw_range = data.get("range")
        range_obj = LspRange.from_dict(raw_range) if isinstance(raw_range, Mapping) else None
        return cls(contents=contents, range=range_obj)


@dataclass(frozen=True)
class LspSymbol:
    """A symbol outline entry (function, class, variable, etc.)."""

    name: str
    kind: int
    kind_name: str
    location: LspLocation

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "kind_name": self.kind_name,
            "location": self.location.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LspSymbol:
        kind = int(data.get("kind", 12))
        kind_name = str(data.get("kind_name") or SYMBOL_KIND_NAMES.get(kind, f"Kind({kind})"))
        return cls(
            name=str(data["name"]),
            kind=kind,
            kind_name=kind_name,
            location=LspLocation.from_dict(data["location"]),
        )

    @classmethod
    def from_wire(cls, data: Any, file_uri: str = "") -> list[LspSymbol]:
        if not data or not isinstance(data, Sequence):
            return []
        symbols: list[LspSymbol] = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", ""))
            kind = int(item.get("kind", 12))
            kind_name = SYMBOL_KIND_NAMES.get(kind, f"Kind({kind})")

            # Hierarchical DocumentSymbol
            if "range" in item or "selectionRange" in item:
                raw_range = item.get("selectionRange") or item.get("range")
                range_obj = LspRange.from_dict(raw_range) if isinstance(raw_range, Mapping) else LspRange(
                    LspPosition(0, 0), LspPosition(0, 0)
                )
                loc = LspLocation(uri=file_uri, range=range_obj, file_path=uri_to_path(file_uri))
                symbols.append(cls(name=name, kind=kind, kind_name=kind_name, location=loc))
                # Recurse into children
                children = item.get("children")
                if children and isinstance(children, Sequence):
                    symbols.extend(cls.from_wire(children, file_uri=file_uri))
            # Flat SymbolInformation
            elif "location" in item and isinstance(item["location"], Mapping):
                loc = LspLocation.from_wire(item["location"])
                symbols.append(cls(name=name, kind=kind, kind_name=kind_name, location=loc))
        return symbols


# ============================================================================
# Protocol Helpers & URI Conversion
# ============================================================================

def path_to_uri(file_path: str | Path) -> str:
    """Convert a filesystem path to a standard file:// URI."""
    path = Path(file_path).resolve()
    return path.as_uri()


def uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a normalized filesystem path."""
    if not uri.startswith("file://"):
        return uri
    parsed = urllib.parse.urlparse(uri)
    path = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
    if os.name == "nt" and path.startswith("\\") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return os.path.normpath(path)


def _render_hover_contents(contents: Any) -> str:
    """Normalize LSP hover contents into markdown text."""
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, Sequence) and not isinstance(contents, (bytes, bytearray)):
        return "\n\n".join(_render_hover_contents(item) for item in contents if item)
    if isinstance(contents, Mapping):
        # MarkedString object: { language: string, value: string }
        if "language" in contents and "value" in contents:
            lang = contents.get("language", "")
            val = contents.get("value", "")
            return f"```{lang}\n{val}\n```"
        # MarkupContent: { kind: 'markdown' | 'plaintext', value: string }
        if "value" in contents and isinstance(contents["value"], str):
            return contents["value"]
    return str(contents)


# ============================================================================
# Base Protocol Framing (encode/decode)
# ============================================================================

def encode_message(message: dict[str, Any]) -> bytes:
    """Encode a JSON-RPC message as a Content-Length framed byte sequence."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


class MessageDecoder:
    """Streaming decoder for Content-Length framed JSON-RPC messages."""

    def __init__(
        self,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
        max_header_bytes: int = MAX_HEADER_BYTES,
    ) -> None:
        self.max_message_bytes = max_message_bytes
        self.max_header_bytes = max_header_bytes
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[dict[str, Any]]:
        """Append raw incoming bytes and yield all newly completed JSON-RPC messages."""
        self._buffer.extend(chunk)
        messages: list[dict[str, Any]] = []
        while True:
            msg = self._next()
            if msg is None:
                break
            messages.append(msg)
        return messages

    def _next(self) -> dict[str, Any] | None:
        sep_idx = self._buffer.find(HEADER_SEPARATOR)
        if sep_idx < 0:
            if len(self._buffer) > self.max_header_bytes:
                raise LspError(f"LSP header exceeded {self.max_header_bytes} bytes without terminator")
            return None
        if sep_idx > self.max_header_bytes:
            raise LspError(f"LSP header exceeded {self.max_header_bytes} bytes")

        header_text = self._buffer[:sep_idx].decode("ascii", errors="replace")
        content_length = self._parse_content_length(header_text)
        if content_length > self.max_message_bytes:
            raise LspError(
                f"LSP message length {content_length} exceeds limit {self.max_message_bytes}"
            )

        body_start = sep_idx + len(HEADER_SEPARATOR)
        body_end = body_start + content_length
        if len(self._buffer) < body_end:
            return None

        body_bytes = bytes(self._buffer[body_start:body_end])
        del self._buffer[:body_end]

        try:
            return json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise LspError(f"LSP message body was not valid JSON: {e}") from e

    @staticmethod
    def _parse_content_length(header_text: str) -> int:
        for line in header_text.split("\r\n"):
            colon = line.find(":")
            if colon < 0:
                continue
            name = line[:colon].strip().lower()
            if name == "content-length":
                val = line[colon + 1:].strip()
                try:
                    length = int(val)
                    if length < 0:
                        raise ValueError
                    return length
                except ValueError:
                    raise LspError(f"Invalid Content-Length header: {line!r}")
        raise LspError(f"LSP header block missing Content-Length: {header_text!r}")


# ============================================================================
# LspClient: Stdio JSON-RPC Client
# ============================================================================

class LspClient:
    """JSON-RPC Language Server client over stdio."""

    def __init__(
        self,
        command: Sequence[str],
        workspace_root: str | Path | None = None,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.command = list(command)
        self.workspace_root = str(Path(workspace_root).resolve()) if workspace_root else os.getcwd()
        self.timeout = timeout
        self.process: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._pending: dict[int, concurrent.futures.Future[dict[str, Any]]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self.server_capabilities: dict[str, Any] = {}

    def start(self) -> None:
        """Start language server child process and communication threads."""
        if self.process is not None:
            return
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.workspace_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            raise LspConnectionError(f"Failed to spawn LSP server {self.command!r}: {e}") from e

        self._stopped.clear()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        decoder = MessageDecoder()
        read_fn = getattr(self.process.stdout, "read1", self.process.stdout.read)
        try:
            while not self._stopped.is_set():
                chunk = read_fn(4096)
                if not chunk:
                    break
                messages = decoder.push(chunk)
                for msg in messages:
                    self._handle_incoming(msg)
        except (OSError, ValueError):
            pass
        finally:
            self._fail_all_pending("LSP server connection closed")

    def _handle_incoming(self, message: dict[str, Any]) -> None:
        if "id" in message and message["id"] is not None:
            msg_id = message["id"]
            with self._lock:
                future = self._pending.pop(msg_id, None)
            if future is not None and not future.done():
                if "error" in message and message["error"] is not None:
                    err = message["error"]
                    future.set_exception(
                        LspResponseError(
                            code=err.get("code", -1),
                            message=err.get("message", "Unknown LSP error"),
                            data=err.get("data"),
                        )
                    )
                else:
                    future.set_result(message)

    def _fail_all_pending(self, reason: str) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for fut in pending:
            if not fut.done():
                fut.set_exception(LspConnectionError(reason))

    def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if self.process is None or self.process.poll() is not None:
            raise LspConnectionError("LSP server process is not running")

        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            future: concurrent.futures.Future[dict[str, Any]] = concurrent.futures.Future()
            self._pending[req_id] = future

        request_obj = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params if params is not None else {},
        }
        data = encode_message(request_obj)
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except OSError as e:
            with self._lock:
                self._pending.pop(req_id, None)
            raise LspConnectionError(f"Failed to write to LSP server stdin: {e}") from e

        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            response = future.result(timeout=effective_timeout)
            return response.get("result")
        except concurrent.futures.TimeoutError as e:
            with self._lock:
                self._pending.pop(req_id, None)
            raise LspTimeoutError(f"LSP request '{method}' timed out after {effective_timeout}s") from e

    def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self.process is None or self.process.poll() is not None:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
        }
        data = encode_message(notification)
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except OSError:
            pass

    def initialize(self, workspace_root: str | Path | None = None) -> dict[str, Any]:
        """Perform standard LSP initialize handshake."""
        root = str(Path(workspace_root).resolve()) if workspace_root else self.workspace_root
        root_uri = path_to_uri(root)
        params = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "rootPath": root,
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": False, "linkSupport": True},
                    "references": {"dynamicRegistration": False},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
                "workspace": {
                    "workspaceFolders": True,
                },
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": Path(root).name}
            ],
        }
        res = self.send_request("initialize", params)
        if isinstance(res, Mapping):
            self.server_capabilities = dict(res.get("capabilities", {}))
        self.send_notification("initialized", {})
        return self.server_capabilities

    def did_open(
        self,
        file_path: str | Path,
        language_id: str | None = None,
        content: str | None = None,
        version: int = 1,
    ) -> None:
        """Send textDocument/didOpen notification."""
        path = Path(file_path).resolve()
        uri = path_to_uri(path)
        if content is None:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
        lang = language_id or EXTENSION_TO_LANGUAGE.get(path.suffix.lower(), "plaintext")
        self.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": lang,
                    "version": version,
                    "text": content,
                }
            },
        )

    def did_close(self, file_path: str | Path) -> None:
        """Send textDocument/didClose notification."""
        uri = path_to_uri(Path(file_path).resolve())
        self.send_notification("textDocument/didClose", {"textDocument": {"uri": uri}})

    def definition(self, file_path: str | Path, line: int, character: int) -> list[LspLocation]:
        """Query textDocument/definition for symbol locations."""
        uri = path_to_uri(Path(file_path).resolve())
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        }
        res = self.send_request("textDocument/definition", params)
        if res is None:
            return []
        if isinstance(res, Mapping):
            return [LspLocation.from_wire(res)]
        if isinstance(res, Sequence):
            return [LspLocation.from_wire(item) for item in res if isinstance(item, Mapping)]
        return []

    def references(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> list[LspLocation]:
        """Query textDocument/references for symbol occurrences."""
        uri = path_to_uri(Path(file_path).resolve())
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": include_declaration},
        }
        res = self.send_request("textDocument/references", params)
        if not res or not isinstance(res, Sequence):
            return []
        return [LspLocation.from_wire(item) for item in res if isinstance(item, Mapping)]

    def hover(self, file_path: str | Path, line: int, character: int) -> LspHoverResult | None:
        """Query textDocument/hover for symbol type and docstring information."""
        uri = path_to_uri(Path(file_path).resolve())
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        }
        res = self.send_request("textDocument/hover", params)
        return LspHoverResult.from_wire(res)

    def document_symbols(self, file_path: str | Path) -> list[LspSymbol]:
        """Query textDocument/documentSymbol for file symbol outline."""
        uri = path_to_uri(Path(file_path).resolve())
        params = {"textDocument": {"uri": uri}}
        res = self.send_request("textDocument/documentSymbol", params)
        return LspSymbol.from_wire(res, file_uri=uri)

    def shutdown(self) -> None:
        """Gracefully shut down the language server."""
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.send_request("shutdown", None, timeout=3.0)
        except Exception:
            pass
        self.send_notification("exit", None)

    def stop(self) -> None:
        """Terminate process and release reader resources."""
        self._stopped.set()
        if self.process is not None:
            try:
                self.shutdown()
            except Exception:
                pass
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=1.0)
            self._reader_thread = None

    def __enter__(self) -> LspClient:
        self.start()
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


# ============================================================================
# Mock Language Server for Testing & Verification
# ============================================================================

class MockLspServer:
    """Mock LSP server implementing standard JSON-RPC over stdio streams."""

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.shutdown_received = False

    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Process one incoming message and return an optional response dict."""
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "capabilities": {
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "hoverProvider": True,
                        "documentSymbolProvider": True,
                        "textDocumentSync": 1,
                    }
                },
            }

        if method == "initialized":
            return None

        if method == "textDocument/didOpen":
            doc = params.get("textDocument", {})
            uri = doc.get("uri", "")
            text = doc.get("text", "")
            self.documents[uri] = text
            return None

        if method == "textDocument/didClose":
            doc = params.get("textDocument", {})
            uri = doc.get("uri", "")
            self.documents.pop(uri, None)
            return None

        if method == "textDocument/definition":
            uri = params.get("textDocument", {}).get("uri", "")
            pos = params.get("position", {})
            line = pos.get("line", 0)
            char = pos.get("character", 0)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": [
                    {
                        "uri": uri,
                        "range": {
                            "start": {"line": line, "character": char},
                            "end": {"line": line, "character": char + 5},
                        },
                    }
                ],
            }

        if method == "textDocument/references":
            uri = params.get("textDocument", {}).get("uri", "")
            pos = params.get("position", {})
            line = pos.get("line", 0)
            char = pos.get("character", 0)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": [
                    {
                        "uri": uri,
                        "range": {
                            "start": {"line": line, "character": char},
                            "end": {"line": line, "character": char + 5},
                        },
                    },
                    {
                        "uri": uri,
                        "range": {
                            "start": {"line": line + 2, "character": 0},
                            "end": {"line": line + 2, "character": 5},
                        },
                    },
                ],
            }

        if method == "textDocument/hover":
            pos = params.get("position", {})
            line = pos.get("line", 0)
            char = pos.get("character", 0)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "contents": {
                        "kind": "markdown",
                        "value": f"```python\ndef mock_symbol() -> None\n```\nMock documentation at L{line+1}:C{char+1}.",
                    },
                    "range": {
                        "start": {"line": line, "character": char},
                        "end": {"line": line, "character": char + 5},
                    },
                },
            }

        if method == "textDocument/documentSymbol":
            uri = params.get("textDocument", {}).get("uri", "")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": [
                    {
                        "name": "MockClass",
                        "kind": 5,
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 10, "character": 0},
                        },
                        "selectionRange": {
                            "start": {"line": 0, "character": 6},
                            "end": {"line": 0, "character": 15},
                        },
                        "children": [
                            {
                                "name": "mock_method",
                                "kind": 6,
                                "range": {
                                    "start": {"line": 1, "character": 4},
                                    "end": {"line": 3, "character": 0},
                                },
                                "selectionRange": {
                                    "start": {"line": 1, "character": 8},
                                    "end": {"line": 1, "character": 19},
                                },
                            }
                        ],
                    },
                    {
                        "name": "mock_function",
                        "kind": 12,
                        "range": {
                            "start": {"line": 12, "character": 0},
                            "end": {"line": 15, "character": 0},
                        },
                        "selectionRange": {
                            "start": {"line": 12, "character": 4},
                            "end": {"line": 12, "character": 17},
                        },
                    },
                ],
            }

        if method == "shutdown":
            self.shutdown_received = True
            return {"jsonrpc": "2.0", "id": msg_id, "result": None}

        if method == "exit":
            return None

        # Fallback for unknown methods
        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None

    def serve(self, input_stream: BinaryIO, output_stream: BinaryIO) -> None:
        """Run standard stdio server loop reading from input_stream and writing to output_stream."""
        decoder = MessageDecoder()
        read_fn = getattr(input_stream, "read1", input_stream.read)
        while True:
            try:
                chunk = read_fn(4096)
            except Exception:
                break
            if not chunk:
                break
            messages = decoder.push(chunk)
            for msg in messages:
                resp = self.handle_message(msg)
                if resp is not None:
                    data = encode_message(resp)
                    output_stream.write(data)
                    output_stream.flush()
                if msg.get("method") == "exit":
                    return


# ============================================================================
# Fallback AST & Regex Code Intelligence Engine
# ============================================================================

class FallbackLspEngine:
    """Built-in code intelligence engine for offline environments & test runs."""

    @staticmethod
    def _get_word_at_pos(content: str, line: int, character: int) -> tuple[str, LspRange] | None:
        lines = content.splitlines()
        if line < 0 or line >= len(lines):
            return None
        line_text = lines[line]
        if character < 0 or character > len(line_text):
            return None

        # Find word boundaries
        start = character
        while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == "_"):
            start -= 1
        end = character
        while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
            end += 1

        if start >= end:
            return None
        word = line_text[start:end]
        word_range = LspRange(LspPosition(line, start), LspPosition(line, end))
        return word, word_range

    def document_symbols(self, file_path: str | Path) -> list[LspSymbol]:
        """Extract symbol outline using AST (for Python) or regex (for others)."""
        path = Path(file_path).resolve()
        if not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        uri = path_to_uri(path)
        if path.suffix.lower() in {".py", ".pyi"}:
            return self._document_symbols_python(content, uri, str(path))
        return self._document_symbols_regex(content, uri, str(path))

    def _document_symbols_python(self, content: str, uri: str, file_path: str) -> list[LspSymbol]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._document_symbols_regex(content, uri, file_path)

        symbols: list[LspSymbol] = []

        def visit_node(node: ast.AST, parent_kind: int | None = None) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = 6 if parent_kind == 5 else 12
                kind_name = "Method" if kind == 6 else "Function"
                start_line = max(0, getattr(node, "lineno", 1) - 1)
                start_char = getattr(node, "col_offset", 0)
                end_line = max(start_line, getattr(node, "end_lineno", start_line + 1) - 1)
                end_char = getattr(node, "end_col_offset", start_char + len(node.name))
                loc = LspLocation(
                    uri=uri,
                    range=LspRange(LspPosition(start_line, start_char), LspPosition(end_line, end_char)),
                    file_path=file_path,
                )
                symbols.append(LspSymbol(name=node.name, kind=kind, kind_name=kind_name, location=loc))
                for child in node.body:
                    visit_node(child, parent_kind=kind)
            elif isinstance(node, ast.ClassDef):
                kind = 5
                kind_name = "Class"
                start_line = max(0, getattr(node, "lineno", 1) - 1)
                start_char = getattr(node, "col_offset", 0)
                end_line = max(start_line, getattr(node, "end_lineno", start_line + 1) - 1)
                end_char = getattr(node, "end_col_offset", start_char + len(node.name))
                loc = LspLocation(
                    uri=uri,
                    range=LspRange(LspPosition(start_line, start_char), LspPosition(end_line, end_char)),
                    file_path=file_path,
                )
                symbols.append(LspSymbol(name=node.name, kind=kind, kind_name=kind_name, location=loc))
                for child in node.body:
                    visit_node(child, parent_kind=kind)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        is_const = name.isupper()
                        kind = 14 if is_const else 13
                        kind_name = "Constant" if is_const else "Variable"
                        start_line = max(0, getattr(target, "lineno", 1) - 1)
                        start_char = getattr(target, "col_offset", 0)
                        end_char = start_char + len(name)
                        loc = LspLocation(
                            uri=uri,
                            range=LspRange(LspPosition(start_line, start_char), LspPosition(start_line, end_char)),
                            file_path=file_path,
                        )
                        symbols.append(LspSymbol(name=name, kind=kind, kind_name=kind_name, location=loc))

        for item in tree.body:
            visit_node(item)
        return symbols

    def _document_symbols_regex(self, content: str, uri: str, file_path: str) -> list[LspSymbol]:
        symbols: list[LspSymbol] = []
        patterns = [
            (re.compile(r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 12, "Function"),
            (re.compile(r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 5, "Class"),
            (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 12, "Function"),
            (re.compile(r"^\s*(?:export\s+)?(?:class|interface|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 5, "Class"),
            (re.compile(r"^\s*(?:pub\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 12, "Function"),
            (re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([a-zA-Z_][a-zA-Z0-9_]*)"), 23, "Struct"),
            (re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([a-zA-Z_][a-zA-Z0-9_]*)"), 12, "Function"),
            (re.compile(r"^\s*type\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+struct"), 23, "Struct"),
        ]
        for line_num, line_text in enumerate(content.splitlines()):
            for pat, kind, kind_name in patterns:
                m = pat.match(line_text)
                if m:
                    name = m.group(1)
                    start_char = line_text.find(name)
                    end_char = start_char + len(name)
                    loc = LspLocation(
                        uri=uri,
                        range=LspRange(LspPosition(line_num, start_char), LspPosition(line_num, end_char)),
                        file_path=file_path,
                    )
                    symbols.append(LspSymbol(name=name, kind=kind, kind_name=kind_name, location=loc))
                    break
        return symbols

    def go_to_definition(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
    ) -> list[LspLocation]:
        """Navigate to symbol definition in file or workspace."""
        path = Path(file_path).resolve()
        if not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        word_info = self._get_word_at_pos(content, line, character)
        if not word_info:
            return []
        word, _ = word_info

        # 1. Search in current file first
        current_symbols = self.document_symbols(path)
        for sym in current_symbols:
            if sym.name == word:
                return [sym.location]

        # 2. Search in workspace files
        root = Path(workspace_root).resolve() if workspace_root else path.parent
        locations: list[LspLocation] = []
        for file in root.rglob(f"*{path.suffix}"):
            if file == path or not file.is_file():
                continue
            if any(part.startswith(".") or part in {"node_modules", "__pycache__", "venv", ".venv"} for part in file.parts):
                continue
            symbols = self.document_symbols(file)
            for sym in symbols:
                if sym.name == word:
                    locations.append(sym.location)
                    if len(locations) >= 5:
                        return locations
        return locations

    def find_references(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
        include_declaration: bool = True,
    ) -> list[LspLocation]:
        """Find occurrences and references of the symbol across workspace."""
        path = Path(file_path).resolve()
        if not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        word_info = self._get_word_at_pos(content, line, character)
        if not word_info:
            return []
        word, _ = word_info

        root = Path(workspace_root).resolve() if workspace_root else path.parent
        target_files = [path]
        for f in root.rglob(f"*{path.suffix}"):
            if f != path and f.is_file() and not any(part.startswith(".") or part in {"node_modules", "__pycache__", "venv", ".venv"} for part in f.parts):
                target_files.append(f)

        references: list[LspLocation] = []
        word_regex = re.compile(rf"\b{re.escape(word)}\b")

        for f in target_files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            file_uri = path_to_uri(f)
            for line_idx, line_text in enumerate(text.splitlines()):
                for match in word_regex.finditer(line_text):
                    col_start = match.start()
                    col_end = match.end()
                    loc = LspLocation(
                        uri=file_uri,
                        range=LspRange(LspPosition(line_idx, col_start), LspPosition(line_idx, col_end)),
                        file_path=str(f),
                    )
                    references.append(loc)
                    if len(references) >= 100:
                        return references
        return references

    def hover(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
    ) -> LspHoverResult | None:
        """Extract signature or docstring preview for the symbol under cursor."""
        path = Path(file_path).resolve()
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        word_info = self._get_word_at_pos(content, line, character)
        if not word_info:
            return None
        word, word_range = word_info

        # Check Python AST
        if path.suffix.lower() in {".py", ".pyi"}:
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == word:
                        args = [a.arg for a in node.args.args]
                        sig = f"def {node.name}({', '.join(args)})"
                        doc = ast.get_docstring(node) or ""
                        body = f"```python\n{sig}\n```"
                        if doc:
                            body += f"\n\n{doc}"
                        return LspHoverResult(contents=body, range=word_range)
                    elif isinstance(node, ast.ClassDef) and node.name == word:
                        bases = [getattr(b, "id", "object") for b in node.bases if hasattr(b, "id")]
                        sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
                        doc = ast.get_docstring(node) or ""
                        body = f"```python\n{sig}\n```"
                        if doc:
                            body += f"\n\n{doc}"
                        return LspHoverResult(contents=body, range=word_range)
            except SyntaxError:
                pass

        # Regex fallback hover
        lines = content.splitlines()
        for idx, line_text in enumerate(lines):
            if re.search(rf"\b(?:def|class|function|fn|func|struct)\s+{re.escape(word)}\b", line_text):
                doc_lines = []
                for prev_idx in range(idx - 1, max(-1, idx - 6), -1):
                    prev = lines[prev_idx].strip()
                    if prev.startswith(("#", "//", "/*", "*")):
                        doc_lines.insert(0, prev)
                    else:
                        break
                body = f"```\n{line_text.strip()}\n```"
                if doc_lines:
                    body += f"\n\n" + "\n".join(doc_lines)
                return LspHoverResult(contents=body, range=word_range)

        return LspHoverResult(contents=f"Symbol: `{word}`", range=word_range)


# ============================================================================
# LspManager: High-Level Language Server Navigation & Dispatcher
# ============================================================================

class LspManager:
    """High-level LSP manager routing queries to active language servers or fallback engine."""

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        *,
        use_fallback_if_missing: bool = True,
        server_candidates: Mapping[str, Sequence[Sequence[str]]] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.workspace_root = str(Path(workspace_root).resolve()) if workspace_root else os.getcwd()
        self.use_fallback_if_missing = use_fallback_if_missing
        self.timeout = timeout
        self.candidates: dict[str, list[list[str]]] = {
            k: [list(cmd) for cmd in v]
            for k, v in (server_candidates or DEFAULT_SERVER_CANDIDATES).items()
        }
        self._clients: dict[str, LspClient] = {}
        self._fallback_engine = FallbackLspEngine()
        self._lock = threading.Lock()

    def get_language_id(self, file_path: str | Path) -> str:
        """Map file extension to standard LSP language ID."""
        suffix = Path(file_path).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(suffix, "plaintext")

    def get_client(self, language_id: str) -> LspClient | None:
        """Get or spawn an active LspClient for the given language ID, or None if unavailable."""
        with self._lock:
            if language_id in self._clients:
                client = self._clients[language_id]
                if client.process is not None and client.process.poll() is None:
                    return client
                # Stale process
                client.stop()
                del self._clients[language_id]

            commands = self.candidates.get(language_id, [])
            for cmd in commands:
                binary = cmd[0]
                if shutil.which(binary) is not None:
                    try:
                        client = LspClient(cmd, workspace_root=self.workspace_root, timeout=self.timeout)
                        client.start()
                        client.initialize(self.workspace_root)
                        self._clients[language_id] = client
                        return client
                    except Exception:
                        continue
            return None

    def go_to_definition(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
    ) -> list[LspLocation]:
        """Find definitions of symbol at (line, character) using LSP client or fallback."""
        root = workspace_root or self.workspace_root
        lang = self.get_language_id(file_path)
        client = self.get_client(lang)
        if client is not None:
            try:
                client.did_open(file_path)
                return client.definition(file_path, line, character)
            except Exception:
                pass
        if self.use_fallback_if_missing:
            return self._fallback_engine.go_to_definition(file_path, line, character, root)
        return []

    def find_references(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
        include_declaration: bool = True,
    ) -> list[LspLocation]:
        """Find references of symbol at (line, character) using LSP client or fallback."""
        root = workspace_root or self.workspace_root
        lang = self.get_language_id(file_path)
        client = self.get_client(lang)
        if client is not None:
            try:
                client.did_open(file_path)
                return client.references(file_path, line, character, include_declaration)
            except Exception:
                pass
        if self.use_fallback_if_missing:
            return self._fallback_engine.find_references(
                file_path, line, character, root, include_declaration
            )
        return []

    def hover(
        self,
        file_path: str | Path,
        line: int,
        character: int,
        workspace_root: str | Path | None = None,
    ) -> LspHoverResult | None:
        """Hover symbol at (line, character) using LSP client or fallback."""
        root = workspace_root or self.workspace_root
        lang = self.get_language_id(file_path)
        client = self.get_client(lang)
        if client is not None:
            try:
                client.did_open(file_path)
                return client.hover(file_path, line, character)
            except Exception:
                pass
        if self.use_fallback_if_missing:
            return self._fallback_engine.hover(file_path, line, character, root)
        return None

    def document_symbols(
        self,
        file_path: str | Path,
        workspace_root: str | Path | None = None,
    ) -> list[LspSymbol]:
        """Extract symbol outline for file using LSP client or fallback."""
        root = workspace_root or self.workspace_root
        lang = self.get_language_id(file_path)
        client = self.get_client(lang)
        if client is not None:
            try:
                client.did_open(file_path)
                return client.document_symbols(file_path)
            except Exception:
                pass
        if self.use_fallback_if_missing:
            return self._fallback_engine.document_symbols(file_path)
        return []

    def close_all(self) -> None:
        """Shut down and stop all running language servers."""
        with self._lock:
            for client in self._clients.values():
                try:
                    client.stop()
                except Exception:
                    pass
            self._clients.clear()

    def __enter__(self) -> LspManager:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close_all()
