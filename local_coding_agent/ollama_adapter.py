"""Small, transport-independent adapter for the Ollama HTTP API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    """A normalized error returned by the Ollama adapter."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model: str
    endpoint: str = "http://127.0.0.1:11434"
    think: bool = False
    temperature: float = 0
    num_ctx: int = 4096
    num_predict: int = 256
    keep_alive: str = "10m"
    timeout_seconds: float = 30


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]: ...


class UrllibTransport:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        request = Request(
            f"{self._endpoint}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()
        except URLError as error:
            raise OllamaError(f"Ollama transport error: {error.reason}", kind="transport") from error
        except TimeoutError as error:
            raise OllamaError("Ollama request timed out", kind="timeout") from error


class OllamaClient:
    def __init__(self, profile: ModelProfile, *, transport: Transport | None = None) -> None:
        self.profile = profile
        self._transport = transport or UrllibTransport(profile.endpoint)

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "stream": False,
            "think": self.profile.think,
            "keep_alive": self.profile.keep_alive,
            "options": {
                "temperature": self.profile.temperature,
                "num_ctx": self.profile.num_ctx,
                "num_predict": self.profile.num_predict,
            },
        }
        if tools is not None:
            payload["tools"] = tools
        return self._request_json("POST", "/api/chat", payload)

    def loaded_models(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/ps")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {} if body is None else {"Content-Type": "application/json; charset=utf-8"}
        status, raw_body = self._transport.request(
            method,
            path,
            body,
            headers,
            self.profile.timeout_seconds,
        )
        if status < 200 or status >= 300:
            detail = self._error_detail(raw_body)
            suffix = f": {detail}" if detail else ""
            raise OllamaError(f"Ollama HTTP {status}{suffix}", kind="http")
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaError("Ollama returned invalid JSON", kind="invalid_json") from error
        if not isinstance(decoded, dict):
            raise OllamaError("Ollama returned a non-object JSON value", kind="invalid_json")
        return decoded

    @staticmethod
    def _error_detail(raw_body: bytes) -> str:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return raw_body.decode("utf-8", errors="replace").strip()[:500]
        detail = payload.get("error") if isinstance(payload, dict) else None
        return detail if isinstance(detail, str) else ""
