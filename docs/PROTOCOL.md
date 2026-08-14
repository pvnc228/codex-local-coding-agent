# Local model protocol

## Request envelope

Каждый запрос должен содержать:

- короткий system contract;
- task envelope;
- только нужные tools;
- ограничение контекста и output budget;
- 'stream: false' для MVP;
- 'think: false', если задача не требует отдельного reasoning trace.

Пример параметров Ollama:

~~~json
{
  "model": "bonsai-64k:latest",
  "stream": false,
  "think": false,
  "keep_alive": "10m",
  "options": {
    "temperature": 0,
    "num_ctx": 8192,
    "num_predict": 512
  }
}
~~~

Для немедленной выгрузки модели Ollama используется отдельный запрос `/api/generate` с `stream: false` и `keep_alive: 0`. Состояние и фактически занятая VRAM проверяются через `/api/ps`; поле `size_vram` не заменяется размером файла модели.

`options.num_ctx` задаёт размер контекстного окна конкретного запроса. Контроллер принимает это значение из профиля/CLI и отклоняет его, если оно меньше либо равно нулю или превышает `max_context_length` модели.

## System contract

~~~text
Ты локальный coding-subagent для одной атомарной задачи.
Работай только в пределах task envelope.
Не выдумывай отсутствующий контекст.
Не утверждай, что запускал тесты или менял файлы без результата инструмента.
Используй только предоставленные инструменты.
Если данных не хватает, задай один точный вопрос.
Патч должен быть минимальным и затрагивать только разрешённые файлы.
После завершения верни только структурированный результат.
~~~

## Tool loop

1. Отправить задачу и tools.
2. Если пришёл 'tool_calls', сохранить исходное assistant message без изменений.
3. Выполнить каждый tool call через policy layer.
4. Добавить ответ как 'role: tool' с соответствующим 'tool_name'.
5. Повторить запрос.
6. Завершить при финальном ответе, ошибке policy, повторе вызова или превышении 'max_turns'.

Рекомендуемые лимиты MVP:

- 'max_turns: 4';
- 'max_same_call: 1';
- 'max_tool_result_bytes: 32000';
- 'max_files: 5';
- 'max_patch_files: 2'.

`TaskBudget` является bounded preflight на public service/controller seams: по умолчанию ограничены files, context bytes и checks. Для non-empty patch `checks` должен содержать хотя бы одну заранее allowlisted targeted command.

## Финальный формат

~~~json
{
  "status": "candidate",
  "summary": "что изменено",
  "patch": "unified diff",
  "edits": [
    {"file": "src/unique.py", "search": "старый блок", "replace": "новый блок"}
  ],
  "checks": [
    {
      "command": "allowlisted command",
      "passed": false,
      "evidence": "внешний результат runner"
    }
  ],
  "risks": []
}
~~~

Кандидат содержит либо `patch`, либо `edits`, но не оба. `patch` — синтаксически корректный unified diff; `edits` — список SEARCH/REPLACE-блоков. Наличие текста в поле `patch` не означает, что это настоящий unified diff: он проверяется отдельно. Поле `checks` в controller-owned terminal result содержит только наблюдения внешнего runner-а; модель не может засчитать проверку одним текстом финального ответа.

### SEARCH/REPLACE (edits)

Для слабых и сильно квантованных моделей unified diff — одна из самых сложных задач (модель должна сама вычислять номера строк, hunk-заголовки и не путать `+`/`-`). Формат `edits` снимает эту сложность: модель копирует текущий код точно как есть в `search` и пишет новую версию в `replace`; номера строк не нужны.

Правила:

- каждый block — объект `{"file", "search", "replace"}`; `file` — относительный путь из allowlist;
- `search` обязан совпадать с текущим содержимым файла символ в символ, ровно один раз и на границе строк;
- если `search` не найден, встречается несколько раз или не выровнен по строкам — кандидат отклоняется с machine-readable причиной;
- controller сам преобразует каждый block в unified diff (`diff --git`/`---`/`+++`/`@@`), поэтому модель не генерирует hunk-заголовки;
- применимость проверяется `git apply --check` по полученному diff, как для обычного `patch`.

Формат `edits` не ослабляет allowlist, лимиты размера или external evidence: те же проверки применяются к разрешённому diff.

## Mediated apply

Модель только предлагает изменение через `propose_patch`; сама применить его не может. При запуске с `--apply` controller сначала валидирует и применяет patch во workspace, затем повторно запускает все allowlisted checks. Только после успешных post-apply checks результат получает `"applied": true`; при провале patch откатывается, а статус становится `rejected` с риском kind `post_apply_check_failed`. При ошибке самого применения используется риск kind `apply_failed`. По умолчанию (без `--apply`) режим — proposal-only: на диск ничего не пишется.

Инструмент `propose_patch` принимает либо полный unified diff с синтаксически корректными hunk headers, либо список SEARCH/REPLACE `edits`; `\n` внутри patch должен быть реальным переводом строки, а не двумя символами backslash и `n`. Validator проверяет структуру, allowlist и размер, а controller-owned `git apply --check` является источником истины для фактических hunk counts и применимости. До записи diff не модифицирует workspace. Non-empty mediated apply без хотя бы одного targeted check отклоняется до записи.

Если Ollama не возвращает native `tool_calls`, контроллер допускает совместимый JSON-объект в `message.content` только в форме `{"name":"...","arguments":{...}}`, после чего всё равно прогоняет вызов через ту же policy layer. `run_tests` передаётся модели только когда task envelope содержит allowlisted `checks`.

## Process-bound stdio adapter

`StdioDelegationAdapter` принимает по одной UTF-8 JSONL-команде на строку:

```json
{
  "method": "delegate_code",
  "caller_id": "trusted-host",
  "params": {
    "request_id": "opaque-idempotency-key",
    "workspace_ref": "registered-workspace-handle",
    "model_profile": "qwen2.5-1.5b",
    "task": {
      "id": "read-one",
      "goal": "прочитать разрешённый файл",
      "files": ["src/example.py"]
    }
  }
}
```

Адаптер возвращает одну UTF-8 JSONL-строку с тем же core result shape, что и `DelegationService`. Поддерживается только `delegate_code`; пустые строки пропускаются, request ограничен 64 KiB по умолчанию, а malformed JSON, invalid UTF-8, unknown method и oversized request получают machine-readable `failed` error. `caller_id` используется только как scope idempotency, а `workspace_ref` и `model_profile` всё равно проверяются service policy. Adapter не принимает `apply`, произвольный path, endpoint, command или credentials. Этот срез не утверждает modern/legacy MCP negotiation, Tasks, durable state или reconnect.

Allowlisted `run_tests` запускается в отдельном process group/session с урезанным environment: в дочерний процесс не передаются произвольные переменные окружения родителя. stdout/stderr сразу дренируются bounded collectors без неограниченного временного файла, а завершение process tree имеет bounded wait и явную ошибку при failure. Ответ содержит `isolated: true` как runtime evidence, если лимит результата позволяет сохранить эту метаинформацию; при предельно малом `max_tool_result_bytes` приоритет остаётся за `stdout`, `stderr` и `evidence`.

Поля `audit`, `validation`, `applied`, `post_apply_checks` и `error` являются controller-owned. Модель может предложить только candidate fields; её значения этих полей отбрасываются перед финальным результатом.

## Повторная попытка

Повтор разрешён только с конкретной причиной:

- invalid JSON;
- patch не парсится;
- изменён запрещённый файл;
- check failed;
- не хватает конкретного контекста.

Нельзя повторять тот же запрос без изменения контракта или входных данных.

## UTF-8

PowerShell должен отправлять JSON как UTF-8 bytes, а не как неявно закодированную строку. Иначе русские сообщения могут превратиться в '????' ещё до попадания в модель.
