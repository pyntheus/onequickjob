"""Sealing for the few values we must keep in full but never display: a provider's
National Insurance number and date of birth (needed for HMRC platform reporting).

Providers' documents hold only masked copies (QQ •• •• •• C). The full values live in
the tax_identities collection, sealed (Fernet) with the tax data keys, which are
independent of SECRET_KEY, and are unsealed only by the HMRC export (L3).

A sealed value is "<key id>:<token>", so it says which key sealed it. New values use
TAX_DATA_KEY_CURRENT; any key still listed in TAX_DATA_KEYS opens older ones. `make
rotate-tax-key` adds a key, makes it current, re-encrypts (reseal) and then retires the old
key. See decisions.md A8.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings

# Where sealed values live: collection -> fields. app.cli.tax_keys re-encrypts these.
SEALED_FIELDS: dict[str, tuple[str, ...]] = {"tax_identities": ("ni_number_sealed", "dob_sealed")}


def seal(value: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    kid = s.tax_data_key_current
    return f"{kid}:{Fernet(s.tax_keys()[kid]).encrypt(value.encode()).decode()}"


def key_id(sealed: str) -> str:
    """The id of the key a value was sealed with."""
    kid, sep, _ = sealed.partition(":")
    if not sep:
        raise ValueError("not a sealed value (no key id)")
    return kid


def unseal(sealed: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    kid = key_id(sealed)
    key = s.tax_keys().get(kid)
    if key is None:
        raise ValueError(f"cannot unseal: tax data key {kid!r} isn't in TAX_DATA_KEYS")
    try:
        return Fernet(key).decrypt(sealed.partition(":")[2].encode()).decode()
    except InvalidToken as e:
        raise ValueError(f"cannot unseal: tax data key {kid!r} doesn't open this value") from e


def reseal(sealed: str, settings: Settings | None = None) -> str | None:
    """The value sealed again with the current key, or None if it already is."""
    s = settings or get_settings()
    if key_id(sealed) == s.tax_data_key_current:
        return None
    return seal(unseal(sealed, s), s)


def mask_ni(ni: str) -> str:
    """QQ123456C -> QQ •• •• •• C."""
    n = ni.replace(" ", "").upper()
    return f"{n[:2]} •• •• •• {n[-1:]}" if len(n) >= 3 else "•••"


def mask_dob(iso_date: str) -> str:
    """1958-03-14 -> •• / •• / 1958."""
    return f"•• / •• / {iso_date[:4]}"
