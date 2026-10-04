# Notifications: the outbox template catalogue

Generated from `api/app/services/templates.py` by `make docs`. Do not edit by hand.

Nothing is ever sent. Every message is rendered and written to the `outbox` collection with its
channel, recipient, template id, rendered body and related ids (`app.services.notify.notify`).
The demo Outbox drawer shows the latest messages; admins search them all at `/admin/outbox`.

Rules for message copy: UK English; texts start with the brand; say who the agreement is with
where it matters; never promise or guarantee anything; links are full URLs built from
`PUBLIC_BASE_URL`. Sections are grouped by the lane that writes the code that sends each one.
Every template is in the catalogue file, including the ones the lanes added (folded in by the
shared-fixes session); add new ones there.

60 templates.

## Shared (sent by foundation code, or by any lane)

| Template | Channels | To | Trigger |
|---|---|---|---|
| `login_code` | Text, Email | anyone | Someone asks to sign in with a phone number or email (POST /api/auth/code). |
| `counter_offer` | Text | customer | A provider suggests a different price on an open request. |
| `request_booked` | Text | customer | An open request is booked (guide accepted by a provider, or the customer accepted a counter). |
| `message_received` | Text | anyone | Someone posts in a message thread; texted to the other participants (sent by whichever lane's endpoint posted it). |
| `booking_confirmed` | Text | provider | A provider's guide acceptance, or a counter the customer accepted, books the job. |
| `counter_declined` | Text | provider | The customer chooses to keep waiting instead of accepting a counter. |
| `job_taken` | Text | provider | A request books while the provider's counter was still waiting. |
| `guide_raise_withdrawn` | Text | customer | A request is booked (at the guide, or a counter the customer accepted) while a raised guide waits for the customer's approval: the raise is withdrawn in the booking's transaction (A12, A16). |
| `counter_lapsed` | Text | provider | A customer tries to accept a provider's counter, but the provider can no longer take the job (no longer eligible): the counter lapses and the request stays open for others (ruling A9). |
| `document_expiring` | Text | provider | 30 days before a verified document expires (insurance, a basic DBS check 12 months after issue, waste carrier, ladder and pet cover). Sent once per expiry date by the document_expiry task. |
| `provider_activated` | Text | provider | A provider signing up has every required check done (ID, insurance, tax details, a payout account, and a basic DBS check if a chosen job needs one): they become active automatically (A19). |

**`login_code`** (subject: Your {brand} sign-in code)

> {brand}: your sign-in code is {code}. It expires in {minutes} minutes. Don't share it with anyone.

Placeholders: `brand`, `code`, `minutes`

**`counter_offer`**

> {brand}: {provider} suggested {price}{first_text} for your {category}, instead of {guide}. {reason}Accept it or keep waiting: {link}

Placeholders: `brand`, `provider`, `price`, `first_text`, `category`, `guide`, `reason`, `link`

**`request_booked`**

> {brand}: you're booked with {provider} for {category}. {when_text}. {price} {unit}, charged after {charged_after}. Your agreement is with {provider_first}; we arrange it and take payment for them. {link}

Placeholders: `brand`, `provider`, `category`, `when_text`, `price`, `unit`, `charged_after`, `provider_first`, `link`

**`message_received`**

> {brand}: {sender} sent you a message: "{preview}" Reply: {link}

Placeholders: `brand`, `sender`, `preview`, `link`

**`booking_confirmed`**

> {brand}: it's yours. {category} in {area}. {when_text}. You'll get {net} {unit} after the {fee_percent}% {brand} fee. {link}

Placeholders: `brand`, `category`, `area`, `when_text`, `net`, `unit`, `fee_percent`, `link`

**`counter_declined`**

> {brand}: {customer} would rather wait for the guide price of {guide}. If you'd like the {category} job in {area} at that price, it's still open: {link}

Placeholders: `brand`, `customer`, `guide`, `category`, `area`, `link`

**`job_taken`**

> {brand}: the {category} job in {area} has gone to someone else. Thanks for looking.

Placeholders: `brand`, `category`, `area`

**`guide_raise_withdrawn`**

> {brand}: {provider} has booked your {category} at {booked_at}, so the higher guide price we suggested ({proposed}) no longer applies. There's nothing you need to do.

Placeholders: `brand`, `provider`, `category`, `booked_at`, `proposed`

**`counter_lapsed`**

> {brand}: {customer} tried to accept your price of {price} for the {category} job in {area}, but you can't take it at the moment. {reason} Your price has lapsed and the job is open to other providers. {link}

Placeholders: `brand`, `customer`, `price`, `category`, `area`, `reason`, `link`

**`document_expiring`**

> {brand}: your {document} runs out on {date}. Upload the new one so you can keep taking {jobs}: {link}

Placeholders: `brand`, `document`, `date`, `jobs`, `link`

**`provider_activated`**

> {brand}: you're all set, {first}. Your checks are done, so jobs near you will start coming through. {link}

Placeholders: `brand`, `first`, `link`

## L1 Customer

| Template | Channels | To | Trigger |
|---|---|---|---|
| `request_sent` | Text | customer | A job request is created and broadcast to eligible providers. |
| `request_no_providers` | Text | customer | A request is created but no provider is eligible for an alert (admin dispatches by hand). |
| `visit_skipped` | Text | customer | The customer skips a visit, or it is skipped for time off. |
| `plan_changed` | Text | customer | The customer pauses, resumes or changes the frequency of a plan. |
| `plan_cancelled` | Text | customer | The customer cancels a plan. |
| `problem_reported` | Text | customer | The customer reports a problem with a visit (a dispute is opened). |
| `request_closed` | Text | provider | A request closes without being booked (the customer cancels it, or it expires) while the provider's suggested price was still waiting. |
| `request_expired` | Text | customer | An open request has had no booking for 7 days and closes (request_expiry task). |
| `guide_raise_proposed` | Text | customer | The team suggests a higher guide price for an open request nobody has taken (admin's Raise guide); nothing changes unless the customer approves it on Finding someone local (A12). |
| `plan_change_proposed` | Text | provider | A customer asks to change how often their plan's visits happen; the provider accepts or declines the re-priced plan within 48 hours (A10). |
| `plan_change_requested` | Text | customer | The customer has asked to change how often; the provider has been asked (A10). |
| `plan_change_accepted` | Text | customer | The provider accepts a change of frequency and its new price (A10). |
| `plan_change_declined` | Text | customer | The provider declines a change of frequency (A10). |
| `plan_change_lapsed` | Text | customer | The provider hasn't answered a change of frequency within 48 hours (plan_change_expiry task, A10). |
| `job_alert` | Text, WhatsApp | provider | A request is broadcast: one per eligible provider, on their chosen channels; held in quiet hours. |
| `rating_received` | Text | provider | A customer rates a visit. |
| `dispute_opened` | Text | provider | A customer reports a problem with a provider's visit. |
| `invite_accepted` | Text | provider | An invited own customer accepts. |

**`request_sent`**

> {brand}: we've sent your {category} request to checked providers near {district}. We'll text you as soon as someone local picks it up.

Placeholders: `brand`, `category`, `district`

**`request_no_providers`**

> {brand}: we've got your {category} request. We're finding someone local by hand, which can take a little longer. We'll text you as soon as it's booked.

Placeholders: `brand`, `category`

**`visit_skipped`**

> {brand}: your {category} visit on {date} is skipped. {next_text}

Placeholders: `brand`, `category`, `date`, `next_text`

**`plan_changed`**

> {brand}: your {category} plan with {provider} has changed: {summary}.

Placeholders: `brand`, `category`, `provider`, `summary`

**`plan_cancelled`**

> {brand}: your {category} plan with {provider} is cancelled. There's no fee.

Placeholders: `brand`, `category`, `provider`

**`problem_reported`**

> {brand}: thanks for telling us. We've let {provider} know what happened and will text you within a day.

Placeholders: `brand`, `provider`

**`request_closed`**

> {brand}: the {category} job in {area} is no longer available, so your suggested price no longer stands. Thanks for looking.

Placeholders: `brand`, `category`, `area`

**`request_expired`**

> {brand}: we couldn't find someone local for your {category} request this time, so we've closed it. Nothing has been charged. You can ask again whenever you like: {link}

Placeholders: `brand`, `category`, `link`

**`guide_raise_proposed`**

> {brand}: to help find someone local for your {category}, we suggest raising the guide price to {price}{first_text} (it's {current} now). Nothing changes unless you approve it: {link}

Placeholders: `brand`, `category`, `price`, `first_text`, `current`, `link`

**`plan_change_proposed`**

> {brand}: {customer} would like their {category} {new_frequency} instead of {old_frequency}. At that frequency the price would be {price} a visit (it's {current} now). Please accept or decline by {deadline}: {link}

Placeholders: `brand`, `customer`, `category`, `new_frequency`, `old_frequency`, `price`, `current`, `deadline`, `link`

**`plan_change_requested`**

> {brand}: we've asked {provider} about your {category} {new_frequency} at {price} a visit. Your plan carries on as it is unless they accept.

Placeholders: `brand`, `provider`, `category`, `new_frequency`, `price`

**`plan_change_accepted`**

> {brand}: {provider} accepted. Your {category} is now {new_frequency} at {price} a visit. {next_text}

Placeholders: `brand`, `provider`, `category`, `new_frequency`, `price`, `next_text`

**`plan_change_declined`**

> {brand}: {provider} would rather keep your {category} {old_frequency} at {current} a visit, so your plan stays as it is. You can message them from your account.

Placeholders: `brand`, `provider`, `category`, `old_frequency`, `current`

**`plan_change_lapsed`**

> {brand}: {provider} hasn't answered within 48 hours, so your {category} plan stays {old_frequency} at {current} a visit. You can ask again from your account.

Placeholders: `brand`, `provider`, `category`, `old_frequency`, `current`

**`job_alert`**

> {brand}: New job near you. {category} in {area} ({district}), about {mins} minutes, {frequency}. Guide price {guide}, you'd get {net}.{route} Take a look: {link}

Placeholders: `brand`, `category`, `area`, `district`, `mins`, `frequency`, `guide`, `net`, `route`, `link`

**`rating_received`**

> {brand}: {customer} rated your {category} {stars} out of 5.{tip_text}

Placeholders: `brand`, `customer`, `category`, `stars`, `tip_text`

**`dispute_opened`**

> {brand}: {customer} has told us something wasn't right with {category} on {date}: "{summary}" Please reply within a day: {link}

Placeholders: `brand`, `customer`, `category`, `date`, `summary`, `link`

**`invite_accepted`**

> {brand}: {customer} accepted your invite. Their first visit through {brand} is {date}.

Placeholders: `brand`, `customer`, `date`

## L2 Provider

| Template | Channels | To | Trigger |
|---|---|---|---|
| `visit_reminder_customer` | Text | customer | The day before a scheduled visit, 6pm. |
| `visit_done_customer` | Text | customer | A provider finishes a visit and the card is charged. |
| `receipt` | Email | customer | A visit is charged (same moment as visit_done_customer). |
| `helper_coming` | Text | customer | A provider sends their helper to a visit. |
| `cover_coming` | Text | customer | Another provider takes a cover visit while the regular provider is away. |
| `own_customer_invite` | Text | customer | A provider invites a customer they already have. |
| `cover_alert` | Text, WhatsApp | provider | A provider asks for cover; the visit is offered to other eligible providers. |
| `visit_reminder_provider` | Text | provider | The day before a provider's first visit of the day, 6pm. |
| `payment_on_its_way` | Text | provider | A visit is charged successfully. |
| `limit_reached` | Text | provider | A provider's earnings for the period reach their limit. |
| `time_off_arranged` | Text | provider | A provider books time off and the affected visits are arranged. |
| `helper_invite` | Text | helper | A provider adds a helper. |
| `tax_key_date` | Text | provider | A month before 5 October (Self Assessment registration) and 31 January (return and payment). |
| `callback_requested` | Email | admin | A provider taps "Call me" during sign-up. |
| `time_off_unarranged` | Text | provider | A visit is booked into a provider's time off after they arranged it (once per visit). |
| `cover_not_found` | Text | provider | Nobody took a cover visit by the day before, so it's skipped and the customer is told. |
| `visit_done_customer_no_photo` | Text | customer | A provider finishes a visit without adding an after photo, and the card is charged. |

**`visit_reminder_customer`**

> {brand}: reminder, {provider} is coming {when_text} for your {category}. Need to change it? {link}

Placeholders: `brand`, `provider`, `when_text`, `category`, `link`

**`visit_done_customer`**

> {brand}: {provider} has finished your {category} and added an after photo. We've charged {price} to your card. Rate the visit: {link}

Placeholders: `brand`, `provider`, `category`, `price`, `link`

**`receipt`** (subject: Your receipt: {category} on {date})

> Receipt for {category} on {date}, done by {provider}.
> 
> Price: {price}
> Of which {brand} fee: {fee}
> Paid to {provider_first}: {net}
> 
> Your agreement for this work is with {provider_first}. {brand} arranged the booking and took payment on their behalf. Card ending {last4}.

Placeholders: `category`, `date`, `provider`, `price`, `brand`, `fee`, `provider_first`, `net`, `last4`

**`helper_coming`**

> {brand}: {provider} can't make {date}, so {helper}, their helper, is coming instead. {helper} has the same ID, DBS and insurance checks.

Placeholders: `brand`, `provider`, `date`, `helper`

**`cover_coming`**

> {brand}: {provider} is away on {date}, so {cover} is covering your {category} at the same price. {provider} carries on afterwards.

Placeholders: `brand`, `provider`, `date`, `cover`, `category`

**`own_customer_invite`**

> {provider_first} here. I'd like to arrange your {category} through {brand} from now on, at the same price: {price} a visit, paid by card after each visit. Have a look: {link}

Placeholders: `provider_first`, `category`, `brand`, `price`, `link`

**`cover_alert`**

> {brand}: Cover needed. {category} in {area} on {date}, {price}, for {provider}'s regular customer, who stays {provider}'s afterwards. Take a look: {link}

Placeholders: `brand`, `category`, `area`, `date`, `price`, `provider`, `link`

**`visit_reminder_provider`**

> {brand}: Reminder, you're {doing} in {area} on {day} at {time}. Reply PAUSE to stop new job alerts for a week.

Placeholders: `brand`, `doing`, `area`, `day`, `time`

**`payment_on_its_way`**

> {brand}: {customer} has paid {price} for {category}. {net} is on its way with Friday's payout.

Placeholders: `brand`, `customer`, `price`, `category`, `net`

**`limit_reached`**

> {brand}: you've reached your {period_word} earnings limit of {amount}. New job alerts are paused until {resume}. Jobs you've already accepted go ahead.

Placeholders: `brand`, `period_word`, `amount`, `resume`

**`time_off_arranged`**

> {brand}: you're off from {from_date} to {to_date}. {summary} Your regulars come back to you afterwards.

Placeholders: `brand`, `from_date`, `to_date`, `summary`

**`helper_invite`**

> {brand}: {provider} has added you as a helper. Setting up takes about 10 minutes: {link}

Placeholders: `brand`, `provider`, `link`

**`tax_key_date`**

> {brand}: a month to go: {what} by {date}. Your tax pack is ready in the app: {link}

Placeholders: `brand`, `what`, `date`, `link`

**`callback_requested`** (subject: Call-back requested: {name})

> {name} ({phone}) asked for a call-back during sign-up. They're on: {step}.

Placeholders: `name`, `phone`, `step`

**`time_off_unarranged`**

> {brand}: {customer}'s {category} on {date} has been booked while you're away. Choose cover, a helper or skip it: {link}

Placeholders: `brand`, `customer`, `category`, `date`, `link`

**`cover_not_found`**

> {brand}: nobody was free to cover {customer}'s {category} on {date}, so it's skipped and {customer} has been told. Their next visit is with you as usual.

Placeholders: `brand`, `customer`, `category`, `date`

**`visit_done_customer_no_photo`**

> {brand}: {provider} has finished your {category}. We've charged {price} to your card. Rate the visit: {link}

Placeholders: `brand`, `provider`, `category`, `price`, `link`

## L3 Admin and payments

| Template | Channels | To | Trigger |
|---|---|---|---|
| `charge_failed_customer` | Text | customer | Charging a visit fails or needs the customer to confirm (requires_action). |
| `refund_issued` | Text | customer | A full or partial refund is made. |
| `charge_failed_provider` | Text | provider | Charging a visit fails. |
| `payout_sent` | Text | provider | A payout is sent to the provider's bank (gateway webhook, or weekly with the fake gateway). |
| `document_verified` | Text | provider | An admin verifies an uploaded document (a provider's, or a helper's: then the helper is texted). |
| `document_rejected` | Text | provider | An admin rejects an uploaded document (a provider's, or a helper's: then the helper is texted). |
| `provider_nudge` | Text | provider | An admin chases a provider from "Providers needing attention". |
| `dispute_message` | Text | anyone | An admin messages one or both parties in a dispute. |
| `dispute_proposal` | Text | anyone | An admin proposes a fix (a free return visit or a provider-funded partial refund). |
| `dispute_closed` | Text | anyone | An admin closes a dispute. |
| `helper_ready` | Text | provider | An admin marks a provider's helper ready, once their ID has been checked (Session S). |
| `account_suspended` | Text | provider | An admin suspends a provider. |
| `account_reinstated` | Text | provider | An admin reinstates a provider. |
| `tip_received` | Text | provider | A customer's tip is charged (with their rating; L1 charges it through app.payments.charging). |

**`charge_failed_customer`**

> {brand}: we couldn't take {price} for your {category} on {date}. Please check your card: {link}

Placeholders: `brand`, `price`, `category`, `date`, `link`

**`refund_issued`**

> {brand}: we've refunded {amount} for your {category} on {date}. It can take 5 to 10 days to reach your card.

Placeholders: `brand`, `amount`, `category`, `date`

**`charge_failed_provider`**

> {brand}: {customer}'s card didn't go through for {category} on {date}. We're sorting it out with them, and you'll be paid once it does.

Placeholders: `brand`, `customer`, `category`, `date`

**`payout_sent`**

> {brand}: we've paid {amount} to your bank account ending {last4}.

Placeholders: `brand`, `amount`, `last4`

**`document_verified`**

> {brand}: we've checked your {document}. Thanks, you're all set{until_text}.

Placeholders: `brand`, `document`, `until_text`

**`document_rejected`**

> {brand}: we couldn't accept your {document}: {reason} Please upload it again: {link}

Placeholders: `brand`, `document`, `reason`, `link`

**`provider_nudge`**

> {brand}: {message} {link}

Placeholders: `brand`, `message`, `link`

**`dispute_message`**

> {brand}: about {title}: "{preview}" Reply: {link}

Placeholders: `brand`, `title`, `preview`, `link`

**`dispute_proposal`**

> {brand}: suggested fix for {title}: {proposal}. Let us know if that works: {link}

Placeholders: `brand`, `title`, `proposal`, `link`

**`dispute_closed`**

> {brand}: {title} is now closed. {outcome}

Placeholders: `brand`, `title`, `outcome`

**`helper_ready`**

> {brand}: we've checked {helper}'s details, so you can send them to visits from Today. Each visit still needs the documents its job asks for. {link}

Placeholders: `brand`, `helper`, `link`

**`account_suspended`**

> {brand}: we've paused your account, so you won't get new jobs for now. {reason} We'll be in touch.

Placeholders: `brand`, `reason`

**`account_reinstated`**

> {brand}: your account is active again. New jobs near you will start coming through.

Placeholders: `brand`

**`tip_received`**

> {brand}: {customer} added a {tip} tip for your {category}. All of it goes to you, with no fee.

Placeholders: `brand`, `customer`, `tip`, `category`
