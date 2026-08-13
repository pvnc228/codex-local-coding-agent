# Handoff — состояние на конец сессии 2026-08-13

Короткая сводка для передачи в следующую сессию. Перед началом работы сверься с этим файлом.

## Где мы находимся

- Ветка: `main`.
- Review fixes P0/P1/P2 смержены и опубликованы: `3e951bb`, merge `b879b03`.
- Свежий локальный gate этой сессии: **72/72 OK**, `compileall` и `git diff --check` прошли. Live chat и benchmark после review не запускались.
- Ollama: `http://127.0.0.1:11434`, read-only `/api/ps` отвечает; сейчас загруженных моделей нет. Live chat и benchmark после review не запускались.
- Исследование следующей волны моделей и MCP `2026-07-28` оформлено в [MODEL_EVALUATION_PLAN.md](MODEL_EVALUATION_PLAN.md) и [MCP_DESIGN.md](MCP_DESIGN.md). R5.1 transport-neutral core seam реализован; MCP transport R5.2 и runtime evidence остаются впереди.

## Что закрыто в этой сессии

- **R1/R2** (ранее, commits `c09ec0c` и `2033c2a`): все 10 пунктов `docs/AUDIT.md` + hunk-relaxation.
- **R3 — Mediated apply**: новый флаг `--apply` (`cli.py`), controller-only seam `apply_patch` (`validators.py`) — применяется patch к workspace только после подтверждения контроллера; локальная модель не имеет прямого доступа к `apply_patch` (`controller.py` параметр `apply=`); proposal-only как режим по умолчанию.
- **Review fixes**: benchmark oracle вынесен в restricted child process; audit/applied стали controller-owned; `--apply` получил post-apply checks и rollback; subprocess output/termination bounded; fallback patch и trimming исправлены.
- **R5.1 core service seam**: добавлены `ServiceRequest`/`ServiceResult`, opaque `WorkspaceRegistry`, allowlisted direct adapter, idempotency и machine-readable policy errors; proposal-only и controller-owned result semantics сохранены.
- **Документация**: flow, hunk-count contract, benchmark artifact status и branch handoff синхронизированы.

## Benchmark baseline до REQUEST_CHANGES

Это baseline предыдущего runtime-прогона, не evidence текущего исправления. Артефакт `.codex-run/benchmarks/latest.json` gitignored и не публикуется. `repeats=1`, профильные значения по умолчанию, `temperature=0`, `num_predict=512`, `max_turns=4`.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Avg wall, ms | Model calls | Tool calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bonsai-64k` | completed | 0% | 0% | 100% | 0% | 5,980 | 8 | 8 |
| `qwen2.5-coder` | completed | 0% | 0% | 0% | 0% | 3,589 | 10 | 6 |
| `ornith-9b` | completed | 0% | 0% | 100% | 25% | 6,643 | 10 | 8 |
| `qwen3-coder-30b` | completed | 0% | 0% | 75% | 25% | 15,260 | 10 | 7 |
| `devstral-small-2-24b` | completed | 25% | 0% | 75% | 50% | 50,734 | 15 | 13 |
| `ternary-bonsai-27b` | unavailable | — | — | — | — | — | — | — |

- `devstral-small-2-24b` — единственный профиль с ненулевой correctness (25%) и единственный, кто применил patch (50%); лучший текущий кандидат в shortlist, хотя loop reliability всё ещё 0%.
- Ни один профиль не достиг ненулевой loop reliability; correctness в целом остаётся низкой.
- `ternary-bonsai-27b` остаётся недоступным (отсутствует в Ollama `/api/tags`).

## Модели

- Установлены и отвечают: `codex-devstral-small-2-24b`, `codex-qwen3-coder-30b`, `codex-ornith-9b`, `bonsai-64k`, `qwen2.5:1.5b`, `qwen2.5-coder`.
- **НЕ установлен**: `codex-ternary-bonsai-27b:latest` — отсутствует в `/api/tags`; benchmark-профиль помечается `UNAVAILABLE`.

## Что осталось

- **Loop-reliability gap**: содержательные proposal пока ненадёжно доставляются через protocol loop (0% у всех профилей).
- **Следующий причинный эксперимент**: Qwen3-Coder IQ2/Q4 из одного pinned GGUF source/revision. Существующий IQ2 из другого репозитория — только observational baseline.
- **Следующий product race**: Qwen3-8B Q6, Qwen2.5-Coder-14B Q6, Muse Glimmer Q4 и Nemotron MXFP4_MOE после quant A/B.
- **MCP R5**: сначала transport-neutral core seam, затем local `stdio` proposal-only `delegate_code`, после этого Tasks/queue. Apply и remote HTTP не входят в первый slice.
- **Незапущено после review**: live chat и benchmark. Не считать model ranking обновлённым без нового внешнего artifact.
- Приём bare hunk остаётся отдельной protocol hypothesis и не должен внедряться без red tests и проверки, что validation boundary не ослабляется.
- **Операционные детали** из прежней сессии всё ещё актуальны:
  - Субагенты-кодеры: `flash-coder` — надёжный основной; `nemotron-coder` один раз вернул пустой результат (переделегировали на `flash-coder`).
  - Релевантные скиллы: `tdd`, `securing-agentic-ai-tool-invocation`, `ponytail`.
  - CLI: `py -m local_coding_agent --benchmark --benchmark-model <profile> [--benchmark-repeats N] [--benchmark-timeout-seconds N]`.
  - Освободить VRAM: `py -m local_coding_agent --unload-all` (или `--unload-model <name>`).

## Ключевые файлы

- `local_coding_agent/validators.py` — `apply_patch` (controller-only seam), `parse_unified_diff`, `check_patch_applies`, `_fold_path`, `_evidence_facts`.
- `local_coding_agent/controller.py` — параметр `apply=` (mediated apply), `_messages_size` (кумулятивный бюджет), cancellation, canonical signature `list_files`, `ThreadPoolExecutor` для `model.chat`.
- `local_coding_agent/benchmark.py` + `benchmark_oracle_worker.py` — fallback patch capture и restricted external oracle process.
- `local_coding_agent/cli.py` — флаг `--apply`.
- `local_coding_agent/repository_tools.py` — allowlist в `list_files`, pre-read лимит `search_text`, `_kill_tree`, `_trim_stdout_stderr`, `ToolCancelled`.
- `tests/` — новые/переписанные: `test_validators.py`, `test_controller.py`, `test_repository_tools.py`, `test_memory_manager.py`.
- Документы: `ROADMAP.md` (план вперёд), `ROADMAP_HISTORICAL.md` (M0–M6), `AUDIT.md`, `BENCHMARK.md`, `MODEL_RESEARCH.md`, `MODEL_EVALUATION_PLAN.md`, `MCP_DESIGN.md`.
