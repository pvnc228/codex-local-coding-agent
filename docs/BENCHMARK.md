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

`run_tests` теперь запускает только allowlisted command с sanitized environment и отдельной process group/session. stdout/stderr непрерывно дренируются bounded collectors без временных файлов, process tree завершается bounded способом, а regression проверяет verbose output, cancellation и termination failure. При `max_tool_result_bytes=200` сохранён старый контракт: результат остаётся в лимите и содержит внешнее `evidence`; необязательная isolation metadata может быть опущена ради этого evidence.

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

## SEARCH/REPLACE (R9): 2026-08-13

После добавления SEARCH/REPLACE-формата изменения (`edits`) повторён benchmark на тех же четырёх fixtures. Прогон прерван сбоем машины на стадии записи, но artifact `.codex-run/benchmarks/search-replace-20260813.json` (gitignored) сохранился полностью: все четыре профиля завершились. Correctness считается тем же внешним oracle.

| Profile | Correctness (diff → edits) | Loop reliability | Valid proposal |
| --- | ---: | ---: | ---: |
| `qwen3-coder-30b-iq2` | 0% → **75%** | 0% | 75% |
| `qwen3-8b-q6k` | 0% → **50%** | 0% | 75% |
| `devstral-small-2-24b` | 25% → 25% | 0% | 25% |
| `qwen2.5-coder-14b-q6k` | 0% → 0% | 0% | 0% |

### Интерпретация

- **Гипотеза подтверждена**: unified diff был основным барьером. На SEARCH/REPLACE `qwen3-coder-30b-iq2` (10 GB, IQ2_M) поднялся с 0% до 75% correctness — модели теперь не нужно вычислять номера строк и hunk-заголовки.
- `qwen3-8b-q6k` (6.7 GB) поднялся до 50% — самый дешёвый новый профиль теперь продуктивно решает часть задач.
- Loop reliability остаётся 0% у всех: модели предлагают корректные edits через `propose_patch` tool-call, но финальный structured JSON не завершает цикл чисто (`accepted` не достигается). Это следующий дефект протокола, не качества модели.
- Остаточные причины провала: `edit search block is not line-aligned` (модель копирует блок не с границы строки) и семантически неверный `replace` (oracle mismatch). `qwen2.5-coder-14b-q6k` по-прежнему не выдаёт ни patch, ни edits (retry budget exhausted).

Вывод: SEARCH/REPLACE — правильное направление для слабых моделей. Дальше стоит улучшать loop-завершение (чтобы модель корректно закрывала цикл финальным JSON после `propose_patch`) и подсказку про выравнивание `search` по строкам.

## Вторая волна (quant A/B + product race): 2026-08-13

Скачаны и импортированы шесть новых GGUF (см. [MODEL_RESEARCH.md](MODEL_RESEARCH.md)); все размеры и SHA-256 сверены с upstream. Muse Glimmer импорт не прошёл: Ollama 0.32.5 отклонил quant `UD-Q4_K_XL` (`failed to validate GGUF with llama-quantize`), модель не считается установленной.

Прогон на тех же четырёх fixtures (`repeats=1`, `num_ctx=8192`, `temperature=0`, `num_predict=512`, `max_turns=4`). Artifact локально в gitignored `.codex-run/benchmarks/second-wave-20260813.json`.

| Profile | Quant | Status | Correctness | Loop reliability | Model calls | Причина провала |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `qwen3-8b-q6k` | Q6_K | completed | 0% | 0% | 8 | malformed/corrupt patch |
| `qwen2.5-coder-14b-q6k` | Q6_K | completed | 0% | 0% | 12 | `retry_budget_exhausted` (ни одного patch) |
| `qwen3-coder-30b-iq2` | UD-IQ2_M | completed | 0% | 0% | 10 | corrupt patch / нет patch |
| `qwen3-coder-30b-q4` | UD-Q4_K_XL | model_error | — | — | 0 | OOM: CUDA_Host 12.3 GB не выделен |
| `nemotron-30b-mxfp4` | MXFP4_MOE | model_error | — | — | 0 | OOM: CUDA_Host 12.3 GB не выделен |
| `muse-glimmer-30b-q4` | UD-Q4_K_XL | not-imported | — | — | — | llama-quantize отклонил quant |

### Выводы

- **Quant A/B не состоялся в заявленном виде.** `qwen3-coder-30b-q4` (17.7 GB) не загружается на 8 GB VRAM: `ollama create` прошёл, но запуск завершился `model_error`. Диагностика загрузки подтвердила, что это ограничение железа, а не настроек: (1) на Windows+CUDA Ollama отключает mmap и пинует CPU-offloaded тензоры в `CUDA_Host` — запрос 11.8 GB буфера падает; (2) принудительный `num_gpu=0` тоже падает — `CPU_REPACK`-буфер 15.2 GB плюс сами веса 17.7 GB превышают 31.9 GB RAM. Уменьшение `num_ctx` не помогает: ошибка на этапе загрузки тензоров, а не KV-cache. Итог: IQ2 против Q4 на этой машине сравнить нельзя; Q4 30B и Nemotron требуют >32 GB RAM либо другой quant с меньшим footprint.
- **Ни один новый профиль не дал ненулевую correctness.** `qwen3-8b-q6k` и `qwen3-coder-30b-iq2` дошли до tool-call, но выдали malformed/corrupt diff; `qwen2.5-coder-14b-q6k` ни разу не предложил patch (уперся в retry budget). Текущий best candidate остаётся `devstral-small-2-24b` (25%).
- **Nemotron и Muse требуют отдельного решения по памяти** (меньший `num_ctx`, больше CPU-offload или `OLLAMA_NUM_PARALLEL`/quant с меньшим footprint), прежде чем их можно сравнивать по качеству.

## Третья волна: Qwen3.8-27B Q4_K_M — 2026-08-14

Первый прогон нового кандидата `codex-qwen3.8-27b-q4` (17.1 GB, `Q4_K_M`) на тех же четырёх fixtures (`repeats=1`, `num_ctx=8192`, `temperature=0`, `num_predict=512`, `max_turns=4`, `think=false`). В отличие от Qwen3-Coder Q4 и Nemotron MXFP4 (~17–18 GB, OOM на CUDA_Host), модель загрузилась штатно: `size_vram=6.06 GB`, остальное CPU-offload. Artifact локально в gitignored `.codex-run/benchmarks/qwen3.8-27b-q4-20260814.json`.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Model calls | Tool calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-27b-q4` | completed | **75%** | **75%** | 100% | 75% | 12 | 8 |

### Интерпретация

- **Первый профиль с ненулевой loop reliability (75%)** — до этого все модели держали 0%. Три из четырёх задач доведены до `accepted` чистым финальным JSON после `propose_patch`; подтверждается гипотеза о нативном Developer Role и корректном завершении tool loop.
- **Correctness 75%** сравним с лучшим SEARCH/REPLACE-результатом `qwen3-coder-30b-iq2` (75%), но здесь модель ещё и закрывает цикл надёжно, чего IQ2 не делал.
- Единственный провал — `limit-inclusive`: `edit search block is not line-aligned` (`src/window.py`). Модель скопировала `search` без ведущего отступа (`return values[: limit - 1]` вместо строки с 4 пробелами). Это тот же дефект выравнивания строк, что и во второй волне, а не ошибка семантики.
- Нагрузка: 12 model calls на 4 задачи, `prompt_tokens` 13160, `eval_tokens` 856, avg wall ~96 s/задача (модель частично на CPU, отсюда высокий wall time).

Вывод: Qwen3.8-27B Q4 — новый лучший кандидат shortlist по качеству+надёжности доставки. Следующий шаг по плану: повторить с `repeats>=3` и на расширенном наборе задач, а также сравнить с q5/q3 квантами; отдельно проверить, что остаточный `line-aligned` провал закрывается подсказкой про выравнивание `search`.

## Третья волна: repeats=3 и product race — 2026-08-14

Повтор `qwen3.8-27b-q4` с `repeats=3` на тех же четырёх fixtures подтвердил стабильность: `75%` correctness и `75%` loop reliability, причём во всех трёх повторах единственный провал — `limit-inclusive` с одинаковой причиной `edit search block is not line-aligned` (модель детерминированно теряет ведущий отступ). Остальные три задачи проходят `accepted` во всех повторах.

Product race (`repeats=3`) на четырёх fixtures среди доступных в `/api/tags` профилей. Artifact локально в gitignored `.codex-run/benchmarks/product-race-qwen3.8-20260814.json`.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Model calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-27b-q4` | completed | **75%** | **75%** | 100% | 75% | 36 |
| `qwen3-8b-q6k` | completed | 50% | 75% | 100% | 75% | 33 |
| `qwen3-coder-30b-iq2` | completed | 66.7% | 41.7% | 100% | 66.7% | 44 |
| `qwen2.5-coder-14b-q6k` | completed | 0% | 0% | 0% | 0% | 36 |

### Расширенный набор 20 задач

Набор задач расширен с 4 до 20 атомарных задач (см. `default_cases()` в `local_coding_agent/benchmark.py`) с детерминированными внешними oracles в restricted child process. Прогон `qwen3.8-27b-q4` с `repeats=1` на 20 задачах. Artifact локально в gitignored `.codex-run/benchmarks/qwen3.8-27b-q4-extended20-20260814.json`.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Model calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-27b-q4` | completed | **85%** | **85%** | 100% | 85% | 59 |

Все 3 провала — одна и та же причина `edit search block is not line-aligned` (`limit-inclusive`, `abs-sum`, `last-element`): когда `search` начинается с отступленной строки тела функции, модель теряет ведущий отступ. Это дефект формата SEARCH/REPLACE, а не семантики — у задач, где `search` начинается с `def`, все 17 решены корректно.

### Вывод третьей волны

- `qwen3.8-27b-q4` — первый профиль с устойчиво ненулевой loop reliability и лучший по correctness как на 4, так и на 20 задачах. Гипотеза о нативной Developer Role и корректном завершении tool loop подтверждается.
- Quant A/B и расширенный product race ограничены: q5/q6/q3 не импортируются из-за диска (см. [MODEL_RESEARCH.md](MODEL_RESEARCH.md)), Muse/Nemotron — по OOM/import-reject из второй волны.
- Единственный систематический дефект — потеря ведущего отступа в `search` для SEARCH/REPLACE. Следующий шаг: усилить подсказку про точное копирование строк с отступами (или перейти к allowlist строковых/структурных edits), после чего перепрогнать.

## Fix подсказки про отступы SEARCH/REPLACE — 2026-08-15

Подсказка `propose_patch` (system contract и tool description) усилена явным требованием копировать `search` точно, включая ведущие пробелы каждой строки. Это закрыло единственный систематический дефект третьей волны (`edit search block is not line-aligned`).

Прогон `qwen3.8-27b-q4` на 20 задачах после фикса. Artifact локально в gitignored `.codex-run/benchmarks/qwen3.8-27b-q4-extended20-hint-20260815.json`.

| Profile | Status | Correctness | Loop reliability | Valid proposal | Patch applied | Model calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.8-27b-q4` | completed | **100%** | **100%** | 100% | 100% | 61 |

Все 20 задач решены корректно и доведены до `accepted` чистым финальным JSON. Это первый прогон в истории проекта со 100% correctness и 100% loop reliability одновременно. Остаточный дефект был протокольным (недостаточно явная инструкция про отступы), а не ограничением модели.
