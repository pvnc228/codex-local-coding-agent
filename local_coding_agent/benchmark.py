"""Comparable, proposal-only benchmark for local coding models."""

from __future__ import annotations

import json
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Protocol, Sequence

from .controller import Controller
from .task import TaskEnvelope
from .validators import validate_candidate


class ChatModel(Protocol):
    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    task: TaskEnvelope
    fixture: Mapping[str, str]
    expected_files: Mapping[str, str]
    oracle: Callable[[Path], tuple[bool, str]] | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("benchmark case id must be non-empty")
        fixture_paths = set(self.fixture)
        if fixture_paths != set(self.task.files):
            raise ValueError("benchmark fixture paths must match task allowlist")
        if not self.expected_files:
            raise ValueError("benchmark case must have expected files")
        if not set(self.expected_files).issubset(fixture_paths):
            raise ValueError("expected files must be part of the fixture")


class InstrumentedModel:
    """Collect metrics returned by Ollama without changing the model response."""

    def __init__(self, model: ChatModel) -> None:
        self.model = model
        self.model_calls = 0
        self.total_duration_ns = 0
        self.load_duration_ns = 0
        self.prompt_tokens = 0
        self.prompt_eval_duration_ns = 0
        self.eval_count = 0
        self.eval_duration_ns = 0
        self.proposed_patches: list[str] = []
        self.proposed_edits: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.model.chat(messages, tools=tools)
        self.model_calls += 1
        self._record_proposed_patches(response)
        self.total_duration_ns += _metric_int(response, "total_duration")
        self.load_duration_ns += _metric_int(response, "load_duration")
        self.prompt_tokens += _metric_int(response, "prompt_eval_count")
        self.prompt_eval_duration_ns += _metric_int(response, "prompt_eval_duration")
        self.eval_count += _metric_int(response, "eval_count")
        self.eval_duration_ns += _metric_int(response, "eval_duration")
        return response

    def _record_proposed_patches(self, response: Mapping[str, Any]) -> None:
        message = response.get("message")
        if not isinstance(message, Mapping):
            return
        calls = message.get("tool_calls") or []
        if not calls:
            compatible_call = _decode_content_tool_call(message.get("content"))
            if compatible_call is not None:
                calls = [compatible_call]
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            if not isinstance(function, Mapping) or function.get("name") != "propose_patch":
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            if isinstance(arguments, Mapping):
                if isinstance(arguments.get("patch"), str):
                    self.proposed_patches.append(arguments["patch"])
                if isinstance(arguments.get("edits"), list):
                    self.proposed_edits.append(arguments["edits"])


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    status: str
    correct: bool
    loop_reliable: bool
    validation_valid: bool
    patch_applied: bool
    patch_source: str
    patch_error: str
    wall_time_ms: float
    model_calls: int
    tool_calls: int
    total_duration_ns: int
    load_duration_ns: int
    prompt_tokens: int
    prompt_eval_duration_ns: int
    eval_count: int
    eval_duration_ns: int
    result: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "correct": self.correct,
            "loop_reliable": self.loop_reliable,
            "validation_valid": self.validation_valid,
            "patch_applied": self.patch_applied,
            "patch_source": self.patch_source,
            "patch_error": self.patch_error,
            "wall_time_ms": self.wall_time_ms,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "total_duration_ns": self.total_duration_ns,
            "load_duration_ns": self.load_duration_ns,
            "prompt_tokens": self.prompt_tokens,
            "prompt_eval_duration_ns": self.prompt_eval_duration_ns,
            "eval_count": self.eval_count,
            "eval_duration_ns": self.eval_duration_ns,
            "result": dict(self.result),
        }


def default_cases() -> tuple[BenchmarkCase, ...]:
    """Return a small fixed task set with deterministic external oracles."""

    return (
        BenchmarkCase(
            id="unique-preserve-order",
            task=TaskEnvelope(
                id="unique-preserve-order",
                goal="убрать сортировку из unique и сохранить порядок первого появления",
                files=("src/unique.py",),
                context="Функция должна удалить повторы, но не менять порядок входных значений.",
                constraints=("не менять публичную сигнатуру", "не добавлять зависимости"),
                acceptance=("повторы удаляются", "порядок первого появления сохраняется"),
            ),
            fixture={"src/unique.py": "def unique(values):\n    return sorted(set(values))\n"},
            expected_files={"src/unique.py": "def unique(values):\n    return list(dict.fromkeys(values))\n"},
            oracle=_unique_oracle,
        ),
        BenchmarkCase(
            id="limit-inclusive",
            task=TaskEnvelope(
                id="limit-inclusive",
                goal="исправить off-by-one и вернуть ровно limit элементов",
                files=("src/window.py",),
                context="При положительном limit срез должен включать элемент с индексом limit-1.",
                constraints=("изменить только выражение среза",),
                acceptance=("limit=3 возвращает первые три элемента",),
            ),
            fixture={"src/window.py": "def take(values, limit):\n    return values[: limit - 1]\n"},
            expected_files={"src/window.py": "def take(values, limit):\n    return values[:limit]\n"},
            oracle=_limit_oracle,
        ),
        BenchmarkCase(
            id="utf8-json",
            task=TaskEnvelope(
                id="utf8-json",
                goal="сохранить русские символы при сериализации JSON",
                files=("src/encoding.py",),
                context="JSON должен оставаться валидным и не превращать Unicode-символы в escape-последовательности.",
                constraints=("не менять имя функции", "использовать только стандартную библиотеку"),
                acceptance=("ensure_ascii отключён",),
            ),
            fixture={
                "src/encoding.py": "import json\n\ndef encode(value):\n    return json.dumps(value)\n"
            },
            expected_files={
                "src/encoding.py": "import json\n\ndef encode(value):\n    return json.dumps(value, ensure_ascii=False)\n"
            },
            oracle=_utf8_oracle,
        ),
        BenchmarkCase(
            id="avoid-input-mutation",
            task=TaskEnvelope(
                id="avoid-input-mutation",
                goal="добавить flag без изменения входного списка",
                files=("src/flags.py",),
                context="Вызов не должен мутировать values: исходный список должен остаться прежним.",
                constraints=("сохранить имя функции", "не добавлять зависимости"),
                acceptance=("возвращается новый список с flag в конце",),
            ),
            fixture={"src/flags.py": "def append_flag(values, flag):\n    values.append(flag)\n    return values\n"},
            expected_files={
                "src/flags.py": "def append_flag(values, flag):\n    return [*values, flag]\n"
            },
            oracle=_no_mutation_oracle,
        ),
    )


def _unique_oracle(workspace: Path) -> tuple[bool, str]:
    unique = _load_function(workspace / "src/unique.py", "unique")
    if unique([3, 1, 2, 1, 3]) != [3, 1, 2]:
        return False, "external oracle mismatch: unique does not preserve order"
    return True, ""


def _limit_oracle(workspace: Path) -> tuple[bool, str]:
    take = _load_function(workspace / "src/window.py", "take")
    if take([0, 1, 2, 3], 3) != [0, 1, 2]:
        return False, "external oracle mismatch: limit is not inclusive"
    return True, ""


def _utf8_oracle(workspace: Path) -> tuple[bool, str]:
    encode = _load_function(workspace / "src/encoding.py", "encode")
    encoded = encode({"message": "мир"})
    if not isinstance(encoded, str) or "\\u" in encoded or '"мир"' not in encoded:
        return False, "external oracle mismatch: Unicode was escaped"
    return True, ""


def _no_mutation_oracle(workspace: Path) -> tuple[bool, str]:
    append_flag = _load_function(workspace / "src/flags.py", "append_flag")
    values = ["a"]
    returned = append_flag(values, "b")
    if values != ["a"] or returned != ["a", "b"] or returned is values:
        return False, "external oracle mismatch: input list was mutated"
    return True, ""


def _decode_content_tool_call(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    name = payload.get("name")
    arguments = payload.get("arguments")
    if not isinstance(name, str) or not name or not isinstance(arguments, (Mapping, str)):
        return None
    return {"function": {"name": name, "arguments": arguments}}


def _run_oracle_in_restricted_process(
    oracle: Callable[[Path], tuple[bool, str]], workspace: Path
) -> tuple[bool, str]:
    """Run model-controlled fixture code outside the controller process."""

    try:
        oracle_source = textwrap.dedent(inspect.getsource(oracle))
    except (OSError, TypeError) as error:
        return False, f"external oracle source is unavailable: {error}"
    payload = {
        "workspace": str(workspace),
        "oracle_name": getattr(oracle, "__name__", ""),
        "oracle_source": oracle_source,
    }
    worker = Path(__file__).with_name("benchmark_oracle_worker.py")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-u", str(worker)],
            cwd=workspace,
            env=_benchmark_worker_environment(workspace),
            input=(json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
            **_benchmark_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"external oracle process failed: {error}"
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        return False, detail[:2000] or f"external oracle exited with code {completed.returncode}"
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return False, f"external oracle returned invalid JSON: {error}"
    if not isinstance(result, Mapping) or result.get("ok") is not True:
        detail = result.get("error") if isinstance(result, Mapping) else None
        return False, f"external oracle error: {detail or 'unknown worker error'}"
    correct = result.get("correct")
    detail = result.get("detail", "")
    if not isinstance(correct, bool) or not isinstance(detail, str):
        return False, "external oracle returned an invalid result shape"
    return correct, detail


def _benchmark_worker_environment(workspace: Path) -> dict[str, str]:
    python_dir = str(Path(sys.executable).resolve().parent)
    environment = {
        "PATH": python_dir,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TEMP": str(workspace),
        "TMP": str(workspace),
    }
    for key in ("SystemRoot", "WINDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _benchmark_process_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def run_case(
    model: ChatModel,
    case: BenchmarkCase,
    *,
    max_turns: int = 4,
) -> BenchmarkCaseResult:
    """Run one model against a disposable fixture and judge its proposal externally."""

    instrumented = model if isinstance(model, InstrumentedModel) else InstrumentedModel(model)
    with tempfile.TemporaryDirectory(prefix="codex-local-benchmark-") as temp_dir:
        workspace = Path(temp_dir)
        for raw_path, content in case.fixture.items():
            target = workspace / raw_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")

        started = perf_counter_ns()
        result = Controller(instrumented, workspace, max_turns=max_turns).run(case.task)
        wall_time_ms = (perf_counter_ns() - started) / 1_000_000
        fallback_patch = instrumented.proposed_patches[-1] if instrumented.proposed_patches else ""
        fallback_edits = instrumented.proposed_edits[-1] if instrumented.proposed_edits else None
        patch_applied, correct, patch_error, patch_source = _judge_patch(
            result,
            case,
            workspace,
            fallback_patch=fallback_patch,
            fallback_edits=fallback_edits,
        )
        tool_calls = sum(
            1
            for event in result.get("audit", [])
            if isinstance(event, Mapping) and event.get("event") == "tool_call"
        )
        validation = result.get("validation")
        validation_valid = isinstance(validation, Mapping) and validation.get("valid") is True
        if patch_source == "tool_proposal":
            validation_valid = _validate_patch_for_case(fallback_patch, case).valid
        status = result.get("status") if isinstance(result.get("status"), str) else "failed"
        loop_reliable = status == "accepted" and not _has_loop_error(result)
        return BenchmarkCaseResult(
            case_id=case.id,
            status=status,
            correct=correct,
            loop_reliable=loop_reliable,
            validation_valid=validation_valid,
            patch_applied=patch_applied,
            patch_source=patch_source,
            patch_error=patch_error,
            wall_time_ms=wall_time_ms,
            model_calls=instrumented.model_calls,
            tool_calls=tool_calls,
            total_duration_ns=instrumented.total_duration_ns,
            load_duration_ns=instrumented.load_duration_ns,
            prompt_tokens=instrumented.prompt_tokens,
            prompt_eval_duration_ns=instrumented.prompt_eval_duration_ns,
            eval_count=instrumented.eval_count,
            eval_duration_ns=instrumented.eval_duration_ns,
            result=result,
        )


def run_benchmark(
    model_name: str,
    model: ChatModel,
    *,
    cases: Sequence[BenchmarkCase] | None = None,
    repeats: int = 1,
    max_turns: int = 4,
) -> dict[str, Any]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    selected = tuple(cases or default_cases())
    results = [
        run_case(model, case, max_turns=max_turns)
        for _ in range(repeats)
        for case in selected
    ]
    return {
        "model": model_name,
        "repeats": repeats,
        "cases": [result.as_dict() for result in results],
        "summary": summarize_results(model_name, results),
    }


def summarize_results(model_name: str, results: Sequence[BenchmarkCaseResult]) -> dict[str, Any]:
    total = len(results)
    if total == 0:
        raise ValueError("cannot summarize an empty benchmark")
    return {
        "model": model_name,
        "cases": total,
        "correctness_percent": _percent(sum(result.correct for result in results), total),
        "tool_loop_reliability_percent": _percent(sum(result.loop_reliable for result in results), total),
        "validation_percent": _percent(sum(result.validation_valid for result in results), total),
        "patch_apply_percent": _percent(sum(result.patch_applied for result in results), total),
        "average_wall_time_ms": round(mean(result.wall_time_ms for result in results), 3),
        "median_wall_time_ms": round(median(result.wall_time_ms for result in results), 3),
        "model_calls": sum(result.model_calls for result in results),
        "tool_calls": sum(result.tool_calls for result in results),
        "total_duration_ms": round(sum(result.total_duration_ns for result in results) / 1_000_000, 3),
        "load_duration_ms": round(sum(result.load_duration_ns for result in results) / 1_000_000, 3),
        "prompt_tokens": sum(result.prompt_tokens for result in results),
        "eval_tokens": sum(result.eval_count for result in results),
        "prompt_eval_duration_ms": round(
            sum(result.prompt_eval_duration_ns for result in results) / 1_000_000, 3
        ),
        "eval_duration_ms": round(sum(result.eval_duration_ns for result in results) / 1_000_000, 3),
    }


def write_artifact(path: str | Path, artifact: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _judge_patch(
    result: Mapping[str, Any],
    case: BenchmarkCase,
    workspace: Path,
    *,
    fallback_patch: str,
    fallback_edits: list[dict[str, Any]] | None = None,
) -> tuple[bool, bool, str, str]:
    patch_source = "accepted_result" if result.get("status") == "accepted" else "tool_proposal"
    patch = result.get("patch") if patch_source == "accepted_result" else fallback_patch
    if (not isinstance(patch, str) or not patch.strip()) and fallback_patch:
        patch_source = "tool_proposal"
        patch = fallback_patch
    edits = None
    if not isinstance(patch, str) or not patch.strip():
        if fallback_edits:
            patch_source = "tool_proposal"
            edits = fallback_edits
    has_patch = isinstance(patch, str) and bool(patch.strip())
    if not has_patch and not edits:
        return False, False, "candidate did not contain a patch", "none"
    validation = _validate_patch_for_case(patch, case, edits=edits, workspace=workspace)
    if not validation.valid:
        return False, False, "; ".join(validation.issues), patch_source
    resolved = validation.resolved_patch or patch
    if shutil.which("git") is None:
        return False, False, "git executable is unavailable for isolated patch application", patch_source
    apply_check = _git_apply(workspace, resolved, check=True)
    if apply_check.returncode != 0:
        return False, False, _process_error(apply_check), patch_source
    applied = _git_apply(workspace, resolved, check=False)
    if applied.returncode != 0:
        return False, False, _process_error(applied), patch_source
    try:
        if case.oracle is not None:
            correct, oracle_error = _run_oracle_in_restricted_process(case.oracle, workspace)
        else:
            correct, oracle_error = _exact_file_oracle(case, workspace)
    except Exception as error:  # external oracle must turn malformed proposals into a score
        correct, oracle_error = False, f"external oracle error: {error}"
    if not correct:
        return True, False, oracle_error, patch_source
    if set(validation.changed_files) != set(case.expected_files):
        return True, False, "external oracle changed-file set mismatch", patch_source
    return True, True, "", patch_source


def _validate_patch_for_case(patch: str, case: BenchmarkCase, *, edits=None, workspace=None):
    candidate = {
        "status": "candidate",
        "summary": "benchmark proposal",
        "patch": patch,
        "checks": [],
        "risks": [],
    }
    if edits is not None:
        candidate["edits"] = edits
    return validate_candidate(candidate, case.task, workspace_root=workspace)


def _exact_file_oracle(case: BenchmarkCase, workspace: Path) -> tuple[bool, str]:
    for raw_path, expected in case.expected_files.items():
        actual = (workspace / raw_path).read_text(encoding="utf-8")
        if actual != expected:
            return False, f"external oracle mismatch: {raw_path}"
    return True, ""


def _git_apply(workspace: Path, patch: str, *, check: bool) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "apply", "--whitespace=nowarn"]
    if check:
        command.append("--check")
    command.append("-")
    return subprocess.run(
        command,
        cwd=workspace,
        input=patch.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )


def _process_error(process: subprocess.CompletedProcess[bytes]) -> str:
    detail = process.stderr.decode("utf-8", errors="replace").strip()
    return detail or f"git apply exited with code {process.returncode}"


def _has_loop_error(result: Mapping[str, Any]) -> bool:
    error = result.get("error")
    if not isinstance(error, Mapping):
        return False
    return error.get("kind") in {
        "duplicate_tool_call",
        "max_turns",
        "model_error",
        "policy",
        "invalid_json",
        "invalid_response",
    }


def _metric_int(response: Mapping[str, Any], key: str) -> int:
    value = response.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _percent(numerator: int, denominator: int) -> float:
    return round(numerator * 100.0 / denominator, 2)
