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
