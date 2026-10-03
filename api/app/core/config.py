"""Runtime settings, all read from the environment (.env in development).

Every value here can be overridden per worktree, which is how the three lanes run
side by side against one Mongo container (see docs/spec/lanes.md).
"""

import re
from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that have appeared as SECRET_KEY defaults or examples. Never accepted.
PLACEHOLDER_SECRETS = frozenset({"dev-only-secret-change-me", "change-me", "changeme", "secret", "secret-key"})
PLACEHOLDER_WORDS = ("change-me", "changeme", "change_me", "replace-me", "placeholder", "example")
MIN_SECRET_BYTES = 32
KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


def parse_tax_keys(raw: str) -> dict[str, bytes]:
    """TAX_DATA_KEYS: comma-separated id:key pairs, each key a Fernet key (32 url-safe
    base64 bytes, as `make env` writes). Errors name the id, never the key."""
    keys: dict[str, bytes] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        kid, sep, key = item.partition(":")
        if not sep or not KEY_ID.fullmatch(kid):
            raise ValueError("TAX_DATA_KEYS must be id:key pairs separated by commas (ids: letters, digits, - and _)")
        if kid in keys:
            raise ValueError(f"TAX_DATA_KEYS lists the key id {kid!r} twice")
        try:
            Fernet(key.encode())
        except ValueError:
            raise ValueError(
                f"TAX_DATA_KEYS: key {kid!r} isn't a valid key (run make env, or make rotate-tax-key)"
            ) from None
        keys[kid] = key.encode()
    if not keys:
        raise ValueError("TAX_DATA_KEYS is missing: run make env to add one")
    return keys


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected secret must never be echoed into a log.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False, hide_input_in_errors=True)

    app_env: Literal["dev", "test", "prod"] = "dev"
    demo_mode: bool = True
    brand: str = "OneQuickJob"
    public_base_url: str = "https://dev.onequickjob.co.uk"

    # Mongo: one container, one database per worktree (oqj_main, oqj_l1, oqj_l2, oqj_l3).
    # A replica set (rs0), for multi-document transactions.
    mongo_url: str = "mongodb://oqj-mongo:27017/?replicaSet=rs0"
    mongo_db: str = "oqj_main"

    # Secrets, with no fallbacks: the API refuses to start without real ones (`make env`).
    # SECRET_KEY peppers login-code, session and token hashes: at least 32 random bytes.
    secret_key: SecretStr = Field(default=SecretStr(""), validate_default=True)
    # Tax identifiers (NI number, date of birth) are sealed with their own keys, never
    # SECRET_KEY: TAX_DATA_KEYS lists id:key pairs, TAX_DATA_KEY_CURRENT names the one new
    # values use. Every sealed value records its key id, so older keys stay usable until
    # `make rotate-tax-key` has re-encrypted everything.
    tax_data_keys: SecretStr = Field(default=SecretStr(""), validate_default=True)
    tax_data_key_current: str = ""

    # Auth
    cookie_name: str = "oqj_session"
    cookie_secure: bool = True
    session_days: int = 30
    login_code_ttl_minutes: int = 10
    login_code_max_attempts: int = 5
    login_code_min_interval_seconds: int = 30
    magic_link_ttl_hours: int = 72

    # Fees. Rates are decimals; money itself is always integer pence.
    fee_standard_rate: Decimal = Decimal("0.15")
    fee_own_rate: Decimal = Decimal("0.05")
    fee_own_min_pence: int = 100

    # Adapters, chosen by environment.
    payment_gateway: Literal["fake", "stripe"] = "fake"
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    ideal_postcodes_key: str = ""
    ideal_postcodes_base_url: str = "https://api.ideal-postcodes.co.uk"
    area_estimator: Literal["manual_bands_v0"] = "manual_bands_v0"
    files_dir: str = "/data/files"
    files_url_prefix: str = "/files"
    files_max_bytes: int = 10 * 1024 * 1024
    serve_files: bool = True

    # Background tasks (reminders, horizon top-up). Off in tests.
    tasks_enabled: bool = True
    tasks_interval_seconds: int = 60

    @property
    def address_lookup(self) -> Literal["fake", "ideal_postcodes"]:
        return "ideal_postcodes" if self.ideal_postcodes_key else "fake"

    @property
    def pepper(self) -> str:
        """SECRET_KEY, for keyed hashes (app.core.ids.token_hash)."""
        return self.secret_key.get_secret_value()

    def tax_keys(self) -> dict[str, bytes]:
        return parse_tax_keys(self.tax_data_keys.get_secret_value())

    @field_validator("secret_key")
    @classmethod
    def _real_secret(cls, v: SecretStr) -> SecretStr:
        key = v.get_secret_value().strip()
        if not key:
            raise ValueError("SECRET_KEY is missing: run make env (or set it to the output of openssl rand -hex 32)")
        if key.lower() in PLACEHOLDER_SECRETS or any(w in key.lower() for w in PLACEHOLDER_WORDS):
            raise ValueError("SECRET_KEY is a placeholder: set it to the output of openssl rand -hex 32")
        if len(key.encode()) < MIN_SECRET_BYTES or len(set(key)) < 8:
            raise ValueError(f"SECRET_KEY must be at least {MIN_SECRET_BYTES} random bytes: openssl rand -hex 32")
        return v

    @field_validator("tax_data_keys")
    @classmethod
    def _valid_tax_keys(cls, v: SecretStr) -> SecretStr:
        parse_tax_keys(v.get_secret_value())
        return v

    @model_validator(mode="after")
    def _current_tax_key_listed(self) -> Self:
        if self.tax_data_key_current not in self.tax_keys():
            raise ValueError("TAX_DATA_KEY_CURRENT must name one of the ids in TAX_DATA_KEYS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
