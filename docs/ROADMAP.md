# Roadmap

Дата: 2026-08-13.

Историческая летопись завершённых этапов (M0–M6) перенесена в [ROADMAP_HISTORICAL.md](ROADMAP_HISTORICAL.md). Этот файл — план вперёд, отсортированный по приоритету.

Приоритеты согласованы с реализационным аудитом [AUDIT.md](AUDIT.md) и повторным review всего проекта 2026-08-13. Порядок — это оценка, а не обещание; номера первого аудита указаны в скобках.

## Gate перед следующим функциональным этапом

Статус review: исправления P0/P1/P2 смержены в `main` (`3e951bb`, merge `b879b03`). Post-review benchmark повторён 2026-08-13: все пять доступных профилей завершились, Ternary остался `unavailable`; локальный artifact не публикуется. После R6 first worker-pool slice полный локальный gate прошёл `88/88`, `compileall` и `git diff --check`.

Реализационные требования review ниже закрыты кодом и regression tests. R4 получил свежий внешний artifact, однако loop reliability остался нулевым у всех профилей:

- benchmark-oracle исполняет модельный код только в отдельном ограниченном процессе, а не через `exec` в процессе контроллера;
- `status`, `validation`, `audit` и `applied` принадлежат контроллеру и не могут быть подменены финальным JSON модели;
- mediated apply связывает acceptance с проверками уже применённого состояния либо явно возвращает непроверенный applied-результат;
- stdout/stderr тестового процесса читаются без pipe deadlock и обрезаются без посимвольного O(n²) цикла;
- cancellation не зависает, если завершение process tree запрещено или завершается ошибкой;
- публичная документация не ссылается на gitignored evidence как на доступный артефакт.

## R1 — Закрыть реализационные дыры безопасности и бюджета

Статус: реализация доставлена в `main`; свежий model runtime не запускался.

Цель: вернуть инварианты «контекст ограничен allowlist» и «контекст ограничен лимитом токенов» к фактическому поведению.

- ограничить `list_files` тем же allowlist, что `read_file`/`search_text` (AUDIT #1);
- добавить кумулятивный контекстный бюджет поверх накопленных tool-results, а не только стартового envelope (AUDIT #3);
- сделать `git` явным требованием в README или graceful fallback, когда его нет (AUDIT #2);
- прерывать блокирующие вызовы (`model.chat`, `run_tests`) по cancellation (AUDIT #4).

## R2 — Устойчивость и качество протокола

Статус: реализация доставлена в `main`; свежий model runtime не запускался.

Цель: убрать хрупкость, которая сейчас даёт `0%` loop reliability.

- пересмотреть строковую сверку evidence на структурную, не ослабляя анти-fabrication (AUDIT #5);
- pre-read лимит для `search_text`, чтобы огромный allowlisted-файл не стал DoS (AUDIT #6);
- убрать дублирование и O(n²) обрезки вывода (AUDIT #7);
- закрыть обход duplicate-call guard через дефолт `path` в `list_files` (AUDIT #8);
- пересмотреть case-insensitive allowlist на case-sensitive файловых системах (AUDIT #9).

## R3 — Mediated apply

Статус: реализация и review fixes доставлены в `main`; свежий live apply не запускался.

Цель была: следующее крупное направление после закрытия R1/R2.

- применить patch к workspace только после отдельного подтверждения контроллера — opt-in реализован через `--apply`, post-apply checks и rollback добавлены, runtime evidence после review ещё не повторён;
- `apply_patch` остаётся недоступным локальной модели напрямую — реализовано: `apply_patch` — controller-only seam, модель его не получает;
- сохранить proposal-only как режим по умолчанию — реализовано: без `--apply` изменений на диск не производится;
- перезаписывать controller-owned поля результата независимо от одноимённых полей модели — реализовано;
- после apply запускать allowlisted checks на изменённом workspace и откатывать patch при failure — реализовано.

## R4 — Повторный benchmark и evidence

Статус: post-review runtime baseline сохранён локально в `.codex-run/benchmarks/post-review-20260813.json`; runtime artifact gitignored и не является опубликованным evidence.

Цель была: получить ненулевые correctness/loop-reliability после R1/R2.

- повторить benchmark на тех же fixtures и параметрах — реализовано;
- зафиксировать новый runtime artifact — реализовано: `.codex-run/benchmarks/latest.json`;
- пересмотреть shortlist только на основании внешнего oracle — предварительно выполнено;
- вынести исполнение предложенного моделью Python из процесса benchmark — реализовано через restricted child process;
- учитывать совместимый JSON tool call из `message.content` при сохранении fallback proposal — реализовано;
- публиковать воспроизводимое evidence или явно маркировать локальные gitignored ссылки как недоступные читателю репозитория — локальные артефакты явно помечены как недоступные читателю репозитория.

## R4.1 — Quantization A/B и расширенный shortlist

Цель: проверить гипотезу, что агрессивный IQ2 повреждает coding/tool качество сильнее, чем уменьшение числа параметров при Q6/Q8.

Полный план, приоритеты, источники и gates находятся в [MODEL_EVALUATION_PLAN.md](MODEL_EVALUATION_PLAN.md).

- сначала сравнить Qwen3-Coder `UD-IQ2_M` и `UD-Q4_K_XL` из одного pinned revision;
- отдельно провести product race с Qwen3-8B Q6, Qwen2.5-Coder-14B Q6, Muse Glimmer Q4 и Nemotron MXFP4_MOE;
- расширить benchmark минимум до 20 задач и 3 повторов;
- сохранить source revision, SHA-256, model digest, generation profile, RAM/VRAM и внешний oracle в artifact;
- не смешивать quant A/B с model-native reasoning/sampling lane.

Критерии приёмки:

- ноль unsafe/unauthorized tool calls;
- correctness подтверждена только внешним oracle;
- IQ2/Q4 отличаются только квантом и проверяются на одном controller commit;
- новый рейтинг публикуется только после полного artifact, а не по model cards или smoke.

## Требования, извлечённые из продуктового обсуждения

Здесь зафиксированы только требования владельца проекта. Ответы другой модели не считаются архитектурным решением или evidence.

- дорогой агент формулирует задачу и проверяет результат, а локальная модель выполняет bounded coding-работу;
- интеграция должна быть harness-agnostic и не зависеть от одного поставщика агентов;
- один локальный model runtime должен обслуживать несколько логических кодеров через ограниченную очередь;
- слабые модели должны получать более атомарные задачи и конкретный feedback между попытками;
- после ограниченного числа неудач управление возвращается дорогому агенту, который решает, писать ли код самостоятельно;
- почти нулевая correctness в текущем benchmark — причина улучшать протокол и качество evidence, а не обходить oracle.

## R5 — Harness-agnostic core и адаптеры

Цель: отделить controller API от способа подключения к внешнему агенту.

Статус: R5.1 direct Python seam, первый R5.2 process-bound JSONL stdio slice и R6 bounded in-memory worker-pool slice реализованы и покрыты contract tests; official MCP conformance, Tasks, durable state, fairness и model-specific scheduling ещё не реализованы.

Принятое направление и границы MCP `2026-07-28` зафиксированы в [MCP_DESIGN.md](MCP_DESIGN.md).

- определить стабильный transport-neutral request/result contract поверх `TaskEnvelope` и controller-owned result;
- оставить bounded controller единственным владельцем policy, validation и audit;
- добавить минимальный Python SDK/tool seam для прямого in-process вызова;
- проектировать MCP и framework-specific skill/tool wrappers как тонкие адаптеры к одному core, без копирования policy logic;
- начать с local `stdio` и одного proposal-only tool `delegate_code`;
- использовать официальное Tasks extension только после явного capability opt-in клиента;
- не строить новую реализацию на deprecated Roots, Sampling, Logging или legacy HTTP+SSE;
- не передавать локальной модели credentials или неограниченный callback внешнего агента.

Критерии приёмки:

- один contract test запускает одинаковую задачу через direct adapter и как минимум один process-bound adapter;
- результаты имеют одинаковые статусы, audit semantics и policy errors;
- modern и legacy MCP clients получают совместимые, явно согласованные result shapes;
- отключение адаптера не меняет core controller.

R5.2 first slice доставлен: `StdioDelegationAdapter` принимает ограниченный UTF-8 JSONL request только для `delegate_code`, строит тот же `DelegationRequest` и возвращает тот же controller-owned result. Contract test сравнивает direct вызов и настоящий дочерний process. Это ещё не MCP conformance: pinned SDK, modern/legacy negotiation, Tasks и настоящий MCP client остаются отдельными gates.

R6 first slice доставлен: `BoundedWorkerPool` ограничивает worker slots и queued jobs, возвращает bounded `queue_overload`, сохраняет caller-scoped idempotency, изолирует concurrent request state и поддерживает queued/running cooperative cancellation; при отмене физический model-call slot удерживается до завершения executor. Это in-memory execution primitive; durable task store, timeout policy, fairness и Ollama-specific scheduling остаются отдельными gates.

## R6 — Bounded worker pool поверх одного model runtime

Статус: first in-memory execution slice реализован; полный worker/runtime gate ещё не закрыт.

Цель: несколько логических локальных кодеров без обещания «бесконечной» физической параллельности.

- очередь задач с явными `max_workers`, `max_queue`, timeout и cancellation;
- изоляция task state, tool-call history, workspace и audit между workers;
- сериализация либо ограниченная конкурентность запросов к одной модели согласно фактической способности Ollama;
- backpressure вместо неограниченного создания workers;
- VRAM policy и fairness, чтобы одна задача не удерживала модель или очередь бесконечно.

Критерии приёмки:

- concurrency-тест доказывает отсутствие смешивания context/audit двух задач;
- overload-тест возвращает bounded rejection, а не растит память;
- cancellation queued и running задач имеет внешнее runtime evidence.

## R7 — Атомаризация задач

Статус: реализовано. `local_coding_agent/atomizer.py` добавляет формальный `TaskBudget` (files/context-bytes/checks), детерминированный `preflight` с machine-readable причинами (`too_many_files`, `context_too_large`, `too_many_checks`) и `decompose`, который делит широкую задачу только по files на `ceil(N/max_files)` непрерывных children — каждый child не получает больше files/checks, чем явно разрешил родитель, а context/checks сверх бюджета детерминированно отклоняются (`ValueError`). `DelegationService` принимает опциональный `preflight_budget` и отклоняет широкую задачу policy failure `preflight_rejected` до запуска модели. Публичный seam экспортирован в `__init__`. Benchmark-сравнение исходной и атомаризованной постановки на внешнем oracle ещё не запускалось.

Цель: повышать шанс слабой модели за счёт меньшего и проверяемого task envelope.

- формальный бюджет задачи: файлы, строки/байты контекста, один ожидаемый эффект и targeted check;
- preflight, который отклоняет слишком широкую задачу с machine-readable причиной;
- decomposition contract возвращает дочерние envelopes, но не даёт локальной модели самой расширять allowlist;
- acceptance каждого шага проверяется отдельно; следующий шаг не наследует неподтверждённый diff.

Критерии приёмки:

- набор широких задач стабильно раскладывается в bounded envelopes либо детерминированно отклоняется;
- ни один дочерний envelope не получает больше файлов или checks, чем явно разрешил родитель;
- benchmark сравнивает исходную и атомаризованную постановку на одинаковом внешнем oracle.

## R8 — Ограниченные retries и escalation

Цель: после нескольких содержательно разных попыток вернуть управление дорогому агенту без бесконечного tool-loop.

- configurable retry budget с безопасным default и hard cap не выше 10;
- новая попытка разрешена только после machine-readable failure и изменённого feedback/context;
- одинаковый tool call по-прежнему немедленно останавливает текущий цикл;
- после исчерпания бюджета controller возвращает escalation bundle: task, просмотренные файлы, последние patch/validation issues, external evidence и риски;
- дорогой агент, а не локальная модель, решает: уточнить задачу, выбрать другую модель или написать код самостоятельно.

Критерии приёмки:

- oracle доказывает ровно заданное число попыток без off-by-one;
- repeated-call и cancellation имеют приоритет над retry budget;
- fallback не применяет patch и не заявляет checks без нового внешнего evidence;
- audit однозначно связывает каждую попытку с причиной и итоговой escalation.

## Вне MVP

- автоматические commit, push, публикация;
- автономная разработка большой функции;
- постоянная память локальной модели;
- неограниченное число физических workers без backpressure;
- автоматическая отправка задачи во внешний платный API из локального controller core.
