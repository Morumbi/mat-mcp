"""Plain-text application logging."""

from __future__ import annotations

import logging


def configure_logging() -> logging.Logger:
    """Configure conventional, non-JSON application logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    return logging.getLogger("mat_mcp")
