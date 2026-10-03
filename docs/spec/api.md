# API

Generated from the FastAPI routes by `make docs`; the intro is in `api/app/cli/docs.py`. Live,
typed docs are at `/api/docs` and the OpenAPI schema at `/api/openapi.json`; the web's types
in `web/src/api/schema.d.ts` come from it (`make types`).

## Conventions

- Everything is under `/api`. JSON in and out; request bodies reject unknown fields (422).
- **Auth**: the `oqj_session` cookie (httpOnly, Secure, SameSite=Lax) from
  `POST /api/auth/verify`, `/api/auth/magic` or (demo) `/api/demo/switch`. Customer endpoints
  need the customer role (most also a customers record), provider endpoints the provider role
  (helpers act for their provider), admin endpoints the admin role.
- **Errors**: `{"detail": {"code": "...", "message": "...", "lane": ..., "extra": {...}}}`.
  `message` is UK English copy you can show; branch on `code`. Validation errors are FastAPI's
  standard 422.
- **Money** is integer pence in fields ending `_pence`; fee splits come from `money.py`.
  **Dates** are ISO `YYYY-MM-DD` (London); **datetimes** are UTC ISO 8601.
- **Stubs**: every lane endpoint exists with its final request and response models and answers
  `501 {"detail": {"code": "not_implemented", "lane": "L1"}}` until its lane builds it.
  Implement the body; keep the method, path and models, or change them additively and say so.
- **Ownership**: the Lane column. "F" endpoints are built and owned by foundations; lanes don't
  edit them (request changes in `docs/spec/contract-changes/<lane>.md`).

## Shared, built in foundations (F)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/health` |  | Health |  |
| `GET` | `/api/config` |  | PublicConfig |  |
| `POST` | `/api/auth/code` | CodeRequest | CodeSent | Send a 6-digit sign-in code to a phone (as a text) or email. It lands in the outbox. |
| `POST` | `/api/auth/verify` | VerifyRequest | Me | Check the code; sets the session cookie. Creates a customer account for a new number or email. |
| `POST` | `/api/auth/magic` | MagicRequest | MagicResult | Sign in from a single-use link (job alerts: /p/j/R-2301?t=...). |
| `POST` | `/api/auth/logout` |  | 204 |  |
| `GET` | `/api/auth/me` |  | Me |  |
| `GET` | `/api/demo/users` |  | list[DemoUser] | Seeded people for the Switch user menu. |
| `POST` | `/api/demo/switch` | SwitchRequest | Me | Sign in as a seeded user without a code. Only seeded (demo_key) users, only in DEMO_MODE. |
| `GET` | `/api/demo/outbox` |  | list[OutboxItem] | The latest messages, for the Outbox drawer (login codes included: it's a prototype). |
| `GET` | `/api/admin/outbox` |  | OutboxPage | Every message, newest first, searchable. L3 builds the admin view on this. |
| `GET` | `/api/categories` |  | Catalogue | Live categories with intake schemas, groups, document types and the jobs we never list. |
| `GET` | `/api/categories/{category_id}` |  | Category |  |
| `GET` | `/api/area/options` |  | AreaOptions | How the lawn step asks for size (manual bands for v0). |
| `POST` | `/api/quotes` | QuoteRequest | QuoteOut | Price a job from the live pricing version. No account needed. The quote is stored with the version used. |
| `GET` | `/api/quotes/{quote_id}` |  | QuoteOut |  |
| `GET` | `/api/address/search` |  | list[AddressSuggestion] | Suggestions as the customer types (free with Ideal Postcodes). |
| `GET` | `/api/address/{suggestion_id}` |  | Address | The full address with UPRN and coordinates (the paid lookup; cached). |
| `POST` | `/api/files` | multipart | FileOut | Upload a photo or document to the FileStore. Returns its id and URL (served behind basic auth). |
| `POST` | `/api/p/requests/{ref}/accept` |  | BookingConfirmed | Accept the guide price. The first provider to accept books the job; anyone later gets 409 already_taken ("Sorry, someone else took this job first."). |
| `POST` | `/api/p/requests/{ref}/counter` | CounterRequest | Offer | Suggest a different price. The customer accepts it or keeps waiting; if someone accepts the guide price first, the job goes to them. Re-sending replaces your pending suggestion. |
| `POST` | `/api/c/offers/{offer_id}/accept` |  | BookingConfirmed | Accept a provider's suggested price. 409 if the job was booked in the meantime. |
| `POST` | `/api/c/offers/{offer_id}/decline` |  | Offer | Keep waiting for someone at the guide price; the provider is told. |

## L1 Customer (/api/c)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/c/fees/example` |  | FeeExample | "Where your money goes" on the landing page: the split of an example price, from money.py. |
| `POST` | `/api/c/requests` | NewRequest | RequestDetail | Turn a quote into a job request: save the customer profile and address, check the card is saved, record terms acceptance, broadcast to eligible providers (alert_targets) with job_alert messages carrying magic links, and send request_sent. |
| `GET` | `/api/c/requests` |  | list[RequestSummary] |  |
| `GET` | `/api/c/requests/{ref}` |  | RequestDetail | The "Finding someone local" screen polls this: timeline, pending counters, booking. |
| `POST` | `/api/c/requests/{ref}/cancel` |  | RequestDetail |  |
| `POST` | `/api/c/requests/{ref}/price-change/approve` |  | RequestDetail | Approve a raised guide price (A12): the guide changes and the job goes out again at it. (Added by L1.) |
| `POST` | `/api/c/requests/{ref}/price-change/decline` |  | RequestDetail | Keep the original guide price (A12). (Added by L1.) |
| `POST` | `/api/c/requests/{ref}/demo/simulate` |  | SimulationStarted | DEMO_MODE only (404 otherwise): the nearest seeded provider with the skill counters at guide + 20% after a few seconds, and the next accepts at guide shortly after, through the real offer endpoints. |
| `GET` | `/api/c/profile` |  | CustomerProfile |  |
| `PATCH` | `/api/c/profile` | ProfileUpdate | CustomerProfile |  |
| `POST` | `/api/c/payment/setup` |  | CardSetup | Start saving a card through PaymentGateway.save_card_setup (fake: instantly 4242). |
| `POST` | `/api/c/payment/setup/{setup_id}/confirm` |  | CardConfirmed |  |
| `GET` | `/api/c/payment/card` |  | SavedCard \| None |  |
| `GET` | `/api/c/bookings` |  | list[BookingCard] |  |
| `GET` | `/api/c/bookings/{booking_id}` |  | BookingDetail |  |
| `POST` | `/api/c/bookings/{booking_id}/rebook` | RebookIn | RequestSummary | "Book Dave again": a request offered to the same provider at the same price. |
| `GET` | `/api/c/visits` |  | VisitsOut |  |
| `GET` | `/api/c/visits/{visit_id}` |  | CustomerVisit | One visit, for the rate screen. (Added by L1.) |
| `POST` | `/api/c/visits/{visit_id}/skip` |  | CustomerVisit |  |
| `POST` | `/api/c/visits/{visit_id}/change-date` | ChangeDateIn | CustomerVisit |  |
| `POST` | `/api/c/visits/{visit_id}/rating` | RatingIn | RatingOut | Stars, tags and an optional tip (charged with PaymentGateway.charge_visit, purpose tip, fee 0). |
| `POST` | `/api/c/visits/{visit_id}/problem` | ProblemIn | ProblemOut | "Something not right?": opens a dispute (stage 0) and tells the provider. |
| `GET` | `/api/c/plans` |  | list[PlanOut] |  |
| `GET` | `/api/c/plans/{series_id}` |  | PlanOut |  |
| `PATCH` | `/api/c/plans/{series_id}` | PlanUpdate | PlanOut | Pauses and cover change at once. A new frequency is re-priced and sent to the provider to accept (A10): the plan carries on unchanged until they do (see pending_change). |
| `GET` | `/api/c/plans/{series_id}/reprice` |  | PlanPrice | What the plan would cost at another frequency, from the pricing engine (A10). Nothing changes. (Added by L1.) |
| `POST` | `/api/c/plans/{series_id}/cancel` |  | PlanOut |  |
| `GET` | `/api/c/threads` |  | list[ThreadSummary] |  |
| `GET` | `/api/c/threads/{thread_id}/messages` |  | list[MessageOut] |  |
| `POST` | `/api/c/threads/{thread_id}/messages` | NewMessage | MessageOut |  |
| `GET` | `/api/c/plan-changes/{token}` |  | PlanChangeView | Public: the link in the provider's text (the token is the authority, like an invite). (Added by L1.) |
| `POST` | `/api/c/plan-changes/{token}/accept` |  | PlanChangeView | The provider accepts the new frequency and price: the plan changes now. (Added by L1.) |
| `POST` | `/api/c/plan-changes/{token}/decline` |  | PlanChangeView | The provider declines: the plan stays as it is. (Added by L1.) |
| `GET` | `/api/c/invites/{token}` |  | InvitePreview | Public: the invite link in the provider's text. No sign-in needed to read it. |
| `POST` | `/api/c/invites/{token}/accept` | InviteAccept | BookingCard | Signed in with the invited number: creates the customer (joined_via own_customer) and a booking with source own_customer via app.services.bookings.create_booking, in one transaction with marking the invite accepted and its messages. |

## L2 Provider (/api/p)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/p/home` |  | ProviderHome |  |
| `GET` | `/api/p/jobs` |  | list[JobCard] | Open requests this provider can take (eligibility.can_take), nearest first, over-limit marked. |
| `GET` | `/api/p/requests/{ref}` |  | JobOffer | The offer screen. Records a view (JobRequests.record_view) the first time. |
| `GET` | `/api/p/today` |  | TodayRound |  |
| `GET` | `/api/p/visits/{visit_id}` |  | ProviderVisit |  |
| `POST` | `/api/p/visits/{visit_id}/start` |  | ProviderVisit |  |
| `POST` | `/api/p/visits/{visit_id}/photos` | PhotoIn | ProviderVisit |  |
| `POST` | `/api/p/visits/{visit_id}/finish` | FinishIn | FinishOut | Record minutes and flags (calibration data), charge through PaymentGateway.charge_visit with the fee from money.split_for_visit(price, source, performer kind) (a cover provider pays 15% even on an own customer), write the ledger entry (services.ledger), send messages. The charge is never inside a transaction: save the finished visit first, charge with the visit's idempotency key, then record the result, ledger entry and messages in one. |
| `POST` | `/api/p/visits/{visit_id}/send-helper` | SendHelperIn | ProviderVisit |  |
| `POST` | `/api/p/visits/{visit_id}/cover` |  | ProviderVisit |  |
| `GET` | `/api/p/earnings` |  | EarningsOut |  |
| `GET` | `/api/p/tax` |  | TaxSummary |  |
| `GET` | `/api/p/tax/pack.csv` |  | None |  |
| `GET` | `/api/p/tax/pack.html` |  | None |  |
| `GET` | `/api/p/mileage` |  | list[MileageDay] |  |
| `GET` | `/api/p/expenses` |  | list[ExpenseOut] |  |
| `POST` | `/api/p/expenses` | ExpenseIn | ExpenseOut |  |
| `DELETE` | `/api/p/expenses/{expense_id}` |  | 204 |  |
| `GET` | `/api/p/limit` |  | LimitView |  |
| `PUT` | `/api/p/limit` | LimitIn | LimitView |  |
| `GET` | `/api/p/profile` |  | ProviderProfile |  |
| `PATCH` | `/api/p/profile` | ProfilePatch | ProviderProfile |  |
| `GET` | `/api/p/documents` |  | list[DocumentOut] |  |
| `POST` | `/api/p/documents` | DocumentIn | DocumentOut | Attach an uploaded file (POST /api/files) as a document, status pending, for admin checks. Work out its expiry with services.documents.expiry_for (a basic DBS check: 12 months from issue). |
| `POST` | `/api/p/time-off/preview` | TimeOffRange | list[AffectedVisit] |  |
| `GET` | `/api/p/time-off` |  | list[TimeOffOut] |  |
| `POST` | `/api/p/time-off` | TimeOffIn | TimeOffOut |  |
| `DELETE` | `/api/p/time-off/{time_off_id}` |  | 204 |  |
| `GET` | `/api/p/helpers` |  | list[HelperOut] |  |
| `POST` | `/api/p/helpers` | HelperNew | HelperOut |  |
| `GET` | `/api/p/own-customers` |  | OwnCustomersView |  |
| `POST` | `/api/p/own-customers/invites` | InviteIn | InviteOut | 409 platform_customer if the number already belongs to a platform customer (recorded as blocked). |
| `GET` | `/api/p/threads` |  | list[ThreadSummary] |  |
| `GET` | `/api/p/threads/{thread_id}/messages` |  | list[MessageOut] |  |
| `POST` | `/api/p/threads/{thread_id}/messages` | NewMessage | MessageOut |  |
| `GET` | `/api/p/signup` |  | SignupChecklist |  |
| `POST` | `/api/p/signup/start` | SignupStart | SignupChecklist | Adds the provider role (Users.add_role) and creates the providers record (status signing_up). |
| `PUT` | `/api/p/signup/tax` | TaxDetailsIn | TaxDetailsOut | Seal the full values in tax_identities (core.crypto.seal); keep only masked copies on providers. |
| `POST` | `/api/p/signup/payment-account` |  | OnboardingLink | PaymentGateway.create_provider_account then onboarding_link. |
| `POST` | `/api/p/signup/callback` | CallbackIn | Ack |  |

## L3 Admin and payments (/api/admin, /api/payments)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| `GET` | `/api/admin/overview` |  | Overview |  |
| `GET` | `/api/admin/requests/{ref}/whatsapp` |  | WhatsAppText | The text for the providers' WhatsApp group, with the job link (/p/j/{ref}). |
| `POST` | `/api/admin/requests/{ref}/raise-guide` | RaiseGuideIn | UnfilledRequest | Suggest a higher guide price for an open request (rounded to whole pounds), audit-logged. It waits for the customer's approval (A12): the request shows "Awaiting customer" until then. |
| `GET` | `/api/admin/providers` |  | list[ProviderRow] |  |
| `GET` | `/api/admin/providers/{provider_id}` |  | ProviderDetail |  |
| `POST` | `/api/admin/providers/{provider_id}/documents/{doc_type}/verify` | VerifyDocIn | ProviderDetail | Set the expiry with services.documents.expiry_for (a basic DBS check: 12 months from its issue date); F's task reminds the provider 30 days before it lapses. |
| `POST` | `/api/admin/providers/{provider_id}/documents/{doc_type}/reject` | RejectDocIn | ProviderDetail |  |
| `POST` | `/api/admin/providers/{provider_id}/suspend` | SuspendIn | ProviderDetail |  |
| `POST` | `/api/admin/providers/{provider_id}/reinstate` |  | ProviderDetail |  |
| `POST` | `/api/admin/providers/{provider_id}/nudge` | NudgeIn | OutboxItem |  |
| `POST` | `/api/admin/providers/{provider_id}/payment-account` |  | OnboardingLinkOut | Create the provider's payment account if needed and return the payment provider's hosted onboarding link (L3 addition: lets admin support a provider through Stripe onboarding). |
| `POST` | `/api/admin/providers/{provider_id}/payment-account/sync` |  | ProviderDetail | Read the account's state from the payment provider now (webhooks do it too; L3 addition). |
| `GET` | `/api/admin/pricing/calibration` |  | Calibration |  |
| `GET` | `/api/admin/pricing/versions` |  | list[PricingVersionSummary] |  |
| `GET` | `/api/admin/pricing/versions/{version_id}` |  | PricingVersion |  |
| `POST` | `/api/admin/pricing/versions` | DraftIn | PricingVersionSummary |  |
| `POST` | `/api/admin/pricing/versions/{version_id}/approve` |  | PricingVersionSummary | A different admin from the drafter makes it live; the old live version is retired. |
| `GET` | `/api/admin/disputes` |  | list[DisputeView] |  |
| `GET` | `/api/admin/disputes/{ref}` |  | DisputeView |  |
| `POST` | `/api/admin/disputes/{ref}/message` | DisputeMessageIn | DisputeView |  |
| `POST` | `/api/admin/disputes/{ref}/propose` | ProposeIn | DisputeView |  |
| `POST` | `/api/admin/disputes/{ref}/close` | CloseIn | DisputeView |  |
| `POST` | `/api/admin/visits/{visit_id}/refund` | RefundIn | RefundOut | Provider-funded refund through PaymentGateway.refund, split by money.refund_split, recorded with services.ledger.record_refund. |
| `POST` | `/api/admin/visits/{visit_id}/retry-charge` |  | ChargeState |  |
| `GET` | `/api/admin/categories` |  | list[CategoryAdminRow] |  |
| `GET` | `/api/admin/categories/{category_id}` |  | CategoryRecord |  |
| `GET` | `/api/admin/hmrc-export.csv` |  | None | Per calendar year: each provider's identity fields and gross takings and fees from the ledger. The format must be checked against HMRC's specification before real use. |
| `GET` | `/api/admin/audit` |  | list[AuditEntry] |  |
| `POST` | `/api/payments/stripe/webhook` |  | WebhookAck | Verify the Stripe-Signature header, then handle payment_intent.*, account.updated, payout.* and charge.refunded idempotently (by event id). Webhooks are the source of truth for final payment states. |

127 endpoints.
