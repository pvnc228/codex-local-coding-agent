"""Restricted child process for benchmark correctness oracles."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import sys
from pathlib import Path as HostPath
from typing import Any


class _RestrictedPath:
    def __init__(self, root: str, relative: str = "") -> None:
        self._root_text = str(HostPath(root).resolve())
        self._relative = relative.replace("\\", "/").strip("/")

    def __truediv__(self, child: str) -> "_RestrictedPath":
        if not isinstance(child, str):
            raise TypeError("restricted path component must be a string")
        relative = "/".join(part for part in (self._relative, child) if part)
        return _RestrictedPath(self._root_text, relative)

    @property
    def name(self) -> str:
        return self._relative.rsplit("/", 1)[-1]

    def _host_path(self) -> HostPath:
        root = HostPath(self._root_text)
        candidate = (root / self._relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise PermissionError("oracle path escapes the disposable workspace") from error
        return candidate

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._host_path().read_text(encoding=encoding)

    def __str__(self) -> str:
        return str(self._host_path())


def _restricted_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any):
    if not isinstance(file, _RestrictedPath):
        raise PermissionError("oracle file access is limited to the disposable workspace")
    if any(flag in mode for flag in ("w", "a", "+", "x")):
        raise PermissionError("oracle workspace is read-only")
    return open(file._host_path(), mode, *args, **kwargs)


def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
    if name != "json":
        raise ImportError(f"oracle import is not allowlisted: {name}")
    return builtins.__import__(name, *args, **kwargs)


class _BoundedText(io.StringIO):
    def __init__(self, limit: int = 4096) -> None:
        super().__init__()
        self._limit = limit

    def write(self, value: str) -> int:
        remaining = max(0, self._limit - len(self.getvalue()))
        return super().write(value[:remaining])


def _fixture_builtins() -> dict[str, Any]:
    allowed = {
        key: getattr(builtins, key)
        for key in (
            "bool",
            "dict",
            "enumerate",
            "Exception",
            "float",
            "ImportError",
            "int",
            "isinstance",
            "len",
            "list",
            "range",
            "set",
            "str",
            "sum",
            "tuple",
            "type",
            "ValueError",
            "abs",
            "all",
            "any",
            "max",
            "min",
            "reversed",
            "sorted",
            "zip",
            "__build_class__",
        )
    }
    allowed["open"] = _restricted_open
    allowed["__import__"] = _restricted_import
    return allowed


def _load_function(path: _RestrictedPath, name: str) -> Any:
    source = path.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {
        "__builtins__": _fixture_builtins(),
        "__name__": "benchmark_fixture",
        "__file__": str(path),
    }
    exec(compile(source, str(path), "exec"), namespace)
    function = namespace.get(name)
    if not callable(function):
        raise ValueError(f"external oracle could not load {name} from {path.name}")
    return function


def main() -> int:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    root = payload["workspace"]
    oracle_name = payload["oracle_name"]
    oracle_source = payload["oracle_source"]
    if not isinstance(root, str) or not isinstance(oracle_name, str) or not isinstance(oracle_source, str):
        raise ValueError("oracle worker payload is invalid")
    workspace = _RestrictedPath(root)
    namespace: dict[str, Any] = {
        "__builtins__": {
            key: getattr(builtins, key)
            for key in (
                "bool",
                "dict",
                "Exception",
                "isinstance",
                "str",
                "tuple",
                "ValueError",
                "__build_class__",
            )
        },
        "Path": _RestrictedPath,
        "_load_function": _load_function,
    }
    namespace["__builtins__"]["__import__"] = _restricted_import
    exec(compile(oracle_source, "<benchmark-oracle>", "exec"), namespace)
    oracle = namespace.get(oracle_name)
    if not callable(oracle):
        raise ValueError(f"oracle function not found: {oracle_name}")
    correct, detail = oracle(workspace)
    if not isinstance(correct, bool) or not isinstance(detail, str):
        raise ValueError("oracle must return (bool, str)")
    print(json.dumps({"ok": True, "correct": correct, "detail": detail}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    output = _BoundedText()
    error_output = _BoundedText()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
            exit_code = main()
    except BaseException as error:  # worker boundary: serialize oracle failure
        exit_code = 0
        output = _BoundedText()
        output.write(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
    sys.stdout.write(output.getvalue())
    sys.stderr.write(error_output.getvalue())
    raise SystemExit(exit_code)
