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

Статус: частично реализовано: добавлены именованные профили и проверяемая настройка context window; benchmark ещё впереди.

- Bonsai profile;
- Qwen coder profile;
- comparable atomic task set;
- latency and token metrics;
- correctness score;
- tool-loop reliability score.

## M6 — safe repository integration

Статус: частично реализовано: добавлены proposal-only CLI и Ollama VRAM management; mediated apply и persistent run artifacts ещё впереди.

- proposal-only default;
- optional mediated apply;
- isolated test process;
- no implicit commit/push;
- persistent run artifacts.
