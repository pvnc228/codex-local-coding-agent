# Roadmap

Дата: 2026-08-13.

Историческая летопись завершённых этапов (M0–M6) перенесена в [ROADMAP_HISTORICAL.md](ROADMAP_HISTORICAL.md). Этот файл — план вперёд, отсортированный по приоритету.

Приоритеты согласованы с реализационным аудитом [AUDIT.md](AUDIT.md) и повторным review всего проекта 2026-08-13. Порядок — это оценка, а не обещание; номера первого аудита указаны в скобках.

## Gate перед следующим функциональным этапом

Статус review: предыдущий review закрыл базовые P0/P1/P2, но повторный review выявил отдельные P1/P2 в R5.3/R5.4. Первый repair gate и дополнительный self-review hardening документированы в [SESSION-2026-08-14-R5.3-R5.4-REPAIR.md](SESSION-2026-08-14-R5.3-R5.4-REPAIR.md). Предыдущий gate прошёл `170/170`; текущий hardening gate с `mcp==2.0.0` прошёл `178/178`, `compileall` и `git diff --check`.

Реализационные требования review ниже закрыты кодом и regression tests. R4 получил свежий внешний artifact, однако loop reliability остался нулевым у всех профилей:

- benchmark-oracle исполняет модельный код только в отдельном ограниченном процессе, а не через `exec` в процессе контроллера;
- `status`, `validation`, `audit` и `applied` принадлежат контроллеру и не могут быть подменены финальным JSON модели;
- mediated apply связывает acceptance с проверками уже применённого состояния либо явно возвращает непроверенный applied-результат;
- stdout/stderr тестового процесса читаются без pipe deadlock и обрезаются без посимвольного O(n²) цикла;
- cancellation не зависает, если завершение process tree запрещено или завершается ошибкой;
- публичная документация не ссылается на gitignored evidence как на доступный артефакт.

## R1 — Закрыть реализационные дыры безопасности и бюджета

Статус: реализация доставлена в `main`; свежий model runtime не запускался.

Цель: вернуть инварианты «контекст ограничен allowlist» и «контекст ограничен лимитом токенов» к фактическому поведению.

- ограничить `list_files` тем же allowlist, что `read_file`/`search_text` (AUDIT #1);
- добавить кумулятивный контекстный бюджет поверх накопленных tool-results, а не только стартового envelope (AUDIT #3);
- сделать `git` явным требованием в README или graceful fallback, когда его нет (AUDIT #2);
- прерывать блокирующие вызовы (`model.chat`, `run_tests`) по cancellation (AUDIT #4).

## R2 — Устойчивость и качество протокола

Статус: реализация доставлена в `main`; свежий model runtime не запускался.

Цель: убрать хрупкость, которая сейчас даёт `0%` loop reliability.

- пересмотреть строковую сверку evidence на структурную, не ослабляя анти-fabrication (AUDIT #5);
- pre-read лимит для `search_text`, чтобы огромный allowlisted-файл не стал DoS (AUDIT #6);
- убрать дублирование и O(n²) обрезки вывода (AUDIT #7);
- закрыть обход duplicate-call guard через дефолт `path` в `list_files` (AUDIT #8);
- пересмотреть case-insensitive allowlist на case-sensitive файловых системах (AUDIT #9).

## R3 — Mediated apply

Статус: реализация и review fixes доставлены в `main`; свежий live apply не запускался.

Цель была: следующее крупное направление после закрытия R1/R2.

- применить patch к workspace только после отдельного подтверждения контроллера — opt-in реализован через `--apply`, post-apply checks и rollback добавлены, runtime evidence после review ещё не повторён;
- `apply_patch` остаётся недоступным локальной модели напрямую — реализовано: `apply_patch` — controller-only seam, модель его не получает;
- сохранить proposal-only как режим по умолчанию — реализовано: без `--apply` изменений на диск не производится;
- перезаписывать controller-owned поля результата независимо от одноимённых полей модели — реализовано;
- после apply запускать allowlisted checks на изменённом workspace и откатывать patch при failure — реализовано.

## R4 — Повторный benchmark и evidence

Статус: post-review runtime baseline сохранён локально в `.codex-run/benchmarks/post-review-20260813.json`; runtime artifact gitignored и не является опубликованным evidence.

Цель была: получить ненулевые correctness/loop-reliability после R1/R2.

- повторить benchmark на тех же fixtures и параметрах — реализовано;
- зафиксировать новый runtime artifact — реализовано: `.codex-run/benchmarks/latest.json`;
- пересмотреть shortlist только на основании внешнего oracle — предварительно выполнено;
- вынести исполнение предложенного моделью Python из процесса benchmark — реализовано через restricted child process;
- учитывать совместимый JSON tool call из `message.content` при сохранении fallback proposal — реализовано;
- публиковать воспроизводимое evidence или явно маркировать локальные gitignored ссылки как недоступные читателю репозитория — локальные артефакты явно помечены как недоступные читателю репозитория.

## R4.1 — Quantization A/B и расширенный shortlist

Цель: проверить гипотезу, что агрессивный IQ2 повреждает coding/tool качество сильнее, чем уменьшение числа параметров при Q6/Q8.

Полный план, приоритеты, источники и gates находятся в [MODEL_EVALUATION_PLAN.md](MODEL_EVALUATION_PLAN.md).

- сначала сравнить Qwen3-Coder `UD-IQ2_M` и `UD-Q4_K_XL` из одного pinned revision;
- отдельно провести product race с Qwen3-8B Q6, Qwen2.5-Coder-14B Q6, Muse Glimmer Q4 и Nemotron MXFP4_MOE;
- расширить benchmark минимум до 20 задач и 3 повторов;
- сохранить source revision, SHA-256, model digest, generation profile, RAM/VRAM и внешний oracle в artifact;
- не смешивать quant A/B с model-native reasoning/sampling lane.

Критерии приёмки:

- ноль unsafe/unauthorized tool calls;
- correctness подтверждена только внешним oracle;
- IQ2/Q4 отличаются только квантом и проверяются на одном controller commit;
- новый рейтинг публикуется только после полного artifact, а не по model cards или smoke.

## Требования, извлечённые из продуктового обсуждения

Здесь зафиксированы только требования владельца проекта. Ответы другой модели не считаются архитектурным решением или evidence.

- дорогой агент формулирует задачу и проверяет результат, а локальная модель выполняет bounded coding-работу;
- интеграция должна быть harness-agnostic и не зависеть от одного поставщика агентов;
- один локальный model runtime должен обслуживать несколько логических кодеров через ограниченную очередь;
- слабые модели должны получать более атомарные задачи и конкретный feedback между попытками;
- после ограниченного числа неудач управление возвращается дорогому агенту, который решает, писать ли код самостоятельно;
- почти нулевая correctness в текущем benchmark — причина улучшать протокол и качество evidence, а не обходить oracle.

## R5 — Harness-agnostic core и адаптеры

Цель: отделить controller API от способа подключения к внешнему агенту.

Статус: R5.1 direct Python seam, первый R5.2 process-bound JSONL stdio slice, R5.2 official-SDK MCP stdio server (`mcp==2.0.0`, `2026-07-28` stateless + dual-era), R6 bounded in-memory worker-pool slice, R5.3 Tasks extension и R5.4 `apply_proposal` реализованы и покрыты contract tests. Repair gate R5.3/R5.4 закрывает найденные wire/policy/async/evidence gaps. Durable (disk-backed) task store и model-specific scheduling остаются отдельными gates.

Принятое направление и границы MCP `2026-07-28` зафиксированы в [MCP_DESIGN.md](MCP_DESIGN.md).

- определить стабильный transport-neutral request/result contract поверх `TaskEnvelope` и controller-owned result;
- оставить bounded controller единственным владельцем policy, validation и audit;
- добавить минимальный Python SDK/tool seam для прямого in-process вызова;
- проектировать MCP и framework-specific skill/tool wrappers как тонкие адаптеры к одному core, без копирования policy logic;
- начать с local `stdio` и одного proposal-only tool `delegate_code`;
- использовать официальное Tasks extension только после явного capability opt-in клиента;
- не строить новую реализацию на deprecated Roots, Sampling, Logging или legacy HTTP+SSE;
- не передавать локальной модели credentials или неограниченный callback внешнего агента.

Критерии приёмки:

- один contract test запускает одинаковую задачу через direct adapter и как минимум один process-bound adapter;
- результаты имеют одинаковые статусы, audit semantics и policy errors;
- modern и legacy MCP clients получают совместимые, явно согласованные result shapes;
- отключение адаптера не меняет core controller.

R5.2 first slice доставлен: `StdioDelegationAdapter` принимает ограниченный UTF-8 JSONL request только для `delegate_code`, строит тот же `DelegationRequest` и возвращает тот же controller-owned result. Contract test сравнивает direct вызов и настоящий дочерний process.

R5.2 (official SDK) доставлен: `mcp_server.build_server` строит `delegate_code` поверх pinned official `mcp==2.0.0`, который говорит на stateless `2026-07-28` (per-request `_meta`, `server/discover`, `resultType`) и авто-fallback на legacy `initialize` через `serve_dual_era_loop`. `mcp` — опциональная зависимость (`pyproject.toml`, extra `mcp`), core остаётся stdlib-only. Contract tests прогоняют in-process `Client` и process-bound adapter. Tasks extension, durable state и apply-proposal остаются отдельными gates до своих repair points ниже.

R5.3 (Tasks extension) доставлен: `local_coding_agent/tasks.py` реализует `TasksExtension` (`io.modelcontextprotocol/tasks`) поверх `BoundedWorkerPool`. `intercept_tool_call` коротко-замыкает `delegate_code` и возвращает `CreateTaskResult` (`resultType: "task"`) только когда клиент заявил extension в capabilities; без opt-in вызов остаётся синхронным. Extension обслуживает `tasks/get`, `tasks/update` (ack) и `tasks/cancel`; task state — in-memory в pool (не durable disk). Contract tests прогоняют полный lifecycle `working → completed` через in-process `Client` с claim. Durable store остаётся отдельным gate.

R5.4 (explicit apply) доставлен: `apply_proposal(request_id, workspace_ref)` — отдельный tool, НЕ поле в `delegate_code`. Подтверждение — Multi Round-Trip Request elicitation (`Resolve`/`Elicit`, `ElicitationResult` union; decline/cancel не применяют). `DelegationService.apply` находит сохранённый terminal proposal, перевалидирует patch против текущего workspace (`stale_workspace` при расхождении), применяет, прогоняет allowlisted checks и откатывает patch при failure. Contract tests покрывают apply, decline, stale-workspace и rollback.

### R5.3/R5.4 repair gate — Tasks conformance, explicit apply boundary, bounded evidence

Статус: завершено 2026-08-14; полный gate `170/170` с `mcp==2.0.0`. Этот пункт закрывает замечания повторного review, а не объявляет новый live Ollama/model benchmark.

- terminal `tasks/get` возвращает исходный `CallToolResult` wire-shape; controller failure — completed task с `isError: true`, а неизвестный `taskId` — JSON-RPC `-32602` для get/update/cancel;
- `TaskBudget` обязателен на public service/controller seams, non-empty apply требует минимум один targeted check, а confirmation показывает request id, workspace, summary, files и diff;
- sync service/apply calls вынесены из async MCP handlers; external runner является владельцем checks/evidence, rollback failure явно помечает `workspace_modified`;
- SEARCH/REPLACE final newline, bounded child-process output, conservative VRAM calibration и pinned `mcp==2.0.0` исправлены и покрыты regression/contract tests;
- детали и границы evidence находятся в [SESSION-2026-08-14-R5.3-R5.4-REPAIR.md](SESSION-2026-08-14-R5.3-R5.4-REPAIR.md). Durable store, real Ollama benchmark, live apply и reconnect после restart остаются отдельными gates.

### R5.3/R5.4 self-review hardening — fail-closed confirmation and concurrency

Статус: завершено 2026-08-14; `178/178` с `mcp==2.0.0`. Пункт добавлен после повторной проверки по `code-review-expert` и закрывает выявленные P1/P2/P3, не расширяя scope до live Ollama или durable Tasks.

- `apply_proposal` теперь требует строгую preview: accepted proposal, непустой patch, request/workspace identity и SHA-256 digest канонического preview; preview failure и mismatch не вызывают `service.apply`;
- sync MCP compatibility path и mediated apply используют bounded admission gate (`max_workers + max_queue`) и возвращают `queue_overload` вместо unbounded pending work;
- Tasks, legacy sync и mediated apply теперь используют единый `SharedExecutionGate`: общий admission учитывает смешанные клиенты, active slot удерживается до `completion_event`, а queued Tasks освобождают lease при cancel/shutdown;
- `DelegationService.apply` сериализует весь check/apply/post-check/rollback pipeline отдельным lock для каждой зарегистрированной workspace;
- `calibrate_for_model` валидирует параметры до source shortcut и использует один `/api/ps` snapshot для footprint и других loaded models; unreachable failed-task branch удалён;
- regression tests покрывают wrong digest, preview failure, queue overload, workspace serialization, invalid calibration inputs и single-snapshot consistency. Durable store, real Ollama benchmark, live apply и reconnect после restart остаются отдельными gates.

R6 first slice доставлен: `BoundedWorkerPool` ограничивает worker slots и queued jobs, возвращает bounded `queue_overload`, сохраняет caller-scoped idempotency, изолирует concurrent request state и поддерживает queued/running cooperative cancellation; при отмене физический model-call slot удерживается до завершения executor. Это in-memory execution primitive; durable task store, timeout policy, fairness и Ollama-specific scheduling остаются отдельными gates.

## R6 — Bounded worker pool поверх одного model runtime

Статус: first in-memory execution slice реализован; полный worker/runtime gate ещё не закрыт.

Цель: несколько логических локальных кодеров без обещания «бесконечной» физической параллельности.

- очередь задач с явными `max_workers`, `max_queue`, timeout и cancellation;
- изоляция task state, tool-call history, workspace и audit между workers;
- сериализация либо ограниченная конкурентность запросов к одной модели согласно фактической способности Ollama;
- backpressure вместо неограниченного создания workers;
- VRAM policy и fairness, чтобы одна задача не удерживала модель или очередь бесконечно.

Примечание (2026-08-14): fairness в смысле round-robin между model profiles НЕ реализуется в MVP. На одной GPU Ollama держит одну модель в VRAM; смена модели строго последовательная. Запрос с незагруженной моделью отклоняется/ждёт, а не конкурирует за слот с загруженной. При необходимости round-robin scheduler — отдельный gate.

Критерии приёмки:

- concurrency-тест доказывает отсутствие смешивания context/audit двух задач;
- overload-тест возвращает bounded rejection, а не растит память;
- cancellation queued и running задач имеет внешнее runtime evidence.

## R7 — Атомаризация задач

Статус: реализация и regression gate проверены; предыдущий live model oracle не прошёл correctness. `local_coding_agent/atomizer.py` добавляет формальный `TaskBudget` (files/context-bytes/checks), детерминированный `preflight` с machine-readable причинами (`too_many_files`, `context_too_large`, `too_many_checks`) и `decompose`, который делит широкую задачу только по files на `ceil(N/max_files)` непрерывных children — каждый child не получает больше files/checks, чем явно разрешил родитель, а context/checks сверх бюджета детерминированно отклоняются (`ValueError`). `DelegationService` принимает bounded `preflight_budget` и отклоняет широкую задачу policy failure `preflight_rejected` до запуска модели. Публичный seam экспортирован в `__init__`.

Live evidence 2026-08-13 (`python .codex-run/live_check_r7_r8.py`, gitignored): preflight и decompose детерминированно прошли (6 files → `too_many_files`; 7 files → 3 bounded children `wide#1..3`). Live-орacle на атомаризованном ребёнке `src/unique.py` не дал корректного патча: `qwen2.5-1.5b` вернул `patch is not a unified diff` — это дефект качества модели (совпадает с 0% correctness полного benchmark), а не баг механизма атомаризации. Полное benchmark-сравнение исходной и атомаризованной постановки на внешнем oracle остаётся отдельным gate.

Цель: повышать шанс слабой модели за счёт меньшего и проверяемого task envelope.

- формальный бюджет задачи: файлы, строки/байты контекста, один ожидаемый эффект и targeted check;
- preflight, который отклоняет слишком широкую задачу с machine-readable причиной;
- decomposition contract возвращает дочерние envelopes, но не даёт локальной модели самой расширять allowlist;
- acceptance каждого шага проверяется отдельно; следующий шаг не наследует неподтверждённый diff.

Критерии приёмки:

- набор широких задач стабильно раскладывается в bounded envelopes либо детерминированно отклоняется;
- ни один дочерний envelope не получает больше файлов или checks, чем явно разрешил родитель;
- benchmark сравнивает исходную и атомаризованную постановку на одинаковом внешнем oracle.

## R8 — Ограниченные retries и escalation

Статус: реализация и scripted runtime evidence проверены; live model benchmark не повторялся. `Controller.max_retries` получил hard cap 10 (сверх — `ValueError`). Оба retry-пути (`invalid_response`/`invalid_json`) ведут учёт попыток (`attempts`), фиксируют просмотренные файлы (`viewed_files`) и последний предложенный patch (`last_patch`) и после исчерпания бюджета возвращают escalation bundle: task envelope, попытки с machine-readable причинами, просмотренные файлы, последний patch и внешнее evidence проверок; итоговое исчерпание `max_turns` при наличии попыток также возвращает escalation (`reason="max_turns"`). Повторный одинаковый tool call и cancellation сохраняют приоритет над retry budget.

Live evidence 2026-08-13 (scripted model, `python .codex-run/live_check_r7_r8.py`, gitignored): `max_retries=3` + 4 невалидных JSON-ответа дали ровно 4 model request и `attempts=[1..4]` (off-by-one отсутствует); escalation bundle корректно несёт task id/files и пустые `viewed_files`/`external_evidence`; duplicate tool call → `duplicate_tool_call`, pre-set cancel → `cancelled`, оба без escalation. Live oracle-доказательство «ровно заданного числа попыток» на реальной модели заменено scripted-model evidence, поскольку реальные локальные модели не доводят цикл до исчерпания retry бюджета на этом наборе.

Цель: после нескольких содержательно разных попыток вернуть управление дорогому агенту без бесконечного tool-loop.

- configurable retry budget с безопасным default и hard cap не выше 10;
- новая попытка разрешена только после machine-readable failure и изменённого feedback/context;
- одинаковый tool call по-прежнему немедленно останавливает текущий цикл;
- после исчерпания бюджета controller возвращает escalation bundle: task, просмотренные файлы, последние patch/validation issues, external evidence и риски;
- дорогой агент, а не локальная модель, решает: уточнить задачу, выбрать другую модель или написать код самостоятельно.

Критерии приёмки:

- oracle доказывает ровно заданное число попыток без off-by-one;
- repeated-call и cancellation имеют приоритет над retry budget;
- fallback не применяет patch и не заявляет checks без нового внешнего evidence;
- audit однозначно связывает каждую попытку с причиной и итоговой escalation.

## R9 — SEARCH/REPLACE как альтернативный формат изменения

Статус: реализовано и покрыто regression-тестами; live benchmark на новых моделях ещё не повторён.

Цель: убрать барьер unified diff, из-за которого слабые/сильно квантованные модели дают 0% correctness. Генерация валидного unified diff (номера строк, hunk-заголовки, `+`/`-`) — одна из самых сложных задач для локальных моделей; SEARCH/REPLACE требует только скопировать старый код и написать новый.

- `propose_patch` и финальный кандидат принимают либо `patch` (unified diff), либо `edits` (список `{"file", "search", "replace"}`), но не оба;
- `search` обязан совпадать с текущим содержимым файла ровно один раз и на границе строк; иначе кандидат отклоняется machine-readable (`not found` / `ambiguous` / `not line-aligned` / `allowlist`);
- controller сам конвертирует `edits` в unified diff через `resolve_edits`/`_build_edit_diff`, поэтому модель не считает номера строк;
- тот же `git apply --check` остаётся источником истины применимости; allowlist, размер и external evidence не ослаблены;
- benchmark-judge принимает edit-proposal как fallback (аналог content tool-call).

Критерии приёмки:

- `search` не найден / неоднозначен / вне allowlist → отклонение, а не ложное принятие;
- edit-proposal проходит те же проверки применимости и не пишет в workspace до `--apply`;
- benchmark-задача, решённая через `edits`, получает `correct=true` на внешнем oracle.

## Вне MVP

- автоматические commit, push, публикация;
- автономная разработка большой функции;
- постоянная память локальной модели;
- неограниченное число физических workers без backpressure;
- автоматическая отправка задачи во внешний платный API из локального controller core.
