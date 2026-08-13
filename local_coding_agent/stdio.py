"""UTF-8 JSONL process-bound adapter for the proposal-only service seam."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any, BinaryIO, TextIO

from .service import DelegationRequest, DelegationService


class StdioDelegationAdapter:
    """Expose one bounded ``delegate_code`` operation over newline-delimited JSON.

    The adapter owns framing and request decoding only. Workspace registration,
    model-profile allowlisting, idempotency, policy, validation, and result
    ownership remain in :class:`DelegationService`.
    """

    def __init__(self, service: DelegationService, *, max_request_bytes: int = 64 * 1024) -> None:
        if max_request_bytes <= 0:
            raise ValueError("max_request_bytes must be positive")
        self._service = service
        self._max_request_bytes = max_request_bytes

    def handle_line(self, raw_line: str | bytes) -> str:
        if not isinstance(raw_line, (str, bytes)):
            return self._encode_failure("invalid_request", "line must be text or UTF-8 bytes")
        try:
            request_size = len(raw_line) if isinstance(raw_line, bytes) else len(raw_line.encode("utf-8"))
        except UnicodeEncodeError as error:
            return self._encode_failure("invalid_utf8", f"request is not valid UTF-8: {error}")
        if request_size > self._max_request_bytes:
            return self._encode_failure(
                "request_too_large",
                f"request exceeds max_request_bytes={self._max_request_bytes}",
            )
        try:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        except UnicodeDecodeError as error:
            return self._encode_failure("invalid_utf8", f"request is not valid UTF-8: {error}")
        try:
            message = json.loads(line)
        except (TypeError, json.JSONDecodeError) as error:
            return self._encode_failure("invalid_json", f"request is not valid JSON: {error}")
        if not isinstance(message, Mapping):
            return self._encode_failure("invalid_request", "request must be a JSON object")
        if message.get("method") != "delegate_code":
            return self._encode_failure("unknown_method", "only delegate_code is supported")
        params = message.get("params")
        if not isinstance(params, Mapping):
            return self._encode_failure("invalid_request", "params must be a JSON object")
        try:
            request = self._request_from_params(params)
        except (TypeError, ValueError) as error:
            return self._encode_failure("invalid_request", str(error))
        result = self._service.delegate(message.get("caller_id"), request)
        return self._encode(result)

    def serve(
        self,
        input_stream: BinaryIO | TextIO | None = None,
        output_stream: BinaryIO | TextIO | None = None,
    ) -> None:
        source = input_stream or getattr(sys.stdin, "buffer", sys.stdin)
        target = output_stream or getattr(sys.stdout, "buffer", sys.stdout)
        while True:
            raw_line = source.readline(self._max_request_bytes + 1)
            if raw_line in (b"", ""):
                break
            if self._line_size(raw_line) > self._max_request_bytes:
                while not self._line_terminated(raw_line):
                    raw_line = source.readline(self._max_request_bytes + 1)
                    if raw_line in (b"", ""):
                        break
                response = self._encode_failure(
                    "request_too_large",
                    f"request exceeds max_request_bytes={self._max_request_bytes}",
                ) + "\n"
            elif not raw_line.strip():
                continue
            else:
                response = self.handle_line(raw_line) + "\n"
            encoded = response.encode("utf-8")
            try:
                target.write(encoded)
            except TypeError:
                target.write(response)
            target.flush()

    @staticmethod
    def _request_from_params(params: Mapping[str, Any]) -> DelegationRequest:
        return DelegationRequest.from_mapping(params)

    @staticmethod
    def _line_size(raw_line: str | bytes) -> int:
        return len(raw_line) if isinstance(raw_line, bytes) else len(raw_line.encode("utf-8"))

    @staticmethod
    def _line_terminated(raw_line: str | bytes) -> bool:
        return raw_line.endswith(b"\n") if isinstance(raw_line, bytes) else raw_line.endswith("\n")

    @staticmethod
    def _encode(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _encode_failure(cls, kind: str, message: str) -> str:
        return cls._encode(
            {
                "status": "failed",
                "error": {"kind": kind, "message": message},
                "audit": [{"event": "protocol_rejected", "kind": kind}],
                "applied": False,
            }
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the proposal-only JSONL delegation adapter")
    parser.add_argument("--workspace-ref", default="workspace")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    service = DelegationService({args.workspace_ref: args.workspace})
    StdioDelegationAdapter(service).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
