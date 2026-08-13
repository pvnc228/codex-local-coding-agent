# Handoff — состояние на конец сессии 2026-08-13 (вечер)

Короткая сводка для передачи в следующую сессию. Перед началом работы сверься с этим файлом.

## Где мы находимся

- Ветка: `main`. Всё запушено; `HEAD` = `90d0c93`.
- Полный локальный gate: **123/123 тестов OK**, `python -m compileall -q local_coding_agent tests` и `git diff --check` чистые.
- Python: рабочий `python` = 3.13.3 (bundled Codex Python). Системный `py` launcher ненадёжен, не использовать.
- Команды gate:
  - `python -m unittest discover -s tests`
  - `python -m compileall -q local_coding_agent tests`
  - `git diff --check`

## Что закрыто сегодня (R7, R8, R9, вторая волна моделей)

- **R7 — атомаризация** (`d8435de`): `local_coding_agent/atomizer.py` (`TaskBudget`, `preflight`, `decompose`), preflight gate в `DelegationService`. Live-проверка детерминированной части прошла; live-орacle на ребёнке не дал патч (дефект модели, не код).
- **R8 — retries/escalation** (`71763aa`): hard cap `max_retries≤10`, escalation bundle (task/attempts/viewed_files/last_patch/external_evidence), duplicate-call и cancellation приоритетнее retry budget. Live-проверка через scripted model прошла (ровно 4 попытки, off-by-one нет).
- **Вторая волна моделей** (`2214f79`, `44b7299`): скачаны 6 новых GGUF на `Q:\AI\Models\codex-local-coding-agent` (размеры+SHA-256 сверены с upstream). Импортированы 5 в Ollama под именами `codex-*`. Итоги:
  - `codex-qwen3-8b-q6k` (Q6_K, 6.7 GB), `codex-qwen2.5-coder-14b-q6k` (Q6_K, 12 GB), `codex-qwen3-coder-30b-ud-iq2` (UD-IQ2_M, 10.8 GB), `codex-qwen3-coder-30b-ud-q4` (UD-Q4_K_XL, 17.7 GB), `codex-nemotron-30b-mxfp4` (MXFP4_MOE, 18 GB).
  - **Muse Glimmer НЕ импортирован**: Ollama 0.32.5 отклонил quant `UD-Q4_K_XL` (`failed to validate GGUF with llama-quantize`).
  - **OOM-диагноз** (`4ad7e69`): `qwen3-coder-30b-ud-q4` и `nemotron-30b-mxfp4` (~17–18 GB) не загружаются на 8 GB VRAM. На Windows+CUDA Ollama отключает mmap и пинует CPU-offloaded тензоры в `CUDA_Host`; `num_gpu=0` тоже падает (`CPU_REPACK`-буфер + веса > 31.9 GB RAM). `num_ctx` не помогает (ошибка на загрузке тензоров, не KV-cache). Quant A/B (IQ2 vs Q4) на этой машине невозможен.
- **R9 — SEARCH/REPLACE** (`3d0dccb`, benchmark doc `90d0c93`): добавлен альтернативный формат изменения `edits` (`[{file, search, replace}]`) наравне с `patch` (unified diff). Controller сам конвертирует edits в diff (`resolve_edits`/`_build_edit_diff` в `validators.py`), модель не считает номера строк. `search` обязан совпадать с файлом ровно один раз на границе строки. См. `docs/PROTOCOL.md`.

## SEARCH/REPLACE benchmark (главный результат сессии)

Прогон прерван сбоем машины на записи, но artifact `.codex-run/benchmarks/search-replace-20260813.json` (gitignored) сохранился целиком: все 4 профиля завершились.

| Profile | Correctness (diff → SEARCH/REPLACE) | Loop reliability |
| --- | ---: | ---: |
| `qwen3-coder-30b-iq2` | 0% → **75%** | 0% |
| `qwen3-8b-q6k` | 0% → **50%** | 0% |
| `devstral-small-2-24b` | 25% → 25% | 0% |
| `qwen2.5-coder-14b-q6k` | 0% → 0% | 0% |

Гипотеза подтверждена: unified diff был главным барьером для слабых моделей. Две дешёвые модели (iq2 10 GB, qwen3-8b 6.7 GB) теперь реально решают задачи.

## Остаточные проблемы (следующие задачи)

1. **Loop reliability 0% у всех**: модели предлагают корректные edits через `propose_patch`, но не закрывают цикл чистым финальным JSON → `accepted` не достигается, результат падает в `max_turns`/rejected. Правильный кандидат при `patch_source=tool_proposal` засчитывается benchmark-judge'ем, но сам controller не завершает цикл accept'ом. Нужно продумать: разрешить завершение цикла прямо после валидного `propose_patch` без отдельного финального JSON.
2. **`edit search block is not line-aligned`**: модель копирует блок не с границы строки. Добавить в system contract явную подсказку про выравнивание `search` по строкам.
3. **`qwen2.5-coder-14b-q6k`**: не выдаёт ни patch, ни edits (retry budget exhausted) — сама не следует tool-контракту.
4. **Quant A/B не закрыт** (нужен Q4 с меньшим footprint или >32 GB RAM) — см. OOM-диагноз выше.

## Модели и профили

- Профили `profiles.py`: существующие + `qwen3-8b-q6k`, `qwen3-coder-30b-iq2`, `qwen3-coder-30b-q4`, `qwen2.5-coder-14b-q6k`, `nemotron-30b-mxfp4`. Muse не добавлен (не импортирован).
- Установлены в Ollama (store на `D:\ui\ui\ComfyUI\models`, переменная `OLLAMA_MODELS` активна в запущенном сервере): `codex-qwen3-8b-q6k`, `codex-qwen2.5-coder-14b-q6k`, `codex-qwen3-coder-30b-ud-iq2`, `codex-qwen3-coder-30b-ud-q4`, `codex-nemotron-30b-mxfp4` + старые (`codex-devstral-small-2-24b`, `codex-qwen3-coder-30b`, `codex-ornith-9b`, `bonsai-64k` и др.).
- **Загрузить невозможно** (OOM): `codex-qwen3-coder-30b-ud-q4`, `codex-nemotron-30b-mxfp4`.
- **Не импортирован**: Muse Glimmer (quant отклонён).

## Оставшиеся направления (из ROADMAP)

- R4.1 quant A/B — заблокирован памятью машины.
- Loop-reliability gap — приоритет №1 (см. остаточную проблему 1).
- MCP/R6: transport-neutral core (R5.1), stdio slice (R5.2), worker pool (R6) готовы; дальше — официальный MCP SDK/conformance, durable Tasks lifecycle, model-specific scheduling.
- Live mediated apply после R9 не перезапускался.

## Ключевые файлы

- `local_coding_agent/validators.py` — `validate_candidate` (принимает `patch` или `edits`), `resolve_edits`, `_build_edit_diff`, `apply_patch`, `parse_unified_diff`, `check_patch_applies`.
- `local_coding_agent/controller.py` — `SYSTEM_CONTRACT` и `TOOL_DEFINITIONS` (SEARCH/REPLACE), mediated apply, retry/escalation, canonical signature, cancellation.
- `local_coding_agent/atomizer.py` — R7.
- `local_coding_agent/repository_tools.py` — `propose_patch` принимает `patch`/`edits`.
- `local_coding_agent/benchmark.py` — judge принимает edit-proposal fallback.
- `local_coding_agent/profiles.py` — профили второй волны.
- `tests/test_edits.py` — новые тесты SEARCH/REPLACE.
- Документы: `ROADMAP.md` (R9 добавлен), `PROTOCOL.md` (SEARCH/REPLACE), `ARCHITECTURE.md`, `BENCHMARK.md`, `MODEL_RESEARCH.md`, `MODEL_EVALUATION_PLAN.md`.
- Throwaway probe (gitignored): `.codex-run/probe_search_replace.py`, `.codex-run/download_models.py`, `.codex-run/import_models.ps1`, `.codex-run/live_check_r7_r8.py`.
