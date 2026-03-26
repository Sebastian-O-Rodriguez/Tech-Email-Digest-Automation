# Email Ingester — Guava AI Daily Digest

> Automated system that ingests unread emails from an Outlook folder, synthesizes an executive-framed intelligence brief via LLM, and delivers it as a polished HTML digest. Once daily, Mon-Fri at 9:30 AM ET. No UI. No interaction. Just open and read.

---

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ |
| Email API | Microsoft Graph API (client credentials flow) |
| LLM | OpenRouter (openai SDK) |
| Scheduling | GitHub Actions cron (once daily, Mon-Fri) |
| Templates | Jinja2 (HTML digest) |
| Linting | ruff |
| Testing | pytest |
| HTTP | httpx |

---

## Architecture

- **No server** — runs as a GitHub Actions job, exits cleanly
- **No UI** — no dashboard, no web interface, no CLI interaction
- **No database** — read/unread status on emails IS the state
- **No state file** — no delta tokens, no processed IDs, no cache
- **Single user** — one mailbox, one folder, one recipient
- **Client credentials auth** — app-only permissions, no interactive login
- **One digest per run** — all unread emails aggregated into a single report

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

DigestReport:
  strategic_intel: str       # CEO-framed section (bullet points)
  engineering: str           # CTO-framed section
  tools_and_ops: str         # COO-framed section
  radar: str                 # Catch-all notable signals
  source_indices: list[int]  # Which input emails were referenced

DigestOutput:
  generated_at: datetime
  total_processed: int
  report: DigestReport
  source_emails: list[Email] # Referenced emails only
  html: str                  # Rendered HTML
```

---

## Pipeline (Execution Flow)

Each run executes exactly these steps:

1. Load config from environment variables
2. Authenticate to Microsoft Graph (client credentials)
3. Fetch all unread emails from target folder (`isRead eq false`)
4. Normalize content (HTML to text, extract links)
5. Send all emails to LLM in one call, get aggregated report back
6. Render HTML digest with executive-framed sections and MLA citations
7. Send digest email via Graph API
8. Mark all processed emails as read
9. Exit cleanly

---

## Digest Sections

| Section | Audience | Frame |
|---------|----------|-------|
| Strategic Intel | CEO | Market shifts, why it matters for AI companies |
| Engineering | CTO | Stack decisions, adopt/avoid signals |
| Tools & Ops | COO | Workflow improvements, ship-faster tools |
| On the Radar | General | Notable signals that don't fit above |

LLM outputs bullet points with **bold key terms** and [n] source refs.
Template renders as proper `<ul>` lists with 16px body text.
Works Cited section uses MLA-style citations in a collapsible dropdown.

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
- Cloud infrastructure beyond GitHub Actions
- Per-email summarization (we aggregate)
- State files or caching (read/unread is the state)

**Any of the above is a scope violation.**

---

## Conventions

### Git
- Branch: `feat/`, `fix/`, `chore/`
- Commit: `type(scope): description`
- One logical change per commit

### Code
- Python 3.12+ (use modern syntax: `type` unions, `match`, f-strings)
- Type hints on all function signatures
- No `Any` types without justification
- Dataclasses for data contracts (in `models.py`)
- `httpx` for HTTP (synchronous)
- No classes where functions suffice
- No premature abstraction

---

## Quality Gates

```bash
ruff check src/ tests/
ruff format --check src/ tests/
python -m pytest
```

Run all: `./scripts/quality-gate.sh all`

---

## Next Up: Article Fetcher

Planned feature to enrich the LLM context by following links from emails
and fetching actual article content (not just newsletter summaries).

See `.gorp/plans/current-sprint.md` for the implementation plan.
