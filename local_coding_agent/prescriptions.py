"""Deterministic Pinpointed Prescriptions Engine for Small Local Models.

Translates validation issues, JSON parse failures, tool policy violations,
SEARCH/REPLACE mismatches, and test failures into precise, actionable,
laser-focused instructions that small models (2B-4B) can follow deterministically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class DiagnosticKind(str, Enum):
    JSON_SYNTAX_ERROR = "JSON_SYNTAX_ERROR"
    SCHEMA_CHECKS_TYPE_ERROR = "SCHEMA_CHECKS_TYPE_ERROR"
    SCHEMA_RISKS_TYPE_ERROR = "SCHEMA_RISKS_TYPE_ERROR"
    SCHEMA_MISSING_REQUIRED = "SCHEMA_MISSING_REQUIRED"
    TOOL_DUAL_PATCH_AND_EDITS = "TOOL_DUAL_PATCH_AND_EDITS"
    TOOL_MISSING_PATCH_AND_EDITS = "TOOL_MISSING_PATCH_AND_EDITS"
    TOOL_FORBIDDEN_FILE = "TOOL_FORBIDDEN_FILE"
    SEARCH_BLOCK_NOT_FOUND = "SEARCH_BLOCK_NOT_FOUND"
    SEARCH_NOT_LINE_ALIGNED = "SEARCH_NOT_LINE_ALIGNED"
    SEARCH_AMBIGUOUS = "SEARCH_AMBIGUOUS"
    DUPLICATE_EDIT_FILE = "DUPLICATE_EDIT_FILE"
    DIFF_CORRUPT_HUNK = "DIFF_CORRUPT_HUNK"
    DIFF_APPLY_FAILED = "DIFF_APPLY_FAILED"
    TEST_CHECK_FAILED = "TEST_CHECK_FAILED"
    GENERIC_DIAGNOSTIC = "GENERIC_DIAGNOSTIC"


@dataclass(frozen=True)
class Prescription:
    kind: DiagnosticKind
    code: str
    summary: str
    instruction: str
    fix_example: Optional[str] = None

    def format_message(self) -> str:
        if self.fix_example:
            return f"{self.instruction} Пример: {self.fix_example}"
        return self.instruction


def prescribe_issue(issue: str, *, context: Optional[Mapping[str, Any]] = None) -> Prescription:
    """Analyze a single diagnostic issue string and return an actionable prescription."""
    raw = str(issue or "").strip()
    lower = raw.lower()

    # 1. Checks schema issues (e.g. checks must be a list of objects)
    if "check" in lower and ("must be an object" in lower or "must be a list" in lower or "string" in lower or "type" in lower):
        return Prescription(
            kind=DiagnosticKind.SCHEMA_CHECKS_TYPE_ERROR,
            code="ERR_CHECKS_TYPE",
            summary="Поле 'checks' заполнено неверным типом",
            instruction="Поле 'checks' не должно содержать строки или произвольный текст. Укажи пустой массив 'checks': [] (или объекты результатов тестов).",
            fix_example='"checks": []',
        )

    # 2. Risks schema issues
    if "risk" in lower and ("must be a list" in lower or "not-a-list" in lower or "type" in lower):
        return Prescription(
            kind=DiagnosticKind.SCHEMA_RISKS_TYPE_ERROR,
            code="ERR_RISKS_TYPE",
            summary="Поле 'risks' должно быть списком",
            instruction="Поле 'risks' должно быть массивом строк или пустым массивом 'risks': [].",
            fix_example='"risks": []',
        )

    # 3. Tool Policy: Dual format (both patch and edits)
    if "not both" in lower or ("patch" in lower and "edits" in lower and "both" in lower):
        return Prescription(
            kind=DiagnosticKind.TOOL_DUAL_PATCH_AND_EDITS,
            code="ERR_DUAL_FORMAT",
            summary="Переданы одновременно и patch, и edits",
            instruction="Не передавай 'patch' и 'edits' одновременно. Передай ТОЛЬКО список 'edits' со структурой [{\"file\": \"...\", \"search\": \"...\", \"replace\": \"...\"}], удалив поле 'patch'.",
            fix_example='{"edits": [{"file": "src/a.py", "search": "old_code", "replace": "new_code"}]}',
        )

    # 4. Tool Policy: Missing patch/edits
    if "must be provided" in lower or "no patch nor edits" in lower or "no resolved patch" in lower:
        return Prescription(
            kind=DiagnosticKind.TOOL_MISSING_PATCH_AND_EDITS,
            code="ERR_MISSING_CHANGES",
            summary="Не указаны изменения",
            instruction="Необходимо передать список изменений 'edits': [{\"file\": \"...\", \"search\": \"...\", \"replace\": \"...\"}].",
            fix_example='{"edits": [{"file": "src/a.py", "search": "old_code", "replace": "new_code"}]}',
        )

    # 5. File Allowlist violations
    if "allowlist" in lower or "outside" in lower or "forbidden" in lower:
        file_match = re.search(r"([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)", raw)
        filename = file_match.group(1) if file_match else "указанный файл"
        return Prescription(
            kind=DiagnosticKind.TOOL_FORBIDDEN_FILE,
            code="ERR_FILE_FORBIDDEN",
            summary=f"Файл {filename} вне task allowlist",
            instruction=f"Файл '{filename}' не входит в разрешенный список задачи. Работай только с файлами из task allowlist.",
        )

    # 6. Search block not found
    if "search block not found" in lower or ("search" in lower and "not found" in lower):
        file_match = re.search(r":\s*([a-zA-Z0-9_\-\./\\]+)", raw)
        filename = file_match.group(1) if file_match else "файле"
        return Prescription(
            kind=DiagnosticKind.SEARCH_BLOCK_NOT_FOUND,
            code="ERR_SEARCH_NOT_FOUND",
            summary=f"Блок search не найден в {filename}",
            instruction=f"Блок 'search' не совпадает с содержимым файла '{filename}'. Вызови инструмент read_file и скопируй точные строки символ-в-символ, включая пробелы и отступы в начале каждой строки.",
        )

    # 7. Search not line-aligned
    if "line-aligned" in lower or "line aligned" in lower:
        return Prescription(
            kind=DiagnosticKind.SEARCH_NOT_LINE_ALIGNED,
            code="ERR_SEARCH_ALIGNMENT",
            summary="Блок search не выровнен по границам строк",
            instruction="Блок 'search' должен начинаться с самого начала строки файла и заканчиваться концом строки (не вырезай фрагменты из середины строки).",
        )

    # 8. Search ambiguous
    if "ambiguous" in lower:
        return Prescription(
            kind=DiagnosticKind.SEARCH_AMBIGUOUS,
            code="ERR_SEARCH_AMBIGUOUS",
            summary="Блок search встречается в файле несколько раз",
            instruction="Блок 'search' неоднозначен (найдено несколько совпадений). Добавь 2-3 уникальные строки контекста выше и ниже заменяемого кода.",
        )

    # 9. Duplicate edit file
    if "duplicate edit file" in lower:
        return Prescription(
            kind=DiagnosticKind.DUPLICATE_EDIT_FILE,
            code="ERR_DUPLICATE_FILE_EDIT",
            summary="Несколько блоков правок для одного файла",
            instruction="Объедини все изменения в одном файле в единый блок 'search'/'replace'.",
        )

    # 10. Corrupt hunk / diff syntax issues
    if "hunk" in lower or "corrupt patch" in lower or "invalid hunk" in lower or "diff header" in lower:
        return Prescription(
            kind=DiagnosticKind.DIFF_CORRUPT_HUNK,
            code="ERR_DIFF_SYNTAX",
            summary="Неверный синтаксис diff / hunk header",
            instruction="Ошибка синтаксиса в diff hunk header (не совпали номера строк). Рекомендуется использовать формат 'edits' со списком {file, search, replace}, где номера строк не требуются.",
            fix_example='"edits": [{"file": "src/a.py", "search": "...", "replace": "..."}]',
        )

    # 11. Patch does not apply cleanly
    if "cleanly" in lower or "apply" in lower:
        return Prescription(
            kind=DiagnosticKind.DIFF_APPLY_FAILED,
            code="ERR_PATCH_APPLY",
            summary="Патч не накладывается на текущее состояние файлов",
            instruction="Патч не накладывается на актуальную версию файла. Вызови read_file, чтобы получить свежий код, и сформируй SEARCH/REPLACE блок в поле 'edits'.",
        )

    # Fallback generic prescription
    return Prescription(
        kind=DiagnosticKind.GENERIC_DIAGNOSTIC,
        code="ERR_GENERIC",
        summary=raw,
        instruction=raw,
    )


def prescribe_all(issues: Sequence[str], *, context: Optional[Mapping[str, Any]] = None) -> str:
    """Build a unified, de-duplicated prescription string from multiple issues."""
    if not issues:
        return "Исправь структуру ответа и верни корректный JSON."
    prescriptions = [prescribe_issue(issue, context=context) for issue in issues]
    formatted = [p.format_message() for p in prescriptions]
    # Deduplicate preserving order
    unique_messages = list(dict.fromkeys(formatted))
    return " ".join(unique_messages)


def json_syntax_prescription(error: Optional[str] = None) -> str:
    """Return an exact prescriptive prompt when a model outputs malformed non-JSON."""
    err_detail = f" ({error})" if error else ""
    return (
        f"ОШИБКА JSON: Твой ответ не удалось разобрать как валидный JSON{err_detail}. "
        "Верни СТРОГО один JSON-объект без markdown-разметки (без ```json), без текста до и после: "
        '{"status": "candidate", "summary": "краткое описание", "patch": "", "checks": [], "risks": []} '
        'или вместо "patch" передай "edits": [{"file": "...", "search": "...", "replace": "..."}].'
    )


def tool_policy_prescription(tool_name: str, error: str) -> dict[str, Any]:
    """Return a structured error payload with code, summary, and actionable hint for tool policy errors."""
    prescription = prescribe_issue(error)
    return {
        "ok": False,
        "status": "error",
        "error_code": prescription.code,
        "error": error,
        "hint": prescription.instruction,
        "diagnostic_kind": prescription.kind.value,
    }
