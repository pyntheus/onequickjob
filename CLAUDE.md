# OneQuickJob: read this first

A local marketplace for non-certified home and garden jobs (mowing, cleaning, flat-pack,
small repairs...) around High Wycombe. This repo is a **private working prototype** at
https://dev.onequickjob.co.uk (basic auth). The UX and copy spec is
`docs/design/prototype.jsx` (village theme only); the plan is `docs/design/build-pack.md`.
Detail lives in `docs/spec/`: start with `decisions.md` and `lanes.md`.

## Stack (settled, don't reopen)

- `api/`: Python 3.14 via uv (never the system Python), FastAPI, Pydantic v2, PyMongo
  `AsyncMongoClient` (not Motor), no ODM (models in `app/models`, one repo per collection in
  `app/repos`), ruff, pytest + pytest-asyncio + httpx.
- `web/`: Vite + React + strict TypeScript, React Router, TanStack Query, types generated from
  the OpenAPI schema (`make types`), plain CSS ported from the prototype (same class names).
  Routes: `/` customer, `/p` provider (PWA), `/admin`.
- `infra/`: Docker Compose (shared Mongo, a single-node replica set `rs0`, + Caddy; per-worktree
  api + web), `seed/`: seed JSON.

## Rules that never bend

1. **Money is integer pence.** Fees come only from `api/app/core/money.py` (15%; own
   customers 5% with a 100p minimum; tips none). Round with `app.core.rounding` (Decimal,
   half-up), never `round()` or floats. The pricing golden tests never change.
2. **Agency wording.** The customer's agreement is with the named provider; we are their
   booking and payment agent; the commission is always shown. Never promise or guarantee.
3. **Outbox only.** No real SMS, WhatsApp or email: everything goes through
   `app.services.notify.notify` into the outbox. No new external services without a decision.
4. **Security.** Only Caddy publishes ports (80, 443); API and web bind 127.0.0.1; Mongo
   publishes nothing. `make check` must pass. No secrets or live keys in the repo; Stripe test
   keys only.
5. **DEMO_MODE** features (Outbox drawer, Switch user, banner, simulators) must vanish when
   `DEMO_MODE=false`, in the API as well as the web.
6. **First acceptance is atomic**: use `app.services.marketplace`, never your own update.
7. Times stored UTC, shown Europe/London; phones E.164; UK English copy.
8. **Stay in your lane** (`docs/spec/lanes.md`). Don't edit files you don't own; write
   `docs/spec/contract-changes/<lane>.md` instead. Shared logic is in `app/services`: call it,
   don't copy it.
9. **Never merge.** Push your branch, open a PR, report. Hasan merges.

**Stop and ask (in your report, don't guess):** anything that changes money, fees or pricing
semantics; the auth or security model; adding an external service; dropping a prototype
feature; anything the golden tests can't pass without changing a model.

## Run and test

```bash
make env        # once per worktree: .env from .env.example with fresh secrets
make dev        # shared Mongo + Caddy, then this worktree's API and web (ports from .env)
make test       # pytest in the api container (against <MONGO_DB>_test) + vitest
make lint       # ruff, eslint, tsc, and generated API types up to date
make types      # after changing the API: regenerate web/src/api/schema.d.ts
make seed       # demo data (idempotent); make seed-reset drops and reseeds
make check      # nothing but Caddy and sshd exposed publicly
make docs       # regenerate notifications.md, api.md, domain.md from the code
make rotate-tax-key  # new tax data key: current, re-encrypt, retire the old (decisions.md A8)
```

`make test-api ARGS="tests/shared/test_auth.py -x"` runs a subset. Lanes are viewed through
an SSH tunnel to their web port (see `README.md`).

## Writing to several collections

One transaction, always this way (`app.core.db.transaction`; decisions.md A7):

```python
from app.core.db import DbSession, transaction

async def accept_invite(db: Db, s: Settings, invite: OwnCustomerInvite, ...) -> Booking:
    # Checks that can fail fast go here, on plain reads.

    async def accept(session: DbSession) -> Booking:
        if await OwnCustomerInvites(db).update(
            invite.id, {"status": "accepted"}, extra_filter={"status": "invited"}, session=session
        ) is None:
            fail(409, "not_open", "...")             # raising undoes everything written so far
        booking, _ = await create_booking(db, session=session, ...)
        await notify(db, "invite_accepted", ..., session=session)
        return booking

    return await transaction(db, accept)
```

- Pass `session=` to **every** repository, service and `notify` call inside it. A call without
  it raises: it would run outside the transaction and wait on its locks.
- The function may run more than once (the driver retries write conflicts), so it only reads
  and writes Mongo. **Never** call the payment gateway, the file store or anything else
  external inside it: charge after the visit is saved as finished, with its per-visit
  idempotency key, then record the result in a transaction of its own.
- Don't catch `DuplicateKeyError` inside it (it aborts the transaction); use
  `Repo.insert_once` for "insert unless it exists". Transactions don't nest: pass the session
  down instead.

## Review and hand-off

Follow `docs/prompts/CODEX-review.md` exactly: run `make lint` and `make test`, **commit
everything**, then `scripts/codex-review.sh "<focus text>"`. One review, one re-check, a third
only if a critical or high finding is still open. Findings are inputs, not vetoes; say which
you accepted and why. Then push, open a PR, and report.

## Map

- `api/app/core`: config, db (`transaction`), money, rounding, ids, time, phone, crypto, auth
  dependencies (`deps.py`).
- `api/app/services`: auth, quotes, eligibility, marketplace, bookings, schedule, ledger,
  notify + `templates.py` (the outbox catalogue), audit.
- `api/app/pricing`: the ported pricing models and engine. Params are in `pricing_versions`.
- `api/app/adapters`: payments (L3), address, area, files, notifier.
- `api/app/shared`: endpoints built in F. `api/app/{customer,provider,admin,payments}`: lanes.
- `web/src/{shared,demo,api,styles}`: F. `web/src/{customer,provider,admin,payments}`: lanes.
