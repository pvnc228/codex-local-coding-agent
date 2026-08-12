# Roadmap

## M0 — project contract

Статус: оформлено.

- зафиксирована роль локальной модели;
- описаны границы MVP;
- описан tool-loop;
- описаны проверки diff и test evidence;
- зафиксированы результаты первичного теста Bonsai.

## M1 — Ollama adapter

Статус: реализовано.

Цель: надёжно отправлять chat-запросы в Ollama.

- UTF-8 transport;
- '/api/chat';
- model profile;
- timeout;
- 'think', 'num_ctx', 'num_predict';
- нормализация ошибок;
- получение '/api/ps' для диагностики loaded state.

## M2 — bounded tools

Статус: реализовано.

- 'read_file';
- 'search_text';
- 'propose_patch';
- allowlisted 'run_tests';
- path and output limits;
- audit events.

## M3 — controller loop

Статус: реализовано.

- max turns;
- duplicate-call guard;
- tool-result correlation;
- structured result parsing;
- retry policy;
- cancellation.

## M4 — validators

Статус: реализовано.

- JSON Schema;
- unified diff parser;
- changed-file allowlist;
- patch size limits;
- check evidence;
- clean failure states.

## M5 — model profiles and benchmark

Статус: реализовано как измерительный этап; correctness gate моделей пока не пройден.

- Bonsai profile;
- Qwen coder profile;
- comparable atomic task set;
- latency and token metrics;
- correctness score;
- tool-loop reliability score.

Добавлены профили исследованных GGUF, CLI `--benchmark`, внешний oracle в disposable fixture и JSON artifact. Первый запуск зафиксирован в [docs/BENCHMARK.md](BENCHMARK.md); он показал `0%` correctness и `0%` loop reliability у всех завершённых профилей, поэтому shortlist не считается доказанным рейтингом.

## M6 — safe repository integration

Статус: частично реализовано: proposal-only CLI, Ollama VRAM management, isolated benchmark fixture, persistent benchmark artifacts и protocol-facing repair slice добавлены; workspace applicability check, mediated apply и isolated test process ещё впереди.

- proposal-only default;
- optional mediated apply;
- isolated test process;
- no implicit commit/push;
- persistent run artifacts.
