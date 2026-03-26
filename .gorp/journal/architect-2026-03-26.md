# Architect Report — 2026-03-26

## Task: A1/A2 Data Contract — ArticleContent
## Status: done

## Decisions Made
- Added `ArticleContent` as a frozen dataclass, consistent with `Email`, `DigestReport`, and `DigestOutput`
- All four fields are required (no defaults, no `field(default_factory=...)`): `url`, `title`, `text`, `email_index`
- `email_index: int` ties each fetched article back to its source email by position in the input list — avoids embedding a full `Email` reference, keeps the contract flat and serializable
- `text` is typed `str` with no enforced truncation at the model layer; the 500-char limit is a responsibility of the fetcher (A1/A2), not the contract
- Placed after `Email` and before `DigestReport` per the sprint spec, matching the pipeline order (fetch -> enrich -> summarize)

## Files Modified
- `src/email_ingester/models.py` — inserted `ArticleContent` dataclass between `Email` and `DigestReport`

## Contracts Defined/Changed

```python
@dataclass(frozen=True)
class ArticleContent:
    url: str
    title: str        # From <title> or <h1>
    text: str         # Clean article text, max 500 chars
    email_index: int  # Which input email this came from
```

Expected downstream interface (for backend to implement in A1/A2):

```python
def fetch_articles(emails: list[Email]) -> list[ArticleContent]:
    """Fetch top article content from links in each email.

    Constraints: max 10 articles total, 500 char text limit, 10s timeout per fetch.
    Failed fetches are silently skipped (best-effort).
    """
    ...
```

## Blockers
- None
