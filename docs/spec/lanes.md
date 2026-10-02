# Lanes: who owns what

Three lanes work in parallel after foundations (F) is merged, each in its own worktree,
branch, ports and database:

| Lane | Worktree | Branch | API | Web | Database |
|---|---|---|---|---|---|
| main (F, then I) | `/srv/oqj/main` | `main`, `f/foundations`, `i/integration` | 8000 | 5170 | `oqj_main` |
| L1 Customer | `/srv/oqj/lane-customer` | `l1/customer` | 8001 | 5171 | `oqj_l1` |
| L2 Provider | `/srv/oqj/lane-provider` | `l2/provider` | 8002 | 5172 | `oqj_l2` |
| L3 Admin and payments | `/srv/oqj/lane-admin` | `l3/admin-payments` | 8003 | 5173 | `oqj_l3` |

Each worktree's `.env` sets `API_PORT`, `WEB_PORT` and `MONGO_DB`; the Makefile derives
`INSTANCE` from the directory name, so containers (`oqj-<instance>-api`, `-web`), files
volumes and Compose projects never collide. Tests use `<MONGO_DB>_test`. Only `main` is
served at `https://dev.onequickjob.co.uk`; lanes are viewed through an SSH tunnel:
`ssh -N -L 5171:127.0.0.1:5171 -L 5172:127.0.0.1:5172 -L 5173:127.0.0.1:5173 oqj-dev`.

**Merge order: L3, then L1, then L2.** L3 goes first because the others call its payment
gateway. Each lane rebases on `main` before its final review. No session merges its own work.

## The rule

**Never edit a file another lane owns.** If you need a change in one, write it up in
`docs/spec/contract-changes/<your lane>.md` and, where you can, work around it with an
additive change inside your own directories. Foundation-owned (F) files belong to nobody
after F merges: changes to them are contract-change requests, resolved by integration (I).

## API (`api/`)

| Path | Owner | Notes |
|---|---|---|
| `app/customer/**` | **L1** | `router.py` (`/api/c`), `schemas.py`, `tasks.py`; add modules freely |
| `app/provider/**` | **L2** | `router.py` (`/api/p`), `schemas.py`, `tasks.py` |
| `app/admin/**` | **L3** | `router.py` (`/api/admin`), `schemas.py`, `tasks.py` |
| `app/payments/**` | **L3** | Stripe webhooks (`/api/payments`) |
| `app/adapters/payments/**` | **L3** | the PaymentGateway interface, the fake (keep it working and the default) and Stripe |
| `tests/customer/**`, `tests/provider/**`, `tests/admin/**`, `tests/payments/**` | L1, L2, L3, L3 | lane tests |
| `app/models/<collection>.py`, `app/repos/<collection>.py` | the collection's owner (`domain.md`) | the owner may add fields (optional, with defaults) and repo functions; anything breaking is a contract change |
| `app/core/**`, `app/services/**`, `app/pricing/**`, `app/shared/**`, `app/adapters/{address,area,files,notifier}/**`, `app/main.py`, `app/cli/**`, `app/seed/**`, `tests/shared/**`, `tests/conftest.py`, `tests/factories.py`, `tests/fixtures/**` | **F** | shared; contract-change requests only |
| `pyproject.toml`, `uv.lock` | shared | adding a dependency is fine; on conflict at rebase take main's and re-run `uv lock` |

Rules that make parallel work possible:

- **Routers are already wired.** `app/main.py` includes every lane router; add endpoints to
  your router (or sub-routers it includes). Every endpoint in `api.md` exists as a 501 stub
  with its final request and response models; replace the body, keep the contract.
- **Shared logic lives in services**, built and tested in F: fees (`core/money.py`, the only
  place fees are computed), pricing (`pricing/`), quotes, eligibility, the marketplace (atomic
  first acceptance, counters, cover), bookings and scheduling, the ledger, notifications,
  audit, auth. Call them; don't re-implement them.
- **Outbox templates**: use the catalogue (`services/templates.py`, `notifications.md`). If you
  need a new one, `templates.register(...)` it from your own package and list it in your
  report; I folds it in.
- **Periodic tasks**: register with `@periodic` in your own `tasks.py`; `main.py` imports it.
- **Reading other lanes' collections**: use the existing repo functions, or write a read-only
  query in your own package with `Repo(db).coll`. Writes to another lane's collection go only
  through the repo or service functions listed in `domain.md` ("Writers").

## Web (`web/`)

| Path | Owner | Routes |
|---|---|---|
| `src/customer/**`, `src/styles/customer.css` | **L1** | `/`, `/quote/:categoryId/size`, `/quote/:categoryId/details`, `/quote/:categoryId/price`, `/quote/:categoryId/contact`, `/requests/:ref`, `/bookings/:bookingId`, `/account`, `/account/visits/:visitId/rate`, `/invite/:token` |
| `src/provider/**`, `src/styles/provider.css`, `public/p/**` (manifest, icons, any service worker) | **L2** | `/p`, `/p/j/:ref`, `/p/today`, `/p/visits/:visitId/finish`, `/p/earnings`, `/p/tax`, `/p/limit`, `/p/me`, `/p/time-off`, `/p/own-customers`, `/p/signup` |
| `src/admin/**`, `src/styles/admin.css`, `src/payments/**` | **L3** | `/admin`, `/admin/providers`, `/admin/providers/:providerId`, `/admin/pricing`, `/admin/disputes`, `/admin/categories`, `/admin/outbox` |
| `src/App.tsx`, `src/main.tsx`, `src/app/**`, `src/shared/**`, `src/demo/**`, `src/test/**`, `src/api/client.ts`, `src/api/queries.ts`, `src/styles/{tokens,base,demo}.css`, `index.html`, `vite.config.ts`, `scripts/**`, configs | **F** | `/signin`, not found |
| `src/api/openapi.json`, `src/api/schema.d.ts` | generated | run `make types` after changing your API; on a rebase conflict take either side and re-run `make types` (`make lint` fails if they're stale) |
| `package.json`, `package-lock.json` | shared | as for `uv.lock`: on conflict take main's, re-run `npm install` |

- Each surface's routes are exported from its own `routes.tsx`; `App.tsx` composes them, so
  adding a screen never touches another lane's file.
- Every prototype screen already has a placeholder page at its route; lift the screen from
  `docs/design/prototype.jsx` into it. Class names in the CSS match the prototype.
- `src/payments/CardCapture.tsx` belongs to L3 so Stripe Elements can replace the fake without
  touching L1's screens; L1 uses the component.
- Need a new shared component or a change to one? Put a local copy in your directory and file
  a contract-change request.

## Docs

| Path | Owner |
|---|---|
| `docs/spec/contract-changes/L1.md`, `L2.md`, `L3.md` | the lane |
| `docs/spec/payments.md` | L3 (new) |
| everything else in `docs/` | F, then I. `notifications.md`, `api.md` and `domain.md` are generated by `make docs` |

## Cross-lane dependencies, and how they're broken

| Need | Provided by | So that |
|---|---|---|
| L1's DEMO simulator must counter and accept "through the real offer endpoints" | F built `/api/p/requests/{ref}/accept|counter` and `/api/c/offers/{id}/accept|decline` | L1 doesn't wait for L2 (which merges after it) |
| L2 needs open requests to show and accept | the seed has three open requests and three unfilled ones, with job alerts in the outbox | L2 doesn't wait for L1's request creation |
| L1 and L2 both need "who is eligible" and "how close to their limit" | `services/eligibility.py` | broadcast and job lists agree |
| L1 (invites) and the marketplace both create bookings | `services/bookings.create_booking` | one booking shape, one scheduler |
| L2 charges visits; L3 implements Stripe | `adapters/payments` interface + fake | L2 builds against the fake; Stripe drops in |
| L2 writes ledger entries; L3 refunds and exports | `services/ledger.py`, `money.refund_split` | gross = fee + net in every entry |
| L1 captures cards; L3 owns Stripe | `web/src/payments/CardCapture.tsx` (L3) | no edits to L1's screens |
| Everyone sends messages | `services/notify.py` + the catalogue | one outbox shape |
