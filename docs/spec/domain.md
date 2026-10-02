# Domain: collections

Generated from the Pydantic models (`api/app/models/`) and repositories (`api/app/repos/`) by
`make docs`; ownership is maintained in `api/app/cli/docs.py`. Conventions:

- `_id` is a 24-hex string (a fresh ObjectId's hex); references store the same string.
- Money is integer pence in fields ending `_pence`; `SignedPence` may be negative (refunds).
- Datetimes are timezone-aware UTC. `IsoDate` fields are London calendar dates stored as
  `YYYY-MM-DD` strings. Phones are E.164.
- Seeded documents carry `_seed: true` (ignored by the models) so `make seed` can replace
  them without touching data people created.
- **Owner** decides the schema and adds repo functions; changes by anyone else go through
  `docs/spec/contract-changes/<lane>.md`. **Writers** lists who else writes and how.
- One repository class per collection in `api/app/repos/` (the catalogue's four are in
  `categories.py`, threads and messages in `messages.py`, users with sessions, codes and links
  in `users.py`). A lane needing a new read-only query on a collection it doesn't own writes it
  in its own package using `Repo(db).coll`.

## Summary

| Collection | Owner | Writers |
|---|---|---|
| `users` | F | F (auth creates; Users.add_role); L2 sign-up adds the provider role; L3 suspends |
| `sessions` | F | F only (services.auth) |
| `login_codes` | F | F only (services.auth) |
| `magic_links` | F | F mints and consumes; L1 (job alerts) and L2 (helper invites) mint via create_magic_link |
| `customers` | L1 | L1; F test factories; L1 invite acceptance creates own-customer customers |
| `providers` | L2 | L2 (self-service, sign-up); L3 via Providers.set_document / set_status; L1 via apply_rating |
| `tax_identities` | L2 | L2 writes (sign-up, sealed); L3 reads for the HMRC export |
| `categories` | L3 | Seed only in the prototype (viewing only); L3 owns future editing |
| `category_groups` | L3 | Seed only |
| `document_types` | L3 | Seed only |
| `excluded_jobs` | L3 | Seed only |
| `pricing_versions` | L3 | L3 drafts and approves; seed inserts version 1 |
| `quotes` | F | F (POST /api/quotes); L1 sets request_id |
| `job_requests` | L1 | L1 creates and cancels; F marketplace claims (status open -> booked); L2 records views; L3 raises guides |
| `offers` | F | F marketplace (counter, accept, decline, lapse) |
| `bookings` | F | F services.bookings.create_booking (marketplace, and L1's invite acceptance); L1 cancels |
| `series` | F | F creates; L1 pauses, changes frequency, cancels; F task tops up the horizon |
| `visits` | L2 | F creates (services.schedule / bookings); L2 starts, photos, finishes, helper, cover; L1 skips; L3 writes charge state from webhooks and refunds |
| `ratings` | L1 | L1 |
| `disputes` | L3 | L1 opens (stage 0); L3 runs them; L2 may add the provider's reply |
| `message_threads` | F | F creates booking threads; L3 creates dispute threads; everyone posts via Messages.post |
| `messages` | F | Every lane via Messages.post |
| `outbox` | F | Every lane via services.notify.notify only |
| `ledger_entries` | L2 | L2 via services.ledger.record_charge / record_tip; L3 via record_refund |
| `mileage_logs` | L2 | L2 |
| `expenses` | L2 | L2 |
| `time_off` | L2 | L2 |
| `own_customer_invites` | L2 | L2 creates (and records blocked attempts); L1 accepts |
| `audit_log` | F | Every lane via services.audit.audit (admin actions, pricing, money changes) |
| `files` | F | F (POST /api/files) for every lane |
| `counters` | F | core.ids.next_ref: {_id: request, booking or dispute; seq}, atomic $inc for human refs |
| `address_cache` | F | Ideal Postcodes resolutions by suggestion id, so a chosen address is paid for once |
| `fake_gateway` | L3 | The fake PaymentGateway's own state (accounts, setups, charges, refunds); no other code |

## `users`

users, sessions, login_codes, magic_links. Owner: F (auth). Lanes call app.services.auth.

Model `app.models.users.User`; repo `app.repos.users.Users`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `name` | str |  |
| `phone` | str \| None (optional) |  |
| `email` | str \| None (optional) | Lower-cased |
| `roles` | list[Literal['customer', 'provider', 'admin']] |  |
| `status` | Literal['active', 'suspended'] |  |
| `helper_of` | str \| None (optional) | Provider id this user helps, if a helper |
| `demo_key` | str \| None (optional) | Seeded users only: key for Switch user |
| `last_login_at` | datetime \| None (optional) |  |

Indexes:
- `phone` (unique; partial {'phone': {'$type': 'string'}})
- `email` (unique; partial {'email': {'$type': 'string'}})
- `demo_key` (unique; partial {'demo_key': {'$type': 'string'}})
- `roles`

## `sessions`

Server-side session. _id is the HMAC of the cookie token, never the token.

Model `app.models.users.Session`; repo `app.repos.users.Sessions`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `user_id` | str |  |
| `created_at` | datetime |  |
| `expires_at` | datetime |  |
| `last_seen_at` | datetime |  |
| `via` | Literal['code', 'magic', 'demo'] |  |
| `user_agent` | str |  |

Indexes:
- `user_id`
- `expires_at` (TTL 0s)

## `login_codes`

users, sessions, login_codes, magic_links. Owner: F (auth). Lanes call app.services.auth.

Model `app.models.users.LoginCode`; repo `app.repos.users.LoginCodes`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `identifier` | str | E.164 phone or lower-cased email |
| `channel` | Literal['sms', 'whatsapp', 'email'] |  |
| `code_hash` | str |  |
| `attempts` | int |  |
| `max_attempts` | int |  |
| `created_at` | datetime |  |
| `expires_at` | datetime |  |
| `consumed_at` | datetime \| None (optional) |  |
| `outbox_id` | str \| None (optional) |  |

Indexes:
- `identifier, created_at desc`
- `expires_at` (TTL 3600s)

## `magic_links`

Single-use sign-in token carried in job-alert links (/p/j/R-2301?t=...).

Model `app.models.users.MagicLink`; repo `app.repos.users.MagicLinks`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `token_hash` | str |  |
| `user_id` | str |  |
| `purpose` | Literal['job_alert', 'invite', 'helper_signup'] |  |
| `target_path` | str | Where the web goes after signing in |
| `created_at` | datetime |  |
| `expires_at` | datetime |  |
| `used_at` | datetime \| None (optional) |  |

Indexes:
- `token_hash` (unique)
- `expires_at` (TTL 86400s)

## `customers`

customers: one per user who books. Owner: L1.

Model `app.models.customers.Customer`; repo `app.repos.customers.Customers`. Owner L1.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `user_id` | str |  |
| `name` | str |  |
| `addresses` | list[Address] |  |
| `payment` | CustomerPayment \| None (optional) |  |
| `joined_via` | Literal['platform', 'own_customer'] | platform: found us; own_customer: invited by a provider. Drives the invite-only rule. |
| `invited_by_provider_id` | str \| None (optional) |  |
| `terms_accepted_at` | datetime \| None (optional) |  |

Indexes:
- `user_id` (unique)

## `providers`

providers and tax_identities. Owner: L2 (self-service). L3 writes document verification and suspension through app.repos.providers functions.

Model `app.models.providers.Provider`; repo `app.repos.providers.Providers`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `user_id` | str |  |
| `name` | str |  |
| `short` | str | Display name used to customers, e.g. "Dave H." |
| `initials` | str |  |
| `home` | Home |  |
| `travel_radius_miles` | int |  |
| `working_days` | list[Literal['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']] |  |
| `skills` | list[str] | Category ids |
| `documents` | list[ProviderDocument] |  |
| `alert_settings` | AlertSettings |  |
| `earnings_limit` | EarningsLimit |  |
| `helpers` | list[Helper] |  |
| `payment_account` | PaymentAccount \| None (optional) |  |
| `tax` | TaxDetails |  |
| `status` | Literal['signing_up', 'active', 'payouts_paused', 'suspended'] |  |
| `status_reason` | str \| None (optional) |  |
| `stats` | ProviderStats |  |
| `joined_on` | date \| None (optional) |  |

Indexes:
- `user_id` (unique)
- `skills`
- `status`
- `home.district`

## `tax_identities`

Full NI number and date of birth, sealed (app.core.crypto). Read only by the HMRC export.

Model `app.models.providers.TaxIdentity`; repo `app.repos.providers.TaxIdentities`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `provider_id` | str |  |
| `ni_number_sealed` | str |  |
| `dob_sealed` | str |  |
| `updated_at` | datetime |  |

Indexes:
- `provider_id` (unique)

## `categories`

categories, category_groups, document_types, excluded_jobs: the catalogue as data.

Model `app.models.categories.Category`; repo `app.repos.categories.Categories`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `name` | str |  |
| `short` | str |  |
| `group` | Literal['outside', 'inside', 'help'] |  |
| `status` | Literal['live', 'planned'] | Only live categories are bookable |
| `skill` | str | Provider skill tag, e.g. garden.mowing |
| `pricing_model` | str | Key into PRICING_MODELS |
| `measure` | Literal['lawn'] \| None (optional) | lawn: the quote flow has a lawn-size step |
| `recurring` | bool |  |
| `from_price_pence` | int |  |
| `requires` | list[Literal['identity', 'insurance', 'waste_carrier', 'ladder_cover', 'dbs_basic', 'pet_cover']] | Documents a provider must hold (verified, unexpired) |
| `intake` | list[IntakeField] |  |
| `icon` | str | lucide-react icon name used by the web |
| `sort` | int |  |

Indexes:
- `group, sort`
- `status`

## `category_groups`

categories, category_groups, document_types, excluded_jobs: the catalogue as data.

Model `app.models.categories.CategoryGroup`; repo `app.repos.categories.CategoryGroups`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `name` | str |  |
| `tab` | str | Short tab label on the quote starter |
| `sort` | int |  |

Indexes: `_id` only.

## `document_types`

categories, category_groups, document_types, excluded_jobs: the catalogue as data.

Model `app.models.categories.DocumentType`; repo `app.repos.categories.DocumentTypes`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `label` | str |  |
| `expires` | bool |  |
| `note` | str \| None (optional) |  |
| `sort` | int |  |

Indexes: `_id` only.

## `excluded_jobs`

Jobs we never list, shown to customers with who to use instead.

Model `app.models.categories.ExcludedJob`; repo `app.repos.categories.ExcludedJobs`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `name` | str |  |
| `instead` | str |  |
| `why` | str |  |
| `sort` | int |  |

Indexes: `_id` only.

## `pricing_versions`

pricing_versions: the params every pricing model reads. Owner: L3.

Model `app.models.pricing_versions.PricingVersion`; repo `app.repos.pricing_versions.PricingVersions`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `version` | int |  |
| `status` | Literal['draft', 'live', 'retired'] |  |
| `params` | dict[str, dict[str, Any]] | category id -> params for its pricing model |
| `notes` | str |  |
| `changes` | list[ParamChange] | What changed from based_on |
| `based_on` | str \| None (optional) | Version id this draft was copied from |
| `created_by` | str | User id, or 'seed' |
| `created_at` | datetime |  |
| `approved_by` | str \| None (optional) |  |
| `approved_at` | datetime \| None (optional) |  |
| `retired_at` | datetime \| None (optional) |  |

Indexes:
- `version` (unique)
- `status` (unique; partial {'status': 'live'})

## `quotes`

quotes: every priced estimate, with the pricing version it used. Owner: F (L1 reads).

Model `app.models.quotes.Quote`; repo `app.repos.quotes.Quotes`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `category_id` | str |  |
| `answers` | dict[str, Any] | Validated answers with defaults filled in |
| `measure` | Measure \| None (optional) |  |
| `address` | Address \| None (optional) |  |
| `pricing_version_id` | str |  |
| `pricing_version` | int |  |
| `result` | QuoteResult |  |
| `fee` | FeeSplit |  |
| `first_fee` | FeeSplit \| None (optional) |  |
| `user_id` | str \| None (optional) | Set if the visitor was signed in |
| `request_id` | str \| None (optional) | Set when the quote becomes a job request |

Indexes:
- `created_at desc`
- `user_id`
- `pricing_version_id`

## `job_requests`

job_requests: a customer's priced job, broadcast to eligible providers. Owner: L1.

Model `app.models.job_requests.JobRequest`; repo `app.repos.job_requests.JobRequests`. Owner L1.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `ref` | str | Human reference, e.g. R-2291. Used in job links /p/j/{ref} |
| `customer_id` | str |  |
| `category_id` | str |  |
| `quote_id` | str |  |
| `pricing_version_id` | str |  |
| `answers` | dict[str, Any] |  |
| `measure` | Measure \| None (optional) |  |
| `address` | Address | Exact address: shown to the provider only once booked |
| `approx` | GeoPoint | About 1 km resolution, for the provider's approximate map |
| `notes` | str |  |
| `when` | When |  |
| `recurring` | bool |  |
| `frequency` | str \| None (optional) |  |
| `guide_pence` | int | Integer pence |
| `first_pence` | int \| None (optional) |  |
| `mins` | int |  |
| `first_mins` | int \| None (optional) |  |
| `unit` | Literal['a visit', 'one-off', 'a clean', 'a walk'] |  |
| `photos` | list[str] | File ids |
| `status` | Literal['open', 'booked', 'cancelled', 'expired'] |  |
| `broadcast` | Broadcast \| None (optional) |  |
| `viewed_by` | list[str] | Provider ids who opened it |
| `events` | list[RequestEvent] |  |
| `booked` | Booked \| None (optional) |  |
| `direct_provider_id` | str \| None (optional) | Book again: offered to this provider only |
| `cover_for_visit_id` | str \| None (optional) | Time-off cover (L2 creates): accepting reassigns this one visit instead of creating a booking |
| `admin_note` | str \| None (optional) |  |

Indexes:
- `ref` (unique)
- `status, category_id`
- `customer_id, created_at desc`
- `broadcast.provider_ids`

## `offers`

Immutable terms: a provider who changes their price withdraws this offer and makes a new one, so a customer always accepts exactly the price they saw.

Model `app.models.offers.Offer`; repo `app.repos.offers.Offers`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `request_id` | str |  |
| `provider_id` | str |  |
| `price_pence` | int | Suggested price per visit |
| `first_price_pence` | int \| None (optional) | Optional different first-visit price |
| `guide_pence` | int | The guide price when the counter was made |
| `reasons` | list[str] |  |
| `message` | str |  |
| `status` | Literal['pending', 'accepting', 'accepted', 'declined', 'lapsed', 'withdrawn'] |  |
| `supersedes` | str \| None (optional) | The offer this one replaced (now withdrawn) |
| `accepting_at` | datetime \| None (optional) | When the customer accepted; the request claim is finished from here (resumable) |
| `decided_at` | datetime \| None (optional) |  |

Indexes:
- `request_id, status`
- `provider_id, created_at desc`
- `request_id, provider_id` (unique; partial {'status': 'pending'})

## `bookings`

bookings and series. Owner: F creates them (marketplace core); L1 changes plans, L2 creates own-customer bookings through app.services.bookings.

Model `app.models.bookings.Booking`; repo `app.repos.bookings.Bookings`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `ref` | str | Human reference, e.g. B-1104 |
| `source` | Literal['platform', 'own_customer'] |  |
| `customer_id` | str |  |
| `provider_id` | str |  |
| `category_id` | str |  |
| `request_id` | str \| None (optional) |  |
| `invite_id` | str \| None (optional) |  |
| `via` | Literal['guide', 'counter', 'invite', 'direct'] |  |
| `price_pence` | int | Agreed price per visit |
| `first_price_pence` | int \| None (optional) | First-visit price, if different |
| `unit` | Literal['a visit', 'one-off', 'a clean', 'a walk'] |  |
| `recurring` | bool |  |
| `frequency` | Literal['oneoff', 'weekly', 'fortnightly', 'threeweekly', 'fourweekly', 'eightweekly', 'monthly', 'threemonthly', 'weekdays', 'someweekdays'] |  |
| `series_id` | str \| None (optional) |  |
| `address` | Address |  |
| `answers` | dict[str, Any] |  |
| `notes` | str |  |
| `when` | Literal['morning', 'afternoon', 'either'] |  |
| `days` | Literal['any', 'weekdays', 'weekends'] |  |
| `est_mins` | int | Estimated minutes for a routine visit |
| `first_est_mins` | int \| None (optional) | Estimated minutes for the first visit |
| `pricing_version_id` | str \| None (optional) |  |
| `first_visit_start` | datetime \| None (optional) | Chosen when the booking is created, so a resumed setup schedules the same slot |
| `thread_id` | str \| None (optional) |  |
| `setup_complete` | bool | Series, first visit and thread all exist (services.bookings.finish_setup) |
| `confirmations_sent_at` | datetime \| None (optional) | Booking messages sent (once) |
| `status` | Literal['active', 'completed', 'cancelled'] |  |
| `cancelled_at` | datetime \| None (optional) |  |

Indexes:
- `ref` (unique)
- `request_id` (unique; partial {'request_id': {'$type': 'string'}})
- `invite_id` (unique; partial {'invite_id': {'$type': 'string'}})
- `customer_id, created_at desc`
- `provider_id, status`

## `series`

A recurring plan. Visits are materialised a few weeks ahead (services.schedule).

Model `app.models.bookings.Series`; repo `app.repos.series.SeriesRepo`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `booking_id` | str |  |
| `customer_id` | str |  |
| `provider_id` | str |  |
| `category_id` | str |  |
| `frequency` | Literal['oneoff', 'weekly', 'fortnightly', 'threeweekly', 'fourweekly', 'eightweekly', 'monthly', 'threemonthly', 'weekdays', 'someweekdays'] |  |
| `days` | list[Literal['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']] | Weekdays visits fall on (several for dog walks) |
| `start_time` | str | London wall-clock "HH:MM" |
| `anchor_date` | date | First visit date; intervals count from here |
| `price_pence` | int | Integer pence |
| `est_mins` | int | Estimated minutes for a routine visit |
| `window` | Literal['morning', 'afternoon', 'either'] |  |
| `status` | Literal['active', 'paused', 'cancelled'] |  |
| `pause` | Pause |  |
| `cover_when_away` | bool |  |
| `horizon_until` | date \| None (optional) | Visits exist up to this date |

Indexes:
- `booking_id` (unique)
- `provider_id, status`
- `customer_id`

## `visits`

visits: one occurrence of a booking. Owner: L2 (start, photos, finish). L3 writes charge state from webhooks; L1 skips and reschedules.

Model `app.models.visits.Visit`; repo `app.repos.visits.Visits`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `booking_id` | str |  |
| `series_id` | str \| None (optional) |  |
| `customer_id` | str |  |
| `provider_id` | str | The booked provider, who is paid |
| `performer` | Performer |  |
| `category_id` | str |  |
| `source` | Literal['platform', 'own_customer'] |  |
| `local_date` | date | London date, for day and week queries |
| `scheduled_start` | datetime | UTC |
| `window` | Literal['morning', 'afternoon', 'either'] |  |
| `is_first` | bool |  |
| `price_pence` | int | Integer pence |
| `est_mins` | int | Estimate when booked: the calibration baseline |
| `pricing_version_id` | str \| None (optional) |  |
| `status` | Literal['scheduled', 'in_progress', 'finished', 'skipped', 'cancelled'] |  |
| `started_at` | datetime \| None (optional) |  |
| `finished_at` | datetime \| None (optional) |  |
| `minutes_actual` | int \| None (optional) |  |
| `minutes_from_timer` | bool |  |
| `flags` | list[str] | "What was different", e.g. "Access was harder" |
| `flags_none` | bool | Provider chose "Nothing, it was as described" |
| `overrun` | bool \| None (optional) | minutes_actual > est_mins x 1.1 |
| `over_25` | bool \| None (optional) | minutes_actual > est_mins x 1.25 |
| `finish_note` | str |  |
| `photos` | Photos |  |
| `charge` | Charge |  |
| `tip_pence` | int | Integer pence |
| `tip_charge` | Charge \| None (optional) |  |
| `cover` | CoverState |  |
| `rating_id` | str \| None (optional) |  |
| `dispute_id` | str \| None (optional) |  |
| `skipped_reason` | str \| None (optional) |  |

Indexes:
- `provider_id, local_date`
- `performer.user_id, local_date`
- `customer_id, scheduled_start`
- `booking_id, scheduled_start`
- `status, local_date`
- `category_id, status`
- `series_id, local_date` (unique; partial {'series_id': {'$type': 'string'}})
- `booking_id` (unique; partial {'is_first': True})

## `ratings`

ratings. Owner: L1.

Model `app.models.ratings.Rating`; repo `app.repos.ratings.Ratings`. Owner L1.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `visit_id` | str |  |
| `booking_id` | str |  |
| `customer_id` | str |  |
| `provider_id` | str |  |
| `stars` | int |  |
| `tags` | list[str] |  |
| `tip_pence` | int | Integer pence |
| `comment` | str |  |

Indexes:
- `visit_id` (unique)
- `provider_id, created_at desc`

## `disputes`

We mediate; we don't guarantee. Refunds are provider-funded (decisions.md).

Model `app.models.disputes.Dispute`; repo `app.repos.disputes.Disputes`. Owner L3.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `ref` | str | Human reference, e.g. D-014 |
| `visit_id` | str |  |
| `booking_id` | str |  |
| `customer_id` | str |  |
| `provider_id` | str |  |
| `category_id` | str |  |
| `title` | str |  |
| `description` | str |  |
| `photos` | list[str] |  |
| `amount_pence` | int | Value of the visit in dispute |
| `stage` | Literal[0, 1, 2, 3] | Index into Reported, Provider replied, Fix agreed, Closed |
| `status_text` | str | One line for the admin card, e.g. Waiting for Alan's reply |
| `proposed` | Resolution \| None (optional) |  |
| `resolution` | Resolution \| None (optional) |  |
| `thread_id` | str \| None (optional) |  |
| `events` | list[DisputeEvent] |  |
| `closed_at` | datetime \| None (optional) |  |

Indexes:
- `ref` (unique)
- `visit_id`
- `stage`
- `provider_id`
- `customer_id`

## `message_threads`

message_threads and messages. Owner: F; every lane posts through app.repos.messages.

Model `app.models.messages.MessageThread`; repo `app.repos.messages.MessageThreads`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `kind` | Literal['booking', 'dispute', 'support'] |  |
| `booking_id` | str \| None (optional) |  |
| `dispute_id` | str \| None (optional) |  |
| `participants` | list[Participant] |  |
| `last_message_at` | datetime \| None (optional) |  |
| `last_message_preview` | str |  |

Indexes:
- `booking_id` (unique; partial {'booking_id': {'$type': 'string'}, 'kind': 'booking'})
- `dispute_id`
- `participants.user_id, last_message_at desc`

## `messages`

message_threads and messages. Owner: F; every lane posts through app.repos.messages.

Model `app.models.messages.Message`; repo `app.repos.messages.Messages`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `thread_id` | str |  |
| `sender_user_id` | str \| None | None for system messages |
| `sender_role` | Literal['customer', 'provider', 'admin'] \| Literal['system'] |  |
| `body` | str |  |
| `attachments` | list[str] | File ids |
| `read_by` | list[str] |  |

Indexes:
- `thread_id, created_at`

## `outbox`

A message we would have sent. Nothing is ever sent: the outbox is the channel.

Model `app.models.system.OutboxMessage`; repo `app.repos.outbox.Outbox`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `channel` | Literal['sms', 'whatsapp', 'email'] |  |
| `recipient` | Recipient |  |
| `template_id` | str |  |
| `subject` | str \| None (optional) | Email only |
| `body` | str | Rendered text exactly as it would be sent |
| `data` | dict[str, Any] | Template variables (no secrets) |
| `related` | Related |  |
| `status` | Literal['logged'] |  |
| `not_before` | datetime \| None (optional) | Held for quiet hours: would send at |
| `idempotency_key` | str \| None (optional) | Unique when set: the same message is never written twice (e.g. booking:<id>:request_booked) |
| `created_at` | datetime |  |

Indexes:
- `created_at desc`
- `recipient.user_id, created_at desc`
- `template_id, created_at desc`
- `related.request_id`
- `idempotency_key` (unique; partial {'idempotency_key': {'$type': 'string'}})

## `ledger_entries`

One charge entry per charged visit (unique on visit_id + kind=charge), plus tip, refund and adjustment entries. gross = what the customer paid, fee = ours, net = what the provider receives; gross == fee + net always.

Model `app.models.records.LedgerEntry`; repo `app.repos.ledger_entries.LedgerEntries`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `provider_id` | str |  |
| `customer_id` | str |  |
| `visit_id` | str \| None |  |
| `booking_id` | str \| None |  |
| `kind` | Literal['charge', 'tip', 'refund', 'adjustment'] |  |
| `source` | Literal['platform', 'own_customer'] |  |
| `gross_pence` | int | Integer pence; negative for refunds and reversals |
| `fee_pence` | int | Integer pence; negative for refunds and reversals |
| `net_pence` | int | Integer pence; negative for refunds and reversals |
| `occurred_at` | datetime | When the money moved (UTC) |
| `local_date` | date | London date of occurred_at |
| `tax_year` | str | UK tax year, e.g. "2026-27" |
| `gateway` | Literal['fake', 'stripe'] |  |
| `gateway_ref` | str \| None (optional) | Charge or refund id at the gateway |

Indexes:
- `visit_id, kind` (unique; partial {'kind': 'charge'})
- `provider_id, occurred_at desc`
- `provider_id, local_date`
- `tax_year, provider_id`

## `mileage_logs`

One per provider per working day: home -> job -> job -> home, straight line x 1.25.

Model `app.models.records.MileageLog`; repo `app.repos.mileage_logs.MileageLogs`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `provider_id` | str |  |
| `local_date` | date |  |
| `tax_year` | str |  |
| `legs` | list[MileageLeg] |  |
| `miles` | float | Road miles, one decimal place |
| `rate_pence_per_mile` | int |  |
| `amount_pence` | int | Integer pence |
| `method` | Literal['calculated_estimate', 'manual'] |  |
| `visit_ids` | list[str] |  |

Indexes:
- `provider_id, local_date` (unique)
- `tax_year, provider_id`

## `expenses`

ledger_entries, mileage_logs, expenses: the provider's money records. Owner: L2 (L3 writes refund entries). The tax pack and the HMRC export derive from these.

Model `app.models.records.Expense`; repo `app.repos.expenses.Expenses`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `provider_id` | str |  |
| `local_date` | date |  |
| `tax_year` | str |  |
| `description` | str |  |
| `category` | Literal['kit', 'supplies', 'fuel', 'other'] |  |
| `amount_pence` | int | Integer pence |
| `receipt_file_id` | str \| None (optional) |  |

Indexes:
- `provider_id, local_date`
- `tax_year, provider_id`

## `time_off`

time_off and own_customer_invites. Owner: L2 (L1 accepts invites).

Model `app.models.provider_ops.TimeOff`; repo `app.repos.time_off.TimeOffRepo`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `provider_id` | str |  |
| `from_date` | date |  |
| `to_date` | date |  |
| `status` | Literal['planned', 'active', 'done', 'cancelled'] |  |
| `arrangements` | list[Arrangement] |  |

Indexes:
- `provider_id, from_date`

## `own_customer_invites`

A provider inviting a customer they already have, at the provider's own price.

Model `app.models.provider_ops.OwnCustomerInvite`; repo `app.repos.own_customer_invites.OwnCustomerInvites`. Owner L2.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `created_at` | datetime |  |
| `updated_at` | datetime |  |
| `provider_id` | str |  |
| `name` | str |  |
| `phone` | str | UK phone in E.164 |
| `category_id` | str |  |
| `price_pence` | int | Integer pence |
| `frequency` | Literal['oneoff', 'weekly', 'fortnightly', 'threeweekly', 'fourweekly', 'eightweekly', 'monthly', 'threemonthly', 'weekdays', 'someweekdays'] |  |
| `token_hash` | str \| None (optional) | HMAC of the token in the invite link |
| `status` | Literal['invited', 'accepted', 'declined', 'blocked', 'expired'] |  |
| `blocked_reason` | str \| None (optional) |  |
| `customer_id` | str \| None (optional) |  |
| `booking_id` | str \| None (optional) |  |
| `accepted_at` | datetime \| None (optional) |  |
| `outbox_id` | str \| None (optional) |  |

Indexes:
- `provider_id, status`
- `phone`
- `token_hash` (unique; partial {'token_hash': {'$type': 'string'}})

## `audit_log`

outbox, audit_log, files. Owner: F. Every lane writes through app.services.notify, app.services.audit and the FileStore adapter.

Model `app.models.system.AuditEntry`; repo `app.repos.audit_log.AuditLog`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `at` | datetime |  |
| `actor` | Actor |  |
| `action` | str | Dotted verb, e.g. "request.guide_raised", "pricing.approved" |
| `target` | Related |  |
| `before` | dict[str, Any] \| None (optional) |  |
| `after` | dict[str, Any] \| None (optional) |  |
| `note` | str |  |

Indexes:
- `at desc`
- `action, at desc`
- `actor.user_id`

## `files`

outbox, audit_log, files. Owner: F. Every lane writes through app.services.notify, app.services.audit and the FileStore adapter.

Model `app.models.system.StoredFile`; repo `app.repos.files.Files`. Owner F.

| Field | Type | Notes |
|---|---|---|
| `_id` | str |  |
| `kind` | Literal['request_photo', 'visit_before', 'visit_after', 'document', 'receipt', 'dispute_photo', 'other'] |  |
| `owner_user_id` | str |  |
| `path` | str | Relative to FILES_DIR; random, unguessable |
| `url` | str | Served by Caddy behind basic auth (and by the API in dev) |
| `content_type` | str |  |
| `size` | int |  |
| `original_name` | str |  |
| `related` | Related |  |
| `created_at` | datetime |  |

Indexes:
- `owner_user_id, created_at`
- `path` (unique)

## Embedded value objects

### `Actor`

| Field | Type | Notes |
|---|---|---|
| `kind` | Literal['user', 'system'] |  |
| `user_id` | str \| None (optional) |  |
| `role` | Literal['customer', 'provider', 'admin'] \| None (optional) |  |
| `name` | str \| None (optional) |  |

### `Address`

| Field | Type | Notes |
|---|---|---|
| `line1` | str |  |
| `line2` | str |  |
| `locality` | str | Village or area, e.g. Hazlemere (post town is High Wycombe) |
| `town` | str |  |
| `postcode` | str |  |
| `district` | str | Outward code, e.g. HP15 |
| `uprn` | str \| None (optional) | Unique Property Reference Number |
| `lat` | float |  |
| `lng` | float |  |
| `label` | str | One-line display form |

### `AlertSettings`

| Field | Type | Notes |
|---|---|---|
| `sms` | bool |  |
| `whatsapp` | bool |  |
| `quiet_hours` | bool |  |
| `quiet_from` | str |  |
| `quiet_to` | str |  |

### `Arrangement`

| Field | Type | Notes |
|---|---|---|
| `visit_id` | str |  |
| `action` | Literal['cover', 'helper', 'skip'] |  |
| `helper_user_id` | str \| None (optional) |  |
| `cover_request_id` | str \| None (optional) |  |
| `state` | Literal['planned', 'arranged', 'done', 'failed'] |  |

### `Booked`

| Field | Type | Notes |
|---|---|---|
| `booking_id` | str |  |
| `provider_id` | str |  |
| `price_pence` | int | Integer pence |
| `first_price_pence` | int \| None (optional) | First-visit price, if different |
| `via` | Literal['guide', 'counter'] |  |
| `offer_id` | str \| None (optional) |  |
| `at` | datetime |  |

### `Broadcast`

| Field | Type | Notes |
|---|---|---|
| `at` | datetime |  |
| `provider_ids` | list[str] |  |
| `rule` | str | Eligibility rule that chose them |

### `Charge`

| Field | Type | Notes |
|---|---|---|
| `status` | Literal['none', 'pending', 'succeeded', 'requires_action', 'failed', 'refunded', 'partially_refunded'] |  |
| `amount_pence` | int | Integer pence |
| `fee_pence` | int | Integer pence |
| `provider_pence` | int | Integer pence |
| `gateway` | Literal['fake', 'stripe'] \| None (optional) |  |
| `charge_id` | str \| None (optional) |  |
| `payment_intent_id` | str \| None (optional) |  |
| `idempotency_key` | str \| None (optional) |  |
| `charged_at` | datetime \| None (optional) |  |
| `failure_reason` | str \| None (optional) |  |
| `refunded_pence` | int | Integer pence |
| `refund_ids` | list[str] |  |

### `CoverState`

| Field | Type | Notes |
|---|---|---|
| `state` | Literal['none', 'offered', 'covered'] |  |
| `request_id` | str \| None (optional) | The cover request offered to other providers |
| `original_provider_id` | str \| None (optional) |  |

### `CustomerPayment`

| Field | Type | Notes |
|---|---|---|
| `gateway` | Literal['fake', 'stripe'] |  |
| `gateway_customer_id` | str \| None (optional) |  |
| `setup_id` | str \| None (optional) |  |
| `setup_status` | Literal['none', 'pending', 'succeeded', 'failed'] |  |
| `card` | SavedCard \| None (optional) |  |

### `DisputeEvent`

| Field | Type | Notes |
|---|---|---|
| `at` | datetime |  |
| `by_user_id` | str \| None (optional) |  |
| `kind` | Literal['opened', 'provider_replied', 'proposed', 'agreed', 'message', 'refunded', 'closed'] |  |
| `text` | str |  |

### `EarningsLimit`

| Field | Type | Notes |
|---|---|---|
| `on` | bool |  |
| `period` | Literal['week', 'month'] |  |
| `amount_pence` | int | Integer pence |

### `FeeSplit`

| Field | Type | Notes |
|---|---|---|
| `mode` | Literal['standard', 'own_customer', 'tip'] |  |
| `rate_percent` | int |  |
| `price_pence` | int | Integer pence |
| `fee_pence` | int | Integer pence |
| `provider_pence` | int | Integer pence |

### `GeoPoint`

| Field | Type | Notes |
|---|---|---|
| `lat` | float |  |
| `lng` | float |  |

### `Helper`

| Field | Type | Notes |
|---|---|---|
| `user_id` | str |  |
| `name` | str |  |
| `relationship` | str |  |
| `status` | Literal['invited', 'checking', 'ready', 'removed'] |  |

### `Home`

| Field | Type | Notes |
|---|---|---|
| `postcode` | str |  |
| `district` | str |  |
| `area` | str | Locality shown to customers, e.g. Hazlemere |
| `location` | GeoPoint |  |

### `IntakeField`

| Field | Type | Notes |
|---|---|---|
| `key` | str |  |
| `type` | Literal['choice', 'chips', 'multi', 'number', 'counts', 'text', 'photos'] |  |
| `label` | str |  |
| `hint` | str \| None (optional) |  |
| `placeholder` | str \| None (optional) |  |
| `options` | list[IntakeOption] \| None (optional) |  |
| `items` | list[CountItem] \| None (optional) | For counts: the things being counted |
| `unit` | str \| None (optional) | For number: plural unit, e.g. bedrooms |
| `unit1` | str \| None (optional) | For number: singular unit, e.g. bedroom |
| `min` | int \| None (optional) |  |
| `max` | int \| None (optional) |  |
| `step` | int \| None (optional) |  |
| `max_photos` | int \| None (optional) | For photos: most files accepted |
| `default` | Any | Default answer: str, list[str], int, dict[str, int] or [] for photos |

### `Measure`

| Field | Type | Notes |
|---|---|---|
| `estimator` | str | AreaEstimator id, e.g. manual_bands_v0 |
| `area_m2` | int |  |
| `band` | str \| None (optional) |  |
| `adjust` | Literal['smaller', 'right', 'bigger'] \| None (optional) |  |
| `detail` | dict[str, Any] \| None (optional) | Estimator-specific, e.g. LIDAR polygons |

### `MileageLeg`

| Field | Type | Notes |
|---|---|---|
| `from_label` | str |  |
| `to_label` | str |  |
| `straight_miles` | float |  |
| `road_miles` | float |  |

### `ParamChange`

| Field | Type | Notes |
|---|---|---|
| `category_id` | str |  |
| `path` | str | Dotted path inside that category's params, e.g. growth.overgrown |
| `before` | Any (optional) |  |
| `after` | Any |  |

### `Participant`

| Field | Type | Notes |
|---|---|---|
| `user_id` | str |  |
| `role` | Literal['customer', 'provider', 'admin'] |  |
| `name` | str |  |

### `Pause`

| Field | Type | Notes |
|---|---|---|
| `winter` | bool | Outside jobs: no visits November to February |
| `away_from` | date \| None (optional) |  |
| `away_to` | date \| None (optional) |  |

### `PaymentAccount`

| Field | Type | Notes |
|---|---|---|
| `gateway` | Literal['fake', 'stripe'] |  |
| `account_id` | str |  |
| `status` | Literal['pending', 'enabled', 'restricted'] |  |
| `payouts_enabled` | bool |  |
| `bank_last4` | str \| None (optional) |  |

### `Performer`

| Field | Type | Notes |
|---|---|---|
| `kind` | Literal['provider', 'helper', 'cover'] |  |
| `provider_id` | str |  |
| `user_id` | str |  |
| `name` | str |  |

### `Photos`

| Field | Type | Notes |
|---|---|---|
| `before` | list[str] | File ids |
| `after` | list[str] |  |

### `ProviderDocument`

| Field | Type | Notes |
|---|---|---|
| `type` | Literal['identity', 'insurance', 'waste_carrier', 'ladder_cover', 'dbs_basic', 'pet_cover'] |  |
| `status` | Literal['missing', 'pending', 'verified', 'rejected', 'expired'] |  |
| `expires_on` | date \| None (optional) |  |
| `file_id` | str \| None (optional) |  |
| `verified_by` | str \| None (optional) |  |
| `verified_at` | datetime \| None (optional) |  |
| `note` | str \| None (optional) |  |

### `ProviderStats`

| Field | Type | Notes |
|---|---|---|
| `rating_avg` | float \| None (optional) |  |
| `rating_count` | int |  |
| `jobs_30d` | int |  |
| `accept_rate` | float \| None (optional) |  |

### `QuoteResult`

| Field | Type | Notes |
|---|---|---|
| `price_pence` | int | Integer pence |
| `first_pence` | int \| None (optional) |  |
| `first_reason` | str \| None (optional) |  |
| `mins` | int |  |
| `first_mins` | int \| None (optional) |  |
| `low_pence` | int | Integer pence |
| `high_pence` | int | Integer pence |
| `spread` | tuple[float, float] |  |
| `confidence` | Literal['high', 'medium', 'low'] |  |
| `unit` | Literal['a visit', 'one-off', 'a clean', 'a walk'] |  |
| `note` | str \| None (optional) |  |
| `conf_note` | str \| None (optional) |  |

### `Recipient`

| Field | Type | Notes |
|---|---|---|
| `user_id` | str \| None (optional) |  |
| `name` | str |  |
| `phone` | str \| None (optional) | E.164, for sms and whatsapp |
| `email` | str \| None (optional) |  |

### `Related`

| Field | Type | Notes |
|---|---|---|
| `user_id` | str \| None (optional) |  |
| `customer_id` | str \| None (optional) |  |
| `provider_id` | str \| None (optional) |  |
| `request_id` | str \| None (optional) |  |
| `offer_id` | str \| None (optional) |  |
| `booking_id` | str \| None (optional) |  |
| `series_id` | str \| None (optional) |  |
| `visit_id` | str \| None (optional) |  |
| `dispute_id` | str \| None (optional) |  |
| `invite_id` | str \| None (optional) |  |
| `thread_id` | str \| None (optional) |  |
| `time_off_id` | str \| None (optional) |  |

### `RequestEvent`

| Field | Type | Notes |
|---|---|---|
| `at` | datetime |  |
| `kind` | Literal['created', 'broadcast', 'viewed', 'countered', 'counter_declined', 'accepted', 'guide_raised', 'cancelled', 'note'] |  |
| `provider_id` | str \| None (optional) |  |
| `offer_id` | str \| None (optional) |  |
| `price_pence` | int \| None (optional) |  |
| `count` | int \| None (optional) | broadcast: how many providers were alerted |
| `by_user_id` | str \| None (optional) |  |
| `text` | str \| None (optional) |  |

### `Resolution`

| Field | Type | Notes |
|---|---|---|
| `kind` | Literal['return_visit', 'partial_refund', 'full_refund', 'none'] |  |
| `amount_pence` | int \| None (optional) |  |
| `refund_id` | str \| None (optional) |  |
| `funded_by` | Literal['provider'] |  |
| `note` | str |  |

### `TaxDetails`

| Field | Type | Notes |
|---|---|---|
| `complete` | bool |  |
| `ni_masked` | str \| None (optional) |  |
| `dob_masked` | str \| None (optional) |  |
| `updated_at` | datetime \| None (optional) |  |

### `When`

| Field | Type | Notes |
|---|---|---|
| `days` | Literal['any', 'weekdays', 'weekends'] |  |
| `time` | Literal['morning', 'afternoon', 'either'] |  |
