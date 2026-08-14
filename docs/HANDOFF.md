# Handoff — состояние на конец сессии 2026-08-14

Короткая сводка для передачи в следующую сессию. Перед началом работы сверься с этим файлом.

## Где мы находимся

- Ветка: `main`. `HEAD` = `ccbbfa3`; незакоммиченные изменения текущей сессии (R5.3/R5.4) ещё НЕ смержены.
- Полный локальный gate: **156/156 тестов OK**, `python -m compileall -q local_coding_agent tests` и `git diff --check` чистые.
- Python: рабочий `python` = 3.13.3 (bundled Codex Python). Системный `py` launcher ненадёжен, не использовать.
- Команды gate:
  - `python -m unittest discover -s tests`
  - `python -m compileall -q local_coding_agent tests`
  - `git diff --check`

## Что закрыто в этой сессии (R5.3, R5.4)

- **R5.3 — Tasks extension** (`local_coding_agent/tasks.py`): `TasksExtension` (`io.modelcontextprotocol/tasks`) поверх `BoundedWorkerPool`. `intercept_tool_call` коротко-замыкает `delegate_code` и возвращает flat `CreateTaskResult` (`resultType:"task"`, `taskId`/`status`/`createdAt`/`lastUpdatedAt`/`ttlMs`/`pollIntervalMs`) ТОЛЬКО когда клиент заявил extension в `_meta.clientCapabilities.extensions`; без opt-in — обычный синхронный путь. Обслуживает `tasks/get`, `tasks/update` (ack), `tasks/cancel`. Task store — in-memory pool, НЕ durable.
- **R5.4 — apply_proposal**: отдельный tool `apply_proposal(request_id, workspace_ref)` с MRTR elicitation подтверждением (`Resolve`/`Elicit`, `ElicitationResult` union; decline/cancel не применяют). `DelegationService.apply` находит terminal proposal из idempotency-кэша, перевалидирует (`stale_workspace` при расхождении), применяет `apply_patch`, прогоняет allowlisted checks и откатывает при failure.
- **Поддержка**: `worker_pool._Job` получил `created_at`/`updated_at`; `service._CachedResult` хранит `request`; `controller.run_post_apply_checks` вынесен в модульную функцию для переиспользования.
- **R6 fairness** решено НЕ реализовывать round-robin: одна GPU = одна модель, смена последовательная (см. ROADMAP примечание).

## Проверенные факты SDK (mcp==2.0.0), важные для продолжения

- `mcp.types.CreateTaskResult`/`GetTaskResult`/`Task` помечены "2025-11-25 only": это **старый** shape (`task` nested, `ttl`/`pollInterval` required), НЕ dispatchable и НЕ то, что шлёт современная Tasks extension (SEP-2663, ext-tasks repo). Современный wire shape — **flat** `Task` (`taskId`, `status`, `createdAt`, `lastUpdatedAt`, `ttlMs`, `pollIntervalMs`), `CreateTaskResult = Result & Task`, `GetTaskResult = Result & DetailedTask` (`resultType:"complete"`).
- Поэтому `tasks/get` в тестах парсится кастомной flat-моделью, а не `mcp.types.GetTaskResult` (у него `ttl` required).
- `intercept_tool_call` short-circuit dict с `resultType:"task"` доезжает до клиента целиком (sieve пропускается для modern extension-тегов, проверено эмпирически probe'ом).
- Client-claim: `ResultClaim(result_type="task", model=<Result subclass с result_type: Literal["task"]>)`; `resolve` возвращает `CallToolResult`. Либо `session.call_tool(..., allow_claimed=True)`.
- `require_client_extension` поднимает `-32021` (не `-32003` — номер кода изменился в mcp 2.0.0).
- Resolver-annotations обязаны быть на module-level (SDK делает `inspect.signature(eval_str=True)`), иначе `InvalidSignature`. `Elicit`-resolver принимает `ctx: Context`; возвращает `Elicit[T]`; tool принимает `Annotated[ElicitationResult[T], Resolve(fn)]`.
- Client elicitation_callback должен быть `async`.

## Остаточные задачи (следующие)

1. **Durable task store**: сейчас task state in-memory в `BoundedWorkerPool`; после перезапуска процесса task handle теряется. Отдельный gate (см. MCP_DESIGN R5.3).
2. **Loop reliability 0%** (из прошлой сессии, не тронут): модели предлагают edits, но не закрывают цикл чистым финальным JSON.
3. **Quant A/B** заблокирован памятью машины.
4. **Live apply с реальной моделью** не перезапускался (все apply-тесты на заглушках).

## Ключевые файлы

- `local_coding_agent/tasks.py` — TasksExtension, `task_dict`, `UpdateTaskParams`.
- `local_coding_agent/mcp_server.py` — `build_server(enable_tasks=...)`, `apply_proposal` tool, `_resolve_apply`.
- `local_coding_agent/service.py` — `DelegationService.apply`.
- `local_coding_agent/controller.py` — `run_post_apply_checks` (module-level).
- `local_coding_agent/worker_pool.py` — `created_at`/`updated_at` в snapshots.
- `tests/test_tasks.py` — contract tests tasks lifecycle + apply elicit.
- `tests/test_service.py` — `DelegationServiceApplyTests`.

## Предыдущий контекст (кратко)

R7 (атомаризация), R8 (retries/escalation), R9 (SEARCH/REPLACE) закрыты в прошлых сессиях. Вторая волна моделей импортирована в Ollama (кроме Muse Glimmer и OOM-моделей >17GB). Главный нерешённый результат прошлой сессии — SEARCH/REPLACE поднял correctness (iq2 0→75%, qwen3-8b 0→50%), но loop reliability остался 0% у всех.
