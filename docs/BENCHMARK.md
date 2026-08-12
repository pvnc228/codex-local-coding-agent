# Benchmark моделей

Дата первого запуска: 2026-08-12.

## Методика

Benchmark запускает один и тот же набор из четырёх атомарных задач на disposable fixture. Локальная модель работает через обычный proposal-only controller; её patch не записывается в checkout. Для correctness benchmark отдельно применяет только валидированный patch во временной директории и выполняет внешний Python oracle. Поэтому `correctness` и `tool-loop reliability` не смешиваются: содержательно удачное предложение после нарушения policy не считается надёжно доставленным результатом.

Параметры запуска:

- `repeats=1`;
- `num_ctx=4096`;
- `temperature=0`;
- `num_predict=512`;
- `max_turns=4`;
- перед каждым профилем предыдущая модель выгружается через `/api/ps`/`keep_alive=0`.

Из Ollama сохраняются `total_duration`, `load_duration`, prompt/eval token counters, digest, размер и capabilities. Полный JSON с audit trail и patch proposals:

- [shortlist.json](../.codex-run/benchmarks/shortlist.json) — Bonsai, Ornith, Qwen3-Coder, Devstral и Ternary availability;
- [qwen25-coder.json](../.codex-run/benchmarks/qwen25-coder.json) — существующий tool-capable baseline.

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
- `ornith-9b` и `qwen3-coder-30b` часто находили правильную идею изменения, но выдавали неверные hunk counts; отдельные циклы также пытались вызвать неразрешённый `run_tests`.
- `devstral-small-2-24b` чаще выдавал malformed/absolute-path diff и не дошёл до принятого кандидата.
- Ternary Bonsai не прошёл импорт: Ollama завершил parsing ошибкой `tensor "output.weight" size overflow`. Он не считается установленным или протестированным.

Следующий разумный этап — не объявлять победителя, а улучшить protocol-facing regression set: добавить тесты на malformed hunk counts, plain-text tool-call compatibility и явный запрет `run_tests`, когда `checks` пуст. После этого benchmark нужно повторить с теми же fixtures и параметрами.
