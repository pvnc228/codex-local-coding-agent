# Working rules

## Scope

Этот проект строит контроллер для делегирования малых coding-задач локальным моделям Ollama.

## Invariants

- Локальная модель не получает больше контекста, чем нужно задаче.
- Никакие тесты не считаются выполненными без внешнего evidence.
- Никакой diff не принимается без проверки затронутых файлов.
- Proposal-only является режимом по умолчанию.
- Повторяющийся tool call — сигнал остановить цикл, а не продолжать бесконечно.
- Русский JSON передаётся в UTF-8.
- Commit, push и публикация не являются частью MVP.

## Development workflow

Перед реализацией:

1. прочитать 'PROJECT.md', 'docs/ARCHITECTURE.md' и 'docs/PROTOCOL.md';
2. проверить текущую модель через Ollama API;
3. определить минимальный публичный seam;
4. добавить тест, который показывает требуемое поведение;
5. только затем менять реализацию.

После реализации:

1. проверить diff;
2. выполнить targeted checks;
3. проверить, что заявленные checks подтверждены внешним runner-ом;
4. зафиксировать незапущенные проверки явно.

---

## AI Agent Automated Setup Instructions

If you are an AI coding agent (Claude Code, Cursor, Windsurf, Roo Code, ChatGPT Codex, etc.) instructed to install or configure this project:

1. **Install package & dependencies**: `pip install -e .[mcp]`
2. **Verify runtime environment**: `python -m local_coding_agent doctor`
3. **Register MCP server in host IDE**: `python -m local_coding_agent init-mcp --auto --write`
4. **Run end-to-end sandbox verification**: `python -m local_coding_agent test-run --mock`

