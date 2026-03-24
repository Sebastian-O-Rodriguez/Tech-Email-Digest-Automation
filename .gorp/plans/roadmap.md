# Email Ingester — Roadmap

> CTO-maintained. Agents must never modify this file.

## Phase 1: Foundation
- Project scaffold (directory layout, agents, scripts, CI)
- Data contracts (`models.py`)
- Configuration system (`config.py`)
- State management (`state.py`)

## Phase 2: Core Pipeline
- Microsoft Graph authentication (`auth.py`)
- Email ingestion with delta queries (`ingester.py`)
- HTML normalization and link extraction (`processor.py`)
- LLM summarization (`summarizer.py`)
- Hybrid scoring (`scorer.py`)

## Phase 3: Digest & Delivery
- Jinja2 digest template
- Digest generation (`digest.py`)
- Email sending via Graph API (`sender.py`)
- Main entry point (`main.py`)

## Phase 4: CI & Polish
- GitHub Actions workflow (cron + cache)
- Quality gates in CI
- Error handling and logging
- Edge cases (empty inbox, API failures, rate limits)
- State corruption recovery

## Phase 5: Hardening
- DST handling validation
- Token refresh/expiry handling
- Digest readability tuning
- LLM prompt optimization
