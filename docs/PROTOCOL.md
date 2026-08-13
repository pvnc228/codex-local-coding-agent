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

## Финальный формат

~~~json
{
  "status": "candidate",
  "summary": "что изменено",
  "patch": "unified diff",
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

Значение 'patch' обязательно проверяется отдельно. Наличие текста в поле 'patch' не означает, что это настоящий unified diff.

## Mediated apply

Модель только предлагает изменение через `propose_patch`; сама применить его не может. При запуске с `--apply` controller сначала валидирует и применяет patch во workspace, затем повторно запускает все allowlisted checks. Только после успешных post-apply checks результат получает `"applied": true`; при провале patch откатывается, а статус становится `rejected` с риском kind `post_apply_check_failed`. При ошибке самого применения используется риск kind `apply_failed`. По умолчанию (без `--apply`) режим — proposal-only: на диск ничего не пишется.

Инструмент `propose_patch` принимает только полный unified diff с синтаксически корректными hunk headers; `\n` внутри patch должен быть реальным переводом строки, а не двумя символами backslash и `n`. Validator проверяет структуру, allowlist и размер, а controller-owned `git apply --check` является источником истины для фактических hunk counts и применимости. До записи diff не модифицирует workspace.

Если Ollama не возвращает native `tool_calls`, контроллер допускает совместимый JSON-объект в `message.content` только в форме `{"name":"...","arguments":{...}}`, после чего всё равно прогоняет вызов через ту же policy layer. `run_tests` передаётся модели только когда task envelope содержит allowlisted `checks`.

Allowlisted `run_tests` запускается в отдельном process group/session с урезанным environment: в дочерний процесс не передаются произвольные переменные окружения родителя. stdout/stderr сразу направляются в bounded temporary sinks, а завершение process tree имеет bounded wait и явную ошибку при failure. Ответ содержит `isolated: true` как runtime evidence, если лимит результата позволяет сохранить эту метаинформацию; при предельно малом `max_tool_result_bytes` приоритет остаётся за `stdout`, `stderr` и `evidence`.

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
