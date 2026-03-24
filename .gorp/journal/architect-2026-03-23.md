# Architect Journal — 2026-03-23

## Task 1A: Define data contracts in models.py

### What was done

Refined `src/email_ingester/models.py` to match the CLAUDE.md data model with precise type hints.

### Changes

1. **`Priority` type alias** — Added `Priority = Literal["high", "medium", "low"]` and applied it to `ProcessedEmail.priority` (was `str`).

2. **`EmailSummary` intermediate type** — New frozen dataclass representing the raw LLM summarizer output before the scorer runs. Fields: `email_id`, `summary`, `priority`, `why_it_matters`, `recommended_action`, `key_links`, `model_confidence`. This decouples summarization from scoring so each step has a clean input/output contract.

3. **`DigestOutput` made frozen** — It is constructed once and sent; no reason to mutate it.

4. **`State` docstring** — Documented that `processed_ids` is a `set[str]` for O(1) dedup lookups, but sets are not JSON-serializable. The `state.py` module handles the conversion (set to sorted list on save, list to set on load). Callers must use `state.load_state`/`state.save_state`, not raw `json.dumps`.

5. **No `Any` types** — Verified none exist.

### Decisions

- **Config stays in config.py** — It has its own `from_env()` factory and no other module needs to import it as a data contract alongside the pipeline types. Duplicating it in models.py would add coupling for no benefit.
- **`EmailSummary.model_confidence`** — Included as a float so the scorer can blend LLM self-assessed confidence with rule-based signals into the final `ProcessedEmail.score`. Default 0.0.
- **All pipeline data types are frozen** except `State`, which needs mutation during a run (adding to `processed_ids`).

---

## Task 4A: Review digest.yml for production gaps

### Status: done

### Findings

#### 1. Secrets usage — one gap found

`config.py` requires `DIGEST_RECIPIENT` as an env var (it defaults to `MAILBOX_USER_ID` when absent, but that is a silent fallback — the digest goes to the sender's own mailbox, which may or may not be the intent). `LLM_MODEL` and `STATE_FILE` are optional with defaults and are fine.

The actual gap: `DIGEST_RECIPIENT` is not injected in the workflow's `env:` block under "Run digest pipeline". If the intent is to send to a different address, it will silently use `MAILBOX_USER_ID` as the recipient without error. This should either be explicitly set via a secret, or the default behavior documented as intentional.

All five required secrets (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `MAILBOX_USER_ID`, `ANTHROPIC_API_KEY`) are present. `MAILBOX_FOLDER` is optional and present.

Recommendation: add `DIGEST_RECIPIENT: ${{ secrets.DIGEST_RECIPIENT }}` to the pipeline step's `env:` block. If the mailbox owner is always the recipient, add a comment in the workflow making that explicit so it is not a silent assumption.

#### 2. Cache key strategy — structural problem

Using `run_id` as the cache key means every run writes a new entry. The `restore-keys` prefix fallback will find the most recent entry on restore — that part works. However:

- Cache entries accumulate indefinitely. GitHub Actions retains cache entries for 7 days (or until the 10 GB repo limit is hit), then evicts LRU. With four cron triggers per day, that is ~28 entries per week and churn is high. The risk is that eviction removes a recent entry before the next run, causing a cold start and reprocessing emails already seen (wasted LLM calls, possibly duplicate digest content).
- The `always()` condition on "Save state" means a failed run still saves state. If the pipeline partially ran and corrupted state before failing, the corrupted state is persisted.

Recommendation: use a fixed key like `email-ingester-state` for both save and restore. Always overwrite the single canonical entry. This eliminates accumulation and ensures the latest successful state is always at the same key. Pair this with task 4D's atomic write + backup so corruption is recoverable at the file level rather than the cache level.

```yaml
# Recommended cache key (both restore and save)
key: email-ingester-state
```

The `restore-keys` prefix fallback becomes unnecessary with a fixed key and can be removed.

For the `always()` condition on save: it is correct to save state even if the pipeline step fails (state may have been partially updated and saving it avoids re-fetching), but this should be coupled with 4D's backup strategy so a corrupt state can be rolled back from `.bak`.

#### 3. Failure notifications — missing

There is no notification when the workflow fails. For a twice-daily digest system, a silent failure means the user simply does not receive the digest with no indication why. This could go unnoticed for days.

Recommendation: add a final step that runs `if: failure()` and sends a failure email via the Graph API (reusing the same sender credentials already in scope). However, this introduces a dependency on the pipeline code itself, which may have caused the failure.

Simpler alternative (no new code): use GitHub's built-in email notification for workflow failures — this is configured per-user in GitHub settings and requires no workflow changes. Document this as the expected failure alerting mechanism, since the system is single-user and the recipient already has a GitHub account.

If a workflow step is added, it should be the last step, use `if: failure()`, and be kept to a minimal `curl` call against the Graph API sendMail endpoint using the already-available secrets.

#### 4. Step ordering — correct, one minor issue

The order is correct: checkout → setup Python → install → DST guard → restore cache → run pipeline → save state.

One issue: the "Save state" step uses `if: steps.dst.outputs.skip != 'true' && always()`. The `always()` function in GitHub Actions always evaluates to `true`, but combining it with `&&` against a string comparison means this is actually `(steps.dst.outputs.skip != 'true') && true`, which is equivalent to just `steps.dst.outputs.skip != 'true'`. The `always()` is not doing what the author likely intended (which is "run this even if a prior step failed, as long as DST guard didn't skip").

To run save-state even on pipeline failure (but only when DST guard didn't skip), the correct expression is:

```yaml
if: steps.dst.outputs.skip != 'true' && (success() || failure())
```

`always()` would also skip this step if the workflow was cancelled, which is probably fine, but the current `always()` has no effect here as written due to operator precedence with `&&`.

#### 5. Other production gaps

**Timeout:** No `timeout-minutes` is set on the job or the pipeline step. GitHub Actions default is 360 minutes (6 hours). If the LLM call or Graph API call hangs, the job will block a runner for 6 hours. Recommend setting `timeout-minutes: 15` at the job level — the pipeline should complete in well under 5 minutes under normal conditions.

**Concurrency:** No `concurrency:` group is set. If a `workflow_dispatch` is triggered while a scheduled run is in flight, two instances will race on the same cache key, and the later save will win — which may overwrite good state with partial state. Recommend:

```yaml
concurrency:
  group: email-digest
  cancel-in-progress: false
```

`cancel-in-progress: false` queues rather than cancels so no run is silently dropped.

**Permissions:** No `permissions:` block is set, so the job runs with the repository's default token permissions. Since the pipeline does not use `GITHUB_TOKEN` (it uses explicit secrets for Graph and Anthropic), this has no functional impact. However, explicitly setting minimal permissions is good hygiene:

```yaml
permissions:
  contents: read
```

This follows the principle of least privilege and makes the intent explicit.

**DST guard robustness:** The DST guard compares `$HOUR` as a string against `"06"` and `"17"`. This works correctly with `date +%H` (zero-padded). No issue, but worth noting that this guard fires four cron triggers and only two run — the two off-target triggers complete in seconds and do nothing. This is intentional and acceptable.

**No `pip install --upgrade pip`:** Minor. The install step runs `pip install .` without upgrading pip first. This can cause warnings on older pip versions bundled with the Python setup action. Low severity.

### Files Modified

- None (findings only, per task scope)

### Summary of recommended changes for backend agent

| Priority | Change | Requires CTO? |
|----------|--------|---------------|
| High | Add `DIGEST_RECIPIENT` secret to pipeline env | Yes (env var change) |
| High | Fix cache key to fixed string `email-ingester-state`, remove `restore-keys` | No |
| High | Add `timeout-minutes: 15` at job level | No |
| High | Add `concurrency:` group to prevent race on cache | No |
| Medium | Fix save-state condition from `always()` to `success() \|\| failure()` | No |
| Medium | Add `permissions: contents: read` | No |
| Low | Document failure alerting via GitHub notification settings | No |
| Low | Add `pip install --upgrade pip` before `pip install .` | No |

---

## Task: Phase 5 Sprint Planning — Hardening
## Status: done

## Decisions Made

- **DST handling is correct at the pipeline level; gap is presentation only.** The workflow DST
  guard checks the actual America/New_York hour at runtime. UTC is used throughout storage and
  pipeline logic. The only gap: `sender.py` formats the digest subject with no timezone label,
  and email card timestamps in the template omit a timezone hint. Fix is a format-string change
  only — no model or interface change needed.

- **Token refresh/expiry needs no code change.** Token lifetime (3600s) vs pipeline runtime
  (<2 min) makes mid-run expiry a non-issue. `GraphAuthError` (401) and `GraphThrottleError`
  (429 with `retry_after`) are already raised correctly. For a cron job, a clean fatal error
  on auth failure is the right behavior. Task 5B is QA-only: assert the existing error behavior
  is tested.

- **`model_confidence` is dead weight in the scoring equation; zero the weight, keep the field.**
  `summarizer.py` hardcodes `model_confidence=0.5` unconditionally. The prompt never asks the
  LLM for a confidence value. The scorer applies a flat `+0.075` bonus to every email, which is
  noise. Decision: set `_CONFIDENCE_WEIGHT = 0.0` in `scorer.py`. The `model_confidence` field
  is retained in `EmailSummary` (no schema change) to preserve the hook for a future phase.
  Rationale for not removing the field from `models.py`: avoids touching the stable data
  contract, summarizer, and tests for a change that is semantically equivalent to zeroing the
  weight.

- **URL truncation bump from 60 to 80 chars is safe.** Jinja `truncate(60)` only affects the
  visible link text; the `href` is always the full URL. 60 chars routinely severs domain names
  mid-word. Bumping to 80 is cosmetic and low-risk.

- **LLM prompt is left unchanged.** It is clear and well-structured. Adding promotional/thread
  instructions introduces regression risk without an offline evaluation mechanism. Deferred.

## Files Modified

- `/Users/sebastianrodriguez/Projects/email-ingester-0/.gorp/plans/current-sprint.md` — Phase 5 sprint plan written

## Contracts Defined/Changed

No model or interface changes. All Phase 5 changes are within function bodies, constants, or
template strings:

- `sender.py` — format string only (no signature change)
- `scorer.py` — `_CONFIDENCE_WEIGHT` constant set to `0.0` (no signature change)
- `digest.html.j2` — template string changes only

`EmailSummary.model_confidence: float` is retained as-is in `models.py`.

## Blockers

None.
