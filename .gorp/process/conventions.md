# Conventions

## Git

- **Branches**: `feat/`, `fix/`, `chore/` prefixes
- **Commits**: `type(scope): description`
  - Types: `feat`, `fix`, `chore`, `test`, `docs`, `refactor`
  - Scopes: `ingester`, `processor`, `summarizer`, `scorer`, `digest`, `sender`, `state`, `auth`, `config`, `ci`
- One logical change per commit
- No force pushes

## Code

- Python 3.12+ — use modern syntax
- Type hints on all function signatures
- No `Any` without justification
- `dataclasses` for data contracts (defined in `models.py`)
- `httpx` for HTTP (synchronous)
- `anthropic` SDK for LLM calls
- No classes where functions suffice
- No premature abstraction
- `ruff` for linting and formatting (line length: 100)

## Sprint Tracking

- Roadmap: `.gorp/plans/roadmap.md` (CTO only, never modify)
- Sprint: `.gorp/plans/current-sprint.md`
- Journals: `.gorp/journal/<agent>-YYYY-MM-DD.md`
- Reports: `.gorp/plans/reports/`

## Quality Gates (must pass before shipping)

```bash
ruff check src/ tests/
ruff format --check src/ tests/
python -m pytest
find src/ tests/ -name "*.py" -exec python -m py_compile {} +
```
