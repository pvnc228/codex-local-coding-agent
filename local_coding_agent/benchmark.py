"""Comparable, proposal-only benchmark for local coding models."""

from __future__ import annotations

import json
import inspect
import math
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
        prompt_eval_tps = (
            round(self.prompt_tokens * 1e9 / self.prompt_eval_duration_ns, 2)
            if self.prompt_eval_duration_ns > 0
            else 0.0
        )
        eval_tps = (
            round(self.eval_count * 1e9 / self.eval_duration_ns, 2)
            if self.eval_duration_ns > 0
            else 0.0
        )
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
            "prompt_eval_tps": prompt_eval_tps,
            "eval_count": self.eval_count,
            "eval_duration_ns": self.eval_duration_ns,
            "eval_tps": eval_tps,
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
        _edit_case(
            "count-positives",
            "посчитать количество положительных элементов",
            "count",
            "def count_positives(values):\n    return len(values)\n",
            "def count_positives(values):\n    return sum(1 for value in values if value > 0)\n",
            "Считать нужно только элементы строго больше нуля.",
            "счётчик учитывает только положительные элементы",
            _count_positives_oracle,
        ),
        _edit_case(
            "max-value",
            "вернуть максимальное значение из списка",
            "maxval",
            "def max_value(values):\n    return values[0]\n",
            "def max_value(values):\n    return max(values)\n",
            "Функция должна возвращать наибольший элемент входного списка.",
            "для [3,7,2,5] возвращается 7",
            _max_value_oracle,
        ),
        _edit_case(
            "abs-sum",
            "вернуть сумму модулей элементов",
            "abssum",
            "def abs_sum(values):\n    return sum(values)\n",
            "def abs_sum(values):\n    return sum(abs(value) for value in values)\n",
            "Отрицательные числа должны входить в сумму как положительные.",
            "для [-1,2,-3] возвращается 6",
            _abs_sum_oracle,
        ),
        _edit_case(
            "reverse-str",
            "развернуть строку в обратном порядке",
            "reverse",
            "def reverse_str(value):\n    return value\n",
            "def reverse_str(value):\n    return value[::-1]\n",
            "Результат — та же строка в обратном порядке символов.",
            "для 'мир' возвращается 'рим'",
            _reverse_str_oracle,
        ),
        _edit_case(
            "filter-evens",
            "оставить только чётные элементы",
            "evens",
            "def evens(values):\n    return values\n",
            "def evens(values):\n    return [value for value in values if value % 2 == 0]\n",
            "Нужно вернуть новый список только с чётными числами.",
            "для [1,2,3,4,6] возвращается [2,4,6]",
            _filter_evens_oracle,
        ),
        _edit_case(
            "count-words",
            "посчитать слова в строке",
            "words",
            "def count_words(text):\n    return len(text)\n",
            "def count_words(text):\n    return len(text.split())\n",
            "Слова разделены пробелами; считать именно слова, а не символы.",
            "для 'один два три' возвращается 3",
            _count_words_oracle,
        ),
        _edit_case(
            "dict-default",
            "вернуть значение ключа или ноль",
            "defval",
            "def get_or_zero(mapping, key):\n    return mapping[key]\n",
            "def get_or_zero(mapping, key):\n    return mapping.get(key, 0)\n",
            "Отсутствующий ключ не должен выбрасывать ошибку.",
            "для отсутствующего ключа возвращается 0",
            _dict_default_oracle,
        ),
        _edit_case(
            "strip-text",
            "убрать пробелы по краям строки",
            "strip",
            "def normalize(text):\n    return text.replace(' ', '')\n",
            "def normalize(text):\n    return text.strip()\n",
            "Убирать пробелы нужно только по краям, а не внутри.",
            "для '  hi  ' возвращается 'hi'",
            _strip_text_oracle,
        ),
        _edit_case(
            "join-words",
            "склеить слова через пробел",
            "join",
            "def join_words(words):\n    return words\n",
            "def join_words(words):\n    return ' '.join(words)\n",
            "Результат — одна строка из слов, разделённых одиночным пробелом.",
            "для ['a','b','c'] возвращается 'a b c'",
            _join_words_oracle,
        ),
        _edit_case(
            "last-element",
            "вернуть последний элемент списка",
            "last",
            "def last(values):\n    return values[0]\n",
            "def last(values):\n    return values[-1]\n",
            "Нужен именно последний, а не первый элемент.",
            "для [1,2,3] возвращается 3",
            _last_element_oracle,
        ),
        _edit_case(
            "sorted-copy",
            "вернуть отсортированную копию без изменения входа",
            "sortcopy",
            "def sorted_copy(values):\n    values.sort()\n    return values\n",
            "def sorted_copy(values):\n    return sorted(values)\n",
            "Исходный список не должен изменяться.",
            "вход [3,1,2] остаётся неизменным, результат [1,2,3]",
            _sorted_copy_oracle,
        ),
        _edit_case(
            "replace-dash",
            "заменить дефисы на подчёркивания",
            "replace",
            "def replace_dash(text):\n    return text\n",
            "def replace_dash(text):\n    return text.replace('-', '_')\n",
            "Все символы '-' должны стать '_'.",
            "для 'a-b-c' возвращается 'a_b_c'",
            _replace_dash_oracle,
        ),
        _edit_case(
            "starts-with",
            "проверить начало строки",
            "starts",
            "def starts_with(text, prefix):\n    return prefix in text\n",
            "def starts_with(text, prefix):\n    return text.startswith(prefix)\n",
            "Совпадение должно быть именно в начале строки.",
            "для 'hello','he' — True; для 'hello','xy' — False",
            _starts_with_oracle,
        ),
        _edit_case(
            "dot-product",
            "посчитать скалярное произведение",
            "dot",
            "def dot(left, right):\n    return sum(left) * sum(right)\n",
            "def dot(left, right):\n    return sum(a * b for a, b in zip(left, right))\n",
            "Суммировать нужно попарные произведения элементов.",
            "для [1,2,3] и [4,5,6] возвращается 32",
            _dot_product_oracle,
        ),
        _edit_case(
            "min-value",
            "вернуть минимальное значение из списка",
            "minval",
            "def min_value(values):\n    return values[0]\n",
            "def min_value(values):\n    return min(values)\n",
            "Функция должна возвращать наименьший элемент входного списка.",
            "для [3,7,2,5] возвращается 2",
            _min_value_oracle,
        ),
        _edit_case(
            "title-case",
            "перевести каждое слово в регистр заголовка",
            "title",
            "def title_case(text):\n    return text.upper()\n",
            "def title_case(text):\n    return text.title()\n",
            "Первая буква каждого слова — заглавная, остальные — строчные.",
            "для 'hello world' возвращается 'Hello World'",
            _title_case_oracle,
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


def _edit_case(
    case_id: str,
    goal: str,
    file_name: str,
    buggy: str,
    expected: str,
    context: str,
    acceptance: str,
    oracle: Callable[[Path], tuple[bool, str]],
) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        task=TaskEnvelope(
            id=case_id,
            goal=goal,
            files=(f"src/{file_name}.py",),
            context=context,
            constraints=("сохранить имя функции", "не добавлять зависимости"),
            acceptance=(acceptance,),
        ),
        fixture={f"src/{file_name}.py": buggy},
        expected_files={f"src/{file_name}.py": expected},
        oracle=oracle,
    )


def _count_positives_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/count.py", "count_positives")
    if fn([-1, 2, -3, 4, 0]) != 2:
        return False, "external oracle mismatch: count_positives"
    return True, ""


def _max_value_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/maxval.py", "max_value")
    if fn([3, 7, 2, 5]) != 7:
        return False, "external oracle mismatch: max_value"
    return True, ""


def _abs_sum_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/abssum.py", "abs_sum")
    if fn([-1, 2, -3]) != 6:
        return False, "external oracle mismatch: abs_sum"
    return True, ""


def _reverse_str_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/reverse.py", "reverse_str")
    if fn("мир") != "рим":
        return False, "external oracle mismatch: reverse_str"
    return True, ""


def _filter_evens_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/evens.py", "evens")
    if fn([1, 2, 3, 4, 6]) != [2, 4, 6]:
        return False, "external oracle mismatch: evens"
    return True, ""


def _count_words_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/words.py", "count_words")
    if fn("один два три") != 3:
        return False, "external oracle mismatch: count_words"
    return True, ""


def _dict_default_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/defval.py", "get_or_zero")
    if fn({"a": 1}, "b") != 0 or fn({"a": 5}, "a") != 5:
        return False, "external oracle mismatch: get_or_zero"
    return True, ""


def _strip_text_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/strip.py", "normalize")
    if fn("  hi  ") != "hi":
        return False, "external oracle mismatch: normalize"
    return True, ""


def _join_words_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/join.py", "join_words")
    if fn(["a", "b", "c"]) != "a b c":
        return False, "external oracle mismatch: join_words"
    return True, ""


def _last_element_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/last.py", "last")
    if fn([1, 2, 3]) != 3:
        return False, "external oracle mismatch: last"
    return True, ""


def _sorted_copy_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/sortcopy.py", "sorted_copy")
    values = [3, 1, 2]
    returned = fn(values)
    if returned != [1, 2, 3] or values != [3, 1, 2]:
        return False, "external oracle mismatch: sorted_copy"
    return True, ""


def _replace_dash_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/replace.py", "replace_dash")
    if fn("a-b-c") != "a_b_c":
        return False, "external oracle mismatch: replace_dash"
    return True, ""


def _starts_with_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/starts.py", "starts_with")
    if not fn("hello", "he") or fn("hello", "xy"):
        return False, "external oracle mismatch: starts_with"
    return True, ""


def _dot_product_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/dot.py", "dot")
    if fn([1, 2, 3], [4, 5, 6]) != 32:
        return False, "external oracle mismatch: dot"
    return True, ""


def _min_value_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/minval.py", "min_value")
    if fn([3, 7, 2, 5]) != 2:
        return False, "external oracle mismatch: min_value"
    return True, ""


def _title_case_oracle(workspace: Path) -> tuple[bool, str]:
    fn = _load_function(workspace / "src/title.py", "title_case")
    if fn("hello world") != "Hello World":
        return False, "external oracle mismatch: title_case"
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
    with tempfile.TemporaryDirectory(prefix="local-benchmark-") as temp_dir:
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
    total_eval_tokens = sum(result.eval_count for result in results)
    total_eval_duration_ns = sum(result.eval_duration_ns for result in results)
    eval_tps = (
        round(total_eval_tokens * 1_000_000_000.0 / total_eval_duration_ns, 2)
        if total_eval_duration_ns > 0
        else 0.0
    )
    total_prompt_tokens = sum(result.prompt_tokens for result in results)
    total_prompt_eval_duration_ns = sum(result.prompt_eval_duration_ns for result in results)
    prompt_eval_tps = (
        round(total_prompt_tokens * 1_000_000_000.0 / total_prompt_eval_duration_ns, 2)
        if total_prompt_eval_duration_ns > 0
        else 0.0
    )
    correct_count = sum(result.correct for result in results)
    loop_reliable_count = sum(result.loop_reliable for result in results)
    patch_applied_count = sum(result.patch_applied for result in results)
    return {
        "model": model_name,
        "cases": total,
        "correctness_percent": _percent(correct_count, total),
        "correctness_ci_95": _wilson_score_interval(correct_count, total),
        "tool_loop_reliability_percent": _percent(loop_reliable_count, total),
        "tool_loop_reliability_ci_95": _wilson_score_interval(loop_reliable_count, total),
        "validation_percent": _percent(sum(result.validation_valid for result in results), total),
        "patch_apply_percent": _percent(patch_applied_count, total),
        "patch_apply_ci_95": _wilson_score_interval(patch_applied_count, total),
        "error_categories": _categorize_errors(results),
        "average_wall_time_ms": round(mean(result.wall_time_ms for result in results), 3),
        "median_wall_time_ms": round(median(result.wall_time_ms for result in results), 3),
        "model_calls": sum(result.model_calls for result in results),
        "tool_calls": sum(result.tool_calls for result in results),
        "total_duration_ms": round(sum(result.total_duration_ns for result in results) / 1_000_000, 3),
        "load_duration_ms": round(sum(result.load_duration_ns for result in results) / 1_000_000, 3),
        "prompt_tokens": total_prompt_tokens,
        "eval_tokens": total_eval_tokens,
        "prompt_eval_duration_ms": round(total_prompt_eval_duration_ns / 1_000_000, 3),
        "eval_duration_ms": round(total_eval_duration_ns / 1_000_000, 3),
        "eval_tokens_per_second": eval_tps,
        "prompt_tokens_per_second": prompt_eval_tps,
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


def _wilson_score_interval(successes: int, total: int, confidence_z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    z = confidence_z
    denominator = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denominator
    margin = (z * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * total)) / total)) / denominator
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return round(low * 100.0, 2), round(high * 100.0, 2)


def _categorize_errors(results: Sequence[BenchmarkCaseResult]) -> dict[str, int]:
    categories: dict[str, int] = {}
    for r in results:
        if r.correct and r.loop_reliable:
            continue
        err_msg = r.patch_error or ""
        error_kind = (
            r.result.get("error", {}).get("kind")
            if isinstance(r.result.get("error"), Mapping)
            else None
        )
        if "not line-aligned" in err_msg:
            cat = "search_not_line_aligned"
        elif "search block not found" in err_msg or "not found" in err_msg:
            cat = "search_not_found"
        elif "ambiguous" in err_msg:
            cat = "search_ambiguous"
        elif "git apply exited" in err_msg or "does not apply" in err_msg:
            cat = "git_apply_failed"
        elif "oracle mismatch" in err_msg:
            cat = "oracle_mismatch"
        elif error_kind:
            cat = str(error_kind)
        elif not r.patch_applied:
            cat = "patch_not_applied"
        else:
            cat = "other"
        categories[cat] = categories.get(cat, 0) + 1
    return dict(sorted(categories.items()))
