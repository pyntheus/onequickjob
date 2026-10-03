"""Command-line tools (python -m app.cli.<tool>)."""

import secrets

from cryptography.fernet import Fernet

from app.core.config import Settings


def offline_settings() -> Settings:
    """Settings for tools that only read code (the OpenAPI schema, generated docs): throwaway
    keys, since nothing is hashed or sealed, and no database or file serving."""
    return Settings(
        secret_key=secrets.token_hex(32),
        tax_data_keys=f"offline:{Fernet.generate_key().decode()}",
        tax_data_key_current="offline",
        serve_files=False,
    )
