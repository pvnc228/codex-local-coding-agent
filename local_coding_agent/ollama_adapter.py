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
    provider: str = "ollama"
    think: bool = False
    temperature: float = 0
    num_ctx: int = 4096
    num_predict: int = 256
    keep_alive: str = "10m"
    timeout_seconds: float = 30
    max_context_length: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    repeat_penalty: float | None = None
    seed: int | None = None
    stop: tuple[str, ...] | None = None
    system_contract: str | None = None

    def __post_init__(self) -> None:
        if self.num_ctx <= 0:
            raise ValueError("num_ctx must be positive")
        if self.provider not in ("ollama", "openai"):
            raise ValueError(f"unsupported provider {self.provider!r}; expected 'ollama' or 'openai'")
        if self.max_context_length is not None:
            if self.max_context_length <= 0:
                raise ValueError("max_context_length must be positive")
            if self.num_ctx > self.max_context_length:
                raise ValueError(
                    f"num_ctx={self.num_ctx} exceeds model context limit {self.max_context_length}"
                )


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
        options: dict[str, Any] = {
            "temperature": self.profile.temperature,
            "num_ctx": self.profile.num_ctx,
            "num_predict": self.profile.num_predict,
        }
        if self.profile.top_p is not None:
            options["top_p"] = self.profile.top_p
        if self.profile.top_k is not None:
            options["top_k"] = self.profile.top_k
        if self.profile.min_p is not None:
            options["min_p"] = self.profile.min_p
        if self.profile.presence_penalty is not None:
            options["presence_penalty"] = self.profile.presence_penalty
        if self.profile.frequency_penalty is not None:
            options["frequency_penalty"] = self.profile.frequency_penalty
        if self.profile.repeat_penalty is not None:
            options["repeat_penalty"] = self.profile.repeat_penalty
        if self.profile.seed is not None:
            options["seed"] = self.profile.seed
        if self.profile.stop is not None:
            options["stop"] = list(self.profile.stop)

        payload: dict[str, Any] = {
            "model": self.profile.model,
            "messages": messages,
            "stream": False,
            "think": self.profile.think,
            "keep_alive": self.profile.keep_alive,
            "options": options,
        }
        if tools is not None:
            payload["tools"] = tools
        return self._request_json("POST", "/api/chat", payload)


    def loaded_models(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/ps")

    def available_models(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/tags")

    def unload_model(self, model: str | None = None) -> dict[str, Any]:
        target = model or self.profile.model
        if not isinstance(target, str) or not target.strip():
            raise ValueError("model must be a non-empty string")
        return self._request_json(
            "POST",
            "/api/generate",
            {"model": target, "stream": False, "keep_alive": 0},
        )

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


class OpenAICompatibleClient:
    """Adapter for OpenAI-compatible backends (e.g. llama-server `/v1`).

    The controller speaks a neutral message/tool vocabulary (the same one
    ``OllamaClient`` produces). This adapter maps it onto the OpenAI chat
    completions wire format and normalizes the response back so callers see no
    difference. Tool calls arrive as JSON strings in the OpenAI payload and are
    parsed to objects for the controller.
    """

    def __init__(self, profile: ModelProfile, *, transport: Transport | None = None) -> None:
        self.profile = profile
        self._transport = transport or UrllibTransport(profile.endpoint)
        self._active_model_name: str | None = None

    def complete(self, prompt: str, *, system: str = "", max_tokens: int | None = None) -> dict[str, Any]:
        """Convenience completion method for compatibility with controller / warmup callers."""
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages)

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        openai_messages: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            converted: dict[str, Any] = {"role": role, "content": content or ""}
            if "tool_calls" in message:
                converted["tool_calls"] = message["tool_calls"]
            if role == "tool":
                converted["tool_call_id"] = message.get("tool_call_id") or "call_0"
            if "name" in message:
                converted["name"] = message["name"]
            openai_messages.append(converted)

        model_name = self._active_model_name or self.profile.model
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": openai_messages,
            "temperature": self.profile.temperature,
            "max_tokens": self.profile.num_predict,
            "chat_template_kwargs": {"thinking_option": "off", "enable_thinking": False},
        }
        if self.profile.top_p is not None:
            payload["top_p"] = self.profile.top_p
        if self.profile.seed is not None:
            payload["seed"] = self.profile.seed
        if self.profile.stop:
            payload["stop"] = list(self.profile.stop)
        if tools is not None:
            payload["tools"] = tools

        try:
            decoded = self._request_json("POST", "/v1/chat/completions", payload)
        except OllamaError as err:
            # If backend rejected specific model name, try auto-resolving to actively loaded llama-server model
            if "not found" in str(err).lower() or "400" in str(err) or "404" in str(err):
                try:
                    avail = self.available_models()
                    models_list = avail.get("models", [])
                    if models_list and isinstance(models_list[0], dict) and models_list[0].get("name"):
                        self._active_model_name = str(models_list[0]["name"])
                        payload["model"] = self._active_model_name
                        decoded = self._request_json("POST", "/v1/chat/completions", payload)
                    else:
                        raise
                except Exception:
                    raise err
            else:
                raise

        choice = _first_choice(decoded)
        message = choice.get("message") if isinstance(choice, dict) else None
        content = (message or {}).get("content") or ""
        raw_calls = (message or {}).get("tool_calls") or []
        tool_calls = [_normalize_tool_call(call) for call in raw_calls if isinstance(call, dict)]

        usage = decoded.get("usage") if isinstance(decoded.get("usage"), dict) else {}
        timings = decoded.get("timings") if isinstance(decoded.get("timings"), dict) else {}
        prompt_ms = _as_float(timings.get("prompt_ms", 0))
        predicted_ms = _as_float(timings.get("predicted_ms", 0))
        return {
            "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
            "prompt_eval_count": _as_int(usage.get("prompt_tokens", 0)),
            "eval_count": _as_int(usage.get("completion_tokens", 0)),
            "prompt_eval_duration": _as_nanos_ms(timings.get("prompt_ms", 0)),
            "eval_duration": _as_nanos_ms(timings.get("predicted_ms", 0)),
            "total_duration": _as_nanos_ms(prompt_ms + predicted_ms),
            "load_duration": 0,
        }

    def available_models(self) -> dict[str, Any]:
        decoded = self._request_json("GET", "/v1/models", None)
        data = decoded.get("data") if isinstance(decoded, dict) else None
        models = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    models.append({"name": item["id"]})
        return {"models": models}

    def loaded_models(self) -> dict[str, Any]:
        raise OllamaError(
            "the openai provider does not expose loaded-model/VRAM introspection",
            kind="unsupported",
        )

    def unload_model(self, model: str | None = None) -> dict[str, Any]:
        raise OllamaError(
            "the openai provider does not support unloading models",
            kind="unsupported",
        )

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
            detail = _openai_error_detail(raw_body)
            suffix = f": {detail}" if detail else ""
            raise OllamaError(f"backend HTTP {status}{suffix}", kind="http")
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaError("backend returned invalid JSON", kind="invalid_json") from error
        if not isinstance(decoded, dict):
            raise OllamaError("backend returned a non-object JSON value", kind="invalid_json")
        return decoded


def _openai_error_detail(raw_body: bytes) -> str:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw_body.decode("utf-8", errors="replace").strip()[:500]
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return ""


def _first_choice(decoded: dict[str, Any]) -> dict[str, Any]:
    choices = decoded.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OllamaError("backend returned no choices", kind="invalid_json")
    first = choices[0]
    if not isinstance(first, dict):
        raise OllamaError("backend returned an invalid choice", kind="invalid_json")
    return first


def _normalize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    function = call.get("function")
    if isinstance(function, dict) and isinstance(function.get("arguments"), str):
        try:
            function = dict(function)
            function["arguments"] = json.loads(function["arguments"])
        except json.JSONDecodeError:
            pass
    return {**call, "function": function}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _as_nanos_ms(value: Any) -> int:
    try:
        return int(_as_float(value) * 1_000_000)
    except (TypeError, ValueError, OverflowError):
        return 0


def build_client(profile: ModelProfile, *, transport: Transport | None = None) -> OllamaClient | OpenAICompatibleClient:
    """Return the transport matching the profile's declared provider."""
    if profile.provider == "openai":
        return OpenAICompatibleClient(profile, transport=transport)
    return OllamaClient(profile, transport=transport)
