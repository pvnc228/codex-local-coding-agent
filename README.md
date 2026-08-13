# Codex Local Coding Agent

Исследование shortlist, SHA-256 и проверенный импорт GGUF: [docs/MODEL_RESEARCH.md](docs/MODEL_RESEARCH.md). Следующий quantization A/B и новые модели: [docs/MODEL_EVALUATION_PLAN.md](docs/MODEL_EVALUATION_PLAN.md). Архитектурное решение для MCP `2026-07-28`: [docs/MCP_DESIGN.md](docs/MCP_DESIGN.md).

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
- вызывать тот же controller через transport-neutral Python API с зарегистрированным `workspace_ref`, allowlisted profile и caller-scoped idempotency.
- принимать тот же proposal-only `delegate_code` через bounded UTF-8 JSONL process-bound adapter.
- ставить proposal-only delegations в bounded in-memory worker pool с caller-scoped job state и cancellation.
- отклонять слишком широкую задачу до запуска модели через preflight budget (`TaskBudget`/`preflight`) и детерминированно раскладывать её по files через `decompose` без расширения allowlist.
- ограничивать retry budget (hard cap 10) и после исчерпания возвращать escalation bundle с просмотренными файлами, попытками и внешним evidence вместо бесконечного tool-loop.

## Безопасные границы

Локальная модель не получает произвольный shell-доступ и не может сама применить patch. Команды проверки берутся из task envelope, а не из свободного текста модели. Пути проверяются относительно workspace, результаты инструментов ограничиваются по размеру, а повторный одинаковый tool call завершает задачу со статусом `failed`.

Проект не пытается заменить полноценный Codex или человека на больших задачах. В текущем MVP нет автономной разработки всей функции, постоянной памяти модели и автоматических commit/push. Proposal-only остаётся режимом по умолчанию; mediated apply — opt-in через `--apply`.

## Требования

- Windows, Linux или macOS;
- Python 3.10 или новее;
- Ollama с доступным HTTP endpoint, по умолчанию `http://127.0.0.1:11434`;
- установленная модель с поддержкой chat/tool calls;
- git в `PATH` (для проверки применимости patch через `git apply --check`).

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
  --num-ctx 4096 `
  --apply
```

`--apply` включает mediated apply: принятый patch применяется к workspace после валидации. Без него режим остаётся proposal-only, и файлы не изменяются.

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

## Direct Python API

R5.1 добавляет transport-neutral seam для host-ов до появления MCP. Хост сам регистрирует рабочие области, а запрос не принимает произвольный путь, endpoint или `apply`:

```python
from local_coding_agent import DelegationRequest, DelegationService, TaskEnvelope

service = DelegationService({"repo": "."})
request = DelegationRequest(
    request_id="opaque-idempotency-key",
    workspace_ref="repo",
    model_profile="qwen2.5-1.5b",
    task=TaskEnvelope(id="read-one", goal="прочитать файл", files=("src/example.py",)),
)
result = service.delegate("trusted-host-process", request)
```

`request_id` идемпотентен внутри пары caller/workspace: точно такой же запрос, включая одновременный, ждёт и возвращает один terminal result; тот же ключ с другой нагрузкой — machine-readable `idempotency_conflict`. In-memory LRU-кэш bounded (по умолчанию 256 terminal results); reconnect, очередь и durable Tasks не входят в R5.1. Вызов всегда proposal-only: mediated apply остаётся отдельной CLI/controller operation и не открывается этому API.

### Process-bound stdio API

Запуск доверенным host-процессом из корня workspace:

```powershell
py -m local_coding_agent.stdio --workspace-ref repo --workspace .
```

Adapter читает UTF-8 JSONL из stdin и пишет UTF-8 JSONL в stdout. Поддерживается одна операция `delegate_code`; request передаётся в `params` в том же формате, что и `DelegationRequest`, а `caller_id` задаётся верхним полем сообщения. Размер строки ограничен 64 KiB, apply и произвольные shell/path/endpoint параметры отсутствуют. Это process-bound core slice, не полная modern/legacy MCP conformance.

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

## Документация

| Файл | Назначение |
| --- | --- |
| `local_coding_agent/ollama_adapter.py` | HTTP adapter Ollama, профили параметров, unload и нормализация ошибок |
| `local_coding_agent/task.py` | валидация task envelope и относительных путей |
| `local_coding_agent/repository_tools.py` | bounded repository tools и audit events |
| `local_coding_agent/controller.py` | tool-loop, retry, cancellation и duplicate-call guard |
| `local_coding_agent/service.py` | R5.1 direct proposal-only service, request parsing, workspace registry и idempotency |
| `local_coding_agent/stdio.py` | bounded UTF-8 JSONL process-bound `delegate_code` adapter |
| `local_coding_agent/worker_pool.py` | bounded in-memory delegation queue, job state и cooperative cancellation |
| `local_coding_agent/atomizer.py` | формальный task budget, preflight и детерминированная decomposition по files |
| `local_coding_agent/validators.py` | schema, unified diff, allowlist и check evidence |
| `local_coding_agent/memory.py` | snapshot, выгрузка моделей и VRAM budget policy |
| `local_coding_agent/profiles.py` | именованные профили локальных моделей |
| `local_coding_agent/cli.py` | proposal-only CLI и opt-in mediated apply |

Подробные контракты находятся в документации:


- [PROJECT.md](PROJECT.md) — цель и границы проекта;
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — компоненты и поток выполнения;
- [PROTOCOL.md](docs/PROTOCOL.md) — протокол общения с Ollama;
- [MODEL_RESEARCH.md](docs/MODEL_RESEARCH.md) — проверенные локальные GGUF, импорт и исторический shortlist;
- [MODEL_EVALUATION_PLAN.md](docs/MODEL_EVALUATION_PLAN.md) — quant A/B, новые кандидаты и будущий benchmark gate;
- [MCP_DESIGN.md](docs/MCP_DESIGN.md) — harness-agnostic MCP adapter, Tasks, compatibility и security boundaries;
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

Текущий набор содержит 88 тестов. Live smoke с Ollama и benchmark выполняются отдельно, потому что наличие модели, её загрузка и фактическая VRAM зависят от локальной машины.

## Статус

Рабочий MVP опубликован в [pvnc228/codex-local-coding-agent](https://github.com/pvnc228/codex-local-coding-agent).

Mediated apply работает opt-in через `--apply`: controller применяет patch только после валидации, повторно запускает checks и откатывает изменение при post-apply failure; модель напрямую применить patch не может. Review fixes смержены в `main`. R5.1 direct seam, первый process-bound stdio slice R5.2 и R6 bounded in-memory worker-pool slice реализованы; полноценный MCP adapter/conformance, durable Tasks store, fairness и Ollama-specific scheduling остаются следующими этапами.
