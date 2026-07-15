# Email Digest Pipeline

Stateless Python pipeline that ingests unread emails from a Microsoft 365 mailbox, resolves newsletter tracking redirects, fetches upstream article content, synthesizes a structured brief via LLM, and delivers a templated HTML digest through Microsoft Graph.

Runs as a scheduled GitHub Actions job. No server, no database, no UI. Mailbox read/unread status is the state machine.

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Microsoft 365  │────▶│  Ingester    │────▶│  Processor       │
│  Graph API      │     │  fetch inbox │     │  normalize HTML  │
│  (unread email) │     │              │     │  extract links   │
└─────────────────┘     └──────────────┘     └────────┬─────────┘
                                                      │
                        ┌──────────────┐     ┌────────▼─────────┐
                        │  Summarizer  │◀────│  Article Fetcher │
                        │  LLM call    │     │  unwrap tracking │
                        │  (OpenRouter)│     │  resolve redirects│
                        └──────┬───────┘     │  extract content │
                               │             └──────────────────┘
                        ┌──────▼───────┐     ┌──────────────────┐
                        │  Digest      │────▶│  Sender          │
                        │  Jinja2 HTML │     │  Graph sendMail  │
                        │  MLA cites   │     │  mark as read    │
                        └──────────────┘     └──────────────────┘
```

**Pipeline steps:**

1. Authenticate to Microsoft Graph via OAuth2 client credentials flow
2. Fetch all unread emails from target folder (`isRead eq false`)
3. Normalize HTML to plain text, extract HTTP links
4. Resolve tracking redirects, unwrap URLs, fetch article content (max 10)
5. Send all content to LLM in a single aggregation call
6. Parse structured JSON response with fallback handling
7. Render HTML digest with Jinja2 (hyperlinked footnotes, MLA citations)
8. Send digest via Graph API `/sendMail`
9. Mark all processed emails as read

## Design Decisions

**Stateless execution** — No database, no delta tokens, no processed-ID cache. Each run queries for `isRead eq false` and marks emails as read on completion. The mailbox itself is the state machine.

**Single LLM call** — All emails and fetched article content are sent in one prompt. No per-email summarization, no chained calls. The LLM returns a structured JSON report with four sections and source indices. Fallback handling covers malformed JSON and partial responses.

**App-only auth** — Uses OAuth2 client credentials flow (no interactive login). The Azure AD app registration holds `Mail.Read`, `Mail.ReadWrite`, and `Mail.Send` application permissions.

**No persistent infrastructure** — Runs entirely inside GitHub Actions. The workflow sets a 15-minute timeout, uses concurrency grouping (`email-digest`, non-cancelling) to prevent overlapping runs, and exits cleanly.

## Link Resolution Pipeline

Newsletter emails wrap article links in tracking redirects and platform-specific redirectors. The `article_fetcher` module resolves these before fetching content:

1. **Unwrap tracking URLs** — Extract embedded destination from wrappers (e.g., `tracking.tldrnewsletter.com/CL0/https:%2F%2Fexample.com/1/...`)
2. **Resolve Substack redirects** — Decode JWT payload from `substack.com/redirect/2/<jwt>` to extract the destination URL
3. **Filter** — Drop non-article URLs: skip domains (`github.com`, `youtube.com`, `reddit.com`, `substack.com`, `tldr.tech`), skip patterns (unsubscribe, social share, tracking, ads, web-version links)
4. **Normalize** — Strip query params to canonical `scheme://host/path` for deduplication
5. **Distribute slots** — Round-robin across emails (max 10 total) so one link-heavy newsletter doesn't consume all slots
6. **Fetch** — `httpx` GET with 10s timeout, follow HTTP redirects, store final resolved URL
7. **Paywall detection** — Skip HTTP 402/403 responses and pages containing paywall phrases (`subscribe to read`, `members only`, etc.)
8. **Extract** — Title from `<title>` / `<h1>`, body text via BeautifulSoup/lxml with nav/footer/ad stripping, truncated to 500 chars

Fallback URL resolution for digest hyperlinks: if no fetched article URL is available, the renderer runs the email's original links through the same filter pipeline to produce a cleaned URL.

## Graph API Integration

**Authentication** (`auth.py`): POST to Azure AD token endpoint (`/oauth2/v2.0/token`) with client credentials. Returns bearer token for all subsequent Graph calls.

**Email ingestion** (`ingester.py`): GET `/users/{mailbox}/mailFolders/{folder}/messages` filtered by `isRead eq false`. Resolves folder display names to Graph folder IDs. Handles 401 (auth failure), 403 (permission denied), and 429 (throttle) with `Retry-After` header parsing.

**Sending** (`sender.py`): POST `/users/{mailbox}/sendMail` with HTML body. Same error handling as ingestion (401/403/429).

**Mark as read** (`ingester.py`): PATCH `/users/{mailbox}/messages/{id}` setting `isRead: true`.

## LLM Output Handling

The summarizer sends all email content plus fetched article text to OpenRouter in a single call. The prompt requests structured JSON with four report sections and source indices.

**Parsing strategy**: Attempt `json.loads` on the response. On failure, attempt to extract a JSON block from markdown fences. If both fail, generate a fallback report indicating parse failure — the pipeline still completes and sends the digest rather than crashing.

**Output structure**: `DigestReport` dataclass with `strategic_intel`, `engineering`, `tools_and_ops`, `radar` (each a string of bullet points with `[n]` source references), and `source_indices` (list of ints mapping to input emails).

The digest renderer converts `[n]` references into hyperlinks pointing to the best available URL for each source, and generates MLA-style citations in a collapsible "Works Cited" section.

## Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Email API | Microsoft Graph API (client credentials flow) |
| LLM | OpenRouter via OpenAI SDK |
| HTTP | httpx |
| HTML parsing | BeautifulSoup4 + lxml |
| Templating | Jinja2 |
| Scheduling | GitHub Actions cron |
| Linting | ruff |
| Testing | pytest + pytest-cov |
| Build | hatchling |

## Project Structure

```
src/email_ingester/
  __main__.py         Entry point (python -m email_ingester)
  main.py             Pipeline orchestration
  config.py           Environment variable loader (frozen dataclass)
  models.py           Data contracts: Email, ArticleContent, DigestReport, DigestOutput
  auth.py             Microsoft Graph OAuth2 client credentials token acquisition
  ingester.py         Fetch unread emails, resolve folders, mark as read, 429 handling
  processor.py        HTML-to-text normalization, HTTP link extraction
  article_fetcher.py  Tracking URL unwrap, Substack JWT decode, article fetch, paywall detection
  summarizer.py       Single-call LLM aggregation via OpenRouter, JSON parse with fallback
  digest.py           Jinja2 rendering, hyperlinked footnotes, MLA citations
  sender.py           Graph API sendMail, error handling (401/403/429)
  templates/
    digest.html.j2    HTML email template

tests/
  test_article_fetcher.py   67 tests — URL filtering, tracking unwrap, Substack redirects, paywall
  test_processor.py         16 tests — HTML normalization, link extraction
  test_auth.py              10 tests — token acquisition, error scenarios
  test_sender.py             8 tests — sendMail, error handling
  test_ingester.py           6 tests — email fetch, folder resolution, 429 handling
  test_summarizer.py         6 tests — LLM response parsing, JSON fallback
  test_digest.py             5 tests — rendering, citations, hyperlinks
  test_main.py               3 tests — end-to-end pipeline integration
```

121 tests across 8 modules.

## Setup

### Azure AD App Registration

Register an application in [Azure Entra](https://entra.microsoft.com):

- Add **Application** permissions: `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`
- Grant admin consent
- Generate a client secret

### OpenRouter API Key

Obtain a key at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).

### GitHub Secrets

Add these to Settings > Secrets > Actions:

| Secret | Required | Description |
|--------|----------|-------------|
| `AZURE_TENANT_ID` | Yes | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Yes | App registration client ID |
| `AZURE_CLIENT_SECRET` | Yes | App registration secret |
| `MAILBOX_USER` | Yes | Target mailbox email address |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `TARGET_FOLDER_NAME` | No | Outlook folder name (default: `Inbox`) |
| `LLM_MODEL` | No | OpenRouter model ID (default: `google/gemini-3.5-flash`) |

`DIGEST_RECIPIENT` defaults to `MAILBOX_USER` if not set.

See `.env.example` for local development configuration.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_TENANT_ID` | Yes | — | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Yes | — | App registration client ID |
| `AZURE_CLIENT_SECRET` | Yes | — | App registration secret |
| `MAILBOX_USER` | Yes | — | Target mailbox email address |
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key |
| `TARGET_FOLDER_NAME` | No | `Inbox` | Outlook folder display name |
| `LLM_MODEL` | No | `google/gemini-3.5-flash` | OpenRouter model identifier |
| `DIGEST_RECIPIENT` | No | `MAILBOX_USER` | Digest email recipient |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install '.[dev]'

# Quality gates
ruff check src/ tests/
ruff format --check src/ tests/
python -m pytest

# Run all gates
./scripts/quality-gate.sh all

# Manual pipeline run (requires env vars)
python -m email_ingester
```

## Scheduling

GitHub Actions runs the pipeline on a cron schedule:

```
30 13 * * 1-5   # Mon-Fri 1:30 PM UTC (9:30 AM ET)
```

The workflow sets `TZ=America/New_York` and enforces a 15-minute timeout. Concurrency group `email-digest` with `cancel-in-progress: false` queues overlapping runs rather than dropping them.

Manual dispatch is available via `workflow_dispatch`.

CI runs ruff lint, format check, and pytest on push to `main` and on pull requests.

## Scope Notes

This is a single-user, single-mailbox automation pipeline. It does not support:

- Multiple mailboxes or folders per run
- Attachment processing
- Thread reconstruction
- Persistent storage or caching
- Real-time triggers or webhooks
- Web UI or CLI interaction

## License

Private. Guava AI.
