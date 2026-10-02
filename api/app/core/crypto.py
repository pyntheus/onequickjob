"""Sealing for the few values we must keep in full but never display: a provider's
National Insurance number and date of birth (needed for HMRC platform reporting).

Providers' documents hold only masked copies (QQ •• •• •• C). The full values live in
the tax_identities collection, sealed with a key derived from SECRET_KEY, and are
unsealed only by the HMRC export (L3). See decisions.md.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


def _fernet(settings: Settings | None = None) -> Fernet:
    s = settings or get_settings()
    key = hashlib.sha256(("tax-identity:" + s.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(value: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(value.encode()).decode()


def unseal(token: str, settings: Settings | None = None) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as e:  # pragma: no cover - only with a rotated SECRET_KEY
        raise ValueError("cannot unseal: SECRET_KEY changed since this was stored") from e


def mask_ni(ni: str) -> str:
    """QQ123456C -> QQ •• •• •• C."""
    n = ni.replace(" ", "").upper()
    return f"{n[:2]} •• •• •• {n[-1:]}" if len(n) >= 3 else "•••"


def mask_dob(iso_date: str) -> str:
    """1958-03-14 -> •• / •• / 1958."""
    return f"•• / •• / {iso_date[:4]}"
