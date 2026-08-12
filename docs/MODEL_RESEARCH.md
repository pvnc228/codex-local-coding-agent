# Исследование локальных моделей

Дата фиксации: 2026-08-12

Этот документ фиксирует исследование моделей для `Codex Local Coding Agent`, фактическую загрузку GGUF на локальный диск и проверенный путь импорта в Ollama. Веса моделей не входят в репозиторий: они хранятся отдельно на `Q:`.

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

Это порядок для практического smoke/benchmark-плана, а не утверждение о победителе: единый benchmark проекта ещё не проводился.

## Локальное хранилище

Корень staging-каталога:

```text
Q:\AI\Models\codex-local-coding-agent
```

Файлы:

```text
Q:\AI\Models\codex-local-coding-agent\qwen3-coder-30b-a3b-iq2_m\Qwen3-Coder-30B-A3B-Instruct-IQ2_M.gguf
Q:\AI\Models\codex-local-coding-agent\devstral-small-2-24b-q4_k_m\Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf
Q:\AI\Models\codex-local-coding-agent\ornith-1.0-9b-q4_k_m\ornith-1.0-9b-Q4_K_M.gguf
Q:\AI\Models\codex-local-coding-agent\ternary-bonsai-27b-q2_0\Ternary-Bonsai-27B-Q2_0.gguf
```

`Q:` используется как архив/staging. Модели не копируются в Git и не должны добавляться в публичный репозиторий.

## Evidence скачивания

Проверены фактические размеры файлов и SHA-256:

| Файл | Байты | SHA-256 |
| --- | ---: | --- |
| `Qwen3-Coder-30B-A3B-Instruct-IQ2_M.gguf` | 10169509696 | `74890B900E4C5E118BF7A349AB3C61195644556E26239103EECD26AE7158729E` |
| `Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf` | 14334446752 | `D14BA9EDEE1BB4C4996A726DEB81E49AE81800A3216F0774634238C380AEE496` |
| `ornith-1.0-9b-Q4_K_M.gguf` | 5629108704 | `5720D1F671B4996481274FFFE01868C3C36E87C135CC8538471CC7BD6087B106` |
| `Ternary-Bonsai-27B-Q2_0.gguf` | 7165121600 | `868C11714CF8FE47F5EC9EEB2BE0AB1A337112886F92EE0EDE6B855C4FA31757` |

При сборе evidence на дисках было примерно 1.5 TB свободного места на `Q:` и 255 GB на `D:`. `D:` подходит для активного набора из нескольких моделей, но для всей коллекции нужно учитывать также место Ollama store.

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
