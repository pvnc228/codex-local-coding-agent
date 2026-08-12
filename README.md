# Codex Local Coding Agent

Исследование shortlist локальных моделей, SHA-256 и проверенный импорт GGUF в Ollama: [docs/MODEL_RESEARCH.md](docs/MODEL_RESEARCH.md).

Небольшой контроллер для делегирования атомарных coding-задач локальным моделям Ollama.

Большая модель формулирует задачу и контролирует результат, а локальная модель выполняет ограниченную работу: читает разрешённые файлы, ищет нужный код, предлагает diff и запускает заранее разрешённую проверку.

## Что уже умеет проект

- отправлять запросы в Ollama через `/api/chat` в UTF-8;
- работать с профилями `bonsai-64k`, `qwen2.5-coder` и `qwen2.5-1.5b`;
- запускать единый proposal-only benchmark для Bonsai, Qwen coder и импортированных research-профилей;
- ограничивать модель явным списком файлов и размером контекста;
- предоставлять только bounded tools:
  - `list_files`;
  - `read_file`;
  - `search_text`;
  - `propose_patch`;
  - allowlisted `run_tests`;
- проверять unified diff и список изменённых файлов до принятия результата;
- подтверждать тесты только по evidence внешнего runner-а;
- останавливать tool-loop по лимиту ходов, повторному вызову или cancellation;
- смотреть состояние загруженных моделей и управлять их VRAM;
- работать в proposal-only режиме: файлы не изменяются локальной моделью.

## Безопасные границы

Локальная модель не получает произвольный shell-доступ и не может сама применить patch. Команды проверки берутся из task envelope, а не из свободного текста модели. Пути проверяются относительно workspace, результаты инструментов ограничиваются по размеру, а повторный одинаковый tool call завершает задачу со статусом `failed`.

Проект не пытается заменить полноценный Codex или человека на больших задачах. В текущем MVP нет автономной разработки всей функции, постоянной памяти модели, автоматических commit/push и mediated apply.

## Требования

- Windows, Linux или macOS;
- Python 3.10 или новее;
- Ollama с доступным HTTP endpoint, по умолчанию `http://127.0.0.1:11434`;
- установленная модель с поддержкой chat/tool calls.

Проект использует только стандартную библиотеку Python и не требует установки Python-зависимостей.

## Быстрый старт

Проверь, что Ollama запущен и модель доступна:

```powershell
ollama list
```

Запусти встроенные тесты:

```powershell
py -m unittest discover -s tests -v
```

Посмотри доступные параметры CLI:

```powershell
py -m local_coding_agent --help
```

## Task envelope

Контроллер принимает UTF-8 JSON с одной атомарной задачей. Минимальный пример:

```json
{
  "id": "read-one",
  "goal": "прочитать разрешённый файл и вернуть результат",
  "files": ["src/example.py"],
  "context": "Краткий контекст, необходимый для задачи.",
  "constraints": [
    "не менять публичную сигнатуру"
  ],
  "checks": [],
  "acceptance": [
    "прочитан только файл из allowlist"
  ]
}
```

Для задачи с изменением файла команда проверки должна быть записана в `checks` заранее:

```json
{
  "id": "unique-preserve-order",
  "goal": "убрать сортировку из unique и сохранить порядок первого появления",
  "files": ["src/unique.py"],
  "checks": ["py -m unittest tests.test_unique -v"],
  "constraints": ["не добавлять зависимости"],
  "acceptance": ["diff меняет только src/unique.py", "targeted test passed"]
}
```

Запуск из корня workspace:

```powershell
py -m local_coding_agent `
  --task task.json `
  --workspace . `
  --profile qwen2.5-1.5b `
  --num-ctx 4096
```

Результат содержит статус, summary, предложенный patch, checks, risks, validation report и audit events.

Возможные статусы:

- `accepted` — структурированный результат прошёл проверки;
- `rejected` — результат нарушил контракт или validation rules;
- `needs_context` — контекст задачи превышает установленный лимит;
- `failed` — ошибка модели, инструмента, проверки, cancellation или tool-loop.

## Профили и контекстное окно

Доступные профили:

| Профиль | Модель Ollama | Значение `num_ctx` по умолчанию | Максимум модели |
| --- | --- | ---: | ---: |
| `qwen2.5-1.5b` | `qwen2.5:1.5b` | 4096 | 32768 |
| `qwen2.5-coder` | `qwen2.5-coder:latest` | 8192 | 32768 |
| `bonsai-64k` | `bonsai-64k:latest` | 8192 | 262144 |

Исследовательские профили: `ornith-9b`, `qwen3-coder-30b`, `devstral-small-2-24b`, `ternary-bonsai-27b`. Последний профиль оставлен для availability check, но GGUF пока не импортируется в текущем Ollama.

## Benchmark моделей

Запуск из корня workspace:

```powershell
py -m local_coding_agent `
  --benchmark `
  --num-ctx 4096 `
  --benchmark-timeout-seconds 600 `
  --benchmark-output .codex-run/benchmarks/latest.json
```

Можно выбрать один профиль повторяемым параметром `--benchmark-model`. Результат сохраняется как UTF-8 JSON с audit trail, patch proposals, внешним correctness oracle и Ollama token/latency metrics. Методика и первый runtime result находятся в [docs/BENCHMARK.md](docs/BENCHMARK.md).

Размер окна можно изменить параметром `--num-ctx`. Контроллер отклоняет нулевые, отрицательные и превышающие лимит модели значения.

## Управление VRAM Ollama

Посмотреть и выгрузить все модели:

```powershell
py -m local_coding_agent --unload-all
```

Выгрузить одну модель:

```powershell
py -m local_coding_agent --unload-model bonsai-64k:latest
```

Удержать VRAM в заданном бюджете и не выгружать выбранную модель:

```powershell
py -m local_coding_agent `
  --vram-limit-bytes 5000000000 `
  --keep-model qwen2.5:1.5b
```

Состояние берётся из Ollama `/api/ps`, включая фактическое поле `size_vram`. Выгрузка выполняется запросом с `keep_alive: 0`. Если защищённые модели сами превышают бюджет, операция завершается ошибкой, а не выгружает их молча.

## Архитектура

| Файл | Назначение |
| --- | --- |
| `local_coding_agent/ollama_adapter.py` | HTTP adapter Ollama, профили параметров, unload и нормализация ошибок |
| `local_coding_agent/task.py` | валидация task envelope и относительных путей |
| `local_coding_agent/repository_tools.py` | bounded repository tools и audit events |
| `local_coding_agent/controller.py` | tool-loop, retry, cancellation и duplicate-call guard |
| `local_coding_agent/validators.py` | schema, unified diff, allowlist и check evidence |
| `local_coding_agent/memory.py` | snapshot, выгрузка моделей и VRAM budget policy |
| `local_coding_agent/profiles.py` | именованные профили локальных моделей |
| `local_coding_agent/cli.py` | proposal-only CLI |

Подробные контракты находятся в документации:

- [PROJECT.md](PROJECT.md) — цель и границы проекта;
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — компоненты и поток выполнения;
- [PROTOCOL.md](docs/PROTOCOL.md) — протокол общения с Ollama;
- [ROADMAP.md](docs/ROADMAP.md) — этапы развития;
- [ROADMAP_HISTORICAL.md](docs/ROADMAP_HISTORICAL.md) — историческая летопись M0–M6;
- [AUDIT.md](docs/AUDIT.md) — аудит реализации;
- [AGENTS.md](AGENTS.md) — правила работы с checkout.

## Проверка проекта

Полный локальный test gate:

```powershell
py -m unittest discover -s tests -v
py -m compileall -q local_coding_agent tests
git diff --check
```

Текущий набор содержит 45 тестов. Live smoke с Ollama выполняется отдельно, потому что наличие модели, её загрузка и фактическая VRAM зависят от локальной машины.

## Статус

Рабочий MVP опубликован в [pvnc228/codex-local-coding-agent](https://github.com/pvnc228/codex-local-coding-agent).

Следующее крупное направление — mediated apply после отдельного подтверждения; protocol-facing blockers и isolated test process уже покрыты тестами и runtime evidence.
