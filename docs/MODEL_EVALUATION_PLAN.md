# План следующего исследования моделей

Дата фиксации: 2026-08-13.

Статус: исследовательское решение и план будущих прогонов. Указанные ниже новые GGUF ещё не скачаны, не импортированы и не проверены текущим benchmark. Исторические результаты установленных моделей остаются в [BENCHMARK.md](BENCHMARK.md), а проверенные локальные файлы и SHA-256 — в [MODEL_RESEARCH.md](MODEL_RESEARCH.md).

## Вывод

Главная следующая гипотеза — качество текущего `Qwen3-Coder-30B-A3B` ограничивает не только controller contract, но и агрессивная `IQ2_M`-квантизация. Проверять её нужно отдельным A/B одной и той же базовой модели, а не сравнением разных архитектур.

Параллельно нужен второй эксперимент: меньшая dense-модель в `Q6_K` или `Q8_0` может дать более надёжный код и tool calls, чем 30B MoE в двух битах, а также лучше использовать 8 GB VRAM целевой машины.

Новые Muse и Nemotron интересны как agentic-кандидаты, но их результаты не доказывают влияние квантизации на Qwen. Они входят в следующий product race только после чистого quant A/B.

## Проверенная локальная граница

Снимок 2026-08-13:

- GPU: NVIDIA GeForce RTX 4060, `8188 MiB` VRAM;
- RAM: `31.9 GiB` физической памяти;
- Ollama: `0.32.5`;
- `/api/ps`: загруженных моделей нет;
- текущий импорт `codex-qwen3-coder-30b:latest`: `IQ2_M`, исторический локальный GGUF около `10.17 GB`.

Модельный файл размером больше примерно 7 GB не гарантирует полного GPU-offload: нужен запас под KV cache, compute buffers и драйвер. Все 30B-кандидаты ниже будут частично работать из RAM и должны измеряться на реальном `size_vram`, а не только по размеру GGUF.

## Приоритетный набор

| Приоритет | Кандидат | Квант | Размер файла | Роль |
| ---: | --- | --- | ---: | --- |
| 1 | [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF) | `UD-IQ2_M` и `UD-Q4_K_XL` из одного pinned revision | около 10.8 / 17.7 GB | чистый quant A/B |
| 2 | [Qwen3-8B](https://huggingface.co/unsloth/Qwen3-8B-GGUF) | `Q6_K` | 6.73 GB | быстрый high-precision tool-use baseline, близкий к полному GPU-offload |
| 3 | [Qwen2.5-Coder-14B-Instruct](https://huggingface.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF) | `Q6_K`; затем опционально `Q8_0` | 12.1 / 15.7 GB | меньшая code-specific dense-модель с более щадящей квантизацией |
| 4 | [Muse Glimmer 30B](https://huggingface.co/unsloth/Muse-Glimmer-30B-GGUF) | `UD-Q4_K_XL` | около 15.9 GB | новый agentic/tool-recovery кандидат |
| 5 | [Nemotron 3.5 Lightning 30B-A3B](https://huggingface.co/vcruz305/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF) | `MXFP4_MOE` | 17.98 GB | MoE-кандидат для длинных tool loops |
| 6 | тот же Nemotron | mixed `2.97 BPW` | 11.74 GB | отдельный memory/speed tier, не quality reference |

### Почему эти модели

#### Qwen3-Coder-30B-A3B

[Официальная карточка базовой модели](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) указывает `30.5B` параметров, `3.3B` активных, native context `262144`, non-thinking режим и специально разработанный function-call формат. Это наиболее прямой кандидат для текущего controller contract.

Исторический локальный IQ2 был взят из другого GGUF-репозитория. Он остаётся полезным baseline, но строгий A/B требует заново взять IQ2 и Q4 из одного репозитория и одного commit/revision, сохранить SHA-256 и одинаковый Modelfile. Иначе различия quantizer, imatrix, metadata или chat template будут смешаны с влиянием числа бит.

#### Qwen3-8B Q6_K

Это не code-specific модель, но её карточка заявляет agent/tool capabilities и thinking/non-thinking режимы. `Q6_K` размером 6.73 GB — единственный новый кандидат, который близок к полному размещению в 8 GB VRAM. Он нужен как быстрый контроль: если 8B Q6 стабильно обходит 30B IQ2, это практический аргумент в пользу сохранения точности весов.

Для capability-прогона нельзя использовать greedy decoding в thinking-режиме: авторы Qwen предупреждают о деградации и повторениях. Comparable lane всё равно сохраняет одинаковый deterministic профиль и явно помечает его как искусственный контроль.

#### Qwen2.5-Coder-14B Q6_K/Q8_0

[Базовая карточка](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct) описывает `14.7B` code-specific модель, обученную для code generation, reasoning, fixing и code-agent сценариев. `Q6_K` — основной практический профиль; `Q8_0` — верхняя граница качества, только если CPU-offload и latency остаются приемлемыми.

#### Muse Glimmer 30B

Muse — dense agentic-модель примерно на `29.6B` параметров с отдельным perception encoder, контекстом `131072+`, controllable reasoning, tool use и failure recovery. Карточка приводит `75.5` на MCP Atlas и `51.2` на SWE-Bench Pro, но эти числа относятся к опубликованному evaluation scaffold и не являются evidence для нашего controller.

Первый прогон должен быть text-only: без vision projector и DFlash drafter. Они меняют memory footprint и производительность, но не нужны для проверки proposal-only coding.

#### Nemotron 3.5 Lightning 30B-A3B

[Официальная BF16-карточка NVIDIA](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16) описывает hybrid Mamba-2/MoE/Attention модель с `30B` общих и `3B` активных параметров, configurable reasoning и tool-call parser формата Qwen3-Coder. Лицензия — `OpenMDW-1.1`, поэтому перед дальнейшим распространением весов или производным релизом нужен отдельный license review.

Связанный community GGUF удаляет MTP head при конвертации. Автор квантов сообщает `6/6` на своей небольшой simulated agentic battery для `MXFP4_MOE`, а `2.47 BPW` получил `4/6` и допустил небезопасный ambiguous-delete call. Это полезный сигнал для выбора кванта, но не независимый benchmark. Поэтому основной профиль — `MXFP4_MOE`; low-bit варианты не должны считаться эквивалентными по безопасности.

## Два независимых режима benchmark

### Lane A — quantization causality

Цель: проверить только влияние квантизации.

- одна базовая модель Qwen3-Coder;
- один pinned upstream revision;
- один GGUF publisher/quantizer;
- одинаковые chat template, Modelfile и controller commit;
- одинаковые `num_ctx`, `num_predict`, sampling, task order и repeats;
- различается только quant: `UD-IQ2_M` против `UD-Q4_K_XL`;
- модели прогоняются поочерёдно с выгрузкой предыдущей через `/api/ps` и `keep_alive: 0`.

Исторический KikoCis IQ2 можно оставить третьей observational точкой, но не использовать как единственную сторону причинного A/B.

### Lane B — product race

Цель: выбрать лучший реальный профиль, а не измерить один фактор.

- каждая модель использует свой корректный chat template;
- reasoning/thinking и sampling соответствуют рекомендациям производителя;
- отдельно фиксируется, какие настройки отличаются;
- Muse сначала идёт без vision/DFlash;
- Nemotron сначала идёт без speculative decoding;
- результат сравнивается с comparable lane, но не смешивается с ним в одну таблицу.

Текущий `ModelProfile` хранит только `think`, `temperature`, `num_ctx` и `num_predict`. До честного capability race ему понадобятся явные `top_p`, `top_k`, template/reasoning options и их сериализация в artifact. Это будущая реализация, а не разрешение незаметно менять параметры вручную.

## Расширение набора задач

Четырёх fixtures и `repeats=1` недостаточно для решения о модели. Следующий воспроизводимый gate:

- минимум 20 атомарных задач;
- минимум 3 повтора каждой задачи;
- фиксированный порядок либо сохранённый seed/order в artifact;
- одинаковый внешний oracle для всех моделей;
- proposal-only в основном сравнении;
- никакого зачёта model-reported tests без evidence внешнего runner.

Обязательные категории:

1. минимальный семантический fix;
2. boundary/off-by-one;
3. сохранение публичного API;
4. UTF-8 и русский текст;
5. корректный unified diff;
6. выбор разрешённого tool;
7. запрет `run_tests`, когда checks пуст;
8. recovery после отказа tool;
9. остановка повторного tool call;
10. отказ от destructive/ambiguous действия;
11. соблюдение file allowlist;
12. корректный escalation при исчерпании бюджета.

## Метрики и gates

Главная метрика — `correctness` внешнего oracle. Остальные нельзя сворачивать в один score без сохранения исходных значений:

- tool-loop reliability;
- valid proposal rate;
- patch apply rate;
- unauthorized/unsafe tool calls;
- attempts до terminal status;
- wall time и model time;
- prompt/eval tokens;
- peak RAM, `size_vram` и доля CPU-offload;
- причина каждого rejected/failed результата.

Hard gates:

- `unsafe_tool_calls == 0`;
- ни один patch вне allowlist;
- ни один check не считается пройденным без внешнего evidence;
- повторный одинаковый tool call не превращается в дополнительную попытку;
- полные GGUF size и SHA-256 проверены до импорта;
- artifact содержит controller commit, Ollama version, model digest, GGUF source revision и полный профиль параметров.

Решение о Q4 принимается по качеству и latency вместе. Ненулевой результат Q4 после нуля IQ2 будет сильным сигналом, но при малой выборке не достаточным доказательством; следует смотреть по категориям ошибок и доверительным интервалам, а не только на разницу процентов.

## Порядок будущей работы

1. Зафиксировать чистый post-review controller baseline на текущих моделях.
2. Добавить artifact provenance: source URL/revision, SHA-256, quant и полный generation profile.
3. Импортировать пару Qwen3-Coder IQ2/Q4 из одного pinned источника.
4. Выполнить Lane A.
5. Добавить `Qwen3-8B Q6_K` и `Qwen2.5-Coder-14B Q6_K`.
6. Выполнить малый compatibility smoke, затем полный Lane B.
7. Добавить Muse text-only.
8. Добавить Nemotron `MXFP4_MOE`; low-bit — только отдельным tier.
9. Обновить [BENCHMARK.md](BENCHMARK.md) только по сохранённому внешнему artifact.

## Что не следует делать

- не скачивать все кванты одной модели без заранее определённого сравнения;
- не называть модель победителем по model card или одному smoke;
- не смешивать controller fixes и quant A/B в одном прогоне;
- не увеличивать context до 128K/1M на этой машине без измеренной необходимости;
- не добавлять vision/speculative decoding до text-only baseline;
- не считать 3B active эквивалентом 3B memory footprint: MoE-веса всё равно должны храниться.

## Источники

- [Qwen3-Coder-30B-A3B-Instruct — official model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
- [Qwen3-Coder-30B-A3B-Instruct — Unsloth GGUF](https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF)
- [Qwen3-8B — Unsloth GGUF](https://huggingface.co/unsloth/Qwen3-8B-GGUF)
- [Qwen2.5-Coder-14B-Instruct — official model card](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct)
- [Qwen2.5-Coder-14B-Instruct — Unsloth GGUF](https://huggingface.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF)
- [Muse Glimmer 30B — Unsloth GGUF/model card](https://huggingface.co/unsloth/Muse-Glimmer-30B-GGUF)
- [NVIDIA Nemotron 3.5 Lightning — official BF16 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16)
- [NVIDIA Nemotron 3.5 Lightning — community GGUF](https://huggingface.co/vcruz305/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF)
