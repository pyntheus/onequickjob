"""UK phone numbers, stored in E.164 (+447700900123)."""

import re

_DIGITS = re.compile(r"\D+")


class InvalidPhone(ValueError):
    pass


def to_e164(raw: str) -> str:
    """Normalise a UK number typed any common way to E.164.

    Accepts 07700 900123, +44 7700 900123, 0044 7700 900123 and 447700900123.
    Only UK numbers are accepted; the service area is High Wycombe.
    """
    s = raw.strip()
    digits = _DIGITS.sub("", s)
    if s.startswith("+"):
        if not digits.startswith("44"):
            raise InvalidPhone("Only UK numbers are supported")
        national = digits[2:]
    elif digits.startswith("0044"):
        national = digits[4:]
    elif digits.startswith("44") and len(digits) == 12:
        national = digits[2:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        raise InvalidPhone("Enter a UK number, for example 07700 900123")
    national = national.removeprefix("0")
    if not (9 <= len(national) <= 10) or national[0] not in "123789":
        raise InvalidPhone("That doesn't look like a UK phone number")
    return f"+44{national}"


def is_mobile(e164: str) -> bool:
    return e164.startswith("+447")


def to_national(e164: str) -> str:
    """+447700900123 -> 07700 900123 (mobiles); other numbers 0 + national digits."""
    national = "0" + e164.removeprefix("+44")
    if len(national) == 11 and national.startswith("07"):
        return f"{national[:5]} {national[5:]}"
    return national


def mask(e164: str) -> str:
    """07700 9•••23: enough to recognise, not enough to copy."""
    n = to_national(e164)
    return n[:7] + "•••" + n[-2:]
