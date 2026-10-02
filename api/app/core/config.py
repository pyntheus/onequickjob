"""Runtime settings, all read from the environment (.env in development).

Every value here can be overridden per worktree, which is how the three lanes run
side by side against one Mongo container (see docs/spec/lanes.md).
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["dev", "test", "prod"] = "dev"
    demo_mode: bool = True
    brand: str = "OneQuickJob"
    public_base_url: str = "https://dev.onequickjob.co.uk"

    # Mongo: one container, one database per worktree (oqj_main, oqj_l1, oqj_l2, oqj_l3).
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "oqj_main"

    # Secrets. SECRET_KEY peppers code and token hashes and derives the sealing key
    # for tax identifiers. It must be long and random outside tests.
    secret_key: str = Field(default="dev-only-secret-change-me", min_length=16)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
