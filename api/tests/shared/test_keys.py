"""Keys (decisions.md A8): SECRET_KEY has no fallback and must be real; tax identifiers are
sealed with their own keys, each value records its key id, and rotation re-encrypts."""

import os
import secrets

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.cli import tax_keys
from app.core import crypto
from app.core.config import Settings, get_settings
from app.core.timeutil import utcnow
from app.models.providers import TaxIdentity
from app.repos import TaxIdentities
from tests.conftest import make_settings

GOOD_SECRET = secrets.token_hex(32)


def _tax(**ids: str) -> dict:
    return {"tax_data_keys": ",".join(f"{k}:{v}" for k, v in ids.items())}


@pytest.mark.parametrize(
    "secret",
    [
        "",  # missing
        "dev-only-secret-change-me",  # the old built-in default
        "change-me",
        "please-change-me-0123456789abcdef0123456789",  # long, but a placeholder
        "x" * 64,  # long, but not random
        "0123456789abcdef0123456789abcde",  # 31 bytes
    ],
)
def test_a_missing_placeholder_or_short_secret_key_is_refused(secret):
    with pytest.raises(ValidationError, match="SECRET_KEY") as e:
        make_settings(secret_key=secret)
    if secret:
        assert secret not in str(e.value), "a rejected secret is never echoed"


def test_the_api_refuses_to_start_without_a_secret_key(monkeypatch):
    from app.main import create_app

    monkeypatch.delenv("SECRET_KEY")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="SECRET_KEY is missing"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_a_real_secret_key_is_accepted():
    assert make_settings(secret_key=GOOD_SECRET).pepper == GOOD_SECRET
    assert GOOD_SECRET not in repr(make_settings(secret_key=GOOD_SECRET))


@pytest.mark.parametrize(
    ("keys", "current", "message"),
    [
        ("", "k1", "TAX_DATA_KEYS is missing"),
        ("no-colon", "k1", "id:key pairs"),
        ("k1:not-a-fernet-key", "k1", "isn't a valid key"),
        ("k1:{a},k1:{b}", "k1", "twice"),
        ("k1:{a}", "k2", "TAX_DATA_KEY_CURRENT"),
    ],
)
def test_tax_data_keys_are_checked_without_echoing_them(keys, current, message):
    a, b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    raw = keys.format(a=a, b=b)
    with pytest.raises(ValidationError, match=message) as e:
        make_settings(tax_data_keys=raw, tax_data_key_current=current)
    assert a not in str(e.value) and b not in str(e.value)


def test_tax_data_keys_are_independent_of_the_secret_key():
    sealed = crypto.seal("QQ123456C")
    other_secret = make_settings(secret_key=secrets.token_hex(32))
    assert crypto.unseal(sealed, other_secret) == "QQ123456C"


def _settings_from(env_file) -> Settings:
    lines = env_file.read_text().splitlines()
    return make_settings(
        tax_data_keys=tax_keys._get(lines, "TAX_DATA_KEYS"),
        tax_data_key_current=tax_keys._get(lines, "TAX_DATA_KEY_CURRENT"),
    )


async def test_rotation_end_to_end(db, tmp_path, capsys):
    """make rotate-tax-key's steps: add a key (current), re-encrypt everything, retire the old."""
    env = tmp_path / ".env"
    k1 = Fernet.generate_key().decode()
    env.write_text(f"SECRET_KEY={GOOD_SECRET}\nTAX_DATA_KEYS=k1:{k1}\nTAX_DATA_KEY_CURRENT=k1\nDEMO_MODE=true\n")
    os.chmod(env, 0o600)
    before = _settings_from(env)
    people = {f"p{i}": (f"QQ12345{i}C", f"19{50 + i}-03-14") for i in range(3)}
    for pid, (ni, dob) in people.items():
        await TaxIdentities(db).insert(
            TaxIdentity(
                provider_id=pid,
                ni_number_sealed=crypto.seal(ni, before),
                dob_sealed=crypto.seal(dob, before),
                updated_at=utcnow(),
            )
        )

    assert tax_keys.add_key(env) == "k2"
    during = _settings_from(env)
    assert during.tax_data_key_current == "k2" and set(during.tax_keys()) == {"k1", "k2"}
    assert (env.stat().st_mode & 0o777) == 0o600 and "DEMO_MODE=true" in env.read_text()
    old = await TaxIdentities(db).find_one({"provider_id": "p0"})
    assert crypto.unseal(old.ni_number_sealed, during) == people["p0"][0], "old values stay readable"

    assert await tax_keys.reencrypt(db, during) == (6, 0)
    assert await tax_keys.reencrypt(db, during) == (0, 0), "idempotent"

    assert tax_keys.retire_keys(env, keep="k2") == ["k1"]
    after = _settings_from(env)
    assert set(after.tax_keys()) == {"k2"}
    for t in await TaxIdentities(db).find({}):
        assert crypto.key_id(t.ni_number_sealed) == crypto.key_id(t.dob_sealed) == "k2"
        assert (crypto.unseal(t.ni_number_sealed, after), crypto.unseal(t.dob_sealed, after)) == people[t.provider_id]
        with pytest.raises(ValueError, match="'k2' isn't in TAX_DATA_KEYS"):
            crypto.unseal(t.ni_number_sealed, before)
    out = capsys.readouterr()
    assert k1 not in out.out + out.err


def test_overlapping_rotations_never_retire_a_key_in_use(tmp_path):
    """Codex (high): rotation A re-encrypted to k2, then B added k3 before A retired. A's retire
    must not drop k2 (make also holds a lock around the whole rotation)."""
    env = tmp_path / ".env"
    env.write_text(f"TAX_DATA_KEYS=k1:{Fernet.generate_key().decode()}\nTAX_DATA_KEY_CURRENT=k1\n")
    assert tax_keys.add_key(env) == "k2"  # rotation A
    assert tax_keys.add_key(env) == "k3"  # rotation B, overlapping
    before = env.read_text()
    with pytest.raises(SystemExit, match="not 'k2'"):
        tax_keys.retire_keys(env, keep="k2")
    assert env.read_text() == before, "nothing retired"
    assert tax_keys.retire_keys(env, keep="k3") == ["k1", "k2"]  # B, after re-encrypting to k3


def test_reencrypt_only_acts_on_the_key_the_rotation_added(capsys):
    assert tax_keys.main(["reencrypt", "--expect-current", "k9"]) == 1
    assert "not re-encrypting" in capsys.readouterr().err


async def test_reencrypt_refuses_to_finish_while_a_value_is_unreadable(db):
    """make stops before retire unless every value is under the current key."""
    ghost = make_settings(tax_data_keys=f"k9:{Fernet.generate_key().decode()}", tax_data_key_current="k9")
    await TaxIdentities(db).insert(
        TaxIdentity(
            provider_id="p",
            ni_number_sealed=crypto.seal("QQ1", ghost),
            dob_sealed=crypto.seal("1960", ghost),
            updated_at=utcnow(),
        )
    )
    with pytest.raises(ValueError, match="'k9' isn't in TAX_DATA_KEYS"):
        await tax_keys.reencrypt(db, make_settings())
