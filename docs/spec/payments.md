# Payments

How money moves in the prototype, and how to test it. Owner: L3. Stripe runs in **test mode
only**; the fake gateway is the default and needs no keys.

## The model

- **The provider is the settlement merchant.** Each provider has a Stripe **Connect Express**
  account (country GB, business type individual). The customer's agreement is with the provider;
  OneQuickJob is their booking and payment agent and takes a disclosed fee.
- **The customer is a Customer on the platform.** Their card is saved once, with a SetupIntent
  (`usage: off_session`) that the browser confirms with Stripe.js, and becomes their default
  payment method.
- **Each visit is one destination charge**, made off-session after the visit is finished:
  a PaymentIntent with `on_behalf_of` = the provider's account, `transfer_data.destination` = the
  same account and `application_fee_amount` = our fee from `app.core.money` (none on tips).
  Stripe moves the whole price to the provider and takes our fee back as an application fee.
- **Refunds are provider-funded**: the refund reverses the transfer, and our fee is returned in
  proportion with an explicit application-fee refund of exactly the amount `money.refund_split`
  gives (we don't rely on Stripe's own proportional rounding, so the ledger and Stripe always
  agree to the penny).
- **Webhooks are the source of truth** for final states.

| Visit | Price | Our fee | Provider gets | Rule |
|---|---|---|---|---|
| Customer we found | £30.00 | £4.50 | £25.50 | 15%, half-up |
| Provider's own customer | £15.00 | £1.00 | £14.00 | 5%, £1 minimum |
| Own customer, done by their helper | £15.00 | £1.00 | £14.00 | still their customer |
| Own customer, done by a cover provider | £30.00 | £4.50 | £25.50 | standard (A4) |
| First visit at £33 (A1) | £33.00 | £4.95 | £28.05 | the visit's stored price |
| Tip | £5.00 | £0 | £5.00 | no fee |
| Half refund of the £30 visit | −£15.00 | −£2.25 | −£12.75 | proportional, provider-funded |

## Configuration

| Variable | Meaning |
|---|---|
| `PAYMENT_GATEWAY` | `fake` (default) or `stripe`. Selects the gateway; `/api/config` tells the web which one. |
| `STRIPE_SECRET_KEY` | `sk_test_...` (or a restricted `rk_test_...`). Needed for `stripe`. |
| `STRIPE_PUBLISHABLE_KEY` | `pk_test_...`, for Stripe Elements in the browser. |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...`, from `stripe listen` (below). Webhooks answer 503 until it's set. |

The API **refuses to start** (`app.adapters.payments.check_payment_config`, run from the payments
router's lifespan) when:

- any live key (`sk_live_`, `rk_live_`, `pk_live_`) is set while `DEMO_MODE` is true, whichever
  gateway is selected;
- `PAYMENT_GATEWAY=stripe` has no secret key, or a value that isn't a Stripe key, or a secret and
  publishable key from different modes.

No error message ever contains a key.

## The flows

### Provider onboarding

`PaymentGateway.create_provider_account` makes the Express account (idempotency key
`account:<provider id>`, so a repeat returns the same account) and `onboarding_link` returns a
Stripe-hosted onboarding URL. L2's sign-up calls both; admins can do it from a provider's page
(**Set up payment account** / **Continue onboarding**, `POST /api/admin/providers/{id}/payment-account`).
`account.updated` webhooks keep `providers.payment_account` (status, payouts enabled, bank last 4)
in sync; **Check status** reads it on demand.

### Saving a card

`web/src/payments/CardCapture.tsx` (L3) calls L1's `POST /api/c/payment/setup`, which calls
`save_card_setup`: a platform Customer (idempotency key `customer:<customer id>`) and a
SetupIntent. With Stripe the component shows the Payment Element, confirms the SetupIntent in the
browser (`redirect: "if_required"`, so 3D Secure appears as a pop-up), then calls
`POST /api/c/payment/setup/{id}/confirm`, which calls `card_setup_status`: that makes the card the
customer's default payment method and returns brand, last 4 and expiry. Stripe.js loads only when
a card is being added with the Stripe gateway.

### Charging a visit (`app.payments.charging`)

Never inside a transaction (CLAUDE.md):

1. **Intent**: the visit's `charge` becomes `pending` with the attempt's idempotency key and the
   amounts from `money.split_for_visit(visit.price_pence, visit.source, visit.performer.kind)`,
   guarded on the charge being as it was read (two attempts can't start together).
2. **Call**: `PaymentGateway.charge_visit(..., idempotency_key=key)`. Repeating the call with the
   same key can't charge twice; Stripe returns the first result.
3. **Result**, in one transaction: the charge's status, payment intent and charge ids; on success
   the ledger `charge` entry (`services.ledger.record_charge`) and `visit_done_customer`, `receipt`
   (if the customer has an email) and `payment_on_its_way`; on failure or when the bank wants the
   customer, `charge_failed_customer` and `charge_failed_provider`, once per attempt.

Keys: `visit:<visit id>:visit` for the first attempt (`:tip` for a tip), then
`visit:<visit id>:visit:retry2`, `:retry3`... A retry needs a **new** key because Stripe replays a
declined attempt's result for 24 hours. **Retry charge** (overview, "Payments needing a look";
`POST /api/admin/visits/{id}/retry-charge`) first cancels the old attempt (or finds it went
through after all), then starts the next one.

Outcomes we can't see (Stripe unreachable, a concurrent request with the same key) leave the
charge `pending`; the webhook settles it, and the `settle_pending_payments` task (every 5
minutes, between 5 minutes and 23 hours old) repeats the call with the same key.

Failures that aren't the card (`ChargeResult.failure_code` starting `platform:`, e.g. the
provider has no payment account) never tell the customer to check their card; they show in the
admin overview.

**For L2 (finish) and L1 (tips):** after saving the finished visit, call
`await app.payments.charging.charge_visit(db, settings, gateway, visit_id)` (or
`purpose="tip"` once `tip_pence` is set). It is idempotent and returns the visit with its charge
state. Its messages use the idempotency keys `charge:<visit id>:visit:paid:<template>` and
`<attempt key>:<status>:<template>`, so a webhook arriving at the same time never doubles them.

### Refunds (`app.payments.refunds`)

1. **Intent** (`payment_refunds`), in a transaction that also writes the visit, so two refunds of
   one visit at once conflict and the retry sees the other: it must fit in what's left
   (`charge.amount - charge.refunded - refunds still pending`).
2. **Call** `PaymentGateway.refund(charge, amount, fee, idempotency_key=<intent id>)`: Stripe
   `refunds.create(reverse_transfer=true, refund_application_fee=false)` then
   `application_fees.refunds.create(amount=fee)` (key `<intent id>:fee`).
3. **Result**, one transaction: the visit's `charge.refunded_pence` and status
   (`partially_refunded` / `refunded`), a negative ledger `refund` entry, `refund_issued` to the
   customer, and an audit entry (`payment.refunded`, `funded_by: provider`).

The fee is **cumulative proportional**: each refund returns
`refund_split(total refunded after) - refund_split(total refunded before)`. One refund is exactly
`money.refund_split`; several always add up to what one refund of their total would return, and a
full refund returns exactly the fee. If the fee part fails after the customer's refund, the
intent is `fee_pending` and the settle task retries it with the same keys.

Disputes close with a refund through the same path (`dispute_id` on the intent); a repeated close
reuses the refund already made rather than making another.

### Payouts

Stripe pays providers on the account's payout schedule. `payout_summary` reads the connected
account's payouts and balance (`Stripe-Account` header). `payout.paid` sends `payout_sent`
(once per payout); `payout.failed` is audit-logged.

### Webhooks (`POST /api/payments/stripe/webhook`)

- The `Stripe-Signature` header is verified against `STRIPE_WEBHOOK_SECRET` (5-minute tolerance):
  bad or missing signature 400, no secret configured 503.
- Each event is applied **once**: its id is recorded in `payment_events` in the same transaction
  as its effects, so a second delivery (or a concurrent one) finds the record and answers
  `{"received": true, "duplicate": true}`.
- Handlers read only the event and Mongo, never Stripe, so the transaction holds nothing external.
- Order doesn't matter: a payment event applies only to the attempt named in its metadata
  (`idempotency_key`), and nothing undoes a success.
- Handled: `payment_intent.succeeded | payment_failed | requires_action | processing | canceled`,
  `charge.refunded` (confirms our refunds; one made in the Stripe dashboard is recorded in the
  ledger with our usual split and audit-logged as `payment.refund_external`), `account.updated`,
  `payout.paid`, `payout.failed`. Anything else is acknowledged and logged.
- Live-mode events are ignored while `DEMO_MODE` is on.

## Testing with Stripe (test mode)

Hasan adds the keys; never paste a key into a chat.

1. In this worktree's `.env`: `PAYMENT_GATEWAY=stripe`, `STRIPE_SECRET_KEY=sk_test_...`,
   `STRIPE_PUBLISHABLE_KEY=pk_test_...`. The Stripe account needs **Connect** enabled (test mode).
2. The Stripe CLI is installed on the droplet at `~/.local/bin/stripe` (1.53.0). The lane API
   listens only on 127.0.0.1, so Stripe can't reach it; the CLI forwards events to it. Platform
   events (payments, refunds) and Connect events (`account.updated`, `payout.*`) both need
   forwarding:

   ```bash
   cd /srv/oqj/lane-admin
   set -a; . ./.env; set +a
   STRIPE_API_KEY="$STRIPE_SECRET_KEY" stripe listen \
     --forward-to 127.0.0.1:8003/api/payments/stripe/webhook \
     --forward-connect-to 127.0.0.1:8003/api/payments/stripe/webhook
   ```

   (`STRIPE_API_KEY` in the environment is the same as `--api-key "$STRIPE_SECRET_KEY"`, but keeps
   the key out of the process list.) Leave it running (a `tmux` window, or `nohup ... &` with its
   output in `var/`).
3. Write its signing secret into `.env` without displaying it, then restart the API:

   ```bash
   cd api && uv run python -m app.payments.cli webhook-secret --env-file ../.env && cd .. && make dev
   ```

   The secret is stable for this machine and key, so this is needed once.
4. Run the acceptance check:

   ```bash
   cd api && uv run python -m app.payments.cli smoke --env-file ../.env
   ```

   It creates an Express account and prints its onboarding link: open it and use the test values
   below. Once the account can take payments it saves test card 4242 for a platform customer,
   charges £30 (standard) and £15 (own customer) and refunds half of the £30, checking against
   Stripe that the provider is the settlement merchant (`on_behalf_of`), the application fees are
   £4.50 and £1.00, the provider receives £25.50 and £14.00, and the refund returned £2.25 of our
   fee and reversed £15 of the transfer. It prints dashboard links for each payment. Re-run with
   `--account acct_...` to reuse an onboarded account. The webhooks appear in the `stripe listen`
   window and in `payment_events`.

### Test values

Express onboarding (test mode):

| Field | Value |
|---|---|
| Mobile number | `000 000 0000`, then SMS code `000000` |
| Date of birth | `01/01/1901` (verifies) |
| Address line 1 | `address_full_match` |
| ID number, if asked | `000000000` |
| Bank (GB) | sort code `10-88-00`, account number `00012345` |
| Identity document upload, if asked | Stripe's "Use test document" button |

Cards (any future expiry, any CVC, any postcode):

| Card | What happens |
|---|---|
| `4242 4242 4242 4242` | Saves, and charges succeed |
| `4000 0025 0000 3155` | 3D Secure when saving; charges off-session afterwards succeed |
| `4000 0027 6000 3184` | Always wants authentication: off-session charges come back "needs the customer" (`requires_action`) |
| `4000 0000 0000 0341` | Saves, then every charge is declined: the failure path and **Retry charge** |
| `4000 0000 0000 9995` | Declined, insufficient funds |

With the fake gateway, a customer whose name contains "decline" is declined and one containing
"3ds" needs authentication (decisions.md R37).

## Collections (L3)

| Collection | What | Writers |
|---|---|---|
| `payment_events` | One per verified webhook, `_id` = Stripe event id: type, account, object id, outcome (`applied`, `ignored`, `no_match`), received at | the webhook only |
| `payment_refunds` | One per refund: visit, charge, dispute, amount, our fee, provider's share, reason, who asked, status (`pending`, `fee_pending`, `succeeded`, `failed`), refund id | `app.payments.refunds` |
| `fake_gateway` | The fake's own records (accounts, setups, charges, refunds) | the fake only |

Both new collections and their indexes are created at start-up by the payments router; folding
them into `app.repos.ALL` and `domain.md` is a contract change (`contract-changes/L3.md`).
