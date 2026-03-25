# Guava AI Daily Digest

Automated intelligence brief that reads your Outlook inbox and delivers a concise, categorized summary twice daily.

## What it does

Every weekday at 9:30 AM and 12:30 PM ET, this pipeline:

1. Fetches all **unread** emails from a target Outlook folder
2. Processes and cleans the content (HTML to text, link extraction)
3. Sends everything to an LLM in one call to produce an aggregated report
4. Renders a polished HTML digest with four sections:
   - **Breaking News** -- urgent developments, security alerts, outages
   - **Tech Stacks** -- backend, frontend, infrastructure trends
   - **New Software** -- tools, product launches, dev tooling
   - **Deep Dives** -- notable long-form content worth reading later
5. Sends the digest via Outlook
6. Marks all processed emails as read

No state files. No database. Read/unread on the emails IS the state.

## Stack

| Layer | Tech |
|-------|------|
| Language | Python 3.12 |
| Email API | Microsoft Graph (client credentials) |
| LLM | OpenRouter (any model) |
| Scheduling | GitHub Actions cron |
| Templates | Jinja2 |
| HTTP | httpx |

## Setup

### 1. Azure AD App Registration

Register an app in [Azure Entra](https://entra.microsoft.com):
- Add **Application** permissions: `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`
- Grant admin consent
- Generate a client secret

### 2. OpenRouter API Key

Get one at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).

### 3. GitHub Secrets

Add these to your repo under Settings > Secrets > Actions:

| Secret | Description |
|--------|-------------|
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration secret |
| `MAILBOX_USER` | Mailbox email address |
| `TARGET_FOLDER_NAME` | Outlook folder name (e.g. `Inbox`, `Tech Digest`) |
| `OPENROUTER_API_KEY` | OpenRouter API key |

### 4. Enable GitHub Actions

Push to `main`. The cron schedule and CI workflow activate automatically.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install '.[dev]'

# Run quality gates
ruff check src/ tests/
ruff format --check src/ tests/
python -m pytest

# Or all at once
./scripts/quality-gate.sh all

# Manual run
python -m email_ingester
```

## Project Structure

```
src/email_ingester/
  __main__.py      # python -m email_ingester entry point
  main.py          # Pipeline orchestration
  config.py        # Environment variable loader
  models.py        # Data contracts (Email, DigestReport, DigestOutput)
  auth.py          # Microsoft Graph OAuth2 token acquisition
  ingester.py      # Fetch unread emails, mark as read
  processor.py     # HTML normalization, link extraction
  summarizer.py    # LLM aggregation via OpenRouter
  digest.py        # Jinja2 rendering, MLA citations
  sender.py        # Send digest via Graph API
  templates/
    digest.html.j2 # HTML email template (Guava AI branded)
```

## License

Private. Guava AI.
