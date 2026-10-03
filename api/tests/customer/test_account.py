"""The customer's account: bookings with provider badges and the fee split, visits, skipping,
asking to move a one-off, plans (winter and away pauses, cover, frequency, cancel), rating with
a tip, reporting a problem within 48 hours, and booking the same provider again."""

import contextlib
import itertools
from datetime import timedelta

from app.core.timeutil import london_today
from app.customer.schemas import RatingIn
from app.repos import Bookings, Disputes, LedgerEntries, Messages, MessageThreads, Providers, SeriesRepo, Users, Visits
from tests.conftest import new_client
from tests.customer.helpers import book_at_guide, customer_of, finish_visit, make_request_via_api, signed_in_with_card
from tests.factories import make_provider


async def _payable(db, name: str, phone: str, skills: list[str]):
    """A provider with a (fake) payment account, so tips can be charged to them."""
    from app.models.providers import PaymentAccount

    p = await make_provider(db, name, phone, skills)
    account = PaymentAccount(
        gateway="fake", account_id=f"acct_fake_{p.id[-8:]}", status="enabled", payouts_enabled=True
    )
    await Providers(db).patch(p.id, {"payment_account": account.model_dump(mode="python")})
    return await Providers(db).get(p.id)


async def _booked(client, db, category_id: str = "mowing", **over):
    dave = await _payable(db, "Dave Hughes", "+447700900201", [category_id])
    await signed_in_with_card(client, db)
    detail = await make_request_via_api(client, category_id, **over)
    out = await book_at_guide(db, detail["ref"], dave)
    return dave, out.booking, out.first_visit


async def test_booking_card_and_detail(app, client, db, catalogue):
    _dave, booking, _first = await _booked(client, db, "cleaning")
    cards = (await client.get("/api/c/bookings")).json()
    assert [c["id"] for c in cards] == [booking.id]
    r = await client.get(f"/api/c/bookings/{booking.id}")
    d = r.json()
    assert d["price_pence"] == 6600 and d["first_price_pence"] == 8800 and d["unit"] == "a clean"
    assert d["split"] == {
        "mode": "standard",
        "rate_percent": 15,
        "price_pence": 6600,
        "fee_pence": 990,
        "provider_pence": 5610,
    }
    assert d["charged_after"] == "each visit" and d["frequency_label"] == "every 2 weeks"
    labels = [b["label"] for b in d["provider"]["badges"]]
    assert labels[:3] == ["ID checked", "Basic DBS checked", "Insured until Jan 2030"]
    assert labels[3].startswith("Lives ") and labels[3].endswith(" away")
    assert d["first_visit_text"].endswith("morning, 8am to 12pm")
    assert d["agreement_text"].startswith("Your agreement for this job is with Dave.")
    assert d["sms_sent_to"] == "07700 900123" and d["thread_id"]
    async with await new_client(app) as other:
        await signed_in_with_card(other, db, "+447700900130", "Robert Brown")
        assert (await other.get(f"/api/c/bookings/{booking.id}")).status_code == 404


async def test_visits_list_labels_and_skip(client, db, catalogue):
    _dave, booking, first = await _booked(client, db)
    v = (await client.get("/api/c/visits")).json()
    assert v["next_visit"]["id"] == first.id and v["next_visit"]["label"] == "booked"
    assert all(x["label"] == "planned" for x in v["upcoming"][1:]) and len(v["upcoming"]) >= 2
    assert v["next_visit"]["can_skip"] is True and v["next_visit"]["can_change_date"] is False
    second = v["upcoming"][1]
    r = await client.post(f"/api/c/visits/{second['id']}/skip")
    assert r.status_code == 200 and r.json()["status"] == "skipped" and r.json()["label"] == "skipped"
    msg = await db["outbox"].find_one({"template_id": "visit_skipped"})
    assert "is skipped." in msg["body"]
    notes = await Messages(db).in_thread(booking.thread_id)
    assert notes[-1].sender_role == "system" and "skipped the visit on" in notes[-1].body
    again = await client.post(f"/api/c/visits/{second['id']}/skip")
    assert again.status_code == 409


async def test_asking_to_move_a_one_off_messages_the_provider(client, db, catalogue):
    _dave, booking, first = await _booked(client, db, "flatpack")
    view = (await client.get(f"/api/c/visits/{first.id}")).json()
    assert view["can_change_date"] is True and view["can_skip"] is False
    days = [(london_today() + timedelta(days=n)).isoformat() for n in (3, 4)]
    r = await client.post(f"/api/c/visits/{first.id}/change-date", json={"preferred": days, "note": "Any time."})
    assert r.status_code == 200
    (msg,) = await Messages(db).in_thread(booking.thread_id)
    assert (
        msg.sender_role == "customer" and msg.body.startswith("Could we move the visit on") and "Any time." in msg.body
    )
    texted = await db["outbox"].find_one({"template_id": "message_received"})
    assert texted["recipient"]["phone"] == "+447700900201"
    bad = await client.post(f"/api/c/visits/{first.id}/change-date", json={"preferred": [london_today().isoformat()]})
    assert bad.status_code == 422


async def test_rating_with_a_tip_charges_it_without_a_fee(client, db, catalogue):
    dave, _booking, first = await _booked(client, db)
    early = await client.post(f"/api/c/visits/{first.id}/rating", json={"stars": 5})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "not_finished"
    await finish_visit(db, first.id)
    view = (await client.get(f"/api/c/visits/{first.id}")).json()
    assert view["can_rate"] and view["can_report"] and view["label"] == "done"
    r = await client.post(
        f"/api/c/visits/{first.id}/rating", json={"stars": 5, "tags": ["On time", "Thorough"], "tip_pence": 500}
    )
    assert r.status_code == 201, r.text
    assert r.json()["tip_status"] == "charged" and r.json()["tip_pence"] == 500
    visit = await Visits(db).get(first.id)
    assert visit.tip_pence == 500 and visit.tip_charge.status == "succeeded" and visit.tip_charge.fee_pence == 0
    (entry,) = await LedgerEntries(db).find({"visit_id": first.id})
    assert (entry.kind, entry.gross_pence, entry.fee_pence, entry.net_pence) == ("tip", 500, 0, 500)
    assert visit.tip_charge.idempotency_key == f"visit:{first.id}:tip", "L3's charging path and key"
    msg = await db["outbox"].find_one({"template_id": "rating_received"})
    assert msg["body"].endswith("rated your lawn mowing 5 out of 5.")
    tip = await db["outbox"].find_one({"template_id": "tip_received"})
    assert "Sarah added a £5 tip for your lawn mowing. All of it goes to you, with no fee." in tip["body"]
    assert (await Providers(db).get(dave.id)).stats.rating_count == 1
    again = await client.post(f"/api/c/visits/{first.id}/rating", json={"stars": 4})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_rated"
    assert (await client.get(f"/api/c/visits/{first.id}")).json()["rating_stars"] == 5


async def test_a_tip_whose_outcome_is_unknown_is_settled_once_by_the_payments_path(client, db, catalogue, monkeypatch):
    """The tip goes through the one charging path: a gateway error after the charge leaves it
    pending; L3's settle step finds the payment by its idempotency key and records it once
    (ledger entry and tip_received), never charging again."""
    from datetime import timedelta

    from app.adapters.payments.fake import FakeGateway
    from app.core.timeutil import utcnow
    from app.payments import charging
    from tests.conftest import make_settings

    _dave, _booking, first = await _booked(client, db)
    await finish_visit(db, first.id)
    real = FakeGateway.charge_visit

    async def times_out(self, *a, **kw):
        await real(self, *a, **kw)  # the charge goes through ...
        raise TimeoutError("no response")  # ... but the answer never arrives

    monkeypatch.setattr(FakeGateway, "charge_visit", times_out)
    r = await client.post(f"/api/c/visits/{first.id}/rating", json={"stars": 4, "tip_pence": 300})
    assert r.status_code == 201 and r.json()["tip_status"] == "pending"
    assert "still going through" in r.json()["tip_message"]
    visit = await Visits(db).get(first.id)
    assert visit.tip_charge.status == "pending" and await LedgerEntries(db).count({}) == 0
    assert await db["outbox"].count_documents({"template_id": "rating_received"}) == 1, "the rating is in"
    assert await db["outbox"].count_documents({"template_id": "tip_received"}) == 0

    monkeypatch.setattr(FakeGateway, "charge_visit", real)
    key = visit.tip_charge.idempotency_key
    await db["payment_attempts"].update_one({"_id": key}, {"$set": {"created_at": utcnow() - timedelta(minutes=2)}})
    s = make_settings()
    visit = await charging.settle_unknown(db, s, FakeGateway(db), await Visits(db).get(first.id), "tip")
    assert visit.tip_charge.status == "succeeded"
    again = await charging.charge_visit(db, s, FakeGateway(db), first.id, purpose="tip")  # a repeat changes nothing
    assert again.tip_charge == visit.tip_charge
    assert await db["fake_gateway"].count_documents({"kind": "charge", "idempotency_key": key}) == 1
    (entry,) = await LedgerEntries(db).find({"visit_id": first.id})
    assert (entry.kind, entry.gross_pence, entry.fee_pence) == ("tip", 300, 0)
    assert await db["outbox"].count_documents({"template_id": "tip_received"}) == 1


async def test_an_interrupted_tip_is_finished_by_a_retry_or_the_task(client, db, catalogue, monkeypatch):
    """Codex (medium): the rating committed but the request stopped before the tip's charge began."""
    from datetime import timedelta

    from app.adapters.payments.fake import FakeGateway
    from app.core.timeutil import utcnow
    from app.customer import account
    from app.payments import charging
    from tests.conftest import make_settings

    _dave, booking, first = await _booked(client, db)
    second = (await Visits(db).find({"series_id": booking.series_id, "is_first": False}, sort=[("local_date", 1)]))[0]
    for v in (first, second):
        await finish_visit(db, v.id)
    real = charging.charge_visit

    async def crash(*a, **kw):
        raise RuntimeError("the request stopped here")

    monkeypatch.setattr(charging, "charge_visit", crash)
    customer = await customer_of(db)
    user = await Users(db).get(customer.user_id)
    s = make_settings()
    for v in (first, second):
        with contextlib.suppress(RuntimeError):
            await account.rate_visit(
                db, s, FakeGateway(db), await Visits(db).get(v.id), customer, user, RatingIn(stars=5, tip_pence=200)
            )
    monkeypatch.setattr(charging, "charge_visit", real)
    for v in (first, second):
        stored = await Visits(db).get(v.id)
        assert stored.rating_id and stored.tip_pence == 200 and stored.tip_charge is None

    # A retry of the rating finishes its tip ...
    r = await client.post(f"/api/c/visits/{first.id}/rating", json={"stars": 5, "tip_pence": 200})
    assert r.status_code == 201 and r.json()["tip_status"] == "charged"
    # ... and the task finishes one nobody retried.
    assert await account.start_orphaned_tips(db, s, FakeGateway(db)) == 0, "too soon: the request may still be running"
    await Visits(db).coll.update_one({"_id": second.id}, {"$set": {"updated_at": utcnow() - timedelta(minutes=5)}})
    assert await account.start_orphaned_tips(db, s, FakeGateway(db)) == 1
    assert (await Visits(db).get(second.id)).tip_charge.status == "succeeded"
    assert await LedgerEntries(db).count({"kind": "tip"}) == 2
    assert await account.start_orphaned_tips(db, s, FakeGateway(db)) == 0
    again = await client.post(f"/api/c/visits/{first.id}/rating", json={"stars": 5})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_rated"


async def test_a_declined_tip_keeps_the_rating(app, db, catalogue):
    dave = await _payable(db, "Dave Hughes", "+447700900201", ["mowing"])
    async with await new_client(app) as c:
        await signed_in_with_card(c, db, "+447700900150", "Pat Decline")  # the fake declines "decline"
        detail = await make_request_via_api(c, contact={"name": "Pat Decline", "email": None})
        out = await book_at_guide(db, detail["ref"], dave)
        await finish_visit(db, out.first_visit.id)
        r = await c.post(f"/api/c/visits/{out.first_visit.id}/rating", json={"stars": 4, "tip_pence": 200})
        assert r.status_code == 201 and r.json()["tip_status"] == "failed"
        assert r.json()["tip_message"].startswith("Your rating is saved, but the tip didn't go through")
    assert await LedgerEntries(db).count({}) == 0
    msg = await db["outbox"].find_one({"template_id": "rating_received"})
    assert "tip" not in msg["body"]
    assert await db["outbox"].count_documents({"template_id": "tip_received"}) == 0


async def test_reporting_a_problem_opens_a_dispute_within_48_hours(client, db, catalogue):
    _dave, _booking, first = await _booked(client, db, "cleaning")
    await finish_visit(db, first.id, ago=timedelta(hours=20))
    r = await client.post(
        f"/api/c/visits/{first.id}/problem", json={"description": "The bathroom floor wasn't done. Sorry to say."}
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["ref"].startswith("D-") and out["status_text"] == "Waiting for Dave's reply"
    dispute = await Disputes(db).get(out["dispute_id"])
    assert dispute.stage == 0 and dispute.title == "The bathroom floor wasn't done" and dispute.amount_pence == 8800
    thread = await MessageThreads(db).get(dispute.thread_id)
    assert thread.kind == "dispute" and {p.role for p in thread.participants} == {"customer", "provider"}
    assert (await Messages(db).in_thread(thread.id))[0].body.startswith("The bathroom floor")
    assert "We've let Dave H. know" in (await db["outbox"].find_one({"template_id": "problem_reported"}))["body"]
    opened = await db["outbox"].find_one({"template_id": "dispute_opened"})
    assert opened["recipient"]["phone"] == "+447700900201" and "The bathroom floor wasn't done" in opened["body"]
    again = await client.post(f"/api/c/visits/{first.id}/problem", json={"description": "Again please"})
    assert again.status_code == 409
    view = (await client.get(f"/api/c/visits/{first.id}")).json()
    assert view["can_report"] is False and view["dispute_ref"] == out["ref"]


async def test_problems_after_48_hours_go_to_messages_instead(client, db, catalogue):
    _dave, _booking, first = await _booked(client, db)
    await finish_visit(db, first.id, ago=timedelta(hours=49))
    r = await client.post(f"/api/c/visits/{first.id}/problem", json={"description": "Missed a strip"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_late"


async def test_winter_pause_and_cover_toggle(client, db, catalogue):
    _dave, _booking, _first = await _booked(client, db)
    (plan,) = (await client.get("/api/c/plans")).json()
    assert plan["outside"] is True and plan["pause_winter"] is False and plan["cover_when_away"] is True
    r = await client.patch(f"/api/c/plans/{plan['series_id']}", json={"pause_winter": True, "cover_when_away": False})
    assert r.status_code == 200 and r.json()["pause_winter"] is True and r.json()["cover_when_away"] is False
    winter = [
        v for v in await Visits(db).find({"series_id": plan["series_id"]}) if v.local_date.month in (11, 12, 1, 2)
    ]
    assert all(v.status == "skipped" for v in winter if v.local_date > london_today())
    changed = await db["outbox"].find_one({"template_id": "plan_changed"})
    assert "paused over winter" in changed["body"] and "cover when Dave's away off" in changed["body"]
    r = await client.patch(f"/api/c/plans/{plan['series_id']}", json={"pause_winter": False})
    back = [v for v in await Visits(db).find({"series_id": plan["series_id"]}) if v.local_date.month in (11, 12, 1, 2)]
    assert all(v.status == "scheduled" for v in back if v.local_date > london_today())


async def test_away_dates_skip_those_visits(client, db, catalogue):
    _dave, booking, _first = await _booked(client, db, "cleaning")
    series = await SeriesRepo(db).get(booking.series_id)
    visits = [v for v in await Visits(db).find({"series_id": series.id}, sort=[("local_date", 1)])]
    target = visits[1].local_date
    body = {"away_from": (target - timedelta(days=1)).isoformat(), "away_to": (target + timedelta(days=1)).isoformat()}
    r = await client.patch(f"/api/c/plans/{series.id}", json=body)
    assert r.status_code == 200 and r.json()["away_from"] == body["away_from"]
    assert (await Visits(db).get(visits[1].id)).status == "skipped"
    assert (await Visits(db).get(visits[0].id)).status == "scheduled"
    one_date = await client.patch(f"/api/c/plans/{series.id}", json={"away_from": body["away_from"]})
    assert one_date.status_code == 422
    cleared = await client.patch(f"/api/c/plans/{series.id}", json={"away_from": None, "away_to": None})
    assert cleared.json()["away_from"] is None and (await Visits(db).get(visits[1].id)).status == "scheduled"
    inside = await client.patch(f"/api/c/plans/{series.id}", json={"pause_winter": True})
    assert inside.status_code == 422, "the winter pause is for outside jobs"


async def _accepted_change(client, db, series_id: str, frequency: str) -> int:
    """Ask for a frequency (A10) and accept it as the provider would, from the link in their text.
    Returns the new price."""
    r = await client.patch(f"/api/c/plans/{series_id}", json={"frequency": frequency})
    assert r.status_code == 200, r.text
    price = r.json()["pending_change"]["to_price_pence"]
    msg = await db["outbox"].find_one({"template_id": "plan_change_proposed"}, sort=[("created_at", -1), ("_id", -1)])
    token = msg["body"].split("/plan-change/")[1].split()[0]
    assert (await client.post(f"/api/c/plan-changes/{token}/accept")).status_code == 200
    return price


async def _scheduled(db, series_id: str):
    return [
        v.local_date
        for v in await Visits(db).find({"series_id": series_id, "status": "scheduled"}, sort=[("local_date", 1)])
    ]


async def test_an_accepted_frequency_change_keeps_the_next_visit(client, db, catalogue):
    _dave, booking, first = await _booked(client, db)
    price = await _accepted_change(client, db, booking.series_id, "weekly")
    plan = (await client.get(f"/api/c/plans/{booking.series_id}")).json()
    assert plan["frequency"] == "weekly" and plan["price_pence"] == price
    scheduled = await _scheduled(db, booking.series_id)
    assert scheduled[0] == first.local_date
    assert {(b - a).days for a, b in itertools.pairwise(scheduled)} == {7}
    assert (await Bookings(db).get(booking.id)).frequency == "weekly"
    await _accepted_change(client, db, booking.series_id, "threeweekly")
    scheduled = await _scheduled(db, booking.series_id)
    assert scheduled[0] == first.local_date and len(scheduled) >= 2
    assert {(b - a).days for a, b in itertools.pairwise(scheduled)} == {21}, scheduled


async def test_a_frequency_change_during_a_pause_doesnt_bring_old_dates_back(client, db, catalogue):
    """Codex (medium): weekly plan, away pause, change to fortnightly, clear the pause."""
    _dave, booking, first = await _booked(client, db, "cleaning")
    sid = booking.series_id
    await _accepted_change(client, db, sid, "weekly")
    weekly = await _scheduled(db, sid)
    away = {"away_from": weekly[1].isoformat(), "away_to": weekly[3].isoformat()}
    assert (await client.patch(f"/api/c/plans/{sid}", json=away)).status_code == 200
    await _accepted_change(client, db, sid, "fortnightly")
    assert (await client.patch(f"/api/c/plans/{sid}", json={"away_from": None, "away_to": None})).status_code == 200
    scheduled = await _scheduled(db, sid)
    assert scheduled[0] == first.local_date
    assert {(b - a).days for a, b in itertools.pairwise(scheduled)} == {14}, scheduled


async def test_cancelling_a_plan_cancels_a_visit_later_today(client, db, catalogue):
    """Codex (medium): a visit later today is cancelled with the plan; one in progress isn't."""
    from datetime import timedelta

    from app.core.timeutil import london_today, utcnow

    _dave, booking, first = await _booked(client, db)
    later = utcnow() + timedelta(minutes=30)
    await Visits(db).update(first.id, {"local_date": london_today().isoformat(), "scheduled_start": later})
    second = (await Visits(db).find({"series_id": booking.series_id, "is_first": False}, sort=[("local_date", 1)]))[0]
    await Visits(db).update(second.id, {"status": "in_progress"})
    assert (await client.post(f"/api/c/plans/{booking.series_id}/cancel")).status_code == 200
    assert (await Visits(db).get(first.id)).status == "cancelled"
    assert (await Visits(db).get(second.id)).status == "in_progress"


async def _first_visit_later_today(db, visit_id: str) -> None:
    from app.core.timeutil import london_today, utcnow

    await Visits(db).update(
        visit_id, {"local_date": london_today().isoformat(), "scheduled_start": utcnow() + timedelta(minutes=30)}
    )


async def test_an_away_pause_from_today_skips_a_visit_later_today(client, db, catalogue):
    """Codex re-check (medium)."""
    _dave, booking, first = await _booked(client, db, "cleaning")
    await _first_visit_later_today(db, first.id)
    today = london_today().isoformat()
    body = {"away_from": today, "away_to": (london_today() + timedelta(days=3)).isoformat()}
    assert (await client.patch(f"/api/c/plans/{booking.series_id}", json=body)).status_code == 200
    assert (await Visits(db).get(first.id)).status == "skipped"


async def test_a_frequency_change_keeps_a_visit_later_today_as_the_anchor(client, db, catalogue):
    """Codex re-check (medium): fortnightly to weekly before today's visit keeps next week's."""
    _dave, booking, first = await _booked(client, db)
    await _first_visit_later_today(db, first.id)
    await _accepted_change(client, db, booking.series_id, "weekly")
    scheduled = await _scheduled(db, booking.series_id)
    assert scheduled[0] == london_today() and scheduled[1] == london_today() + timedelta(days=7), scheduled
