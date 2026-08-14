# Исследование локальных моделей

Дата фиксации: 2026-08-12 (обновлено: 2026-08-14)

Этот документ фиксирует исследование моделей для `Codex Local Coding Agent`, фактическую загрузку GGUF на локальный диск и проверенный путь импорта в Ollama. Веса моделей не входят в репозиторий: они хранятся отдельно на `Q:`.

Следующая волна моделей, чистый quantization A/B и правила расширенного benchmark зафиксированы отдельно в [MODEL_EVALUATION_PLAN.md](MODEL_EVALUATION_PLAN.md).

## Контекст

Исходная модель проекта — сильно квантованный Bonsai/Qwen 3.5 27B из семейства [prism-ml/Bonsai-27B-gguf](https://huggingface.co/prism-ml/Bonsai-27B-gguf). В локальном Ollama уже были доступны `MichelRosselli/bonsai-27b:latest` и `bonsai-64k:latest`.

Цель shortlist — найти модели, которые интересны именно для небольших coding-задач, tool-loop и proposal-only контроллера:

- более сильный coding/agent вариант;
- заметно меньшая модель для дешёвых задач;
- экстремально компактная квантовка в духе Bonsai;
- несколько разных архитектурных/тренировочных подходов для сравнительного теста.

## Shortlist

| Модель | Источник | Квантовка | Размер файла | Роль в тестах | Состояние |
| --- | --- | ---: | ---: | --- | --- |
| Qwen3-Coder 30B A3B Instruct | [KikoCis/Qwen3-Coder-30B-A3B-Instruct-IQ2_M-GGUF](https://huggingface.co/KikoCis/Qwen3-Coder-30B-A3B-Instruct-IQ2_M-GGUF) | IQ2_M | 10.17 GB | основной кандидат для coding-agent задач при ограниченной памяти | скачан, hash проверен |
| Devstral Small 2 24B | [unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF](https://huggingface.co/unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF) | Q4_K_M | 14.33 GB | кандидат на качество coding и agentic tool use | скачан, hash проверен |
| Ornith 1.0 9B | [deepreinforce-ai/Ornith-1.0-9B-GGUF](https://huggingface.co/deepreinforce-ai/Ornith-1.0-9B-GGUF) | Q4_K_M | 5.63 GB | быстрый и дешёвый кандидат для малых задач | скачан, hash проверен, импортирован в Ollama |
| Ternary Bonsai 27B | [prism-ml/Ternary-Bonsai-27B-gguf](https://huggingface.co/prism-ml/Ternary-Bonsai-27B-gguf) | Q2_0 | 7.17 GB | эксперимент с ternary/1.7-bit подходом и малым footprint | скачан, hash проверен |
| Gemma 4 26B A4B IT | [KikoCis/gemma-4-26B-A4B-it-IQ2_M-GGUF](https://huggingface.co/KikoCis/gemma-4-26B-A4B-it-IQ2_M-GGUF) | IQ2_M | около 9.66 GB | экспериментальный MoE-кандидат | не завершён |

### Рабочий порядок тестирования

1. `codex-ornith-9b` — уже импортирован и отвечает через API.
2. Qwen3-Coder — наиболее прямой следующий кандидат для небольших coding-задач.
3. Devstral Small 2 — сравнительный тест качества при большем расходе памяти.
4. Ternary Bonsai — тест компактного Bonsai-подхода.
5. Gemma 4 — только после возобновления и полной проверки файла.

## Локальное хранилище

Корень staging-каталога:

```text
Q:\AI\Models\codex-local-coding-agent
```

Файлы первой волны:

```text
Q:\AI\Models\codex-local-coding-agent\qwen3-coder-30b-a3b-iq2_m\Qwen3-Coder-30B-A3B-Instruct-IQ2_M.gguf
Q:\AI\Models\codex-local-coding-agent\devstral-small-2-24b-q4_k_m\Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf
Q:\AI\Models\codex-local-coding-agent\ornith-1.0-9b-q4_k_m\ornith-1.0-9b-Q4_K_M.gguf
Q:\AI\Models\codex-local-coding-agent\ternary-bonsai-27b-q2_0\Ternary-Bonsai-27B-Q2_0.gguf
```

`Q:` используется как архив/staging. Модели не копируются в Git и не должны добавляться в публичный репозиторий.

## Evidence скачивания первой волны

Проверены фактические размеры файлов и SHA-256:

| Файл | Байты | SHA-256 |
| --- | ---: | --- |
| `Qwen3-Coder-30B-A3B-Instruct-IQ2_M.gguf` | 10169509696 | `74890B900E4C5E118BF7A349AB3C61195644556E26239103EECD26AE7158729E` |
| `Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf` | 14334446752 | `D14BA9EDEE1BB4C4996A726DEB81E49AE81800A3216F0774634238C380AEE496` |
| `ornith-1.0-9b-Q4_K_M.gguf` | 5629108704 | `5720D1F671B4996481274FFFE01868C3C36E87C135CC8538471CC7BD6087B106` |
| `Ternary-Bonsai-27B-Q2_0.gguf` | 7165121600 | `868C11714CF8FE47F5EC9EEB2BE0AB1A337112886F92EE0EDE6B855C4FA31757` |

## Вторая волна: quantization A/B и product race (2026-08-13)

По плану [MODEL_EVALUATION_PLAN.md](MODEL_EVALUATION_PLAN.md) скачаны новые GGUF на `Q:\AI\Models\codex-local-coding-agent`. Все файлы проверены: размер и SHA-256 сверены с upstream LFS-манифестом Hugging Face по зафиксированным ревизиям.

| Модель | Файл | Размер | SHA-256 | Upstream revision |
| --- | --- | ---: | --- | --- |
| Qwen3-Coder 30B UD-IQ2_M | `qwen3-coder-30b-a3b-ud-iq2_m\Qwen3-Coder-30B-A3B-Instruct-UD-IQ2_M.gguf` | 10837007520 | `7055A02D4D974FD68B26B095A9C676F099507AED1171F89A47275025DF3F521D` | `b17cb02d…` |
| Qwen3-Coder 30B UD-Q4_K_XL | `qwen3-coder-30b-a3b-ud-q4_k_xl\Qwen3-Coder-30B-A3B-Instruct-UD-Q4_K_XL.gguf` | 17665334432 | `2841AA314D916434860CFB8990347528DCDFE5C350DBCB9D1461DBEE88FF2533` | `b17cb02d…` |
| Qwen3-8B Q6_K | `qwen3-8b-q6_k\Qwen3-8B-Q6_K.gguf` | 6725900096 | `0EAEC718FDEAB0F429DFA0EC481C090388811F5E63785DDB582292F4EF3C3827` | `a6adef13…` |
| Qwen2.5-Coder 14B Q6_K | `qwen2.5-coder-14b-q6_k\Qwen2.5-Coder-14B-Instruct-Q6_K.gguf` | 12124683680 | `9650B0290E60AEE15F79112ACD3C5DB00DF14FC4A4D2A934D9B00ED59EDA7C3C` | `388f3f20…` |
| Muse Glimmer 30B UD-Q4_K_XL | `muse-glimmer-30b-ud-q4_k_xl\Muse-Glimmer-30B-UD-Q4_K_XL.gguf` | 15878222368 | `82BECE304887A313ECE08400BC030F6066C7BFF5B906B0CD40308EC8A409FD38` | `faa5b025…` |
| Nemotron 3.5 Lightning 30B MXFP4_MOE | `nemotron-3.5-lightning-30b-a3b-mxfp4_moe\Nemotron-3.5-Lightning-30B-A3B-MXFP4_MOE.gguf` | 17980129152 | `E313920E80C2C473AFDC9439B4400715DDF1E51D973DB483D8848FA3792EC799` | `2ea8eb66…` |

Импорт в Ollama (`ollama create`, имя `codex-*`, `FROM` на исходный GGUF с `Q:`):

| Модель | Ollama name | Status |
| --- | --- | --- |
| Qwen3-8B Q6_K | `codex-qwen3-8b-q6k:latest` | импортирован |
| Qwen3-Coder 30B UD-IQ2_M | `codex-qwen3-coder-30b-ud-iq2:latest` | импортирован |
| Qwen3-Coder 30B UD-Q4_K_XL | `codex-qwen3-coder-30b-ud-q4:latest` | импортирован |
| Qwen2.5-Coder 14B Q6_K | `codex-qwen2.5-coder-14b-q6k:latest` | импортирован |
| Muse Glimmer 30B UD-Q4_K_XL | — | импорт не прошёл: Ollama 0.32.5 отклонил quant (`failed to validate GGUF with llama-quantize`) |
| Nemotron 3.5 Lightning MXFP4_MOE | `codex-nemotron-30b-mxfp4:latest` | импортирован |

Runtime-результаты прогона — в [BENCHMARK.md](BENCHMARK.md) (вторая волна). Ключевой факт: `qwen3-coder-30b-ud-q4` и `nemotron-30b-mxfp4` (по ~17–18 GB) не загружаются на 8 GB VRAM и завершаются `model_error` (не выделен CUDA_Host-буфер ~12.3 GB); quant A/B на этой машине требует меньшего `num_ctx`/полного CPU-offload.

## Третья волна: Qwen3.8-27B (Unsloth Dynamic GGUF, 2026-08-14)

[unsloth/Qwen3.8-27B-GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF) — кандидат нового поколения (август 2026) на базе архитектуры Qwen3.5/Qwen3.8 с гибридным линейным вниманием (48 слоёв Gated DeltaNet + 16 слоёв Gated Attention).

Ключевые свойства для контроллера:
- **Ультра-малый KV cache**: состояние DeltaNet фиксировано по размеру; расход памяти на контекст составляет ~64 KB/токен (~0.5 GB при 8K, ~2 GB при 32K токенах), что решает проблему раздувания RAM при длинных tool-use сессиях и параллельных воркерах.
- **Developer Role & Nested Tool Calling**: встроенная поддержка системных инструкций разработчика и улучшенный парсинг вложенных объектов снижают процент битых JSON в tool loops.
- **Два режима сэмплинга**: Thinking mode (`temp=1.0`, `top_p=0.95`, `presence_penalty=0.0`) для оркестрации/декомпозиции и Non-thinking mode (`temp=0.7`, `top_p=0.80`, `presence_penalty=1.5`) для атомарных кодинг-воркеров.

Файлы на `Q:\AI\Models\codex-local-coding-agent\qwen3.8-27b`:

| Файл | Размер | SHA-256 | Роль / Статус |
| --- | ---: | --- | --- |
| `Qwen3.8-27B-Q4_K_M.gguf` | 17,106,775,008 байт (17.1 GB) | `7E78DA5D7E3AE28D178121F58646953305F3E5BD3CB46F4A75584E8B6C6FE169` | Основной сбалансированный профиль; Modelfile подготовлен, импортируется в Ollama как `codex-qwen3.8-27b-q4` |
| `Qwen3.8-27B-Q5_K_M.gguf` | 19,834,055,648 байт (19.8 GB) | (в архиве Q:) | Повышенная точность для одиночных задач; Modelfile подготовлен (`codex-qwen3.8-27b-q5`) |
| `Qwen3.8-27B-Q6_K.gguf`   | 22,884,408,288 байт (22.9 GB) | (в архиве Q:) | Максимальный квант для глубокого CPU-offload; Modelfile подготовлен (`codex-qwen3.8-27b-q6`) |

Импорт в Ollama (`ollama create codex-qwen3.8-27b-q4 -f Q:\AI\Models\codex-local-coding-agent\_modelfiles\codex-qwen3.8-27b-q4.Modelfile`):
- `codex-qwen3.8-27b-q4:latest` — импортирован.

## Gemma 4: незавершённая загрузка

Файл Gemma отдавался через Hugging Face Xet/CDN нестабильно: после частичной загрузки скорость падала до сотен KB/s. На `Q:` оставлены частичные `part-*` файлы для возможного возобновления; итогового GGUF и SHA-256 для него нет.

Эта модель не считается установленной или готовой к тесту. Частичные файлы нельзя скармливать Ollama.

## Проверенный импорт в Ollama

Официальная схема Ollama допускает импорт GGUF через `Modelfile` с абсолютным или относительным путём к файлу: [Importing a Model](https://docs.ollama.com/import) и [Modelfile reference](https://docs.ollama.com/modelfile).

Минимальная схема:

```text
FROM Q:\AI\Models\codex-local-coding-agent\ornith-1.0-9b-q4_k_m\ornith-1.0-9b-Q4_K_M.gguf

PARAMETER num_ctx 8192
PARAMETER temperature 0
```

Затем создаётся отдельное имя модели через `ollama create`. В smoke-test был создан экземпляр:

```text
codex-ornith-9b
```

Подтверждение через локальный Ollama API:

- Ollama `0.32.5`;
- `/api/show`: `family=qwen35`, `format=gguf`, `parameter_size=9.0B`, `quantization=Q4_K_M`;
- `/api/chat` с запросом `Reply with exactly: ORNITH_OK` вернул ровно `ORNITH_OK`;
- импорт завершился созданием слоёв и manifest без ошибок.

Важный operational detail: `FROM Q:\...` читает исходный файл с `Q:`, но `ollama create` импортирует/копирует модель в текущий Ollama store. В этом smoke-test store оставался на `C:`. Исходный GGUF на `Q:` не изменяется.

Перенос активного Ollama store на `D:` пока не выполнялся. Перед массовым импортом нужно отдельно настроить расположение store, чтобы не расходовать `C:`.

## Что ещё не сделано

- Gemma 4 нужно либо возобновить до полного файла, либо очистить оставшиеся partial-файлы отдельным решением;
- Ternary Bonsai требует отдельного решения по несовместимому с текущим Ollama GGUF;
- benchmark повторяется после исправления protocol-facing дефектов, потому что первый запуск не дал модели с ненулевыми correctness и loop-reliability gates.

Shortlist теперь имеет runtime evidence, но не считается доказанным рейтингом: первый benchmark измерил совместимость с текущим controller contract, а не общее coding-качество.

## Runtime update: 2026-08-12

В Ollama успешно импортированы и получили отдельные имена:

- `codex-qwen3-coder-30b:latest` — `qwen3moe`, `30.5B`, `IQ2_M`, `10,169,510,074` bytes;
- `codex-devstral-small-2-24b:latest` — `mistral3`, `23.6B`, `Q4_K_M`, `14,334,447,131` bytes;
- `codex-ornith-9b:latest` — `qwen35`, `9.0B`, `Q4_K_M`, `5,629,109,078` bytes.

Фактические capabilities первых трёх импортов — только `completion`; native `tools` Ollama для них не заявляет. У `bonsai-64k:latest` capabilities включают `tools`, `thinking`, `vision`. Это различие сохранено в benchmark artifact.

Импорт `Ternary-Bonsai-27B-Q2_0.gguf` не завершился: после копирования и проверки файла Ollama сообщил `tensor "output.weight" size overflow`. Manifest в `/api/tags` не появился, поэтому модель не считается установленной.

Первый единый benchmark и его ограничения задокументированы в [docs/BENCHMARK.md](BENCHMARK.md). Он зафиксировал runtime evidence, но не подтвердил ни одного победителя: все завершённые профили набрали `0%` внешней correctness и `0%` tool-loop reliability.

После protocol repair повторный Ornith smoke также остался на `0%/0%`: malformed или неприменимые diff отклоняются до внешнего применения, поэтому этот результат нельзя трактовать как регрессию безопасности. Следующий benchmark-блок должен добавить и повторить проверку применимости patch к фактическому disposable workspace.

Applicability slice добавлен и проверен на Ornith v4: `git apply --check` выполняется без записи в workspace на границах `propose_patch` и final candidate. Quality gate по-прежнему не пройден (`0% correctness`, `0% loop reliability`), но wrong-context diff больше не доходит до внешнего применения.
