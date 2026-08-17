from __future__ import annotations

import re

# Indian mobiles: 10 digits starting 6-9. Always send as 91 + those 10 digits.
_MOBILE_START = re.compile(r"^[6-9]\d{9}$")


def _digits(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float):
        if raw != raw:  # NaN
            return ""
        raw = str(int(raw))
    elif isinstance(raw, int):
        raw = str(raw)
    else:
        raw = str(raw).strip()
    if not raw or raw.upper() == "NULL":
        return ""
    return re.sub(r"\D", "", raw)


def normalize_in_mobile(raw) -> tuple[str | None, str | None]:
    """Return (ten_digit, wa_to) or (None, None) if not a valid Indian mobile."""
    digits = _digits(raw)
    if not digits:
        return None, None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if _MOBILE_START.fullmatch(digits):
        return digits, "91" + digits
    return None, None


def is_valid_mobile(raw) -> bool:
    ten, _ = normalize_in_mobile(raw)
    return ten is not None
