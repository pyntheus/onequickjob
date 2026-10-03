"""The prototype's three disputes (D-014, D-013, D-011), each with its visit, booking and thread."""

from app.models.disputes import Dispute, DisputeEvent, Resolution
from app.seed.context import Ctx, sid
from app.seed.history import Diary, working_day
from app.seed.jobs import add_booking, add_thread, add_visit

TIMES = {"D-014": "10:00", "D-013": "13:00", "D-011": "09:00"}


async def seed_disputes(ctx: Ctx, diary: Diary) -> None:
    for d in ctx.scenario["disputes"]:
        ref = d["ref"]
        key = f"dispute:{ref}"
        covered_by = d.get("covered_by")
        visit_day = working_day(
            ctx, covered_by or d["provider"], ctx.day(d["visit_days_ago"] - (1 if covered_by else 0))
        )
        booking = add_booking(
            ctx,
            key=key,
            customer=d["customer"],
            provider=d["provider"],
            category_id=d["category"],
            source="platform",
            via="guide",
            price_pence=d["price_pence"],
            created_at=ctx.at(ctx.day(d["visit_days_ago"] + 4), "20:10"),
        )
        hhmm = TIMES[ref]
        visit = add_visit(
            ctx,
            key=key,
            booking=booking,
            day=visit_day,
            hhmm=hhmm,
            est_mins=d["est_mins"],
            actual_mins=d["actual_mins"],
            paid_provider=covered_by,
            performer=covered_by,
            performer_kind="cover" if covered_by else "provider",
            cover_from=d["provider"] if covered_by else None,
            note="Covered for Jan, who couldn't make it." if covered_by else "",
        )
        diary.book(covered_by or d["provider"], visit_day, hhmm, d["est_mins"])
        dispute_id = sid("dispute", ref)
        visit.dispute_id = dispute_id
        users = {
            "customer": ctx.users[d["customer"]].id,
            "provider": ctx.users[d["provider"]].id,
            "admin": next(iter(ctx.admins.values())).id,
        }
        events = [
            DisputeEvent(
                at=ctx.at(ctx.day(days), "11:15"),
                by_user_id=users[who],
                kind=kind,
                text=d["description"] if kind == "opened" else text,
            )
            for kind, days, who, text in d["events"]
        ]
        opened_at = events[0].at
        messages = [
            (
                "customer" if e.kind == "opened" else "provider" if e.kind == "provider_replied" else "admin",
                e.text,
                e.at,
            )
            for e in events
        ]
        thread = add_thread(ctx, key, booking, messages, kind="dispute", dispute_id=dispute_id)
        closed = d["stage"] == 3
        ctx.w.add(
            Dispute(
                id=dispute_id,
                ref=ref,
                visit_id=visit.id,
                booking_id=booking.id,
                customer_id=booking.customer_id,
                provider_id=booking.provider_id,
                category_id=d["category"],
                title=d["title"],
                description=d["description"],
                amount_pence=d["price_pence"],
                stage=d["stage"],
                status_text=d["status_text"],
                proposed=Resolution(**d["proposed"]) if d.get("proposed") else None,
                resolution=Resolution(**d["resolution"]) if d.get("resolution") else None,
                thread_id=thread.id,
                events=events,
                closed_at=events[-1].at if closed else None,
                **ctx.timestamps(opened_at),
            )
        )
        booking.status = "completed"
        ctx.w.add(booking)
