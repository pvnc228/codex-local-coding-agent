# Architecture

## Роли

### Codex controller

Главный управляющий слой. Он выбирает модель, собирает контекст, выдаёт инструменты, применяет политики и проверяет результат.

### Direct service seam (R5.1)

`DelegationService` — transport-neutral вход для доверенного host-процесса. Он разрешает только заранее зарегистрированный `workspace_ref` и имя из существующего списка model profiles, выполняет обязательный bounded `TaskBudget` preflight и затем запускает обычный `Controller` строго без `apply`. `request_id` атомарно резервируется внутри пары caller/workspace: параллельный повтор ждёт тот же terminal result, а другая нагрузка с тем же ключом отклоняется. In-memory LRU-кэш ограничен числом terminal results; durable state, очередь и reconnect относятся к последующим срезам.

### Process-bound stdio adapter (R5.2 first slice)

`StdioDelegationAdapter` — тонкий UTF-8 JSONL process boundary с одной операцией `delegate_code`. Он декодирует ограниченную строку, строит тот же `DelegationRequest` и передаёт её в `DelegationService`; он не владеет workspace registry, model allowlist, validation, audit или apply. Это process-bound seam для будущего MCP adapter, но не заявка на полную MCP conformance, Tasks или reconnect.

### Bounded worker pool (R6 first slice)

`BoundedWorkerPool` — in-memory execution layer поверх `DelegationService`. Он ограничивает число worker slots и ожидающих jobs, сохраняет caller-scoped idempotency и job state, изолирует request/result между workers и передаёт cooperative cancellation в controller. Общий `SharedExecutionGate` также синхронизирует Tasks, legacy MCP и mediated apply, поэтому смешанные клиенты не обходят общий `max_workers`/`max_queue`. При отмене slot удерживается до фактического завершения model-call executor. MCP Tasks lifecycle использует этот pool отдельным thin adapter; сам pool не является durable store и не выбирает Ollama scheduling policy.

### Local model executor

Локальная модель Ollama. Она читает разрешённые данные, делает рассуждение и предлагает изменение через инструменты.

### Repository tools

Узкие операции с явными ограничениями:

- 'list_files' — только внутри рабочей области;
- 'read_file' — только allowlist;
- 'search_text' — ограниченный поиск;
- 'propose_patch' — вернуть изменение без записи, либо как unified diff, либо как SEARCH/REPLACE-блоки (`edits`);
- 'apply_patch' — controller-only seam, не является tool-ом модели: применяется только после валидации и только при `--apply`;
- 'run_tests' — только allowlisted-команда.

## Поток

~~~mermaid
flowchart TD
    A["Task envelope"] --> B["Context packer"]
    B --> C["Ollama adapter"]
    C --> D{"Tool call?"}
    D -- "yes" --> E["Tool policy"]
    E --> F["Execute bounded tool"]
    F --> C
    D -- "no" --> G["Parse structured result"]
    G --> H["Validate scope, diff and evidence"]
    H --> I{"Candidate valid?"}
    I -- "no" --> L["Rejected result and audit log"]
    I -- "yes, proposal-only" --> L2["Accepted proposal and audit log"]
    I -- "yes, --apply" --> J["Controller applies patch"]
    J --> K["Re-run all targeted checks"]
    K --> M{"Post-apply checks pass?"}
    M -- "yes" --> L3["Accepted applied result and audit log"]
    M -- "no" --> R["Rollback patch"]
    R --> L
~~~

## Состояния задачи

~~~text
received
  -> context_ready
  -> awaiting_model
  -> tool_call
  -> awaiting_tool_result
  -> candidate_ready
  -> validating
  -> checking
  -> accepted | rejected | needs_context | failed
~~~

## Защитные границы

- Список файлов передаётся явно.
- Абсолютные пути отбрасываются или нормализуются внутри workspace.
- Размер tool-result ограничивается.
- Команды тестов берутся из конфигурации задачи, а не из свободного текста модели.
- `run_tests` непрерывно дренирует stdout/stderr через bounded collectors, чтобы verbose child не мог заблокировать controller на заполненном pipe или неограниченно разрастить временный sink.
- Завершение процесса и всего его дерева имеет bounded wait; ошибка termination не превращается в безлимитный `wait()`.
- 'apply_patch' не вызывается напрямую локальной моделью: это controller-only seam.
- Proposal-only является режимом по умолчанию; mediated apply — opt-in через `--apply`.
- При `--apply` targeted checks запускаются после изменения; `applied: true` выдаётся только после успешного post-apply результата, иначе patch откатывается.
- Non-empty apply отклоняется без хотя бы одного заранее allowlisted targeted check.
- `audit`, `validation` и `applied` принадлежат controller и не принимаются из model result.
- `checks`/`evidence` в принятом результате принадлежат внешнему runner-у; текст модели не является доказательством запуска.
- При повторном tool call с теми же именем и аргументами цикл завершается.
- После достижения 'max_turns' задача считается незавершённой.

## Модельный профиль

Профиль модели должен быть отдельной конфигурацией, а не зашитым условием:

~~~yaml
name: bonsai-64k
provider: ollama
model: bonsai-64k:latest
endpoint: http://127.0.0.1:11434
think: false
temperature: 0
num_ctx: 8192
num_predict: 512
keep_alive: 10m
max_context_length: 262144
~~~

## Управление VRAM и контекстом

`/api/ps` является источником фактического состояния загруженных моделей и их `size_vram`. `ModelMemoryManager` умеет снять snapshot, выгрузить одну или все модели и вытеснить незащищённые модели до явного VRAM-бюджета. Защита от неожиданной выгрузки задаётся списком `keep`.

`ModelProfile.num_ctx` задаёт окно контекста для запроса, а `max_context_length` ограничивает значение по возможностям конкретной модели. CLI пробрасывает настройку через `--num-ctx`.
