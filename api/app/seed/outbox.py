"""Seeded outbox messages, rendered from the template catalogue through notify(): job alerts
with magic links, request confirmations, Gary's counter, Dave's reminder and Mary's
invite. Re-seeding deletes the previous run's messages first (they're flagged), so they
never pile up; tokens are fresh each run."""

from datetime import datetime, timedelta
from typing import Any

from app.core import money
from app.core.ids import new_token, token_hash
from app.models.common import Channel, Related
from app.models.provider_ops import OwnCustomerInvite
from app.models.system import OutboxMessage, Recipient
from app.models.users import User
from app.seed.context import SEED_FLAG, Ctx, sid
from app.seed.requests import SeededRequest
from app.services.auth import create_magic_link
from app.services.notify import notify, recipient_for
from app.services.wording import FREQUENCY_WORDS, lower_name


def _link(ctx: Ctx, path: str) -> str:
    return ctx.s.public_base_url.rstrip("/") + path


async def message(
    ctx: Ctx,
    key: str,
    template_id: str,
    to: User | Recipient,
    data: dict[str, Any],
    at: datetime,
    related: Related | None = None,
    channel: Channel | None = None,
) -> OutboxMessage:
    recipient = recipient_for(to) if isinstance(to, User) else to
    msg = await notify(
        ctx.db, template_id, to=recipient, data={**data, "seed": key}, related=related, channel=channel, settings=ctx.s
    )
    await ctx.db["outbox"].update_one({"_id": msg.id}, {"$set": {SEED_FLAG: True, "created_at": at}})
    return msg


def _provider_key(ctx: Ctx, provider_id: str) -> str:
    return next(k for k, p in ctx.providers.items() if p.id == provider_id)


async def seed_messages(ctx: Ctx, requests: list[SeededRequest]) -> None:
    for sr in requests:
        req = sr.request
        cat = ctx.cats[req.category_id]
        sent = req.broadcast.at if req.broadcast else req.created_at
        customer_key = sr.spec["customer"]
        related = Related(request_id=req.id, customer_id=req.customer_id)
        split = money.split(req.guide_pence, "standard", ctx.s)
        for i, provider in enumerate(sr.targets):
            pkey = _provider_key(ctx, provider.id)
            user = ctx.users[pkey]
            path = f"/p/j/{req.ref}"
            token = await create_magic_link(ctx.db, ctx.s, user.id, "job_alert", path)
            await ctx.db["magic_links"].update_one(
                {"token_hash": token_hash(token, ctx.s.pepper)}, {"$set": {SEED_FLAG: True}}
            )
            data = {
                "category": cat.name,
                "area": req.address.area,
                "district": req.address.district,
                "mins": req.mins,
                "frequency": FREQUENCY_WORDS.get(req.frequency or "oneoff", "one-off"),
                "guide": money.format_pounds(req.guide_pence),
                "net": money.format_pounds(split.provider_pence),
                "route": sr.route_hints.get(pkey, ""),
                "link": _link(ctx, f"{path}?t={token}"),
            }
            channels: list[Channel] = [
                c
                for c, on in (("sms", provider.alert_settings.sms), ("whatsapp", provider.alert_settings.whatsapp))
                if on
            ]
            for ch in channels:
                await message(
                    ctx,
                    f"job_alert:{req.ref}:{pkey}:{ch}",
                    "job_alert",
                    user,
                    data,
                    sent + timedelta(seconds=2 + i),
                    related.model_copy(update={"provider_id": provider.id}),
                    ch,
                )
        template = "request_sent" if sr.targets else "request_no_providers"
        await message(
            ctx,
            f"{template}:{req.ref}",
            template,
            ctx.users[customer_key],
            {"category": lower_name(cat), "district": req.address.district},
            sent + timedelta(seconds=30),
            related,
        )
        if sr.counter:
            gary = ctx.providers[_provider_key(ctx, sr.counter.provider_id)]
            await message(
                ctx,
                f"counter_offer:{req.ref}",
                "counter_offer",
                ctx.users[customer_key],
                {
                    "provider": gary.short,
                    "price": money.format_pounds(sr.counter.price_pence),
                    "first_text": (
                        f" (first visit {money.format_pounds(sr.counter.first_price_pence)})"
                        if sr.counter.first_price_pence
                        else ""
                    ),
                    "guide": money.format_pounds(req.guide_pence),
                    "category": lower_name(cat),
                    "reason": f'"{sr.counter.message}" ',
                    "link": _link(ctx, f"/requests/{req.ref}"),
                },
                sr.counter.created_at + timedelta(seconds=5),
                related.model_copy(update={"offer_id": sr.counter.id, "provider_id": gary.id}),
            )

    # The prototype's reminder text to Dave, yesterday at 18:02.
    await message(
        ctx,
        "reminder:dave",
        "visit_reminder_provider",
        ctx.users["dave"],
        {"doing": "mowing", "area": "Widmer End", "day": "Tuesday", "time": "9:00"},
        ctx.at(ctx.today - timedelta(days=1), "18:02"),
        Related(provider_id=ctx.providers["dave"].id),
    )


async def seed_invites(ctx: Ctx) -> None:
    """Mary's open invite (with its text) and the two blocked ones. Pat's and John's accepted
    invites are written with their bookings (history.py)."""
    blocked_reason = ctx.scenario["blocked_reason"]
    for inv in ctx.scenario["own_customer_invites"]:
        if inv["status"] == "accepted":
            continue
        provider = ctx.providers[inv["provider"]]
        at = ctx.ago(days=inv["days_ago"])
        invite = OwnCustomerInvite(
            id=sid("invite", inv["key"]),
            provider_id=provider.id,
            name=inv["name"],
            phone=inv["phone"],
            category_id=inv["category"],
            price_pence=inv["price_pence"],
            frequency=inv["frequency"],
            status=inv["status"],
            blocked_reason=blocked_reason if inv["status"] == "blocked" else None,
            **ctx.timestamps(at),
        )
        if inv["status"] == "invited":
            token = new_token()
            invite.token_hash = token_hash(token, ctx.s.pepper)
            msg = await message(
                ctx,
                f"invite:{inv['key']}",
                "own_customer_invite",
                Recipient(name=inv["name"], phone=inv["phone"]),
                {
                    "provider_first": provider.name.split(" ")[0],
                    "category": lower_name(ctx.cats[inv["category"]]),
                    "price": money.format_pounds(inv["price_pence"]),
                    "link": _link(ctx, f"/invite/{token}"),
                },
                at + timedelta(seconds=10),
                Related(invite_id=invite.id, provider_id=provider.id),
            )
            invite.outbox_id = msg.id
        ctx.w.add(invite)
    await ctx.w.flush()
