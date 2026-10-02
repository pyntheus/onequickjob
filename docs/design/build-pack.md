# OneQuickJob: working prototype build pack

Five Claude Code sessions in total:

| Session | When | Branch / worktree |
|---|---|---|
| **F: Foundations** | First, alone | `f/foundations` in `/srv/oqj/main` |
| **L1: Customer** | After F is merged, in parallel | `l1/customer` in `/srv/oqj/lane-customer` |
| **L2: Provider** | After F is merged, in parallel | `l2/provider` in `/srv/oqj/lane-provider` |
| **L3: Admin and payments** | After F is merged, in parallel | `l3/admin-payments` in `/srv/oqj/lane-admin` |
| **I: Integration** | After all three lanes are merged | `i/integration` in `/srv/oqj/main` |

Each prompt is a self-contained cold start. `/clear` before pasting. Each session ends with a report, which you paste back to Claude (chat) for adjudication. No session merges its own work.

**What "working prototype" means here:** real FastAPI + MongoDB back end, the Village design, Stripe in **test mode only**, Ideal Postcodes address lookup, manual lawn-size bands (no LIDAR yet), an **outbox** in place of SMS/WhatsApp/email (login codes appear there too), seeded demo data, password-protected at `dev.onequickjob.co.uk`. No real customers, no real money.

---

## 0. Before Session F (you)

**Done during setup (2 Oct 2026):** droplet `one-quick-job-dev` (LON1, 139.59.189.19) with DNS for `dev.onequickjob.co.uk`; firewall allowing SSH, 80 and 443 only; 4 GB swap; working user `hasan` with passwordless sudo (Claude Code runs as `hasan`, never root); Docker, Node 22, uv with Python 3.14, git and `gh` logged in as `pyntheus`; repo cloned at `/srv/oqj/main` with an initial commit on `main`. From the Mac, the droplet is `ssh oqj-dev`.

**Also done:** Claude Code and OpenAI's official Codex plugin for Claude Code are installed and signed in; Codex effort is `high`; the Ubuntu 24.04 sandbox fix is applied. Every session runs its Codex reviews through `scripts/codex-review.sh`, following `docs/prompts/CODEX-review.md`. The design files below are already in the repo.

**Mac:**
```bash
scp ~/Downloads/onequickjob-prototype.jsx oqj-dev:/srv/oqj/main/docs/design/prototype.jsx
scp ~/Downloads/onequickjob-build-pack.md oqj-dev:/srv/oqj/main/docs/design/build-pack.md
```

**Browser (optional now, needed by L3):** Stripe account in test mode with Connect enabled; copy the `sk_test_` key. Ideal Postcodes account (£9 for 200 lookups); copy the API key. Everything runs on fake adapters until these keys are added to `.env`.

---

## Session F: Foundations

> Paste into: **Claude Code on the dev droplet, in `/srv/oqj/main`**

```text
You are building the foundations of OneQuickJob, a local marketplace for non-certified home and garden jobs (lawn mowing, cleaning, flat-pack, small repairs and so on) in High Wycombe, UK. This session lays the groundwork that three parallel lanes will build on afterwards, so the contracts, structure and shared code you create here matter more than any single feature. Work in /srv/oqj/main on branch f/foundations.

READ FIRST
- docs/design/prototype.jsx: a single-file React prototype of the whole product (customer, provider and admin surfaces). It is the UX and copy specification. It contains the category schema (CATEGORIES), all pricing models (PRICING_MODELS), fee logic (split, splitOwn), mock data, and every screen. Treat its copy as final unless clearly wrong. Use ONLY the "village" theme tokens; ignore the studio and toolshed themes and the prototype shell bar.
- docs/design/build-pack.md: this pack. Sections L1, L2, L3 and I describe what the lanes after you will do; design your contracts so they can work in parallel without editing each other's files.

STACK (settled, do not reopen)
- Monorepo: api/ (FastAPI), web/ (React), infra/, docs/, seed/.
- api: Python 3.14 (installed and pinned by uv via .python-version; never the system Python), uv, FastAPI, Pydantic v2, PyMongo's native async client (AsyncMongoClient; NOT Motor, which is deprecated), ruff, pytest + pytest-asyncio + httpx. No ODM: Pydantic models plus a thin repository module per collection.
- web: Vite + React + TypeScript (strict), React Router, TanStack Query, API types generated from the FastAPI OpenAPI schema with openapi-typescript. No Tailwind: port the prototype's CSS (village tokens only) into web/src/styles/ as plain CSS with the same class names, so screens can be lifted from the prototype with minimal change.
- One web app with three route groups: / (customer), /p (provider, installable PWA with a manifest), /admin.
- infra: docker-compose with mongo, api, web, caddy. SECURITY: Docker bypasses the ufw firewall for any port it publishes, so ONLY Caddy publishes ports (80 and 443). Mongo publishes no port at all, and every API and web dev-server port binds to 127.0.0.1 only. Add a make check that fails if anything else listens on a public interface. Caddy serves dev.onequickjob.co.uk with automatic HTTPS and BASIC AUTH on everything (this is a private prototype). Credentials from .env.
- Everything configurable by .env, including ports and database name, because three lanes will run side by side: lane N uses API port 800N, web port 517N, database oqj_lN, all against the one Mongo container. Provide .env.example and a Makefile (make dev, make test, make seed, make lint, make types).

DOMAIN RULES (settled)
- Money is integer pence everywhere. One module (api/app/core/money.py) owns fees: standard fee = round half-up of price x 15%; own-customer ("bring your own customers") fee = max(100p, round half-up of price x 5%). Rates come from config. Provider receives price minus fee.
- Agency structure: the customer contracts with the named provider; we are booking and payment agent. Commission is always disclosed. Never describe anything as a guarantee.
- Guide price + bidding: a request is broadcast to eligible providers; the FIRST provider to accept the guide price books it (must be atomic: findOneAndUpdate on status=open). Counter-offers wait for the customer to accept or keep waiting.
- Times stored in UTC, displayed Europe/London. Phone numbers stored E.164. UK English in all copy.
- Categories are data: port CATEGORIES (all 15 live categories, groups, required documents, intake schemas, pricing model references and params) and EXCLUDED into seed JSON loaded into Mongo. Planned or excluded jobs are never bookable.
- Pricing engine: port every model in PRICING_MODELS to api/app/pricing/ as pure functions. Pricing params live in a pricing_versions collection (status draft | live, created_by, approved_by, created_at); the engine always uses the live version and every quote records the version it used. Lawn area for v0 comes from an AreaEstimator with one implementation, manual_bands_v0: Small about 40 m2 ("about a double garage"), Medium about 85 m2, Large about 190 m2 ("about a singles tennis court"), Very large about 350 m2 ("bigger than a doubles tennis court"). It must be swappable later for a LIDAR estimator without touching callers.
- GOLDEN TESTS: with each category's default answers (and 186 m2 for mowing), the engine must return exactly: mowing 3000p a visit; hedges 6100; clearance 11000; jetwash 8800; gutters 8500; windows 2200 a clean with first visit 3300; cleaning 6600 a clean, first 8800; deepclean 20400; oven 7000; decorating 18200; flatpack 13300; mounting 11000; repairs 6000; techhelp 2500; dogwalking 1600 a walk. Fee tests: standard fee on 3000p is 450p; own-customer fee on 1500p is 100p, on 3000p is 150p.
- ROUNDING TRAP: the prototype is JavaScript, where Math.round rounds halves up; Python's round() rounds halves to even. Use Decimal with ROUND_HALF_UP everywhere the prototype uses Math.round (durations, prices, fees), or the golden tests will drift by a penny or a minute.

EXTERNAL SERVICES: adapters with fakes (each one an interface plus a fake, chosen by env)
- PaymentGateway: fake now. Lane L3 writes the Stripe implementation (Connect Express, destination charges with on_behalf_of, card saved on the platform customer, charged off-session after each visit). Define the interface now: create_provider_account, onboarding_link, save_card_setup, charge_visit(visit, price_pence, fee_pence, provider_account), refund, payout_summary.
- AddressLookup: fake (a dozen Hazlemere/Widmer End/Penn addresses with UPRN and lat/lng) plus an Ideal Postcodes implementation used when IDEAL_POSTCODES_KEY is set (autocomplete via a backend proxy so the key never reaches the browser; the credit is only spent on the final address retrieval). Store UPRN on every address.
- Notifier: OUTBOX ONLY. Every message (login codes, job alerts, booking confirmations, reminders, payouts) is written to an outbox collection with channel (sms | whatsapp | email), recipient, template id, rendered body and related ids. No real sending.
- FileStore: local disk under a mounted volume, served by Caddy behind the same basic auth.
- AreaEstimator: manual_bands_v0 as above.

AUTH
- Login by phone or email plus a 6-digit code written to the outbox (expires in 10 minutes, 5 attempts). Server-side sessions in Mongo with an httpOnly, Secure, SameSite=Lax cookie. Roles: customer, provider, admin (a user may hold several).
- DEMO_MODE=true (default in dev) adds: a floating "Outbox" drawer showing the latest messages and login codes, and a "Switch user" menu to jump between seeded users (Sarah the customer, Dave and the other providers, an admin). A thin banner reads "Prototype: test payments only". All of this disappears when DEMO_MODE is false.

WHAT TO BUILD IN THIS SESSION
1. Repo scaffold, docker-compose, Caddyfile with basic auth, .env.example, Makefile, a README with exact run commands.
2. docs/spec/: decisions.md (every rule above, as a numbered list), domain.md (every collection: fields, types, indexes, which lane owns writes), state-machines.md (request, offer, booking, recurring series, visit, dispute, own-customer invite, time-off cover), api.md (endpoint list grouped by lane), notifications.md (catalogue of every outbox template with its trigger), lanes.md (directory and route ownership per lane, merge order).
   Collections to cover at minimum: users, sessions, login_codes, customers, providers (skills, documents with status and expiry, home postcode, lat/lng, travel radius, working days, alert settings, earnings limit, helpers, payment account id, tax details stored masked), categories, pricing_versions, quotes, job_requests, offers, bookings (source: platform | own_customer), series (recurring), visits (scheduled, started, finished, minutes_actual, overrun flags, photos, charge ids, fee), ratings, disputes, message_threads and messages, outbox, ledger_entries (one per charged visit: gross, fee, net, tax_year: the tax pack and HMRC export derive from this), mileage_logs, expenses, time_off, own_customer_invites, audit_log.
3. API skeleton: every endpoint in api.md exists with full request/response Pydantic models and returns 501 until a lane implements it. Implement fully only: auth, categories (read), quote pricing (POST a category plus answers, get a priced estimate with confidence, first-visit price, duration, note, fee split), address lookup proxy, outbox read (admin and demo drawer), health.
4. Seed: categories, live pricing version, the providers, customers and own-customer data from the prototype, a few historic visits with recorded times (so admin calibration has points), and the unfilled requests and disputes shown in the prototype. make seed is idempotent.
5. Web shell: tokens and base CSS ported; shared components (Button, Chip, Choice, Stepper including compact, Toggle, CheckRow, Card, Badge, Avatar, Stars, Tabs, FlowTop, LinkRow, BarChart, Toast) in web/src/shared/; the three route groups with a layout each (customer header, provider phone-width layout with bottom nav, admin sidebar); a placeholder page for every screen listed in the prototype's SCREENS so lanes fill them in; generated API client; Outbox drawer, Switch user and prototype banner. Provider area: font-size base 17px, tap targets 44px or more. Aim for WCAG 2.2 AA.
6. Tests: pricing golden tests, fee tests, auth flow tests, an atomic first-acceptance test (two concurrent accepts, exactly one wins). make test runs everything.
7. CLAUDE.md at the repo root: the standing rules every later session reads first (stack, domain rules, the security rule, lane ownership, how to run and test, the review procedure in docs/prompts/CODEX-review.md, never merge). Keep it short and point to docs/spec/ for detail.

RULINGS YOU MAY MAKE YOURSELF
Library versions within the stack, file names and structure inside the agreed layout, test design, internal helper APIs, small copy fixes, filling gaps in the prototype with the obvious behaviour. Record each one in docs/spec/decisions.md under "Rulings made during F".

STOP AND ASK (in your report, do not guess)
Anything that changes money, fees or pricing semantics; the auth or security model; adding any external service; dropping a prototype feature; anything the golden tests can't pass without changing a model.

REVIEW AND HAND-OFF
- Codex review: follow docs/prompts/CODEX-review.md exactly (run make lint and make test yourself first, then scripts/codex-review.sh with the F focus line; one review, one re-check, a third only for an open BLOCKER). Codex findings are inputs, not vetoes.
- make lint and make test must pass. make dev must bring the stack up and the site must load behind basic auth at dev.onequickjob.co.uk.
- Push f/foundations and open a PR. DO NOT MERGE.
- Finish with a report in this shape: (1) what was built; (2) how to run it; (3) rulings you made; (4) Codex findings, each accepted or rejected with a one-line reason; (5) anything you need decided; (6) deviations from this prompt, if any, and why.
```

**After F reports:** paste the report to Claude (chat). Once the PR is merged, create the lane worktrees.

**Dev droplet:**
```bash
cd /srv/oqj/main && git checkout main && git pull
git worktree add ../lane-customer -b l1/customer
git worktree add ../lane-provider -b l2/provider
git worktree add ../lane-admin    -b l3/admin-payments
cp .env ../lane-customer/.env && sed -i 's/^API_PORT=.*/API_PORT=8001/; s/^WEB_PORT=.*/WEB_PORT=5171/; s/^MONGO_DB=.*/MONGO_DB=oqj_l1/' ../lane-customer/.env
cp .env ../lane-provider/.env && sed -i 's/^API_PORT=.*/API_PORT=8002/; s/^WEB_PORT=.*/WEB_PORT=5172/; s/^MONGO_DB=.*/MONGO_DB=oqj_l2/' ../lane-provider/.env
cp .env ../lane-admin/.env    && sed -i 's/^API_PORT=.*/API_PORT=8003/; s/^WEB_PORT=.*/WEB_PORT=5173/; s/^MONGO_DB=.*/MONGO_DB=oqj_l3/' ../lane-admin/.env
grep -H -E '^(API_PORT|WEB_PORT|MONGO_DB)=' ../lane-*/.env
```
(If F named those `.env` keys differently, adjust the `sed` to match its `.env.example`.)

**Viewing a lane's work:** lane dev servers listen only on the droplet itself, so view them through an SSH tunnel. **Mac:** `ssh -N -L 5171:127.0.0.1:5171 -L 5172:127.0.0.1:5172 -L 5173:127.0.0.1:5173 oqj-dev`, then open `http://localhost:5171` (customer lane), `:5172` (provider lane) or `:5173` (admin lane) in your browser. Leave that terminal open while you look.

---

## Session L1: Customer

> Paste into: **Claude Code on the dev droplet, in `/srv/oqj/lane-customer`**

```text
You are lane L1 (Customer) for OneQuickJob, a local marketplace for non-certified home and garden jobs in High Wycombe. Foundations are merged. Work in /srv/oqj/lane-customer on branch l1/customer, using the ports and database in this worktree's .env (API 8001, web 5171, database oqj_l1). Two other lanes run in parallel: L2 Provider and L3 Admin and payments. You must not edit files they own.

READ FIRST
CLAUDE.md, docs/prompts/CODEX-review.md, docs/spec/decisions.md, domain.md, state-machines.md, api.md, notifications.md, lanes.md (your ownership boundaries), then the customer screens in docs/design/prototype.jsx (CustomerApp and everything it renders). The prototype is the UX and copy spec; build it for real against the API.

YOUR SCOPE
Web (web/src/customer/**) and API routes marked L1 in api.md:
1. Landing: Village hero, the grouped quote starter (Outside / Indoors / Help tabs, tiles from the categories API), address autocomplete via the address proxy, How it works, Who does the work and fee split, What we don't do (from the excluded list).
2. Quote flow: the lawn size step uses the manual size bands (show the four bands with their comparisons, plus Looks smaller / About right / Looks bigger), category questions rendered generically from each category's intake schema (choice, chips, multi, number, counts, text, photos), guide price screen (price, first-visit price and reason, range, duration, confidence, note, fee split, when-suits-you), contact details with login by code, card capture through the PaymentGateway interface (fake by default), the agency checkbox wording from the prototype.
3. Request lifecycle for the customer: create the job request (status open, broadcast to eligible providers by skill, required documents, travel radius from postcode coordinates, working days and earnings-limit headroom), a "Finding someone local" screen that polls and shows broadcast, counter-offers (accept / keep waiting) and the booking; booked screen with provider badges (ID checked, Basic DBS where the category requires it, insured until, distance).
4. Account: next visit, visits list, plan (pause, cover toggle, change frequency, cancel), message thread with the provider, rate a visit (stars, tags, tip, report a problem, which creates a dispute), the provider invite acceptance screen for own customers (price set by the provider, the fee not added to the customer's price).
5. Outbox messages for every customer-side event, using the templates in notifications.md.

OUT OF SCOPE
Provider screens (L2), admin and the real Stripe gateway (L3). Use the PaymentGateway interface only; never call Stripe directly.

DEMO REQUIREMENT
Because there are no real providers, add a DEMO_MODE-only control on the "Finding someone local" screen, "Simulate local responses", which makes the nearest seeded provider with the skill counter at guide + 20% after a few seconds and the next accept at guide shortly after (through the real offer endpoints, not by writing to the database directly). It must vanish when DEMO_MODE is false.

RULINGS YOU MAY MAKE YOURSELF
Component structure, polling intervals, loading and empty states, validation messages in the prototype's tone, small copy fixes, filling prototype gaps with the obvious behaviour. Record them in your report.

STOP AND ASK
Changes to shared models or collections you don't own (write the request in docs/spec/contract-changes/L1.md and work around it with an additive change inside your own module if possible); anything touching fees, pricing or the agency wording; new external services.

ACCEPTANCE (walk it yourself before reporting)
As a logged-out visitor: pick Lawn mowing, choose an address, pick a size band, answer the questions, see £31 a visit for the default answers with the Large band (190 m2; the £30 golden test is for 186 m2), request it, log in with the code from the Outbox drawer, add the fake card, simulate responses, accept the counter or wait for the guide acceptance, see the booking, message the provider, rate a past visit, report a problem. Repeat the request flow for Regular cleaning and Flat-pack assembly. Accept an own-customer invite as Mary.

REVIEW AND HAND-OFF
Tests for every new endpoint and the main screens (vitest + Testing Library). Codex review per docs/prompts/CODEX-review.md: run the tests yourself first, then scripts/codex-review.sh with your lane's focus line; one review, one re-check, a third only for an open BLOCKER; findings are inputs, not vetoes. Rebase on main before the final review. Push and open a PR. DO NOT MERGE. Report: (1) built; (2) how to demo; (3) rulings; (4) Codex findings accepted/rejected with reasons; (5) contract-change requests; (6) open questions.
```

---

## Session L2: Provider

> Paste into: **Claude Code on the dev droplet, in `/srv/oqj/lane-provider`**

```text
You are lane L2 (Provider) for OneQuickJob, a local marketplace for non-certified home and garden jobs in High Wycombe. Providers are mostly retired and semi-retired people, so clarity, large type and big tap targets matter more than density. Foundations are merged. Work in /srv/oqj/lane-provider on branch l2/provider, using this worktree's .env (API 8002, web 5172, database oqj_l2). L1 Customer and L3 Admin and payments run in parallel; do not edit files they own.

READ FIRST
CLAUDE.md, docs/prompts/CODEX-review.md, docs/spec/decisions.md, domain.md, state-machines.md, api.md, notifications.md, lanes.md, then the provider screens in docs/design/prototype.jsx (ProviderApp and everything it renders, plus SmsScreen). Build them for real against the API under /p as an installable PWA.

YOUR SCOPE
Web (web/src/provider/**) and API routes marked L2 in api.md:
1. Entry: the outbox job-alert message links to /p/j/{id}; opening it signs the provider in with a single-use magic token (DEMO_MODE: also via Switch user). The SMS screen in the prototype is a demo of this; render the job alert in the Outbox drawer instead.
2. Jobs: greeting, week earnings and rating, the earnings-limit strip, new jobs near you (only jobs the provider is eligible for), over-limit marking, coming up.
3. Offer: approximate area (exact address only after booking), fits-your-round hint (another of their visits within a mile on the same day), facts, customer note, guide price and what they'd keep, accept at guide (atomic, first wins; a clear message if someone beat them to it), suggest a different price with reasons, over-limit warning.
4. Today: the day's round in time order; on-the-job card with a timer (start, elapsed, estimate, over-estimate state), before and after photos via the FileStore, directions link (a maps URL is fine), message the customer, finish job.
5. Finish: minutes taken (pre-filled from the timer), what was different (multi-select, "Nothing" exclusive), note; on submit: record the completion, call PaymentGateway.charge_visit through the interface L3 will implement (use the fake), write the ledger entry, send the outbox messages. Recorded times and flags are the calibration data; never skip them.
6. Earnings: weekly chart, payouts (from the gateway's payout_summary), links to Tax and records, Earnings limit, Your own customers.
7. Tax and records, derived from ledger_entries, mileage_logs and expenses: turnover (what customers paid) versus our fees versus what reached the bank; trading allowance versus actual costs comparison; automatic mileage (sum of home to job to job to home legs per working day, straight-line distance x 1.25 as the road factor, 45p a mile; record it as a calculated estimate); receipts (upload a photo, enter the amount); key dates; download the tax pack as a CSV and a printable HTML page.
8. Earnings limit: on/off, the benefits chips with the prototype's guidance (the benefit answer is NEVER stored; only the limit is), week or month, amount, progress; the limit filters job alerts and marks over-limit jobs.
9. Me: profile, documents with status and expiry (upload, expiring-soon reminders via outbox), jobs I do grouped with the missing-document prompt, travel radius, days, alert settings, add-to-home-screen help, links to Time off and helpers.
10. Time off and helpers: date range, each affected visit set to local cover / send helper / skip; cover offers the visit to other eligible providers through the normal offer flow and the visit returns to the original provider afterwards; helpers are linked user accounts with their own documents, and "Send Tom" reassigns a visit to the helper and tells the customer via outbox.
11. Your own customers: the fee comparison, the list, the invite form (name, mobile, job, the provider's own price, frequency); the invite-only rule (block numbers that already belong to platform customers with the prototype's wording); accepted invites create bookings with source own_customer.
12. Sign-up: the checklist with the benefits notice and "Set an earnings limit", tax details (NI number and date of birth stored masked except where reporting needs them), documents, skills and area, and the payment-account onboarding link from the PaymentGateway interface.

OUT OF SCOPE
Customer screens (L1); admin and the Stripe implementation (L3).

RULINGS YOU MAY MAKE YOURSELF
Layout details within the prototype, PWA manifest and icons (a simple wordmark tile is fine), service-worker caching for the app shell only, how the round is ordered, validation and empty states, small copy fixes. Record them in your report.

STOP AND ASK
Anything that changes money, fees, the ledger's meaning or the tax pack's figures; storing anything about benefits; contract changes to collections you don't own (write them in docs/spec/contract-changes/L2.md).

ACCEPTANCE (walk it yourself before reporting)
As Dave: open a job alert from the Outbox drawer, accept a mowing job, see it on Today, start the timer, add photos, finish with an overrun flag, see the ledger entry, see the tax pack update, set a weekly limit of £250 and see a job marked over it, book a week off with one visit covered and one sent to Tom, invite a new own customer and fail to invite 07700 900123. As a new provider: complete sign-up up to the payment-account link.

REVIEW AND HAND-OFF
Tests for endpoints, the mileage and tax calculations, and the limit filter. Codex review per docs/prompts/CODEX-review.md: run the tests yourself first, then scripts/codex-review.sh with your lane's focus line; one review, one re-check, a third only for an open BLOCKER; findings are inputs, not vetoes. Rebase on main before the final review. Push and open a PR. DO NOT MERGE. Report: (1) built; (2) how to demo; (3) rulings; (4) Codex findings accepted/rejected with reasons; (5) contract-change requests; (6) open questions.
```

---

## Session L3: Admin and payments

> Paste into: **Claude Code on the dev droplet, in `/srv/oqj/lane-admin`**

```text
You are lane L3 (Admin and payments) for OneQuickJob, a local marketplace for non-certified home and garden jobs in High Wycombe. Foundations are merged. Work in /srv/oqj/lane-admin on branch l3/admin-payments, using this worktree's .env (API 8003, web 5173, database oqj_l3). L1 Customer and L2 Provider run in parallel; do not edit files they own.

READ FIRST
CLAUDE.md, docs/prompts/CODEX-review.md, docs/spec/decisions.md, domain.md, state-machines.md, api.md, notifications.md, lanes.md, then the admin screens in docs/design/prototype.jsx (AdminApp and everything it renders).

PART A: STRIPE PAYMENT GATEWAY (do this first; the other lanes call its interface)
Implement the PaymentGateway interface defined in foundations with Stripe, selected when STRIPE_SECRET_KEY is set (test keys only; refuse to start if a live key is supplied while DEMO_MODE is true):
- Providers: Express connected accounts (country GB, individual), account onboarding links, account status sync.
- Customers: a Stripe Customer on the PLATFORM; card saved with a SetupIntent at request time.
- Charging a visit: a destination charge with on_behalf_of set to the provider's account (provider is the settlement merchant), transfer_data.destination the provider's account, application_fee_amount from money.py (15% standard; 5% with a 100p minimum for own customers), off-session with the saved card, idempotency key per visit. Handle requires_action and failures by marking the visit charge as failed and writing an outbox message.
- Refunds (full and partial, reversing the transfer and refunding the application fee proportionally), payout summaries per provider, and a webhook endpoint with signature verification for payment_intent.*, account.updated, payout.*, charge.refunded. Webhooks are the source of truth for final states.
- Keep the fake gateway working; it remains the default.
- Write docs/spec/payments.md explaining the flow and how to test it with Stripe's test cards and test onboarding values.

PART B: ADMIN CONSOLE (web/src/admin/**, API routes marked L3)
1. Overview: the week's KPIs computed from real data, waiting-for-a-provider list with "Copy WhatsApp message" (clipboard, with the text shown as a fallback) and "Raise guide 10%" (recorded in the audit log), where-the-work-is tiles by postcode district, own-customers card, providers needing attention (document expiry, missing tax details, stalled sign-ups).
2. Providers: table with filters, a provider detail page (documents with verify / reject and expiry, skills, ledger, ratings), suspend and reinstate (audit-logged).
3. Pricing and calibration: estimated versus actual scatter from recorded visits, the per-segment table, suggested changes generated from simple rules (for example a segment's median overrun above 20% across at least 10 jobs); "Draft this change" creates a draft pricing version; a second admin action approves it and makes it live. One user cannot both draft and approve the same version. Every change is audit-logged; quotes keep the version they used.
4. Disputes: list, stages, message both parties, propose a return visit or a partial refund (provider-funded, through the gateway), close.
5. Categories: grouped list with provider counts per category, the record viewer, the excluded list. Editing categories is out of scope for the prototype; viewing is enough.
6. Outbox: full searchable view of every message (the demo drawer shows only the latest).
7. HMRC export: a CSV per calendar year of each provider's identity fields and their gross takings and fees from the ledger, with a plain note that the format must be checked against HMRC's specification before real use.

OUT OF SCOPE
Customer (L1) and provider (L2) screens.

RULINGS YOU MAY MAKE YOURSELF
Admin layout details, table pagination, chart construction (hand-written SVG as in the prototype is fine), audit log format, webhook retry handling, small copy fixes. Record them in your report.

STOP AND ASK
Anything changing fee rules or rounding, who is the settlement merchant, or how refunds are funded; contract changes to collections you don't own (docs/spec/contract-changes/L3.md).

ACCEPTANCE (walk it yourself before reporting)
With a Stripe test key: onboard a test provider through the Express link using Stripe's test values; save a test card for a customer; charge a visit and confirm in the Stripe dashboard that the provider is the settlement merchant, the transfer is £25.50 and our fee is £4.50 on a £30 visit, and £1 on a £15 own-customer visit; refund half of a visit; receive the webhooks. Without a key: the fake gateway still passes the same tests. In admin: copy a WhatsApp message, raise a guide, verify a document, draft and approve a pricing change as two different admins, resolve a dispute with a partial refund, export the HMRC CSV.

REVIEW AND HAND-OFF
Tests for the gateway (fake, and Stripe with recorded or mocked responses), fee and refund maths, approval rules and the export. Codex review per docs/prompts/CODEX-review.md: run the tests yourself first, then scripts/codex-review.sh with your lane's focus line; one review, one re-check, a third only for an open BLOCKER; findings are inputs, not vetoes. Rebase on main before the final review. Push and open a PR. DO NOT MERGE. Report: (1) built; (2) how to demo; (3) rulings; (4) Codex findings accepted/rejected with reasons; (5) contract-change requests; (6) open questions.
```

**Merge order:** L3 first (other lanes depend on its gateway), then L1, then L2. Each lane rebases on `main` before its final review, so later merges stay clean.

---

## Session I: Integration

> Paste into: **Claude Code on the dev droplet, in `/srv/oqj/main`** (after all three lanes are merged)

```text
You are the integration session for OneQuickJob, a local marketplace for non-certified home and garden jobs in High Wycombe. Lanes L1 (Customer), L2 (Provider) and L3 (Admin and payments) are merged into main. Work on branch i/integration in /srv/oqj/main.

READ FIRST
CLAUDE.md, docs/prompts/CODEX-review.md, docs/spec/*.md (including any contract-changes files), docs/design/build-pack.md, and the three lane PR descriptions.

TASKS
1. Resolve any open contract-change requests and loose ends between lanes; list each in your report.
2. Run the whole product on the main database with make seed and the Stripe test gateway enabled.
3. Write and pass an end-to-end script (Playwright) for the core journey: Sarah requests fortnightly mowing, Dave accepts at guide, Dave completes the visit with the timer and an overrun flag, the card is charged in Stripe test mode with the correct split, Sarah rates it, the ledger and tax pack update, and the admin calibration view shows the new point. Add a second script for an own-customer job and a cover visit.
4. Production-style run on the droplet: docker-compose with built web assets (no dev servers), Caddy with HTTPS and basic auth at dev.onequickjob.co.uk, nightly mongodump to /srv/oqj/backups with 14 days kept, and a health check. Document the exact commands in README.
5. An accessibility pass on the provider area (WCAG 2.2 AA: contrast, focus, labels, 44px targets) and a mobile pass at 375px wide on all three surfaces.
6. A one-page docs/demo-script.md: the clicks to demo the product to a business partner in ten minutes.

RULINGS, STOP-AND-ASK, REVIEW
As in the lane prompts. Codex review per docs/prompts/CODEX-review.md with the I focus line: one review, one re-check, a third only for an open BLOCKER; findings are inputs, not vetoes. Push and open a PR. DO NOT MERGE. Report: (1) what changed; (2) the demo URL and how to log in; (3) rulings; (4) Codex findings accepted/rejected with reasons; (5) known gaps before a real pilot.
```

---

## Not in this build (deliberately)

LIDAR and aerial lawn measurement (manual bands for now); real SMS, WhatsApp and email; DBS, insurance and identity checks through third parties (admin verifies uploads by hand); legal terms; the company. All of these plug into adapters or admin steps that already exist.
