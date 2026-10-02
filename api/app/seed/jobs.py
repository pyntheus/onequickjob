"""Building bookings, visits, charges, ledger entries, threads and photos for the seed."""

import struct
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.adapters.payments.base import ChargeResult
from app.core import money
from app.core.rounding import round_half_up
from app.core.timeutil import tax_year, to_london
from app.models.bookings import Booking
from app.models.common import BookingSource, Related, TimePref
from app.models.messages import Message, MessageThread, Participant
from app.models.records import LedgerEntry
from app.models.system import StoredFile
from app.models.visits import Charge, CoverState, Performer, Photos, Visit
from app.seed.context import Ctx, sid

UNITS = {"mowing": "a visit", "windows": "a clean", "cleaning": "a clean", "dogwalking": "a walk"}


def unit_for(category_id: str, recurring: bool) -> str:
    return UNITS.get(category_id, "one-off") if recurring else "one-off"


def overran(est: int, actual: int) -> tuple[bool, bool]:
    """(over 10%, over 25%) with exact integer maths."""
    return actual * 10 > est * 11, actual * 4 > est * 5


def add_booking(
    ctx: Ctx,
    *,
    key: str,
    customer: str,
    provider: str,
    category_id: str,
    source: BookingSource,
    via: str,
    price_pence: int,
    created_at: datetime,
    recurring: bool = False,
    frequency: str = "oneoff",
    status: str = "completed",
    answers: dict[str, Any] | None = None,
    when: TimePref = "either",
    request_id: str | None = None,
    invite_id: str | None = None,
    series_id: str | None = None,
    notes: str = "",
) -> Booking:
    b = Booking(
        id=sid("booking", key),
        ref=ctx.next_booking_ref(),
        source=source,
        customer_id=ctx.customers[customer].id,
        provider_id=ctx.providers[provider].id,
        category_id=category_id,
        request_id=request_id,
        invite_id=invite_id,
        via=via,
        price_pence=price_pence,
        unit=unit_for(category_id, recurring),
        recurring=recurring,
        frequency=frequency,
        series_id=series_id,
        address=ctx.customer_address(customer),
        answers=answers or {},
        notes=notes,
        when=when,
        status=status,
        **ctx.timestamps(created_at),
    )
    return b


def add_visit(
    ctx: Ctx,
    *,
    key: str,
    booking: Booking,
    day: date,
    hhmm: str,
    est_mins: int,
    actual_mins: int | None = None,
    paid_provider: str | None = None,
    performer: str | None = None,
    performer_kind: str = "provider",
    is_first: bool = False,
    window: TimePref = "either",
    flags: list[str] | None = None,
    photos_after: list[str] | None = None,
    cover_from: str | None = None,
    note: str = "",
) -> Visit:
    """A visit on `day`. With actual_mins it's finished and charged (charge, ledger entry and the
    fake gateway's record); without, it's scheduled."""
    pkey = paid_provider or next(k for k, p in ctx.providers.items() if p.id == booking.provider_id)
    provider = ctx.providers[pkey]
    doer = ctx.providers[performer or pkey]
    start = ctx.at(day, hhmm)
    vid = sid("visit", key)
    v = Visit(
        id=vid,
        booking_id=booking.id,
        series_id=booking.series_id,
        customer_id=booking.customer_id,
        provider_id=provider.id,
        performer=Performer(kind=performer_kind, provider_id=doer.id, user_id=doer.user_id, name=doer.short),
        category_id=booking.category_id,
        source=booking.source,
        local_date=day,
        scheduled_start=start,
        window=window,
        is_first=is_first,
        price_pence=booking.price_pence,
        est_mins=est_mins,
        pricing_version_id=ctx.pricing.id if ctx.pricing else None,
        cover=CoverState(state="covered", original_provider_id=ctx.providers[cover_from].id)
        if cover_from
        else CoverState(),
        **ctx.timestamps(booking.created_at),
    )
    ctx.visit_address[vid] = booking.address
    ctx.visits.append(v)
    if actual_mins is None:
        ctx.w.add(v)
        return v

    started = start + timedelta(minutes=4)
    finished = started + timedelta(minutes=actual_mins)
    charged = finished + timedelta(minutes=2)
    split = money.split_for_source(booking.price_pence, booking.source, ctx.s)
    charge_id = "ch_fake_" + sid("charge", key)[-12:]
    over, over25 = overran(est_mins, actual_mins)
    v.status = "finished"
    v.started_at, v.finished_at = started, finished
    v.minutes_actual, v.minutes_from_timer = actual_mins, True
    v.flags = flags or []
    v.flags_none = not flags
    v.overrun, v.over_25 = over, over25
    v.finish_note = note
    v.photos = Photos(after=photos_after or [])
    v.charge = Charge(
        status="succeeded",
        amount_pence=split.price_pence,
        fee_pence=split.fee_pence,
        provider_pence=split.provider_pence,
        gateway="fake",
        charge_id=charge_id,
        payment_intent_id="pi_fake_" + sid("pi", key)[-12:],
        idempotency_key=f"visit:{vid}:visit",
        charged_at=charged,
    )
    v.updated_at = charged
    ctx.w.add(v)

    local = to_london(charged).date()
    ctx.w.add(
        LedgerEntry(
            id=sid("ledger", key),
            provider_id=provider.id,
            customer_id=booking.customer_id,
            visit_id=vid,
            booking_id=booking.id,
            kind="charge",
            source=booking.source,
            gross_pence=split.price_pence,
            fee_pence=split.fee_pence,
            net_pence=split.provider_pence,
            occurred_at=charged,
            local_date=local,
            tax_year=tax_year(local),
            gateway="fake",
            gateway_ref=charge_id,
            **ctx.timestamps(charged),
        )
    )
    if provider.payment_account:
        result = ChargeResult(
            status="succeeded",
            charge_id=charge_id,
            payment_intent_id=v.charge.payment_intent_id,
            amount_pence=split.price_pence,
            fee_pence=split.fee_pence,
            idempotency_key=v.charge.idempotency_key or "",
            created_at=charged,
        )
        ctx.w.add_raw(
            "fake_gateway",
            {
                "_id": charge_id,
                "kind": "charge",
                "idempotency_key": result.idempotency_key,
                "account": provider.payment_account.account_id,
                "visit_id": vid,
                "net_pence": split.provider_pence,
                "refunded_pence": 0,
                "result": result.model_dump(mode="python"),
            },
        )
    return v


def add_thread(
    ctx: Ctx,
    key: str,
    booking: Booking,
    messages: list[tuple[str, str, datetime]] | None = None,
    kind: str = "booking",
    dispute_id: str | None = None,
) -> MessageThread:
    """A thread between the booking's customer and provider. messages: (from role, text, at)."""
    customer = next(c for c in ctx.customers.values() if c.id == booking.customer_id)
    provider = next(p for p in ctx.providers.values() if p.id == booking.provider_id)
    cu = next(u for u in ctx.users.values() if u.id == customer.user_id)
    pu = next(u for u in ctx.users.values() if u.id == provider.user_id)
    t = MessageThread(
        id=sid("thread", key),
        kind=kind,
        booking_id=booking.id if kind == "booking" else None,
        dispute_id=dispute_id,
        participants=[
            Participant(user_id=cu.id, role="customer", name=cu.name),
            Participant(user_id=pu.id, role="provider", name=pu.name),
        ],
        **ctx.timestamps(booking.created_at),
    )
    for i, (who, text, at) in enumerate(messages or []):
        sender = {"customer": cu, "provider": pu}.get(who)
        role = who if who in ("customer", "provider") else "admin"
        if sender is None:
            sender = next(iter(ctx.admins.values()))
        ctx.w.add(
            Message(
                id=sid("message", key, i),
                thread_id=t.id,
                sender_user_id=sender.id,
                sender_role=role,
                body=text,
                read_by=[sender.id, *([cu.id, pu.id] if at < ctx.now - timedelta(hours=1) else [])],
                **ctx.timestamps(at),
            )
        )
        t.last_message_at, t.last_message_preview = at, text[:140]
    ctx.w.add(t)
    if kind == "booking":
        booking.thread_id = t.id
    return t


def lawn_png(width: int = 320, height: int = 136) -> bytes:
    """A small striped-lawn picture for seeded after photos (deterministic bytes)."""
    sky, hedge = (0xE2, 0xE9, 0xD8), (0x2E, 0x5D, 0x3E)
    stripes = ((0x5E, 0x99, 0x5A), (0x74, 0xAE, 0x6B))
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            if y < 24:
                c = sky
            elif y < 40 + (4 if (x // 40) % 2 else 0):
                c = hedge
            else:
                c = stripes[(x // 26) % 2]
            row += bytes(c)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def add_after_photo(ctx: Ctx, key: str, owner_user_id: str, at: datetime, visit_id: str) -> str:
    """Store a placeholder after photo in the FileStore and return its file id."""
    data = lawn_png()
    rel = f"visit_after/seed/{sid('photo', key)}.png"
    try:
        target = Path(ctx.s.files_dir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as e:  # the record is still useful without the picture
        print(f"  couldn't write {rel}: {e}")
    f = StoredFile(
        id=sid("file", key),
        kind="visit_after",
        owner_user_id=owner_user_id,
        path=rel,
        url=f"{ctx.s.files_url_prefix.rstrip('/')}/{rel}",
        content_type="image/png",
        size=len(data),
        original_name="after.png",
        related=Related(visit_id=visit_id),
        created_at=at,
    )
    ctx.w.add(f)
    return f.id


def minutes_near(est: int, rnd) -> int:
    """A plausible recorded time: within about -8% to +14% of the estimate."""
    return max(5, round_half_up(est * (0.92 + rnd() * 0.22)))
