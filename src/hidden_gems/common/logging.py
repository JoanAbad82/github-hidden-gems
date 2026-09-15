"""Logging helpers that never emit secrets or the full environment."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(authorization\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([A-Za-z0-9._\-]{8,})", re.IGNORECASE),
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{8,})"),
    re.compile(r"(sk-[A-Za-z0-9]{8,})"),
    re.compile(r"((?:api[_-]?key|token|password|secret)\s*[:=]\s*)(\S+)", re.IGNORECASE),
)


def redact(text: str) -> str:
    """Best-effort redaction applied to every log record."""

    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - stdlib API
        return redact(super().format(record))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
