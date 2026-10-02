# OneQuickJob

A local marketplace for non-certified home and garden jobs around High Wycombe. This is the
working prototype: a FastAPI + MongoDB back end, a React web app with three surfaces
(customer `/`, provider `/p`, admin `/admin`), fake adapters for payments, addresses and
messages, seeded demo data, behind basic auth at https://dev.onequickjob.co.uk.

Read `CLAUDE.md` for the rules and `docs/spec/` for the detail. The design reference is
`docs/design/prototype.jsx`.

## Prerequisites (already on the dev droplet)

Docker with Compose v2, uv (it installs Python 3.14 itself from `api/.python-version`),
Node 22, make, openssl. Docker needs root on the droplet; the Makefile adds `sudo`
automatically when your user can't reach the Docker socket.

## First run

```bash
cd /srv/oqj/main
make env        # writes .env with a random SECRET_KEY and basic-auth password (never overwrites)
make install    # host dependencies for lint and type generation (uv sync, npm ci)
make dev        # starts Mongo + Caddy (shared) and this worktree's API and web
make seed       # loads the demo data into this worktree's database
```

Then open https://dev.onequickjob.co.uk and sign in to the basic-auth prompt with
`BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` from `.env` (`grep BASIC_AUTH .env`). Caddy gets
the HTTPS certificate automatically on first start (ports 80 and 443 must be open, which they
are in ufw).

In the app, DEMO_MODE gives you a **Switch user** menu (Sarah the customer, Dave and the other
providers, Tom the helper, two admins) and an **Outbox** drawer showing every message the
system "sent", including sign-in codes and job alerts with their links.

## Everyday commands

| Command | What it does |
|---|---|
| `make dev` | Build and (re)start this worktree's API and web; start shared Mongo and Caddy if needed |
| `make down` | Stop this worktree's API and web |
| `make logs` | Follow this worktree's API and web logs |
| `make ps` | Show containers and their port bindings |
| `make test` | All tests: pytest in the API container (database `<MONGO_DB>_test`) and vitest |
| `make test-api ARGS="tests/shared/test_marketplace.py -x"` | A subset of the API tests |
| `make lint` | ruff, eslint, TypeScript, and a check that generated API types are current |
| `make types` | Regenerate `web/src/api/schema.d.ts` from the API's OpenAPI schema |
| `make seed` | Load demo data (idempotent: run it as often as you like) |
| `make seed-reset` | Drop this worktree's database and seed it again |
| `make check` | Fail if anything other than Caddy (80, 443) and sshd is exposed publicly |
| `make docs` | Regenerate `docs/spec/notifications.md`, `api.md` and `domain.md` |
| `make mongosh` | A Mongo shell on this worktree's database |
| `make infra-down` | Stop the shared Mongo and Caddy (affects every worktree) |

The API's interactive docs are at `/api/docs` (on the site, or `http://127.0.0.1:<API_PORT>`
on the droplet).

## How it runs

```
internet ──443/80──> Caddy (basic auth, HTTPS) ──> oqj-main-web (Vite dev server, :5173 inside Docker)
                                         ├─/api──> oqj-main-api (uvicorn --reload, :8000 inside Docker)
                                         └─/files> files volume (photos, documents)
oqj-*-api ──> oqj-mongo (no published port; private Docker network "oqj")
```

- Only Caddy publishes ports. Each worktree's API and web are published on 127.0.0.1 only
  (`API_PORT`, `WEB_PORT` in `.env`), Mongo on nothing. `make check` verifies this.
- Source is bind-mounted, so code changes reload without rebuilding. Rebuild (`make dev`)
  after changing `api/pyproject.toml` or `web/package.json`.

## Lanes (parallel worktrees)

After foundations is merged, three lanes run side by side, each with its own `.env`:

| Worktree | API | Web | Database |
|---|---|---|---|
| `/srv/oqj/main` | 8000 | 5170 | `oqj_main` |
| `/srv/oqj/lane-customer` | 8001 | 5171 | `oqj_l1` |
| `/srv/oqj/lane-provider` | 8002 | 5172 | `oqj_l2` |
| `/srv/oqj/lane-admin` | 8003 | 5173 | `oqj_l3` |

Set-up (from the build pack; the `.env` keys are `API_PORT`, `WEB_PORT`, `MONGO_DB`):

```bash
cd /srv/oqj/main && git checkout main && git pull
git worktree add ../lane-customer -b l1/customer
cp .env ../lane-customer/.env && sed -i 's/^API_PORT=.*/API_PORT=8001/; s/^WEB_PORT=.*/WEB_PORT=5171/; s/^MONGO_DB=.*/MONGO_DB=oqj_l1/' ../lane-customer/.env
cd ../lane-customer && make install && make dev && make seed
```

Each worktree's containers are named after its directory (`oqj-lane-customer-api`), so they
never clash. Lanes are reachable only from the droplet; view them from your Mac through a
tunnel and open `http://localhost:5171` (or 5172, 5173):

```bash
ssh -N -L 5171:127.0.0.1:5171 -L 5172:127.0.0.1:5172 -L 5173:127.0.0.1:5173 oqj-dev
```

Links in Outbox messages point at the public site; the Outbox drawer opens them on whatever
address you're using, so they work through a tunnel too. (Safari won't keep the Secure session
cookie on `http://localhost`; use Chrome or Firefox, or set `COOKIE_SECURE=false` in that
lane's `.env`.)

## Configuration

Everything is in `.env` (see `.env.example` for every key and what it does). Adapters switch on
configuration: `PAYMENT_GATEWAY=fake|stripe` (Stripe arrives with lane L3, test keys only),
`IDEAL_POSTCODES_KEY` (empty uses the fake address list), `AREA_ESTIMATOR=manual_bands_v0`.
`DEMO_MODE=false` removes every demo feature.

## Troubleshooting

- **502 from the site**: the main worktree's API or web isn't running. `make ps`, then
  `make dev` in `/srv/oqj/main`.
- **"Generated API types are stale"** from `make lint`: run `make types` and commit the result.
- **Certificate errors on first start**: check `sudo docker logs oqj-caddy`; Let's Encrypt
  needs ports 80 and 443 reachable and the DNS record pointing at the droplet.
- **Tests can't reach Mongo**: they run inside the API container on the `oqj` network; use
  `make test`, not `pytest` on the host.
