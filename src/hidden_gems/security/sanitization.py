"""Sanitization of untrusted external text before it reaches the report.

Repository descriptions and READMEs are attacker-controlled input. Nothing is
emitted raw into a GitHub Issue: HTML/script blocks are dropped, control
characters and instruction-like prompt-injection content are removed, and the
result is truncated to a bounded length.
"""

from __future__ import annotations

import re

_SCRIPT_BLOCK = re.compile(r"<\s*(script|style)\b.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]{0,400}>", re.DOTALL)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")

#: Instruction-like content that must never be rendered as if the system had
#: accepted it (see also `security.untrusted_content`).
_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all )?(the )?(previous|prior|above|earlier) instructions",
        r"disregard (all )?(the )?(previous|prior|above|earlier)",
        r"forget (everything|your instructions)",
        r"(print|reveal|show|repeat) (me )?(your )?(the )?system prompt",
        r"you are now (a|an|the)\b",
        r"new instructions:",
    )
)

_REDACTION = "[external instruction-like content removed]"
_ELLIPSIS = "…"


def contains_prompt_injection(text: str) -> bool:
    """True when ``text`` looks like an attempt to instruct the analyzer."""

    return any(pattern.search(text or "") for pattern in _INJECTION_PATTERNS)


def _clean(text: str, *, max_chars: int) -> str:
    value = str(text or "")
    if contains_prompt_injection(value):
        return _REDACTION[:max_chars]
    value = _SCRIPT_BLOCK.sub(" ", value)
    value = _HTML_COMMENT.sub(" ", value)
    value = _TAG.sub(" ", value)
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = _CONTROL.sub(" ", value)
    value = value.replace("`", "'").replace("*", "")
    value = _WHITESPACE.sub(" ", value).strip()
    value = value.lstrip("#").strip()
    if len(value) > max_chars:
        value = value[: max_chars - 1].rstrip() + _ELLIPSIS
    return value


def sanitize_markdown_text(text: str, *, max_chars: int = 600) -> str:
    """Sanitize one paragraph of untrusted text for report emission."""

    return _clean(text, max_chars=max_chars)


def sanitize_inline(text: str, *, max_chars: int = 200) -> str:
    """Sanitize a short inline value (language, tag, single-line field)."""

    return _clean(text, max_chars=max_chars)
