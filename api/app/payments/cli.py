"""Stripe test-mode helpers, run on the host from api/ (docs/spec/payments.md):

    uv run python -m app.payments.cli webhook-secret --env-file ../.env
        Ask the Stripe CLI for this machine's webhook signing secret (stripe listen
        --print-secret) and write it to STRIPE_WEBHOOK_SECRET. Prints no secret.

    uv run python -m app.payments.cli smoke --env-file ../.env [--account acct_...]
        The L3 acceptance run against real Stripe test mode: a connected Express account
        (onboard it through the printed link with Stripe's test values), a saved test card,
        a £30 standard and a £15 own-customer charge, half of the £30 refunded, each checked
        to the penny. Refuses anything but a test key.

Keys are read from the env file and never printed.
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.adapters.payments import SECRET_PREFIXES, key_mode, stripe_client
from app.adapters.payments.base import CustomerRef, ProviderRef, VisitRef
from app.adapters.payments.stripe_gateway import StripeGateway, as_dict, ref_id
from app.core import money

DASHBOARD = "https://dashboard.stripe.com/test"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def set_env(path: Path, name: str, value: str) -> None:
    """Set one line, atomically, keeping the file's permissions (.env is 0600)."""
    lines = path.read_text().splitlines()
    if any(line.startswith(f"{name}=") for line in lines):
        lines = [f"{name}={value}" if line.startswith(f"{name}=") else line for line in lines]
    else:
        lines.append(f"{name}={value}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def require_test_key(env: dict[str, str]) -> str:
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key:
        sys.exit("STRIPE_SECRET_KEY is empty in the env file. Add a test key (sk_test_...) first.")
    if key_mode(key, SECRET_PREFIXES) != "test":
        sys.exit("STRIPE_SECRET_KEY isn't a Stripe test key (sk_test_...). These helpers only run in test mode.")
    return key


def webhook_secret(env_file: Path) -> None:
    key = require_test_key(read_env(env_file))
    stripe_cli = shutil.which("stripe") or str(Path.home() / ".local/bin/stripe")
    if not Path(stripe_cli).exists():
        sys.exit("The Stripe CLI isn't installed (see docs/spec/payments.md).")
    # STRIPE_API_KEY in the environment rather than --api-key, so the key isn't in the process list.
    run = subprocess.run(  # noqa: S603 - a fixed command, no shell
        [stripe_cli, "listen", "--print-secret"],
        env={**os.environ, "STRIPE_API_KEY": key},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    secret = run.stdout.strip()
    if run.returncode != 0 or not secret.startswith("whsec_"):
        sys.exit("The Stripe CLI didn't return a webhook secret. Is the key right? (stripe listen --print-secret)")
    set_env(env_file, "STRIPE_WEBHOOK_SECRET", secret)
    print(f"STRIPE_WEBHOOK_SECRET written to {env_file}. Restart the API (make dev) to use it.")


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok ' if ok else 'BAD'} {label}: {got}" + ("" if ok else f" (expected {want})"))
    return ok


async def smoke(env_file: Path, account: str | None) -> bool:
    env = read_env(env_file)
    client = stripe_client(require_test_key(env))
    gw = StripeGateway(client, env.get("STRIPE_PUBLISHABLE_KEY", ""))
    run = time.strftime("%Y%m%d%H%M%S")
    good = True

    print("1. Provider: an Express connected account (country GB, individual)")
    if account is None:
        acct = await gw.create_provider_account(ProviderRef(provider_id=f"smoke-{run}", name="Smoke Test Provider"))
        account = acct.account_id
        url = await gw.onboarding_link(
            account, return_url="https://example.com/done", refresh_url="https://example.com/again"
        )
        print(f"  Created {account}. Open this link and use Stripe's test values (docs/spec/payments.md):\n  {url}")
    state = await gw.account_status(account)
    deadline = time.monotonic() + 15 * 60
    while state.status != "enabled" and time.monotonic() < deadline:
        print(
            f"  waiting for onboarding to finish ({state.status}; due: {', '.join(state.requirements_due[:4]) or '-'})"
        )
        await asyncio.sleep(10)
        state = await gw.account_status(account)
    if state.status != "enabled":
        print(f"  Onboarding didn't finish. Re-run with --account {account} once it has.")
        return False
    print(f"  {account} can take payments and receive payouts.")

    print("2. Customer: a Customer on the platform, card saved with a SetupIntent (test card pm_card_visa)")
    setup = await gw.save_card_setup(CustomerRef(customer_id=f"smoke-{run}", name="Smoke Test Customer"))
    await client.v1.setup_intents.confirm_async(setup.setup_id, {"payment_method": "pm_card_visa"})
    st = await gw.card_setup_status(setup.setup_id)
    good &= check("card saved", (st.status, st.card.last4 if st.card else None), ("succeeded", "4242"))

    charges: list[tuple[str, money.Split]] = []
    for label, price, source in (("£30 standard", 3000, "platform"), ("£15 own customer", 1500, "own_customer")):
        split = money.split_for_visit(price, source, "provider")  # type: ignore[arg-type]
        print(f"3. Charge {label}: fee {split.fee_pence}p from money.py, {split.provider_pence}p to the provider")
        visit = VisitRef(
            visit_id=f"smoke-{run}-{price}",
            booking_id=f"smoke-{run}",
            customer_id=f"smoke-{run}",
            gateway_customer_id=setup.gateway_customer_id,
            description=f"OneQuickJob smoke test, {label}",
        )
        res = await gw.charge_visit(
            visit, split.price_pence, split.fee_pence, account, idempotency_key=f"smoke:{run}:{price}"
        )
        good &= check("status", res.status, "succeeded")
        if res.status != "succeeded" or not res.charge_id:
            continue
        ch = as_dict(await client.v1.charges.retrieve_async(res.charge_id, {"expand": ["transfer", "application_fee"]}))
        transfer = as_dict(ch.get("transfer"))
        fee = as_dict(ch.get("application_fee"))
        good &= check("settlement merchant (on_behalf_of)", ref_id(ch.get("on_behalf_of")), account)
        good &= check("transfer destination", ref_id(transfer.get("destination")), account)
        good &= check("our fee (application fee)", fee.get("amount"), split.fee_pence)
        good &= check(
            "provider receives", (transfer.get("amount") or 0) - (fee.get("amount") or 0), split.provider_pence
        )
        print(f"  {DASHBOARD}/payments/{res.payment_intent_id}")
        charges.append((res.charge_id, split))

    if charges:
        ch_id, split = charges[0]
        half = money.refund_split(split, split.price_pence // 2)
        print(
            f"4. Refund half of the £30: {half.price_pence}p, of which our fee {half.fee_pence}p, "
            f"provider {half.provider_pence}p"
        )
        out = await gw.refund(
            ch_id, half.price_pence, half.fee_pence, reason="Smoke test", idempotency_key=f"smoke:{run}:refund"
        )
        good &= check("refund", (out.status, out.fee_refunded_pence), ("succeeded", half.fee_pence))
        ch = as_dict(await client.v1.charges.retrieve_async(ch_id, {"expand": ["transfer", "application_fee"]}))
        good &= check("refunded to the customer", ch.get("amount_refunded"), half.price_pence)
        good &= check("fee returned", as_dict(ch.get("application_fee")).get("amount_refunded"), half.fee_pence)
        good &= check(
            "transfer reversed (provider-funded)", as_dict(ch.get("transfer")).get("amount_reversed"), half.price_pence
        )

    print(f"Connected account: {DASHBOARD}/connect/accounts/{account}")
    print("Webhooks: with stripe listen running, the API logs each event; see payment_events in Mongo.")
    print("All checks passed." if good else "Some checks FAILED (marked BAD above).")
    return good


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.payments.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("webhook-secret", help="write stripe listen's signing secret to the env file")
    w.add_argument("--env-file", type=Path, default=Path("../.env"))
    s = sub.add_parser("smoke", help="the L3 acceptance run in Stripe test mode")
    s.add_argument("--env-file", type=Path, default=Path("../.env"))
    s.add_argument("--account", help="an onboarded connected account to reuse")
    args = p.parse_args(argv)
    if args.cmd == "webhook-secret":
        webhook_secret(args.env_file)
        return 0
    return 0 if asyncio.run(smoke(args.env_file, args.account)) else 1


if __name__ == "__main__":
    sys.exit(main())
