"""Enables `python -m email_ingester`."""

from __future__ import annotations

import logging
import sys

from email_ingester.main import main

logger = logging.getLogger(__name__)

try:
    main()
except Exception:
    logger.exception("Pipeline failed")
    sys.exit(1)
