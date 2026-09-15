"""UNTRUSTED INPUT handling for external repository content (SPEC_V1 §8).

Everything that comes from a candidate repository is data, never instruction.
This module is the canonical place that decides whether external text carries
instruction-like content and how such text is fenced for later consumers.
"""

from __future__ import annotations

import re

OPEN_MARKER = "<<UNTRUSTED_REPOSITORY_CONTENT>>"
CLOSE_MARKER = "<<END_UNTRUSTED_REPOSITORY_CONTENT>>"

#: Instruction-like patterns that must never influence control flow.
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all )?(the )?(previous|prior|above|earlier) instructions",
        r"disregard (all )?(the )?(previous|prior|above|earlier)",
        r"forget (everything|all|your instructions)",
        r"(print|reveal|show|repeat|send) (me )?(your |the )?(system|developer) (prompt|message)",
        r"you are now (a|an|the)\b",
        r"new instructions:",
        r"^\s*system\s*:",  # only at the start of a line
        r"do not (tell|inform) the user",
    )
)


def contains_prompt_injection(text: str | None) -> bool:
    """True when external text looks like an attempt to instruct the analyzer."""

    if not text:
        return False
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def wrap_untrusted(text: str | None, *, max_chars: int | None = None) -> str:
    """Fence external text so it can only ever be read as quoted data."""

    body = "" if text is None else str(text)
    if max_chars is not None and max_chars >= 0 and len(body) > max_chars:
        body = body[:max_chars]
    return f"{OPEN_MARKER}\n{body}\n{CLOSE_MARKER}"
