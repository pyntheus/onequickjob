"""Outbox templates L1 adds to the catalogue (app.services.templates). Registered on import;
integration (I) folds them into the catalogue file. UK English; no promises."""

from app.services.templates import Template, register

REQUEST_CLOSED = register(
    Template(
        id="request_closed",
        lane="L1",
        audience="provider",
        channels=("sms",),
        trigger="A request closes without being booked (the customer cancels it, or it expires) while the "
        "provider's suggested price was still waiting.",
        body="{brand}: the {category} job in {area} is no longer available, so your suggested price no longer "
        "stands. Thanks for looking.",
    )
)

REQUEST_EXPIRED = register(
    Template(
        id="request_expired",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="An open request has had no booking for 7 days and closes (request_expiry task).",
        body="{brand}: we couldn't find someone local for your {category} request this time, so we've closed it. "
        "Nothing has been charged. You can ask again whenever you like: {link}",
    )
)

# ------------------------------------------------------------------ A12: a raised guide needs the customer
GUIDE_RAISE_PROPOSED = register(
    Template(
        id="guide_raise_proposed",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="The team suggests a higher guide price for an open request nobody has taken (admin's Raise guide); "
        "nothing changes unless the customer approves it on Finding someone local (A12).",
        body="{brand}: to help find someone local for your {category}, we suggest raising the guide price to "
        "{price}{first_text} (it's {current} now). Nothing changes unless you approve it: {link}",
    )
)

# ------------------------------------------------------------------ A10: changing how often
PLAN_CHANGE_PROPOSED = register(
    Template(
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
)
PLAN_CHANGE_REQUESTED = register(
    Template(
        id="plan_change_requested",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="The customer has asked to change how often; the provider has been asked (A10).",
        body="{brand}: we've asked {provider} about your {category} {new_frequency} at {price} a visit. Your plan "
        "carries on as it is unless they accept.",
    )
)
PLAN_CHANGE_ACCEPTED = register(
    Template(
        id="plan_change_accepted",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="The provider accepts a change of frequency and its new price (A10).",
        body="{brand}: {provider} accepted. Your {category} is now {new_frequency} at {price} a visit. {next_text}",
    )
)
PLAN_CHANGE_DECLINED = register(
    Template(
        id="plan_change_declined",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="The provider declines a change of frequency (A10).",
        body="{brand}: {provider} would rather keep your {category} {old_frequency} at {current} a visit, so your "
        "plan stays as it is. You can message them from your account.",
    )
)
PLAN_CHANGE_LAPSED = register(
    Template(
        id="plan_change_lapsed",
        lane="L1",
        audience="customer",
        channels=("sms",),
        trigger="The provider hasn't answered a change of frequency within 48 hours (plan_change_expiry task, A10).",
        body="{brand}: {provider} hasn't answered within 48 hours, so your {category} plan stays {old_frequency} at "
        "{current} a visit. You can ask again from your account.",
    )
)
