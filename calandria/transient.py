"""Which failures are worth retrying.

Shared by transcription and translation, because the judgement is the same in
both: a quota or capacity error clears on its own, while a malformed request or
a bad key does not, and retrying the second kind only burns the budget the
first kind was going to need.
"""

from __future__ import annotations

TRANSIENT_STATUSES = (429, 500, 502, 503, 504)


def is_transient(exc: BaseException) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in TRANSIENT_STATUSES:
        return True
    text = str(exc)
    return (any(str(s) in text for s in TRANSIENT_STATUSES)
            or "UNAVAILABLE" in text
            or "RESOURCE_EXHAUSTED" in text)
