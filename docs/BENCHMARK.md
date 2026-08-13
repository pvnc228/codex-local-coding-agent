# Benchmark моделей

Дата первого запуска: 2026-08-12.

## Методика

Benchmark запускает один и тот же набор из четырёх атомарных задач на disposable fixture. Локальная модель работает через обычный proposal-only controller; её patch не записывается в checkout. Для correctness benchmark отдельно применяет только валидированный patch во временной директории и выполняет внешний Python oracle в отдельном restricted child process: isolated Python mode, минимальный environment, allowlisted imports и доступ только к fixture. Поэтому `correctness` и `tool-loop reliability` не смешиваются: содержательно удачное предложение после нарушения policy не считается надёжно доставленным результатом.

Параметры запуска:

- `repeats=1`;
- `num_ctx=4096`;
- `temperature=0`;
- `num_predict=512`;
- `max_turns=4`;
- перед каждым профилем предыдущая модель выгружается через `/api/ps`/`keep_alive=0`.

Из Ollama сохраняются `total_duration`, `load_duration`, prompt/eval token counters, digest, размер и capabilities. Полный JSON с audit trail и patch proposals пишется локально в gitignored `.codex-run/benchmarks/`; эти runtime-файлы не являются частью опубликованного репозитория.

- `.codex-run/benchmarks/shortlist.json` — Bonsai, Ornith, Qwen3-Coder, Devstral и Ternary availability;
- `.codex-run/benchmarks/qwen25-coder.json` — существующий tool-capable baseline.

## Результат

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Avg wall, ms | Model calls | Tool calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bonsai-64k` | completed | 0% | 0% | 0% | 0% | 5,382 | 8 | 8 |
| `qwen2.5-coder` | completed | 0% | 0% | 0% | 0% | 2,185 | 4 | 0 |
| `ornith-9b` | completed | 0% | 0% | 100% | 25% | 7,257 | 12 | 11 |
| `qwen3-coder-30b` | completed | 0% | 0% | 100% | 25% | 25,197 | 13 | 10 |
| `devstral-small-2-24b` | completed | 0% | 0% | 25% | 0% | 64,223 | 13 | 13 |
| `ternary-bonsai-27b` | unavailable | — | — | — | — | — | — | — |

## Интерпретация

Это не рейтинг общего coding-качества. Это baseline контроллера на коротких proposal-only задачах.

- `qwen2.5-coder` вернул function-call-подобный JSON в `message.content`, поэтому native tool-loop не начался и controller отверг результат.
- `bonsai-64k` отвечал tool proposals обычным кодом или literal `\\n`, а не unified diff.
- `ornith-9b` и `qwen3-coder-30b` часто находили правильную идею изменения, но выдавали malformed или неприменимый diff; отдельные циклы также пытались вызвать неразрешённый `run_tests`.
- `devstral-small-2-24b` чаще выдавал malformed/absolute-path diff и не дошёл до принятого кандидата.
- Ternary Bonsai не прошёл импорт: Ollama завершил parsing ошибкой `tensor "output.weight" size overflow`. Он не считается установленным или протестированным.

Следующий разумный этап — не объявлять победителя, а улучшить protocol-facing regression set: добавить тесты на malformed hunk counts, plain-text tool-call compatibility и явный запрет `run_tests`, когда `checks` пуст. После этого benchmark нужно повторить с теми же fixtures и параметрами.

## Protocol repair follow-up: 2026-08-12

Добавлены и проверены (исторический snapshot):

- структурная проверка diff и внешний `git apply --check` для old/new hunk line counts и применимости;
- отсутствие `run_tests` в tool schema при пустом `checks`;
- совместимость с JSON tool-call в `message.content` через ту же policy layer;
- явный tool contract для полного diff, реальных переводов строк и запрета placeholders/literal `\\n`.

После repair suite вырос до `42/42`. Повторный Ornith smoke остался на `0%` correctness и `0%` loop reliability: неприменимые diff теперь отклоняются policy layer до внешнего oracle, а один формально считанный patch всё ещё не проходит `git apply`. Это подтверждает, что исправлен safety/protocol seam, но quality gate модели не пройден.

Applicability run добавил `git apply --check` без записи в workspace для `propose_patch` и final candidate validation. Suite вырос до `44/44`; Ornith v4 сохранил `0%/0%`, при этом wrong-context proposals теперь отклоняются bounded tool до выдачи результата.

## Isolated test process: 2026-08-12

`run_tests` теперь запускает только allowlisted command с sanitized environment и отдельной process group/session. stdout/stderr спулируются в bounded temporary sinks, process tree завершается bounded способом, а regression проверяет verbose output, cancellation и termination failure. При `max_tool_result_bytes=200` сохранён старый контракт: результат остаётся в лимите и содержит внешнее `evidence`; необязательная isolation metadata может быть опущена ради этого evidence.

## Baseline до REQUEST_CHANGES: 2026-08-13

Это runtime baseline до исправлений текущего review (repeats=1, значения профиля по умолчанию, `temperature=0`, `num_predict=512`, `max_turns=4`). Артефакт был gitignored в `.codex-run/benchmarks/latest.json`; benchmark после текущего исправления в этой сессии не запускался.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Avg wall, ms | Model calls | Tool calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bonsai-64k` | completed | 0% | 0% | 100% | 0% | 5,980 | 8 | 8 |
| `qwen2.5-coder` | completed | 0% | 0% | 0% | 0% | 3,589 | 10 | 6 |
| `ornith-9b` | completed | 0% | 0% | 100% | 25% | 6,643 | 10 | 8 |
| `qwen3-coder-30b` | completed | 0% | 0% | 75% | 25% | 15,260 | 10 | 7 |
| `devstral-small-2-24b` | completed | 25% | 0% | 75% | 50% | 50,734 | 15 | 13 |
| `ternary-bonsai-27b` | unavailable | — | — | — | — | — | — | — |

### Интерпретация

- `devstral-small-2-24b` — единственный профиль с ненулевой correctness (25%) и единственный, кто применил patch (50%). Это текущий лучший кандидат в shortlist, хотя loop reliability всё ещё 0%: содержательное предложение пока ненадёжно доставляется через protocol loop.
- `qwen3-coder-30b` и `ornith-9b` дают 75%/100% валидных proposal, но не конвертируются в корректно применённый patch.
- `bonsai-64k` валидирует, но никогда не применяет.
- `qwen2.5-coder` по-прежнему не выдаёт валидный структурированный proposal.
- `ternary-bonsai-27b` остаётся недоступным (отсутствует в Ollama `/api/tags`).
- Ни один профиль не достиг ненулевой loop reliability; correctness в целом остаётся низкой.

## Post-review baseline: 2026-08-13

Повторный прогон выполнен после review fixes на тех же четырёх fixtures с `repeats=1`, `num_ctx=4096`, `temperature=0`, `num_predict=512`, `max_turns=4`. Внешний oracle исполнялся в isolated child process. Полный artifact расположен локально в `.codex-run/benchmarks/post-review-20260813.json` и намеренно не публикуется, поэтому таблица ниже — сводка, а не ссылка на доступный читателю файл.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied |
| --- | --- | ---: | ---: | ---: | ---: |
| `bonsai-64k` | completed | 0% | 0% | 100% | 0% |
| `qwen2.5-coder` | completed | 0% | 0% | 50% | 0% |
| `ornith-9b` | completed | 0% | 0% | 100% | 25% |
| `qwen3-coder-30b` | completed | 0% | 0% | 75% | 25% |
| `devstral-small-2-24b` | completed | 25% | 0% | 75% | 50% |
| `ternary-bonsai-27b` | unavailable | — | — | — | — |

Вывод не изменился: Devstral остаётся единственным профилем с ненулевой correctness (25%), но ни один профиль не доставил корректный результат через loop надёжно. Это закрывает runtime gate R4, но не является основанием объявлять итоговый shortlist или обходить quantization A/B.

## Post-R7/R8 live benchmark: 2026-08-13

Повторный прогон после реализации R7 (атомаризация) и R8 (bounded retries/escalation) на тех же четырёх fixtures с `repeats=1`, `num_ctx=4096`, `temperature=0`, `num_predict=512`, `max_turns=4`. Полный artifact локально в `.codex-run/benchmarks/post-r7-r8.json` (gitignored, не публикуется).

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied |
| --- | --- | ---: | ---: | ---: | ---: |
| `bonsai-64k` | completed | 0% | 0% | 100% | 0% |
| `qwen2.5-coder` | completed | 0% | 0% | 50% | 0% |
| `ornith-9b` | completed | 0% | 0% | 100% | 25% |
| `qwen3-coder-30b` | completed | 0% | 0% | 75% | 25% |
| `devstral-small-2-24b` | completed | 25% | 0% | 75% | 50% |
| `ternary-bonsai-27b` | unavailable | — | — | — | — |

Итог идентичен post-review baseline: Devstral единственный с ненулевой correctness (25%), loop reliability 0% у всех. R7/R8 не меняют качество предложений модели — это ожидаемо, оба этапа про protocol/queueing, а не про выбор модели. Новые модели из MODEL_EVALUATION_PLAN (Qwen3-8B Q6, Qwen2.5-Coder-14B Q6, Muse, Nemotron) в `/api/tags` отсутствуют и не участвовали в прогоне.
