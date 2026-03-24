# Sprint: Hardening

Date: 2026-03-23
Phase: Phase 5 — Hardening
Status: **DONE**

## Tasks

| ID | Agent | Task | Status | Notes |
|----|-------|------|--------|-------|
| 5A | backend | Add UTC label to digest subject and template timestamps | done | sender.py subject + template card timestamps now include "UTC" |
| 5B | qa | Validate DST guard and token expiry handling | done | 10 auth tests + 22 ingester tests (DST offsets, auth errors, success paths) |
| 5C | backend | Fix `model_confidence` dead weight in scorer | done | `_CONFIDENCE_WEIGHT = 0.0`; existing test updated to assert no effect |
| 5D | backend | Bump URL truncation from 60 to 80 chars | done | Both high and medium sections in template updated |
| 5E | qa | Full regression pass | done | 97 tests passing, ruff check + format clean |

## Final Quality Gate

- ruff check: pass
- ruff format: pass
- pytest: 97 passed, 0 failed
- No new dependencies introduced
