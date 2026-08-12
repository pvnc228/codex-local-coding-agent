# Handoff — состояние на конец сессии 2026-08-12

Короткая сводка для передачи в следующую сессию. Перед началом работы сверься с этим файлом.

## Где мы находимся

- Ветка: `agent/document-model-shortlist`, синхронизирована с `origin` (последний commit `2033c2a`).
- Все правки закоммичены и запушены, рабочая копия чистая.
- Тесты: **56/56 OK** — `py -m unittest discover -s tests`.
- Ollama: `http://127.0.0.1:11434`, отвечает. VRAM в конце сессии освобождён (`total_vram_bytes: 0`).

## Что закрыто в этой сессии (R1/R2 из ROADMAP.md)

Все 10 пунктов `docs/AUDIT.md` закрыты и запушены:

- Commit `c09ec0c` — R1/R2: allowlist для `list_files` (#1), git в README + graceful fallback (#2), кумулятивный контекстный бюджет (#3), cancellation блокирующих вызовов (#4), структурная сверка evidence (#5), pre-read лимит `search_text` (#6), убрано дублирование/O(n²) обрезки (#7), duplicate-call guard через canonical signature `list_files` (#8), case-sensitive allowlist (#9), снапшот после unload в `enforce_limit` (#10).

### Hunk-relaxation (последнее изменение, commit `2033c2a`)

- Убрана избыточная проверка old/new hunk line counts в `parse_unified_diff` (`validators.py`), оставлены структурные проверки.
- Мотивация: `git apply --check` уже отвергает malformed hunks (`corrupt patch`), поэтому наш подсчёт строк был дублирующим барьером. Безопасность не ослаблена.
- **Итог — нейтрально**: повторный benchmark не дал прироста correctness (см. ниже). Это подтверждает, что узкое место не в парсере, а в том, что модели генерируют патчи, которые `git` сам отвергает.

## Benchmark (повторный прогон 2 моделей, артефакт gitignored)

Артефакт: `.codex-run/benchmarks/latest.json` (в `.gitignore`).

| model | correct | valid | apply |
| --- | ---: | ---: | ---: |
| devstral-small-2-24b | 25% | 75% | 50% |
| qwen3-coder-30b | 0% | 75% | 25% |

- Недетерминизм: кейс `utf8-json`, который в прошлом анализе давал единственный oracle-`correct`, в этом прогоне упал на структурной проверке. Выводы по отдельным кейсам ненадёжны.
- Доминирующий отказ по-прежнему — `git apply` возвращает `corrupt patch` / `patch does not apply` (не наш парсер).

## Модели

- Установлены и отвечают: `codex-devstral-small-2-24b`, `codex-qwen3-coder-30b`, `codex-ornith-9b`, `bonsai-64k`, `qwen2.5:1.5b`, `qwen2.5-coder`.
- **НЕ установлен**: `codex-ternary-bonsai-27b:latest` — Ollama отклонил импорт (`tensor "output.weight" size overflow`). Benchmark-профиль для него помечается `UNAVAILABLE`.
- `bonsai-64k` заявляет capabilities `tools/thinking/vision`; остальные импорты — только `completion`.

## Roadmap — что осталось (это и есть "делай роадмапу")

Из `docs/ROADMAP.md`:

- **R1 — закрыто.** **R2 — закрыто.**
- **R3 — Mediated apply** (не начато): применять patch к workspace только после отдельного подтверждения контроллера; `apply_patch` остаётся недоступен локальной модели напрямую; proposal-only как режим по умолчанию.
- **R4 — повторный benchmark + evidence** (частично): повторить benchmark на тех же fixtures; зафиксировать runtime artifact; пересмотреть shortlist только по внешнему oracle.

## Следующий рычаг роста correctness (если решим лезть в качество, а не только в R3/R4)

Принимать «голый» hunk без `diff --git` / `---` / `+++` заголовка — `git apply` умеет применять bare hunks. Сейчас модели часто падают именно на форматировании заголовка. Это отдельная гипотеза, не входит в R3/R4 по умолчанию.

## Операционные детали

- Субагенты-кодеры: `flash-coder` — надёжный основной; `nemotron-coder` один раз вернул пустой результат (переделегировали на `flash-coder`).
- Релевантные скиллы: `tdd`, `securing-agentic-ai-tool-invocation`, `ponytail`.
- CLI: `py -m local_coding_agent --benchmark --benchmark-model <profile> [--benchmark-repeats N] [--benchmark-timeout-seconds N]`.
- Освободить VRAM: `py -m local_coding_agent --unload-all` (или `--unload-model <name>`).

## Ключевые файлы

- `local_coding_agent/validators.py` — `parse_unified_diff` (hunk-count gate убран), `check_patch_applies`, `_fold_path`, `_evidence_facts`.
- `local_coding_agent/controller.py` — `_messages_size` (кумулятивный бюджет), cancellation, canonical signature `list_files`, `ThreadPoolExecutor` для `model.chat`.
- `local_coding_agent/repository_tools.py` — allowlist в `list_files`, pre-read лимит `search_text`, `_kill_tree`, `_trim_stdout_stderr`, `ToolCancelled`.
- `tests/` — новые/переписанные: `test_validators.py`, `test_controller.py`, `test_repository_tools.py`, `test_memory_manager.py`.
- Документы: `ROADMAP.md` (план вперёд), `ROADMAP_HISTORICAL.md` (M0–M6), `AUDIT.md`, `BENCHMARK.md`, `MODEL_RESEARCH.md`.
