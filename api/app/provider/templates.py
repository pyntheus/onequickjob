"""Outbox templates L2 needs beyond the catalogue (app/services/templates.py), registered from
this package as lanes.md allows. Integration (I) folds them into the catalogue.
(visit_done_customer_no_photo is sent with the other paid-visit messages, so it's registered in
app.payments.notices.)"""

from app.services.templates import Template, register

register(
    Template(
        id="time_off_unarranged",
        lane="L2",
        audience="provider",
        channels=("sms",),
        trigger="A visit is booked into a provider's time off after they arranged it (once per visit).",
        body="{brand}: {customer}'s {category} on {date} has been booked while you're away. "
        "Choose cover, a helper or skip it: {link}",
    )
)
register(
    Template(
        id="cover_not_found",
        lane="L2",
        audience="provider",
        channels=("sms",),
        trigger="Nobody took a cover visit by the day before, so it's skipped and the customer is told.",
        body="{brand}: nobody was free to cover {customer}'s {category} on {date}, so it's skipped and "
        "{customer} has been told. Their next visit is with you as usual.",
    )
)
