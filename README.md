# OneQuickJob

A local marketplace for non-certified home and garden jobs around High Wycombe. This is the
working prototype: a FastAPI + MongoDB back end, a React web app with three surfaces
(customer `/`, provider `/p`, admin `/admin`), fake adapters for payments, addresses and
messages, seeded demo data, behind basic auth at https://dev.onequickjob.co.uk.

Read `CLAUDE.md` for the rules and `docs/spec/` for the detail. The design reference is
`docs/design/prototype.jsx`.

## Prerequisites (already on the dev droplet)

Docker with Compose v2 (started at boot), uv (it installs Python 3.14 itself from
`api/.python-version`), Node 22, make, openssl, rsync. Your user must be in the `docker` group
(`id -nG` lists it). Only installing the backup timer uses sudo (`make backup-timer`).

## First run

```bash
cd /srv/oqj/main
make env          # writes .env with a random SECRET_KEY, tax data key and basic-auth password (never overwrites)
make install      # host dependencies for lint, types and the web build (uv sync, npm ci)
make prod-up      # the production-style stack: shared Mongo and Caddy, the built web app, the API
make seed         # resets the demo data
make backup-timer # the nightly backup (03:00 London time), once per droplet
```

Then open **https://dev.onequickjob.co.uk** and answer the basic-auth prompt with
`BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` from `.env` (`grep BASIC_AUTH .env`; keep a copy
in your password manager). Caddy gets the HTTPS certificate automatically on first start.

In the app, DEMO_MODE gives you a **Switch user** menu (Sarah the customer, Dave and the other
providers, Tom the helper, two admins) and an **Outbox** drawer showing every message the
system "sent", including sign-in codes and job alerts with their links. `docs/demo-script.md`
is a ten-minute tour.

## Everyday commands

| Command | What it does |
|---|---|
| `make prod-up` | Build the web app into `var/www` and the API image, start the production-style API; then `make status` |
| `make prod-down` | Stop the production-style API (Caddy keeps serving the built app; `/api` answers 502 until `prod-up`) |
| `make status` | Containers and their health, the API directly and through Caddy, the built app, a 401 without the password |
| `make prod-logs` | Follow the production-style API's logs |
| `make dev` | Development: this worktree's API (auto-reload) and Vite on 127.0.0.1:8000 and :5170 |
| `make down` | Stop the development API and web |
| `make test` | All tests: pytest in the API container (database `<MONGO_DB>_test`) and vitest |
| `make test-api ARGS="tests/shared/test_marketplace.py -x"` | A subset of the API tests |
| `make e2e` | Playwright journeys and accessibility checks at 375px and desktop against the production-style stack (re-seeds; failures leave a screenshot and page snapshot in `e2e/results/<width>`, never a trace, and API errors have the site password taken out) |
| `make lint` | ruff, eslint, TypeScript, and a check that generated API types are current |
| `make types` | Regenerate `web/src/api/schema.d.ts` from the API's OpenAPI schema |
| `make seed` | Reset the demo: removes what demo runs created and loads the demo data (idempotent; keeps admins' pricing versions) |
| `make seed-reset` | Drop the database and seed it again |
| `make backup-now` | Back up the database now (`/srv/oqj/backups`) |
| `make restore-test` | Restore the latest backup into a scratch database, compare counts with the live one, drop it |
| `make rotate-tax-key` | Add a tax data key, make it current, re-encrypt NI numbers and birth dates, retire the old key |
| `make check` | Fail if anything other than Caddy (80, 443) and sshd is exposed publicly |
| `make docs` | Regenerate `docs/spec/notifications.md`, `api.md` and `domain.md` |
| `make mongosh` | A Mongo shell on the database |
| `make infra-down` | Stop the shared Mongo and Caddy |

The API's interactive docs are at `/api/docs` on the site.

## How it runs (production-style)

```
internet ──443/80──> Caddy (basic auth, HTTPS) ──> /srv/www: the built web app (var/www on the droplet)
                                         ├─/api──> oqj-prod-api (uvicorn, no reload; 127.0.0.1:8090 for make status)
                                         └─/files> files volume (photos, documents)
oqj-prod-api ──> oqj-mongo (single-node replica set rs0; no published port; private Docker network "oqj")
```

- No dev server is involved: `make prod-up` builds the web app (`npm run build`) into `var/www`,
  which Caddy serves with the app's routes falling back to `index.html`; hashed assets are cached
  for a year, the HTML shell never. The API image has the code baked in (`infra/api.prod.Dockerfile`).
- Every container restarts on its own (`restart: unless-stopped`), including after a reboot:
  Docker starts at boot and brings back Mongo, Caddy and the API. `make status` checks them all.
  A container stopped on purpose (`make prod-down`) stays stopped.
- Only Caddy publishes ports. The API binds 127.0.0.1 only, Mongo nothing. `make check` verifies it.
- Mongo runs as a single-node replica set (`rs0`) so writes that span collections can use
  transactions. Its healthcheck initiates the set the first time and is a no-op afterwards.
  It allows 64000 open files and caps its cache at 1.5 GB (`infra/compose.shared.yml`).

## Development mode

`make dev` runs this worktree's API (auto-reload) and the Vite dev server, bound to
127.0.0.1:8000 and :5170, against the same database and files as the production-style stack.
The two never compete for ports, and only the production-style API runs the periodic tasks when
both are up, whichever started first (`make prod-down` says to run `make dev` again to hand them
back). The public site always serves the built app; view the dev server from your Mac through
a tunnel and open http://localhost:5170:

```bash
ssh -N -L 5170:127.0.0.1:5170 oqj-dev
```

Source is bind-mounted, so code changes reload without rebuilding (rebuild with `make dev`
after changing `api/pyproject.toml` or `web/package.json`). Run `make prod-up` to put a change
on the public site. Links in Outbox messages point at the public site; the Outbox drawer opens
them on whatever address you're using, so they work through the tunnel too. (Safari won't keep
the Secure session cookie on `http://localhost`; use Chrome or Firefox.)

Several sessions at once? `docs/spec/lanes.md` explains worktrees and ownership.

## Backups and restores

A systemd timer (`oqj-backup.timer`, installed by `make backup-timer`) dumps the database every
night at 03:00 London time into `/srv/oqj/backups` as a gzipped `mongodump` archive
(`oqj_main-<UTC time>.archive.gz`, readable only by you), and removes archives 14 or more days
old. A night missed while the droplet was off runs at the next boot. For the second or two the
dump takes, the APIs writing to the database are paused (requests wait, nothing fails), so a
transaction is never half in the archive. Backups run one at a time.

- `systemctl list-timers oqj-backup.timer` shows the next run; `journalctl -u oqj-backup` the last ones.
- `make backup-now` takes one immediately.
- `make restore-test` restores the newest archive into a scratch database, compares every
  collection's document count with the live database and drops the scratch database. Run
  `make backup-now` first for an exact match.

To restore for real (this replaces the database):

```bash
make prod-down
docker exec -i oqj-mongo mongorestore --archive --gzip --drop --nsInclude='oqj_main.*' < /srv/oqj/backups/<archive>
make prod-up
```

**A restore also needs the tax data key.** NI numbers and dates of birth are encrypted with
`TAX_DATA_KEYS` from `.env`, and that key is deliberately not in the backup. Keep the
`TAX_DATA_KEYS` (and `TAX_DATA_KEY_CURRENT`) lines in Hasan's password manager; on a new
droplet, put them back in `.env` before starting the API, or the tax pack and HMRC export can't
read those fields. Keep an old key line until every backup made with it has expired (14 days).
Backups stay on the droplet for now; off-site copies are on `docs/pre-pilot.md`.

## Configuration

Everything is in `.env` (see `.env.example` for every key and what it does). Adapters switch on
configuration: `PAYMENT_GATEWAY=fake|stripe` (the prototype runs on the fake: test keys only,
ever), `IDEAL_POSTCODES_KEY` (empty uses the fake address list), `AREA_ESTIMATOR=manual_bands_v0`.
`DEMO_MODE=false` removes every demo feature, including the Outbox drawer where sign-in codes
appear, so with no real text or email channel nobody could sign in (`docs/pre-pilot.md`).

## Troubleshooting

- **`make status` says the API is down, or the site answers 502 for `/api`**: `make prod-up`
  (and `make prod-logs` for why it stopped).
- **The site shows an old version**: `make prod-up` rebuilds the web app; the browser picks it up
  on the next page load.
- **"Generated API types are stale"** from `make lint`: run `make types` and commit the result.
- **Certificate errors on first start**: check `docker logs oqj-caddy`; Let's Encrypt
  needs ports 80 and 443 reachable and the DNS record pointing at the droplet.
- **Tests can't reach Mongo**: they run inside the API container on the `oqj` network; use
  `make test`, not `pytest` on the host.
