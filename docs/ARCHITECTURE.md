# Architecture

## Роли

### Codex controller

Главный управляющий слой. Он выбирает модель, собирает контекст, выдаёт инструменты, применяет политики и проверяет результат.

### Local model executor

Локальная модель Ollama. Она читает разрешённые данные, делает рассуждение и предлагает изменение через инструменты.

### Repository tools

Узкие операции с явными ограничениями:

- 'list_files' — только внутри рабочей области;
- 'read_file' — только allowlist;
- 'search_text' — ограниченный поиск;
- 'propose_patch' — вернуть diff без записи;
- 'apply_patch' — только после проверки контроллера;
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
    G --> H["Validate scope and diff"]
    H --> I{"Checks required?"}
    I -- "yes" --> J["Run targeted checks"]
    I -- "no" --> K["Accept or reject"]
    J --> K
    K --> L["Result and audit log"]
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
- 'apply_patch' не вызывается напрямую локальной моделью в proposal-only режиме.
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
