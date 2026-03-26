# Next: Article Fetcher

Status: **PLANNED**

## Goal

Enrich LLM context by fetching actual article content from links in emails.
Currently the LLM only sees newsletter email bodies (summaries, headlines).
With article fetching, it reads the source material for richer, more accurate
analysis.

## Problem

Newsletter emails contain short blurbs + links. The LLM summarizes the blurbs,
not the articles. This means:
- Shallow analysis (summarizing a summary)
- Missing details that would change the framing
- Can't assess if something truly "moves the needle" without reading it

## Design

### New module: `article_fetcher.py`

Responsibilities:
- Extract top links from processed emails (skip unsubscribe, tracking, social)
- Fetch each URL via httpx, follow redirects
- Detect paywalls and subscription walls (check for common paywall indicators)
- Extract article text from HTML (strip nav, ads, sidebars)
- Return clean text truncated to ~500 chars per article

### Integration point

Between steps 4 and 5 in the pipeline:

```
4. Normalize content (HTML to text, extract links)
4.5 NEW: Fetch top article content from links  <-- here
5. Send all emails + article content to LLM
```

The LLM prompt gets enriched with article text appended to each email's entry
in the feed.

### Constraints

- Max 10 articles total per run (API budget, runtime)
- 500 char limit per article (context budget)
- 10s timeout per fetch (don't block on slow sites)
- Skip URLs that match paywall/login patterns
- Skip URLs that return non-HTML (PDFs, images, etc)
- Best-effort: failed fetches are silently skipped

### Paywall detection

Check for common signals:
- HTTP 402/403 responses
- Meta tags: `<meta name="robots" content="noindex">` on paywall pages
- Body text containing "subscribe to read", "sign in to continue", etc.
- Known paywall domains (optional allowlist/blocklist)

### Link filtering

Skip these patterns:
- Unsubscribe links
- Social media share links (twitter.com/intent, facebook.com/sharer)
- Tracking pixels / utm redirects that resolve to the same newsletter
- mailto: links
- Anchor-only links (#)

### Output format

```python
@dataclass(frozen=True)
class ArticleContent:
    url: str
    title: str           # From <title> or <h1>
    text: str            # Clean article text, max 500 chars
    email_index: int     # Which input email this came from
```

### LLM prompt change

The email feed format changes from:
```
[1] Subject
From: sender
Body preview...
Links: url1 | url2
```

To:
```
[1] Subject
From: sender
Body preview...
Links: url1 | url2
Article: "Title of article" - First 500 chars of article text...
```

## Tasks

| ID | Task | Status |
|----|------|--------|
| A1 | Build `article_fetcher.py` with link filtering + paywall detection | planned |
| A2 | Add content extraction (HTML to clean article text) | planned |
| A3 | Integrate into pipeline between process and summarize | planned |
| A4 | Update LLM prompt to include article content | planned |
| A5 | Tests for fetcher (mock HTTP, paywall detection, filtering) | planned |
| A6 | E2E test with real run | planned |

## Dependencies

- A1, A2 can be done in parallel
- A3 depends on A1 + A2
- A4 depends on A3
- A5 can start after A1
- A6 is last
