# Decisions

The rules every session builds on. Part 1 is settled (from the foundations brief); part 2
is the rulings made while building foundations (F); part 3 lists what is still open.
Change part 1 only with Hasan's agreement. Lanes add their own rulings to their reports,
and integration (I) folds the accepted ones in here.

## 1. Settled rules

### Stack and layout
1. Monorepo: `api/` (FastAPI), `web/` (React), `infra/`, `docs/`, `seed/`.
2. API: Python 3.14, installed and pinned by uv (`api/.python-version`; never the system
   Python), uv, FastAPI, Pydantic v2, PyMongo's native async client (`AsyncMongoClient`, not
   Motor), ruff, pytest + pytest-asyncio + httpx. No ODM: Pydantic models plus a thin
   repository module per collection.
3. Web: Vite + React + TypeScript (strict), React Router, TanStack Query; API types generated
   from the FastAPI OpenAPI schema with openapi-typescript. No Tailwind: the prototype's CSS
   (village theme only) is ported to `web/src/styles/` as plain CSS with the same class names.
4. One web app, three route groups: `/` customer, `/p` provider (installable PWA with a
   manifest), `/admin`.
5. Infra: Docker Compose with mongo, api, web and caddy.
6. **Security: only Caddy publishes ports (80 and 443).** Docker bypasses the ufw firewall for
   published ports, so Mongo publishes none and every API and web dev-server port binds to
   127.0.0.1. `make check` fails if anything else listens on a public interface.
7. Caddy serves `dev.onequickjob.co.uk` with automatic HTTPS and basic auth on everything
   (private prototype). Credentials come from `.env`.
8. Everything is configurable by `.env`, including ports and database name. Lane N uses API
   port 800N, web port 517N and database `oqj_lN`, all against the one Mongo container.

### Domain
9. Money is integer pence everywhere. `api/app/core/money.py` is the only place fees are
   computed: standard fee = round half-up of price × 15%; own-customer ("bring your own
   customers") fee = max(100p, round half-up of price × 5%). Rates come from config. The
   provider receives price minus fee.
10. Agency structure: the customer contracts with the named provider; OneQuickJob is their
    booking and payment agent. The commission is always disclosed. Nothing is ever described
    as a guarantee.
11. Guide price and bidding: a request is broadcast to eligible providers; the first provider
    to accept the guide price books it, atomically (`findOneAndUpdate` on `status: "open"`).
    Counter-offers wait for the customer to accept, or keep waiting.
12. Times are stored in UTC and displayed in Europe/London. Phone numbers are stored in E.164.
    All copy is UK English.
13. Categories are data: the 15 live categories (groups, required documents, intake schemas,
    pricing model references) and the excluded jobs are seed JSON loaded into Mongo. Planned or
    excluded jobs are never bookable.
14. Pricing engine: every model in the prototype's `PRICING_MODELS` is ported to
    `api/app/pricing/` as a pure function. Params live in `pricing_versions` (status
    draft | live, `created_by`, `approved_by`, `created_at`); the engine always uses the live
    version and every quote records the version it used.
15. Lawn area comes from an `AreaEstimator`. v0 is `manual_bands_v0`: Small about 40 m²
    ("about a double garage"), Medium about 85 m², Large about 190 m² ("about a singles tennis
    court"), Very large about 350 m² ("bigger than a doubles tennis court"). It can be swapped
    for a LIDAR estimator without touching callers.
16. Golden tests, with each category's default answers and 186 m² for mowing: mowing 3000p a
    visit; hedges 6100; clearance 11000; jet wash 8800; gutters 8500; windows 2200 a clean,
    first visit 3300; cleaning 6600 a clean, first 8800; deep clean 20400; oven 7000;
    decorating 18200; flat-pack 13300; mounting 11000; repairs 6000; tech help 2500; dog
    walking 1600 a walk. Fees: standard fee on 3000p is 450p; own-customer fee on 1500p is 100p
    and on 3000p is 150p. (`api/tests/shared/test_pricing_golden.py`, `test_money.py`.)
17. Rounding: JavaScript's `Math.round` rounds halves up; Python's `round()` rounds them to
    even. Use `Decimal` with `ROUND_HALF_UP` (`app.core.rounding`) everywhere the prototype
    uses `Math.round`: durations, prices and fees.

### External services: adapters with fakes, chosen by environment
18. **PaymentGateway** (`app/adapters/payments/`): fake now; L3 writes Stripe (Connect Express,
    destination charges with `on_behalf_of`, card saved on the platform customer, charged
    off-session after each visit). Interface: `create_provider_account`, `onboarding_link`,
    `save_card_setup`, `charge_visit(visit, price_pence, fee_pence, provider_account)`,
    `refund`, `payout_summary` (plus `account_status` and `card_setup_status`, ruling R24).
19. **AddressLookup**: a fake (a dozen Hazlemere, Widmer End and Penn addresses with UPRN and
    coordinates) and Ideal Postcodes when `IDEAL_POSTCODES_KEY` is set. Autocomplete goes
    through a backend proxy so the key never reaches the browser; the credit is spent only on
    the final address retrieval. The UPRN is stored on every address.
20. **Notifier: outbox only.** Every message (login codes, job alerts, booking confirmations,
    reminders, payouts) is written to the `outbox` collection with channel (sms | whatsapp |
    email), recipient, template id, rendered body and related ids. Nothing is sent.
21. **FileStore**: local disk on a mounted volume, served by Caddy behind the same basic auth.
22. **AreaEstimator**: `manual_bands_v0` (rule 15).

### Auth and demo
23. Sign-in by phone or email plus a 6-digit code written to the outbox; it expires in 10
    minutes and allows 5 attempts. Sessions are server-side in Mongo with an httpOnly, Secure,
    SameSite=Lax cookie. Roles: customer, provider, admin; a user may hold several.
24. `DEMO_MODE=true` (the default in dev) adds a floating Outbox drawer (latest messages and
    login codes), a Switch user menu (Sarah the customer, Dave and the other providers, an
    admin) and a thin banner reading "Prototype: test payments only". All of it disappears when
    `DEMO_MODE` is false, server side as well (the demo endpoints return 404).

### Process
25. Every session reads `CLAUDE.md` first. Codex reviews follow `docs/prompts/CODEX-review.md`
    via `scripts/codex-review.sh`. No session merges its own work: Hasan merges.

## 2. Rulings made during F

**Stack and infrastructure**

- **R1. Versions.** Python 3.14.8 (uv-managed), FastAPI 0.142, Pydantic 2.13, PyMongo 4.18,
  uvicorn 0.54, pytest 9 with pytest-asyncio 1.4, ruff 0.16; React 19, Vite 8, TypeScript
  **5.9** (TypeScript 7 is out, but openapi-typescript and typescript-eslint need 5.x), ESLint
  **9** (eslint-plugin-jsx-a11y doesn't support 10 yet), Mongo 8.0, Caddy 2, Node 22.
- **R2. Docker without the docker group.** The working user isn't in the `docker` group, so the
  Makefile prefixes Docker with `sudo` when needed rather than changing the host's groups.
- **R3. Two Compose projects.** `infra/compose.shared.yml` (project `oqj-shared`: Mongo and
  Caddy, network `oqj`) is shared by every worktree; `infra/compose.app.yml` (project
  `oqj-<INSTANCE>`: api and web) is one per worktree. `INSTANCE` is the worktree's directory
  name (`main`, `lane-customer`, ...), derived by the Makefile, so lanes can't collide even
  though the build pack's set-up only changes ports and database. Containers are named
  `oqj-<instance>-api` / `-web`; Caddy proxies to `main`'s. A lane's `make dev` starts the
  shared services if they're down but never recreates them.
- **R4. Where things run.** The dev servers run in containers (uvicorn `--reload` and the Vite
  dev server, source bind-mounted). API tests run in the api container (`make test-api`)
  because Mongo is reachable only on the Docker network; they use `<MONGO_DB>_test`, so lanes
  never touch each other's data. Lint and type generation run on the host with uv and npm.
  Containers write nothing into the worktree (no bytecode, no pytest cache).
- **R5. Caddy.** It hashes `BASIC_AUTH_PASSWORD` with bcrypt at start-up, so `.env` holds plain
  credentials. HTTP/3 is off (UDP 443 isn't open in ufw). It adds HSTS, `nosniff`,
  `noindex` and serves `/files/*` straight from the main instance's files volume.
- **R6. Paths.** The API lives under `/api` (docs at `/api/docs`). Caddy sends `/api/*` to the
  main API, `/files/*` to the files volume and everything else to the main Vite dev server. The
  Vite dev server proxies `/api` and `/files` to its own API, so lanes work through an SSH
  tunnel on 517N.
- **R7. Mongo has no authentication.** It is reachable only from containers on the private
  `oqj` network and publishes no port. Acceptable for the prototype; revisit before real data.

**Pricing**

- **R8. Every pricing constant is a param.** Constants hard-coded inside the prototype's model
  functions (the £45 hourly rate, lawn growth multipliers, disposal charges, minimum prices,
  first-visit multipliers, spreads, the hedge per-metre minutes...) are lifted into each
  category's params in pricing version 1 (`seed/pricing_v1.json`), with money in pence. So
  calibration changes data, not code ("raise the overgrown multiplier from 1.9 to 2.4" is a
  draft version). Version 1 reproduces the prototype exactly.
- **R9. The prototype is the oracle.** `scripts/prototype-extract.mjs` runs the prototype's own
  `CATEGORIES` and `PRICING_MODELS` in Node. It exported the catalogue and generated 1,215
  reference cases (defaults plus 80 random answer sets per category);
  `test_pricing_prototype.py` checks the Python engine against every one.
- **R10. Exact halves round up.** In 9 of those 1,215 cases JavaScript's float maths lands a
  hair below an exact half (138 min × £45 / 60 = £103.50 becomes 103.4999…) and `Math.round`
  goes down. The port rounds the exact value up, as rule 17 requires; the generator flags these
  cases and the test allows exactly one unit (£1 or 1 minute) up there and nowhere else. The
  golden values are unaffected.
- **R11. Mowing confidence note.** The prototype says "Measured from survey data, so most
  providers accept it as it is." With manual size bands that's untrue, so the note is "Based on
  the lawn size you chose, so most providers accept it as it is." The confidence level stays
  high (open question Q2).
- **R12. Medium band comparison**, missing from the brief: "About a badminton court" (13.4 m ×
  6.1 m ≈ 82 m²). Adjustments are the prototype's: Looks smaller ×0.8, About right ×1, Looks
  bigger ×1.2, rounded half-up to whole m².
- **R13. Answers are validated against the intake schema.** Missing answers take the field's
  default; unknown keys and invalid values are a 422. A counts job with nothing in it isn't
  priced ("Add at least one item to see a price."). Photo answers are lists of uploaded file
  ids (the prototype mocks a count), default empty, at most 4.
- **R14. `pricing_versions` has a third status, `retired`,** for the previous live version
  when a new one is approved. A unique partial index guarantees exactly one live version.
  Re-seeding never makes version 1 live again once something else is.

**Money**

- **R15. Tips carry no fee** (prototype: "All of it goes to Dave"): `money.split(tip, "tip")`.
- **R16. Refunds split proportionally**: fee refunded = round half-up of refund × fee / price,
  so a full refund returns exactly the fee and the provider's share
  (`money.refund_split`). Refunds are provider-funded (prototype: "a partial refund, paid by
  the provider"). L3 must check Stripe's own proportional application-fee refund agrees.
- **R17. Counter-offers** are whole pounds between 80% and 300% of the guide (the prototype's
  stepper bounds); one pending counter per provider per request. **Offers are immutable**: a
  provider who changes their price withdraws the old offer and makes a new one, so a customer
  always accepts exactly the terms they saw. Accepting first reserves the offer
  (`accepting`), then claims the request; either step can be resumed (Codex review). A counter sets the per-visit
  price. Unless the provider gives a separate first-visit price, the first visit is the higher
  of the counter and the request's first-visit guide (open question Q1). Counters aren't
  allowed on time-off cover requests (cover is at the regular price).
- **R18. Fees on the price screen** are shown for the routine price and, separately, for the
  first-visit price (`fee` and `first_fee` on a quote).

**Marketplace and scheduling**

- **R19. The offer endpoints are built in F** (`POST /api/p/requests/{ref}/accept|counter`,
  `POST /api/c/offers/{id}/accept|decline`), on `app.services.marketplace`. Both L1 (the
  counter screen and the DEMO simulator, which must use the real endpoints) and L2 (accept and
  counter) need them from day one, and L1 merges before L2. This is a deviation from "implement
  fully only ..." (see the F report).
- **R20. Claim first, then book, resumably.** Accepting atomically flips the request to
  booked with a pre-allocated booking id and the agreed prices frozen in the claim (a guide
  acceptance also checks the guide hasn't changed since it was read). Booking setup then runs
  in idempotent steps: the booking (with its first-visit slot fixed), plan, first visit, visit
  horizon and thread, each checked before it's written, then `setup_complete`; booking
  messages are sent and then marked (at least once). A periodic task resumes any claim from the
  last day whose setup isn't complete, after a two-minute grace so it never races the request
  that won; only setup creates a plan's first visit (the hourly horizon top-up skips plans whose
  booking isn't complete, and setup adopts an anchor-day visit if one exists). Each task item
  is isolated, so one failure doesn't stop the rest. (Mongo runs standalone, so there are no multi-document transactions.)
- **R21. Eligibility** (`app.services.eligibility`). Hard rules, checked on every accept and
  counter: provider active (or payouts paused), the category in their skills, identity checked
  and every document the category requires verified and in date. Distance is not a hard rule,
  because admins dispatch further-away jobs by hand. Broadcast rules (L1): hard rules plus
  within travel radius, a working day that suits the customer, alerts switched on and the
  earnings limit not yet reached. A job that would take a provider over their limit still
  alerts while they have headroom; their job list marks it.
- **R22. Scheduling** (`app.services.schedule`): windows are morning 09:00–12:00, afternoon
  13:00–17:00, either 09:00–17:00 (customers see "morning, 8am to 12pm"). The first visit is
  the earliest day from tomorrow that the provider works, suits the customer and isn't time
  off, at the first free half hour after the provider's previous visit plus 30 minutes' travel
  ("10:30, straight after Widmer End"). Recurring visits keep that weekday and time and are
  materialised six weeks ahead (at least the next two). Monthly frequencies use calendar
  months; "a few days a week" defaults to Monday, Wednesday and Friday. The winter pause skips
  November to February.
- **R23a. Time-off cover goes through the normal offer flow.** L2 creates a job request with
  `cover_for_visit_id` for one visit (same price); accepting it (the shared accept endpoint)
  reassigns that visit to the covering provider (performer kind `cover`, paid for that visit)
  instead of creating a booking, and tells the customer (`cover_coming`). A provider can't take
  cover for their own visit. The plan stays with the regular provider.
- **R23. Message threads**: one per booking, plus one per dispute; every lane posts through
  `Messages.post()`.

**Auth, security and data**

- **R24. Gateway interface additions**: `account_status` (L3 syncs Express accounts) and
  `card_setup_status` (Stripe confirms the SetupIntent in the browser). `charge_visit` also
  takes `idempotency_key` and `purpose` ("visit" or "tip") keyword arguments; the positional
  signature is as specified.
- **R25. Login codes** are stored as HMAC-SHA256 keyed with `SECRET_KEY`; only the latest code
  for an identifier counts; at most one new code per 30 seconds and six an hour per
  identifier. A new phone number or email becomes a customer account on first sign-in.
  Sessions last 30 days; the cookie holds a random token and Mongo holds its HMAC.
- **R25a. Demo sessions end with DEMO_MODE.** Switch-user sessions (`via: demo`) are refused
  and deleted when `DEMO_MODE` is false, so a demo admin cookie can't outlive the demo (Codex
  review). Outside DEMO_MODE the admin outbox also masks sign-in codes and its free-text search
  never matches a code message's body, so staff can neither see nor probe a live code.
- **R26. Magic links** for job alerts: single-use, 72 hours, minted by
  `services.auth.create_magic_link`, consumed by `POST /api/auth/magic`. Part of auth, so built
  in F.
- **R27. Cookies stay Secure.** Chrome and Firefox accept Secure cookies on
  `http://localhost`, so tunnelled lanes work. `COOKIE_SECURE=false` exists for Safari over a
  tunnel; never on the public site.
- **R28. Tax identifiers.** Providers' documents hold only masked copies (QQ •• •• •• C,
  •• / •• / 1958). The full NI number and date of birth are sealed (Fernet, key derived from
  `SECRET_KEY`) in `tax_identities` and unsealed only by the HMRC export.
- **R29. Files.** Upload is a shared endpoint (`POST /api/files`, built in F, used by all three
  lanes). Images and PDFs only, 10 MB. Paths are random and unguessable; anyone past basic auth
  with a URL can fetch the file (no per-file authorisation in the prototype).
- **R30. Ids.** Every `_id` is a string (the hex of a fresh ObjectId); references store the
  same string. Human references come from a `counters` collection: requests R-2301 up,
  bookings B-1101 up, disputes D-016 up. Seeded data sits below them (R-2101 to R-2294,
  B-0001 to B-0132, and the prototype's D-011, D-013, D-014).
- **R31. Addresses** carry `locality` (the village, e.g. Hazlemere) as well as the post town
  (High Wycombe); providers see the locality and district before booking, the exact address
  after.

**Web, demo and copy**

- **R32. Outbox links** are full URLs from `PUBLIC_BASE_URL`, as a real text would be. The demo
  drawer opens them on the current origin, so tunnelled lanes work without changing it.
- **R33. Fonts are self-hosted** (@fontsource Young Serif and Figtree) rather than loaded from
  Google Fonts.
- **R34. Stripe dependencies are pre-added** (Python `stripe`, `@stripe/stripe-js`,
  `@stripe/react-stripe-js`) so L3 doesn't create lock-file conflicts. Unused until L3.
- **R35. `CardCapture`** (`web/src/payments/`) is owned by L3: L1's contact and invite screens
  use it, and L3 can switch it to Stripe Elements without editing L1's files.
- **R36. Seeded mock data follows the engine.** Where the prototype's mock prices contradict
  the pricing models, the seed uses the engine: Sarah's open mowing request uses the Large band
  (£31, not £30 at 186 m²); R-2284 is £28, not £34; R-2291's answers are chosen to give exactly
  £72. Seeded dates are relative to the day of seeding, so the demo always looks current.
- **R36a. How the seed stays idempotent.** Every seeded document has a deterministic id and a
  `_seed: true` marker; each run deletes the marked documents and writes them again, so running
  it twice (or on another day) never accumulates anything. Data people created is kept, except
  what would clash with the demo (bookings and offers made on seeded requests, users who signed
  in with a seeded phone, visits the horizon task added to seeded plans...), which is removed
  with a printed note: `make seed` puts the demo back. Magic-link and invite tokens are minted
  fresh each run. Prototype document expiry dates are kept as absolute dates (only Alan's is
  relative, so he always shows as expiring), so Gary's insurance lapses on 19 November 2026.
- **R37. Fake gateway**: every card is a Visa ending 4242 (12/28) and every charge succeeds,
  except for customers whose name contains "decline" (fails) or "3ds" (needs action), so
  failure paths can be demoed. Payouts arrive the Friday after the charge.
- **R37a. One extra design token**, `--line-strong: #7d8a80`, for input and stepper borders
  only: the prototype's border colour is 1.43:1 against white, below WCAG 2.2's 3:1 for control
  boundaries (1.4.11). Every text colour pair already passes AA.
- **R38. Background tasks** run inside the API process from a registry
  (`app.core.tasks.periodic`); each lane registers its own in `app/<lane>/tasks.py`.
- **R39. Notifications docs are generated** from the template catalogue (`make docs`), and
  `docs/spec/api.md`'s endpoint table from the routes, so neither can drift from the code.

## 3. Open questions (for Hasan)

- **Q1. Counter-offers on jobs with a dearer first visit.** Today a counter sets the per-visit
  price, and the first visit is the higher of the counter and the first-visit guide unless the
  provider names a first-visit price too. Is that right, or should a counter scale both?
- **Q2. Mowing confidence with manual bands.** The prototype shows "Usually close" (high)
  because the area was measured. With the customer choosing a band, should it drop to "Fairly
  close" (medium) until LIDAR? It changes copy, not price.
- **Q3. Lawn copy that assumes LIDAR.** "We measure your garden from public survey data", the
  measure screen's "We've measured it from public survey data" and the Open Government Licence
  line only make sense with LIDAR. L1 should reword them for size bands unless you'd rather keep
  them for the pitch.
- **Q4. DBS renewals.** Basic DBS checks don't expire. How often should a provider renew one?
  For now `dbs_basic` has no expiry.
- **Q5. Fees on covered own-customer visits.** A covered visit keeps its booking's source, so a
  regular's own customer covered by another provider is charged the 5% own-customer fee, which
  the cover provider didn't earn by bringing them. Should cover visits always take the
  standard 15%? (Changes money semantics, so not decided here.)
