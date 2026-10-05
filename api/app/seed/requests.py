"""Open requests: the three jobs in Dave's list (PROVIDER_OFFERS), the three waiting for a
provider on the admin overview (UNFILLED), and four in villages no provider reaches yet, for the
admin map's uncovered demand (A35). Priced through the real quote service and broadcast to
whoever app.services.eligibility.alert_targets picks."""

from dataclasses import dataclass, field
from datetime import timedelta

from app.adapters.area.base import AreaInput
from app.core.geo import approximate
from app.models.common import GeoPoint
from app.models.job_requests import Broadcast, JobRequest, RequestEvent, When
from app.models.offers import Offer
from app.models.providers import Provider
from app.repos.quotes import Quotes
from app.seed.context import Ctx, sid
from app.services.eligibility import alert_targets
from app.services.quotes import create_quote


@dataclass
class SeededRequest:
    request: JobRequest
    spec: dict
    targets: list[Provider]
    counter: Offer | None = None
    route_hints: dict[str, str] = field(default_factory=dict)


async def seed_requests(ctx: Ctx) -> list[SeededRequest]:
    out: list[SeededRequest] = []
    specs = ctx.scenario["open_requests"] + ctx.scenario["unfilled_requests"] + ctx.scenario["outlying_requests"]
    for spec in specs:
        ref = spec["ref"]
        customer = ctx.customers[spec["customer"]]
        address = customer.addresses[0]
        lawn = AreaInput(**spec["lawn"]) if spec.get("lawn") else None
        q = await create_quote(
            ctx.db,
            ctx.s,
            category_id=spec["category"],
            answers=spec["answers"],
            lawn=lawn,
            address=address,
            user_id=customer.user_id,
        )
        await Quotes(ctx.db).delete(q.id)  # stored again below under a stable id
        posted = ctx.ago(minutes=spec["minutes_ago"])
        request_id = sid("request", ref)
        quote = q.model_copy(
            update={"id": sid("quote", ref), "request_id": request_id, **ctx.timestamps(posted - timedelta(minutes=3))}
        )
        ctx.w.add(quote)
        frequency = q.answers.get("frequency")
        lat, lng = approximate(address.lat, address.lng)
        req = JobRequest(
            id=request_id,
            ref=ref,
            customer_id=customer.id,
            category_id=spec["category"],
            quote_id=quote.id,
            pricing_version_id=q.pricing_version_id,
            answers=q.answers,
            measure=q.measure,
            address=address,
            approx=GeoPoint(lat=lat, lng=lng),
            notes=spec["notes"],
            when=When(**spec["when"]),
            recurring=frequency not in (None, "oneoff"),
            frequency=frequency,
            guide_pence=q.result.price_pence,
            first_pence=q.result.first_pence,
            mins=q.result.mins,
            first_mins=q.result.first_mins,
            unit=q.result.unit,
            status="open",
            admin_note=spec.get("admin_note"),
            **ctx.timestamps(posted),
        )
        cat = ctx.cats[spec["category"]]
        targets = [t.provider for t in await alert_targets(ctx.db, req, cat, ctx.today)]
        sent_at = posted + timedelta(seconds=5)
        req.broadcast = Broadcast(at=sent_at, provider_ids=[p.id for p in targets])
        events = [
            RequestEvent(at=posted, kind="created"),
            RequestEvent(at=sent_at, kind="broadcast", count=len(targets)),
        ]
        for pkey, after in spec["viewed_by"]:
            pid = ctx.providers[pkey].id
            events.append(RequestEvent(at=posted + timedelta(minutes=after), kind="viewed", provider_id=pid))
            req.viewed_by.append(pid)
        counter = None
        if c := spec.get("counter"):
            p = ctx.providers[c["provider"]]
            at = posted + timedelta(minutes=c["minutes_after"])
            counter = Offer(
                id=sid("offer", ref, c["provider"]),
                request_id=request_id,
                provider_id=p.id,
                price_pence=c["price_pence"],
                guide_pence=req.guide_pence,
                reasons=c["reasons"],
                message=c["message"],
                status="pending",
                **ctx.timestamps(at),
            )
            ctx.w.add(counter)
            events.append(
                RequestEvent(
                    at=at, kind="countered", provider_id=p.id, offer_id=counter.id, price_pence=counter.price_pence
                )
            )
        req.events = sorted(events, key=lambda e: e.at)
        ctx.w.add(req)
        ctx.request_ids.append(request_id)
        out.append(
            SeededRequest(
                request=req, spec=spec, targets=targets, counter=counter, route_hints=spec.get("route_hint", {})
            )
        )
    await ctx.w.flush()
    return out
