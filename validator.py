from __future__ import annotations

from config import COMPLIANCE_REPLACEMENTS


def sanitize_compliance_text(text: str) -> str:
    safe = str(text or "")
    for old, new in COMPLIANCE_REPLACEMENTS.items():
        safe = safe.replace(old, new)
    return safe
