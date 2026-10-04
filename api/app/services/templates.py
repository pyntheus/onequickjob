"""The outbox template catalogue: every message the product sends, with its trigger.

docs/spec/notifications.md is generated from this file (`make docs`), so the catalogue
and the docs can't drift. Bodies use str.format placeholders; render() fails loudly if
a placeholder is missing. UK English, no promises or guarantees, and the brand prefix
on texts because that's how people recognise them.

Every template is here (the lanes' own were folded in by the shared-fixes session); add new
ones here too.
"""

import string
from dataclasses import dataclass, field
from typing import Literal

from app.models.common import Channel

Audience = Literal["customer", "provider", "helper", "admin", "anyone"]
Lane = Literal["F", "L1", "L2", "L3"]


@dataclass(frozen=True)
class Template:
    id: str
    lane: Lane
    audience: Audience
    channels: tuple[Channel, ...]
    trigger: str
    body: str
    subject: str | None = None  # email only
    example: dict[str, str] = field(default_factory=dict)

    @property
    def placeholders(self) -> list[str]:
        names = [f for _, f, _, _ in string.Formatter().parse(self.body + (self.subject or "")) if f]
        return list(dict.fromkeys(names))


class TemplateError(KeyError):
    pass


_REGISTRY: dict[str, Template] = {}


def register(t: Template) -> Template:
    if t.id in _REGISTRY and _REGISTRY[t.id] != t:
        raise ValueError(f"template {t.id} registered twice")
    _REGISTRY[t.id] = t
    return t


def get(template_id: str) -> Template:
    try:
        return _REGISTRY[template_id]
    except KeyError as e:
        raise TemplateError(f"no outbox template {template_id!r}") from e


def all_templates() -> list[Template]:
    return list(_REGISTRY.values())


def render(t: Template, data: dict[str, object]) -> tuple[str | None, str]:
    missing = [p for p in t.placeholders if p not in data]
    if missing:
        raise TemplateError(f"{t.id} needs {', '.join(missing)}")
    subject = t.subject.format_map(data) if t.subject else None
    return subject, t.body.format_map(data)


def _t(**kw) -> Template:
    return register(Template(**kw))


# --------------------------------------------------------------------------- F
_t(
    id="login_code",
    lane="F",
    audience="anyone",
    channels=("sms", "email"),
    trigger="Someone asks to sign in with a phone number or email (POST /api/auth/code).",
    subject="Your {brand} sign-in code",
    body="{brand}: your sign-in code is {code}. It expires in {minutes} minutes. Don't share it with anyone.",
)

# --------------------------------------------------------------------------- L1 customer
_t(
    id="request_sent",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="A job request is created and broadcast to eligible providers.",
    body="{brand}: we've sent your {category} request to checked providers near {district}. "
    "We'll text you as soon as someone local picks it up.",
)
_t(
    id="request_no_providers",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="A request is created but no provider is eligible for an alert (admin dispatches by hand).",
    body="{brand}: we've got your {category} request. We're finding someone local by hand, "
    "which can take a little longer. We'll text you as soon as it's booked.",
)
_t(
    id="counter_offer",
    lane="F",
    audience="customer",
    channels=("sms",),
    trigger="A provider suggests a different price on an open request.",
    body="{brand}: {provider} suggested {price}{first_text} for your {category}, instead of {guide}. {reason}"
    "Accept it or keep waiting: {link}",
)
_t(
    id="request_booked",
    lane="F",
    audience="customer",
    channels=("sms",),
    trigger="An open request is booked (guide accepted by a provider, or the customer accepted a counter).",
    body="{brand}: you're booked with {provider} for {category}. {when_text}. {price} {unit}, charged after "
    "{charged_after}. Your agreement is with {provider_first}; we arrange it and take payment for them. {link}",
)
_t(
    id="visit_reminder_customer",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="The day before a scheduled visit, 6pm.",
    body="{brand}: reminder, {provider} is coming {when_text} for your {category}. Need to change it? {link}",
)
_t(
    id="visit_done_customer",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="A provider finishes a visit and the card is charged.",
    body="{brand}: {provider} has finished your {category} and added an after photo. We've charged {price} "
    "to your card. Rate the visit: {link}",
)
_t(
    id="receipt",
    lane="L2",
    audience="customer",
    channels=("email",),
    trigger="A visit is charged (same moment as visit_done_customer).",
    subject="Your receipt: {category} on {date}",
    body="Receipt for {category} on {date}, done by {provider}.\n\n"
    "Price: {price}\nOf which {brand} fee: {fee}\nPaid to {provider_first}: {net}\n\n"
    "Your agreement for this work is with {provider_first}. {brand} arranged the booking and took payment "
    "on their behalf. Card ending {last4}.",
)
_t(
    id="charge_failed_customer",
    lane="L3",
    audience="customer",
    channels=("sms",),
    trigger="Charging a visit fails or needs the customer to confirm (requires_action).",
    body="{brand}: we couldn't take {price} for your {category} on {date}. Please check your card: {link}",
)
_t(
    id="refund_issued",
    lane="L3",
    audience="customer",
    channels=("sms",),
    trigger="A full or partial refund is made.",
    body="{brand}: we've refunded {amount} for your {category} on {date}. It can take 5 to 10 days to reach your card.",
)
_t(
    id="helper_coming",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="A provider sends their helper to a visit.",
    body="{brand}: {provider} can't make {date}, so {helper}, their helper, is coming instead. {helper} has "
    "the same ID, DBS and insurance checks.",
)
_t(
    id="cover_coming",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="Another provider takes a cover visit while the regular provider is away.",
    body="{brand}: {provider} is away on {date}, so {cover} is covering your {category} at the same price. "
    "{provider} carries on afterwards.",
)
_t(
    id="visit_skipped",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer skips a visit, or it is skipped for time off.",
    body="{brand}: your {category} visit on {date} is skipped. {next_text}",
)
_t(
    id="plan_changed",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer pauses, resumes or changes the frequency of a plan.",
    body="{brand}: your {category} plan with {provider} has changed: {summary}.",
)
_t(
    id="plan_cancelled",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer cancels a plan.",
    body="{brand}: your {category} plan with {provider} is cancelled. There's no fee.",
)
_t(
    id="problem_reported",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer reports a problem with a visit (a dispute is opened).",
    body="{brand}: thanks for telling us. We've let {provider} know what happened and will text you within a day.",
)
_t(
    id="own_customer_invite",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="A provider invites a customer they already have.",
    body="{provider_first} here. I'd like to arrange your {category} through {brand} from now on, at the same "
    "price: {price} a visit, paid by card after each visit. Have a look: {link}",
)

_t(
    id="request_closed",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="A request closes without being booked (the customer cancels it, or it expires) while the "
    "provider's suggested price was still waiting.",
    body="{brand}: the {category} job in {area} is no longer available, so your suggested price no longer "
    "stands. Thanks for looking.",
)
_t(
    id="request_expired",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="An open request has had no booking for 7 days and closes (request_expiry task).",
    body="{brand}: we couldn't find someone local for your {category} request this time, so we've closed it. "
    "Nothing has been charged. You can ask again whenever you like: {link}",
)
_t(
    id="guide_raise_proposed",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The team suggests a higher guide price for an open request nobody has taken (admin's Raise guide); "
    "nothing changes unless the customer approves it on Finding someone local (A12).",
    body="{brand}: to help find someone local for your {category}, we suggest raising the guide price to "
    "{price}{first_text} (it's {current} now). Nothing changes unless you approve it: {link}",
)
_t(
    id="plan_change_proposed",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="A customer asks to change how often their plan's visits happen; the provider accepts or declines "
    "the re-priced plan within 48 hours (A10).",
    body="{brand}: {customer} would like their {category} {new_frequency} instead of {old_frequency}. At that "
    "frequency the price would be {price} a visit (it's {current} now). Please accept or decline by {deadline}: "
    "{link}",
)
_t(
    id="plan_change_requested",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer has asked to change how often; the provider has been asked (A10).",
    body="{brand}: we've asked {provider} about your {category} {new_frequency} at {price} a visit. Your plan "
    "carries on as it is unless they accept.",
)
_t(
    id="plan_change_accepted",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The provider accepts a change of frequency and its new price (A10).",
    body="{brand}: {provider} accepted. Your {category} is now {new_frequency} at {price} a visit. {next_text}",
)
_t(
    id="plan_change_declined",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The provider declines a change of frequency (A10).",
    body="{brand}: {provider} would rather keep your {category} {old_frequency} at {current} a visit, so your "
    "plan stays as it is. You can message them from your account.",
)
_t(
    id="plan_change_lapsed",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The provider hasn't answered a change of frequency within 48 hours (plan_change_expiry task, A10).",
    body="{brand}: {provider} hasn't answered within 48 hours, so your {category} plan stays {old_frequency} at "
    "{current} a visit. You can ask again from your account.",
)
_t(
    id="plan_change_price_asked",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="An own customer asks to change how often their plan's visits happen: the price is the provider's to "
    "set, so they're asked to name it or decline within 48 hours (A22).",
    body="{brand}: {customer} would like their {category} {new_frequency} instead of {old_frequency} (it's {current} "
    "a visit now). As they're your own customer, you set the price: name it or decline by {deadline}: {link}",
)
_t(
    id="plan_change_price_requested",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="An own customer has asked their provider for a price at a new frequency (A22).",
    body="{brand}: we've asked {provider} for a price to have your {category} {new_frequency}. Your plan carries on "
    "as it is until you've agreed one.",
)
_t(
    id="plan_change_priced",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The provider names their price for an own customer's change of frequency; the customer has 48 hours to "
    "approve or decline it (A22).",
    body="{brand}: {provider} can do your {category} {new_frequency} at {price} a visit (it's {current} now). "
    "Approve or decline it by {deadline}: {link}",
)
_t(
    id="plan_change_agreed",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer approves their provider's price for a change of frequency; the plan is updated (A22).",
    body="{brand}: done. Your {category} with {provider} is now {new_frequency} at {price} a visit. {next_text}",
)
_t(
    id="plan_change_approved",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="An own customer approves the price the provider named for a change of frequency; the plan is updated "
    "(A22).",
    body="{brand}: {customer} agreed {price} a visit to have their {category} {new_frequency}. Your round is updated.",
)
_t(
    id="plan_change_price_declined",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="An own customer declines the price the provider named for a change of frequency (A22).",
    body="{brand}: {customer} would rather keep their {category} {old_frequency} at {current} a visit, so the plan "
    "stays as it is.",
)
_t(
    id="plan_change_price_lapsed",
    lane="L1",
    audience="customer",
    channels=("sms",),
    trigger="The customer hasn't answered their provider's price within 48 hours (plan_change_expiry task, A22).",
    body="{brand}: we didn't hear back about {provider}'s price within 48 hours, so your {category} plan stays "
    "{old_frequency} at {current} a visit. You can ask again from your account.",
)
_t(
    id="plan_change_price_unanswered",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="An own customer hasn't answered the provider's price within 48 hours (plan_change_expiry task, A22).",
    body="{brand}: {customer} didn't answer your price within 48 hours, so their {category} plan stays "
    "{old_frequency} at {current} a visit.",
)

# --------------------------------------------------------------------------- shared
_t(
    id="message_received",
    lane="F",
    audience="anyone",
    channels=("sms",),
    trigger=(
        "Someone posts in a message thread; texted to the other participants "
        "(sent by whichever lane's endpoint posted it)."
    ),
    body='{brand}: {sender} sent you a message: "{preview}" Reply: {link}',
)

# --------------------------------------------------------------------------- L2 provider
_t(
    id="job_alert",
    lane="L1",
    audience="provider",
    channels=("sms", "whatsapp"),
    trigger="A request is broadcast: one per eligible provider, on their chosen channels; held in quiet hours.",
    body="{brand}: New job near you. {category} in {area} ({district}), about {mins} minutes, {frequency}. "
    "Guide price {guide}, you'd get {net}.{route} Take a look: {link}",
)
_t(
    id="cover_alert",
    lane="L2",
    audience="provider",
    channels=("sms", "whatsapp"),
    trigger="A provider asks for cover; the visit is offered to other eligible providers.",
    body="{brand}: Cover needed. {category} in {area} on {date}, {price}, for {provider}'s regular customer, "
    "who stays {provider}'s afterwards. Take a look: {link}",
)
_t(
    id="booking_confirmed",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger="A provider's guide acceptance, or a counter the customer accepted, books the job.",
    body="{brand}: it's yours. {category} in {area}. {when_text}. You'll get {net} {unit} after the "
    "{fee_percent}% {brand} fee. {link}",
)
_t(
    id="counter_declined",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger="The customer chooses to keep waiting instead of accepting a counter.",
    body="{brand}: {customer} would rather wait for the guide price of {guide}. If you'd like the {category} job "
    "in {area} at that price, it's still open: {link}",
)
_t(
    id="job_taken",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger="A request books while the provider's counter was still waiting.",
    body="{brand}: the {category} job in {area} has gone to someone else. Thanks for looking.",
)
_t(
    id="guide_raise_withdrawn",
    lane="F",
    audience="customer",
    channels=("sms",),
    trigger=(
        "A request is booked (at the guide, or a counter the customer accepted) while a raised guide waits for "
        "the customer's approval: the raise is withdrawn in the booking's transaction (A12, A16)."
    ),
    body="{brand}: {provider} has booked your {category} at {booked_at}, so the higher guide price we suggested "
    "({proposed}) no longer applies. There's nothing you need to do.",
)
_t(
    id="counter_lapsed",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger=(
        "A customer tries to accept a provider's counter, but the provider can no longer take the job (no longer "
        "eligible): the counter lapses and the request stays open for others (ruling A9)."
    ),
    body="{brand}: {customer} tried to accept your price of {price} for the {category} job in {area}, but you "
    "can't take it at the moment. {reason} Your price has lapsed and the job is open to other providers. {link}",
)
_t(
    id="visit_reminder_provider",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="The day before a provider's first visit of the day, 6pm.",
    body="{brand}: Reminder, you're {doing} in {area} on {day} at {time}. Reply PAUSE to stop new job alerts "
    "for a week.",
)
_t(
    id="payment_on_its_way",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="A visit is charged successfully.",
    body="{brand}: {customer} has paid {price} for {category}. {net} is on its way with Friday's payout.",
)
_t(
    id="charge_failed_provider",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="Charging a visit fails.",
    body="{brand}: {customer}'s card didn't go through for {category} on {date}. We're sorting it out with them, "
    "and you'll be paid once it does.",
)
_t(
    id="payout_sent",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="A payout is sent to the provider's bank (gateway webhook, or weekly with the fake gateway).",
    body="{brand}: we've paid {amount} to your bank account ending {last4}.",
)
_t(
    id="rating_received",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="A customer rates a visit.",
    body="{brand}: {customer} rated your {category} {stars} out of 5.{tip_text}",
)
_t(
    id="dispute_opened",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="A customer reports a problem with a provider's visit.",
    body='{brand}: {customer} has told us something wasn\'t right with {category} on {date}: "{summary}" '
    "Please reply within a day: {link}",
)
_t(
    id="document_expiring",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger=(
        "30 days before a verified document expires (insurance, a basic DBS check 12 months after issue, "
        "waste carrier, ladder and pet cover). Sent once per expiry date by the document_expiry task."
    ),
    body="{brand}: your {document} runs out on {date}. Upload the new one so you can keep taking {jobs}: {link}",
)
_t(
    id="document_verified",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="An admin verifies an uploaded document (a provider's, or a helper's: then the helper is texted).",
    body="{brand}: we've checked your {document}. Thanks, you're all set{until_text}.",
)
_t(
    id="document_rejected",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="An admin rejects an uploaded document (a provider's, or a helper's: then the helper is texted).",
    body="{brand}: we couldn't accept your {document}: {reason} Please upload it again: {link}",
)
_t(
    id="limit_reached",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="A provider's earnings for the period reach their limit.",
    body="{brand}: you've reached your {period_word} earnings limit of {amount}. New job alerts are paused "
    "until {resume}. Jobs you've already accepted go ahead.",
)
_t(
    id="time_off_arranged",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="A provider books time off and the affected visits are arranged.",
    body="{brand}: you're off from {from_date} to {to_date}. {summary} Your regulars come back to you afterwards.",
)
_t(
    id="invite_accepted",
    lane="L1",
    audience="provider",
    channels=("sms",),
    trigger="An invited own customer accepts.",
    body="{brand}: {customer} accepted your invite. Their first visit through {brand} is {date}.",
)
_t(
    id="helper_invite",
    lane="L2",
    audience="helper",
    channels=("sms",),
    trigger="A provider adds a helper.",
    body="{brand}: {provider} has added you as a helper. Setting up takes about 10 minutes: {link}",
)
_t(
    id="tax_key_date",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="A month before 5 October (Self Assessment registration) and 31 January (return and payment).",
    body="{brand}: a month to go: {what} by {date}. Your tax pack is ready in the app: {link}",
)
_t(
    id="callback_requested",
    lane="L2",
    audience="admin",
    channels=("email",),
    trigger='A provider taps "Call me" during sign-up.',
    subject="Call-back requested: {name}",
    body="{name} ({phone}) asked for a call-back during sign-up. They're on: {step}.",
)

_t(
    id="time_off_unarranged",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="A visit is booked into a provider's time off after they arranged it (once per visit).",
    body="{brand}: {customer}'s {category} on {date} has been booked while you're away. "
    "Choose cover, a helper or skip it: {link}",
)
_t(
    id="cover_not_found",
    lane="L2",
    audience="provider",
    channels=("sms",),
    trigger="Nobody took a cover visit by the day before, so it's skipped and the customer is told.",
    body="{brand}: nobody was free to cover {customer}'s {category} on {date}, so it's skipped and "
    "{customer} has been told. Their next visit is with you as usual.",
)
_t(
    id="visit_done_customer_no_photo",
    lane="L2",
    audience="customer",
    channels=("sms",),
    trigger="A provider finishes a visit without adding an after photo, and the card is charged.",
    body="{brand}: {provider} has finished your {category}. We've charged {price} to your card. Rate the visit: {link}",
)

# --------------------------------------------------------------------------- L3 admin
_t(
    id="provider_nudge",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger='An admin chases a provider from "Providers needing attention".',
    body="{brand}: {message} {link}",
)
_t(
    id="dispute_message",
    lane="L3",
    audience="anyone",
    channels=("sms",),
    trigger="An admin messages one or both parties in a dispute.",
    body='{brand}: about {title}: "{preview}" Reply: {link}',
)
_t(
    id="dispute_proposal",
    lane="L3",
    audience="anyone",
    channels=("sms",),
    trigger="An admin proposes a fix (a free return visit or a provider-funded partial refund).",
    body="{brand}: suggested fix for {title}: {proposal}. Let us know if that works: {link}",
)
_t(
    id="dispute_closed",
    lane="L3",
    audience="anyone",
    channels=("sms",),
    trigger="An admin closes a dispute.",
    body="{brand}: {title} is now closed. {outcome}",
)
_t(
    id="provider_activated",
    lane="F",
    audience="provider",
    channels=("sms",),
    trigger=(
        "A provider signing up has every required check done (ID, insurance, tax details, a payout account, and a "
        "basic DBS check if a chosen job needs one): they become active automatically (A19)."
    ),
    body="{brand}: you're all set, {first}. Your checks are done, so jobs near you will start coming through. {link}",
)
_t(
    id="helper_ready",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="An admin marks a provider's helper ready, once their ID has been checked (Session S).",
    body="{brand}: we've checked {helper}'s details, so you can send them to visits from Today. Each visit still "
    "needs the documents its job asks for. {link}",
)
_t(
    id="account_suspended",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="An admin suspends a provider.",
    body="{brand}: we've paused your account, so you won't get new jobs for now. {reason} We'll be in touch.",
)
_t(
    id="account_reinstated",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="An admin reinstates a provider.",
    body="{brand}: your account is active again. New jobs near you will start coming through.",
)
_t(
    id="tip_received",
    lane="L3",
    audience="provider",
    channels=("sms",),
    trigger="A customer's tip is charged (with their rating; L1 charges it through app.payments.charging).",
    body="{brand}: {customer} added a {tip} tip for your {category}. All of it goes to you, with no fee.",
)
