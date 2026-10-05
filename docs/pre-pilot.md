# Before any real customer or provider

The prototype is safe to demo because nothing in it is real: fake payments, fake addresses, texts
that only appear in an on-screen Outbox, one shared password, and test data. Everything below
has to be done before a real person's job, money or details go into it. Each line says why.

## Keys and secrets

- [ ] **Rotate the tax data key** with `make rotate-tax-key` on the droplet, then copy the new
  `TAX_DATA_KEYS` and `TAX_DATA_KEY_CURRENT` lines straight from the droplet's `.env` into the
  password manager (don't retype them, and never send them by chat or email).
  *Why:* the current key has lived on a development box during the build; NI numbers and dates
  of birth must be sealed with a key only Hasan holds, and a backup can't be read without it.
- [ ] **Give Mongo a password** (and a separate user for the app with only the access it needs).
  *Why:* today it relies on having no published port; one wrong Docker setting would expose
  every customer and provider record.
- [ ] **Replace the shared basic-auth password** with proper accounts only (or remove it once the
  site is public).
  *Why:* one password shared by two people is fine for a prototype, not for customers.
- [ ] **Check no test or demo secrets are reused**: a fresh `SECRET_KEY`, fresh admin accounts
  in real names, and the seeded demo people removed.
  *Why:* everything from the build is known to more machines than it should be.

## Money

- [ ] **A full Stripe test-mode run**: provider onboarding (Connect Express), a saved card, a
  charge after a visit with the right split, a refund, a failed card, a 3-D Secure card and a
  payout, with webhooks arriving at the real site.
  *Why:* the prototype runs on the fake gateway only; the Stripe code has been written and
  unit-tested but never driven end to end against Stripe.
- [ ] **A fresh Codex review of payment recovery** (unknown charge outcomes, retries, the settle
  task, refunds and their fee returns) after that run, and fixes for anything it finds.
  *Why:* this is the code that decides whether someone is charged twice or not at all.
- [ ] **Live Stripe keys only on the production server**, never in the repo or `.env.example`.
  *Why:* the API refuses live keys in DEMO_MODE, but the rule must hold everywhere.

## Addresses, texts and emails

- [ ] **An Ideal Postcodes key** (`IDEAL_POSTCODES_KEY`), with a spending limit set in their
  dashboard.
  *Why:* the fake list has a dozen made-up addresses between Hazlemere and Penn; real customers
  need every address, with its UPRN.
- [ ] **A real text and email channel** behind the outbox (an SMS provider, WhatsApp Business
  if wanted, and an email service), with the sender name, opt-outs and quiet hours tested.
  *Why:* with DEMO_MODE off nobody can sign in today: sign-in codes only appear in the Outbox
  drawer, and job alerts, booking confirmations and receipts reach nobody.
- [ ] **Official postcode centroids for the admin map**: load the free OS Code-Point Open (or
  the ONS Postcode Directory) centroids for the pilot's districts into the lookup the map uses
  (`app/services/postcodes.py`), and show its attribution where they're used ("Contains OS data
  © Crown copyright and database right" and, for the ONS data, "Contains Royal Mail data ©
  Royal Mail copyright and database right" and "Source: Office for National Statistics
  licensed under the Open Government Licence v.3.0").
  *Why:* the admin map plots each provider at their home postcode's centre, never their address
  (decisions.md A33). Today only the demo's postcodes are in its table; any other postcode falls
  back to the home rounded to about 1 km, which is safe but vague (A40).

## Turning DEMO_MODE off

- [ ] **Set `DEMO_MODE=false`** on the real server and check each of these is gone:
  the Outbox drawer, Switch user, the "Prototype: test payments only" strip, the request
  simulator, starting a visit before its day, and the demo endpoints (they answer 404); demo
  sign-in sessions are refused, and the admin outbox masks sign-in codes.
  *Why:* every one of those is a back door or a way to see someone else's code; the API removes
  them as well as the screens, and that should be seen working before launch.

## Data and backups

- [ ] **Off-site backups**: copy each night's archive to storage in another place (and test a
  restore from there), keeping the 14-day rotation.
  *Why:* today's backups sit on the same droplet as the database; losing the droplet loses both.
- [ ] **Protect uploaded files**: photos and documents are reachable by anyone with their link
  and the site password.
  *Why:* insurance certificates and ID photos need a check that the viewer may see them.
- [ ] **Data protection basics**: ICO registration, a privacy notice, how long each kind of
  record is kept, and how someone gets their data or has it deleted.
  *Why:* the business will hold names, addresses, phone numbers, payment and tax details.

## The business

- [ ] **The company** formed, with a bank account and insurance of its own.
  *Why:* customers' payments are taken on providers' behalf; that needs a proper legal entity.
- [ ] **Terms for customers and providers**, and a **legal opinion** on the agency model (we act
  as the provider's booking and payment agent, the customer's agreement is with the provider,
  the commission is always shown) and on the earnings-limit feature for people on benefits.
  *Why:* the whole model rests on that structure being right, and on never promising what we
  can't guarantee.
- [ ] **DBS and insurance partners**: a basic DBS checking service and an insurance route for
  providers (or a firm rule on what cover counts), replacing an admin checking uploads by eye.
  *Why:* "every provider checked" has to mean the same thing every time, with an audit trail.

## Pricing

- [ ] **The lawn-measurement experiment**: measure lawns from the Environment Agency's 2023 LIDAR
  with the 2014 infrared survey to tell grass from hedges and paths, and compare the results with
  a set of tape-measured gardens before using them for prices.
  *Why:* lawn prices today come from a size band the customer picks; a measured area would make
  the guide price fairer, but only once we know how far off it can be.
- [ ] **A first calibration review** after the first real weeks (admin, Pricing), with any
  changes drafted and approved by different people.
  *Why:* the guide prices are the prototype's; real times and flags should correct them.

## Running it

- [ ] **Monitoring**: an uptime check on the site and the API health, and alerts on errors and
  on failed backups or payments.
  *Why:* today `make status` only tells you when you run it.
- [ ] **A support route**: who answers customers and providers, and how disputes are worked.
  *Why:* the admin screens exist; the people and hours behind them don't yet.
