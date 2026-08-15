# Аудит реализации

Дата: 2026-08-12. Сфокусирован на реализационных дефектах, а не на идеях/границах продукта.

## Критичные

### 1. `list_files` не ограничен allowlist

`local_coding_agent/repository_tools.py:247` — `_list_files` вызывает `_resolve_workspace_path`, а не `_resolve_allowlisted`. В отличие от `read_file`/`search_text`, модель может перечислить весь workspace (имена/пути всех файлов, включая не попавшие в `task.files`).

Нарушает инвариант «локальная модель не получает больше контекста, чем нужно задаче» и «контекст ограничен allowlist-файлами». Тест `test_list_files_stays_inside_requested_workspace_directory` это не ловит, потому что листит подпапку `src`, а не корень.

### 2. Необъявленная жёсткая зависимость от `git`

`local_coding_agent/validators.py:107` (`check_patch_applies`), `repository_tools.py:234` (`_propose_patch`), `benchmark.py:375` (`_judge_patch`). При отсутствии `git` в PATH весь pipeline падает на `"git executable is unavailable"`. В README «Требования» git не указан.

### 3. Нет сквозного лимита контекста

`local_coding_agent/controller.py:256` (`_initial_messages`) проверяет только стартовый envelope. Накопленные tool-results (каждый до `max_tool_result_bytes` × до `max_turns`) не учитываются в бюджете. `max_context_bytes` (=32К, не проброшен в CLI) — это только про первый запрос; реальное `num_ctx` можно переполнить. Инвариант «контекст ограничен лимитом токенов» не выполнен end-to-end.

### 4. Cancellation не прерывает блокирующие вызовы

`local_coding_agent/controller.py:151` — `cancel_event` проверяется только в начале хода. `model.chat()` (до 30с) и `run_tests` (до 60с) не прерываются по отмене — задача виснет до таймаута.

## Средние

### 5. Строковая сверка evidence — хрупкая

`local_coding_agent/validators.py:86-96` + `repository_tools.py:193` (`_process_evidence`). Модель обязана дословно повторить строку `stdout_bytes=...; stderr_bytes=...; truncated=...`; любой перефраз → reject. Намеренно (анти-fabrication), но превращает валидную работу в гонку строк; на практике даёт `0%` loop reliability в BENCHMARK.md.

### 6. `search_text` читает файл целиком без pre-read лимита

`local_coding_agent/repository_tools.py:288` — `path.read_text()` до поиска. `read_file` ограничен размером результата, а `search_text` грузит весь файл в память. Огромный allowlisted-файл = DoS по памяти.

### 7. Дублированная O(n²) обрезка вывода

`local_coding_agent/repository_tools.py:123-135` и `_bounded_process_result` (164-183). Посимвольный `[:-1]` с повторной `json.dumps` на каждой итерации + два почти одинаковых цикла обрезки. Корректно, но медленно на больших выводах и дублирует логику.

## Мелкие

### 8. Обход duplicate-call guard через дефолт `path`

`controller.py:188` считает signature по name+arguments. `list_files` с `{}` и `{"path":"."}` дают разные signature — повторный `list_files` не ловится.

### 9. Case-insensitive allowlist на case-sensitive FS

`repository_tools.py:353` (`casefold()`). На Linux патч к `SRC/allowed.py` пройдёт allowlist, а `git apply` создаст новый файл `SRC/...` вне задуманного пути.

### 10. `enforce_limit` доверяет снапшоту после unload

`memory.py:110-116`: если Ollama выгружает модель асинхронно, цикл может уйти в `MemoryBudgetError` по устаревшему состоянию.

## Рекомендуемый порядок

1. **#1** — пропустить `list_files` через allowlist (наименьший diff, закрывает прямую утечку контекста).
2. **#2** — добавить git в требования и/или graceful fallback.
3. **#3** — кумулятивный контекстный бюджет.
4. Остальные — по мере появления реальных сценариев.
