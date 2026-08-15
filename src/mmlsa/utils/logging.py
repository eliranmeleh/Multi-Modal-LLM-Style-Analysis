"""Structured logging.

Two renderings of the same event stream: human-readable on a terminal, JSON when the output is
redirected to a file. A long run's log is read twice — once live while it is running, and once
afterwards when something needs explaining — and those two readings want different formats.

Logs go to **stderr**, so that stdout stays clean for machine-readable CLI output.
Nothing outside ``cli.py`` may call ``print``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog

_configured = False


def configure_logging(
    *,
    verbose: bool = False,
    json_output: bool | None = None,
    log_file: Path | None = None,
) -> None:
    """Configure structlog once per process.

    ``json_output`` defaults to True when stderr is not a terminal, which is what makes a redirected
    run log machine-readable without anyone having to remember a flag.
    """
    global _configured

    if json_output is None:
        json_output = not sys.stderr.isatty()

    level = logging.DEBUG if verbose else logging.INFO

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(format="%(message)s", handlers=handlers, level=level, force=True)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging with defaults if that has not happened yet."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
