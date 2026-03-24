"""Load and save pipeline state (processed IDs + delta token) as JSON."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
from typing import TYPE_CHECKING

from email_ingester.models import State

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_state(raw: dict) -> State:
    """Construct a State from a parsed JSON dict."""
    return State(
        delta_token=raw.get("delta_token"),
        processed_ids=set(raw.get("processed_ids", [])),
        last_run=raw.get("last_run"),
    )


def load_state(path: Path) -> State:
    """Load state from a JSON file. Returns empty state if file is missing or corrupt.

    Falls back to ``path.with_suffix('.json.bak')`` before giving up.
    """
    bak_path = path.with_suffix(".json.bak")

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return _parse_state(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Corrupt state file at %s (%s), attempting backup", path, exc)
    else:
        logger.info("No state file found at %s, attempting backup", path)

    if bak_path.exists():
        try:
            raw = json.loads(bak_path.read_text(encoding="utf-8"))
            logger.info("Loaded state from backup %s", bak_path)
            return _parse_state(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Corrupt backup state file at %s (%s), starting fresh", bak_path, exc)
    else:
        logger.info("No backup state file found at %s, starting fresh", bak_path)

    return State()


def save_state(path: Path, state: State) -> None:
    """Save state to a JSON file using an atomic write.

    If a previous state file exists it is copied to ``path.with_suffix('.json.bak')``
    before the new file is written.  The new content is first written to a
    temporary file in the same directory, then renamed into place so that a
    crash mid-write never leaves a partial (corrupt) state file.
    """
    data = {
        "delta_token": state.delta_token,
        "processed_ids": sorted(state.processed_ids),
        "last_run": state.last_run,
    }
    content = json.dumps(data, indent=2) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)

    # Back up the existing file before overwriting.
    if path.exists():
        bak_path = path.with_suffix(".json.bak")
        shutil.copy2(path, bak_path)
        logger.debug("Backed up state file to %s", bak_path)

    # Write to a temp file in the same directory, then atomically replace.
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the orphaned temp file on any failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    logger.info("State saved to %s (%d processed IDs)", path, len(state.processed_ids))
