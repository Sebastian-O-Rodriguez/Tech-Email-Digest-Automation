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

ArticleContent:
  url: str                   # Final resolved article URL (after redirects)
  title: str                 # From <title> or <h1>
  text: str                  # Clean article text, max 500 chars
  email_index: int           # Which input email (1-based) this came from

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
5. Fetch article content from links (see Link Resolution Pipeline below)
6. Send all emails + article content to LLM in one call, get aggregated report
7. Render HTML digest with hyperlinked footnotes and MLA citations
8. Send digest email via Graph API
9. Mark all processed emails as read
10. Exit cleanly

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
Source refs `[n]` are hyperlinked to the fetched article or best available URL.
Works Cited section uses MLA-style citations with hyperlinked titles in a collapsible dropdown.

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

## Link Resolution Pipeline

Newsletter emails wrap article links in tracking redirects and platform-specific
redirectors. The `article_fetcher` module resolves these to real article URLs
through a multi-step pipeline before fetching content.

### Resolution chain (applied in order)

1. **Unwrap tracking URLs** — extract embedded destination from wrappers like
   `tracking.tldrnewsletter.com/CL0/https:%2F%2Fexample.com%2Farticle/1/...`
2. **Resolve Substack redirects** — decode JWT payload from
   `substack.com/redirect/2/<jwt>` to extract the `"e"` (destination) field
3. **Filter** — drop non-article URLs:
   - Skip domains: github.com, youtube.com, reddit.com, substack.com, tldr.tech
   - Skip patterns: unsubscribe, social share, tracking redirects, ads, web-version
4. **Normalize for dedup** — strip query params to canonical `scheme://host/path`
5. **Distribute slots** — round-robin across emails (max 10 total) so one
   link-heavy newsletter doesn't consume all slots
6. **Fetch** — httpx GET with 10s timeout, follow HTTP redirects, store final URL
7. **Paywall detection** — skip 402/403 and pages containing paywall phrases
8. **Extract** — title from `<title>`/`<h1>`, body text stripped of nav/footer/ads,
   truncated to 500 chars

### URL fallback for hyperlinks

When building hyperlinked footnotes, the digest renderer uses:
- **Fetched article URL** (best quality) if available
- **First resolved link from the email** (run through the same filter_links pipeline)
  as fallback — ensures links are unwrapped and cleaned, never raw tracking URLs

### Adding support for new newsletter platforms

When a new newsletter platform wraps links in a non-standard way:
1. Add an unwrap function (like `_unwrap_tracking_url`) in `article_fetcher.py`
2. Wire it into `filter_links()` before the `_is_skippable` check
3. Add the platform's domain to `_SKIP_DOMAINS` if its own pages aren't articles
4. Test with real emails from that platform
