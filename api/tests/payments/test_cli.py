"""The Stripe test-mode helpers: test keys only, and the env file edited in place."""

import os

import pytest

from app.payments.cli import read_env, require_test_key, set_env


def test_only_test_keys(tmp_path):
    with pytest.raises(SystemExit) as e:
        require_test_key({"STRIPE_SECRET_KEY": "sk_live_abc"})
    assert "abc" not in str(e.value)
    with pytest.raises(SystemExit):
        require_test_key({})
    assert require_test_key({"STRIPE_SECRET_KEY": "sk_test_abc"}) == "sk_test_abc"


def test_set_env_replaces_one_line_and_keeps_permissions(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nSTRIPE_WEBHOOK_SECRET=\n# note\n")
    os.chmod(env, 0o600)
    set_env(env, "STRIPE_WEBHOOK_SECRET", "whsec_x")
    set_env(env, "NEW", "2")
    assert env.read_text() == "A=1\nSTRIPE_WEBHOOK_SECRET=whsec_x\n# note\nNEW=2\n"
    assert env.stat().st_mode & 0o777 == 0o600
    assert read_env(env)["STRIPE_WEBHOOK_SECRET"] == "whsec_x"
