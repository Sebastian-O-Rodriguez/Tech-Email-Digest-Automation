# Email Ingester — Outlook Email Digest

> Automated system that ingests emails from a single Outlook folder, summarizes and ranks content via LLM, and delivers a twice-daily digest email. No UI. No interaction. Just open and read.

---

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ |
| Email API | Microsoft Graph API (client credentials flow) |
| LLM | OpenRouter (openai SDK) |
| Scheduling | GitHub Actions cron (twice daily) |
| State | JSON file persisted via GitHub Actions cache |
| Templates | Jinja2 (HTML digest) |
| Linting | ruff |
| Testing | pytest |
| HTTP | httpx |

---

## Architecture (Inviolable)

- **No server** — runs as a GitHub Actions job, exits cleanly
- **No UI** — no dashboard, no web interface, no CLI interaction
- **No database** — JSON state file only (processed IDs + delta token)
- **Single user** — one mailbox, one folder, one recipient
- **Client credentials auth** — app-only permissions, no interactive login
- **No repo commits for state** — use GitHub Actions cache exclusively
- **Stateless runtime** — all persistence is explicit (cache restore/save)

---

## Data Model

```
Email:
  id: str                    # Graph message ID
  subject: str
  sender: str
  timestamp: datetime
  body_text: str             # Cleaned plain text
  body_html: str             # Original HTML
  links: list[str]           # Extracted URLs

ProcessedEmail:
  email: Email
  summary: str               # LLM-generated
  priority: "high" | "medium" | "low"
  why_it_matters: str        # LLM-generated
  recommended_action: str    # LLM-generated
  key_links: list[str]       # Curated subset of links
  score: float               # Hybrid score (rules + model)

DigestOutput:
  generated_at: datetime
  total_processed: int
  high_priority: list[ProcessedEmail]
  medium_priority: list[ProcessedEmail]
  low_priority_count: int
  html: str                  # Rendered HTML
```

---

## Pipeline (Execution Flow)

Each run executes exactly these steps in order:

1. Load config from environment variables
2. Authenticate to Microsoft Graph (client credentials)
3. Restore state (processed IDs + delta token) from cache
4. Fetch new/changed messages via delta query (or fallback to ID comparison)
5. Normalize content (HTML -> text, extract links)
6. Summarize via LLM (only new/changed emails, never reprocess)
7. Score and rank (hybrid: rules + model confidence)
8. Generate HTML digest from Jinja2 template
9. Send digest email via Graph API
10. Save state (updated IDs + delta token) to cache
11. Exit cleanly

---

## Non-Goals (Do NOT Build)

- Attachment processing or OCR
- Multiple folders or mailboxes
- UI, dashboard, or CLI interface
- Real-time triggers or webhooks
- Vector DB, embeddings, or search
- Notion, Slack, or other integrations
- Multi-user support
- Email reply or automation
- Thread reconstruction
- Advanced NLP classification
- Cloud infrastructure beyond GitHub Actions

**Any of the above is a scope violation.**

---

## Agent System

| Agent | Model | Role | When to Use |
|-------|-------|------|-------------|
| **robo** | opus | Orchestrator — plans sprints, dispatches agents, collects reports | Sprint planning, multi-task coordination |
| **architect** | sonnet | Pipeline design, data contracts, API schema decisions | New modules, interface changes, data flow |
| **backend** | sonnet | Python pipeline code, Graph API, LLM calls, all implementation | Feature work, bug fixes, integrations |
| **qa** | sonnet | Testing, quality gates, code review, validation | Test writing, review, pre-merge checks |

No frontend agent — there is no UI.

---

## Conventions

### Git
- Branch: `feat/`, `fix/`, `chore/`
- Commit: `type(scope): description` (e.g., `feat(ingester): add delta query support`)
- One logical change per commit

### Code
- Python 3.12+ (use modern syntax: `type` unions, `match`, f-strings)
- Type hints on all function signatures
- No `Any` types without justification
- Dataclasses for data contracts (in `models.py`)
- `httpx` for HTTP (async not required — keep synchronous for simplicity)
- No classes where functions suffice
- No premature abstraction

### Sprint Tracking
- Roadmap: `.gorp/plans/roadmap.md` (CTO only)
- Sprint: `.gorp/plans/current-sprint.md`
- Journals: `.gorp/journal/<agent>-YYYY-MM-DD.md`

---

## Quality Gates

```bash
# All must pass before shipping
ruff check src/ tests/                    # Lint
ruff format --check src/ tests/           # Format
python -m pytest                          # Tests
find src/ tests/ -name "*.py" -exec python -m py_compile {} +  # Syntax
```

Run all: `./scripts/quality-gate.sh all`

---

## Approval Matrix

| Action | Approved By |
|--------|-------------|
| Write code, run tests, create branches, write journals | Auto-approved |
| Task re-prioritization, agent reassignment | Robo decides |
| Schema changes, new dependencies, env var changes | CTO required |
| Roadmap changes, deploy config, auth changes | CTO required |
