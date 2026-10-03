"""Today's round, starting the timer, photos, and sending a helper."""

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.timeutil import london_today
from app.provider import round as round_mod
from app.provider.acting import Acting
from app.repos import Visits
from tests.conftest import make_settings
from tests.factories import make_customer
from tests.provider.conftest import TOM_PHONE, add_tom, book, client_for, move_to_today


async def test_today_lists_the_round_in_time_order(dave_client, db, world):
    other = await make_customer(db, "Margaret Turner", "+447700900133")
    _, second = await book(db, other, world.dave)
    await move_to_today(db, second, (13, 30))
    await move_to_today(db, world.first, (9, 0))
    r = await dave_client.get("/api/p/today")
    assert r.status_code == 200, r.text
    day = r.json()
    assert day["is_today"] and day["local_date"] == london_today().isoformat()
    assert [i["start_time"] for i in day["items"]] == ["9:00", "13:30"]
    first = day["items"][0]
    assert (
        first["is_now"]
        and first["customer_name"] == "Sarah W."
        and first["address_line"] == "12 Orchard Way, Hazlemere"
    )
    assert first["note"] == "The side gate sticks." and first["miles_from_previous"] is not None
    assert day["items"][1]["miles_from_previous"] == 0.0  # same street in the test data
    assert day["upcoming_days"], "later visits are offered as other days to look at"


async def test_a_future_visit_starts_early_only_in_demo_mode(db, world):
    from app.repos import Users
    from tests.provider.test_finish import _cu

    a = Acting(provider=world.dave, cu=_cu(await Users(db).get(world.dave.user_id)))
    assert world.first.local_date > london_today()
    with pytest.raises(HTTPException) as e:
        await round_mod.start_visit(db, make_settings(demo_mode=False), a, world.first.id)
    assert e.value.status_code == 409 and e.value.detail["code"] == "not_yet"
    detail = await round_mod.provider_visit(db, make_settings(demo_mode=False), a, world.first)
    assert not detail.can_start and not detail.early_start_demo and detail.start_note
    demo = await round_mod.provider_visit(db, make_settings(demo_mode=True), a, world.first)
    assert demo.can_start and demo.early_start_demo
    started = await round_mod.start_visit(db, make_settings(demo_mode=True), a, world.first.id)
    assert started.status == "in_progress" and started.started_at is not None


async def test_starting_twice_keeps_the_first_start(dave_client, db, world):
    v = await move_to_today(db, world.first)
    a = (await dave_client.post(f"/api/p/visits/{v.id}/start")).json()
    b = (await dave_client.post(f"/api/p/visits/{v.id}/start")).json()
    assert a["started_at"] == b["started_at"] and b["elapsed_seconds"] is not None


async def test_photos_must_be_the_providers_own_uploads(app, dave_client, db, world):
    v = await move_to_today(db, world.first)
    async with client_for(app, db, "+447700900999") as stranger:
        up = await stranger.post(
            "/api/files", data={"kind": "visit_after"}, files={"file": ("x.png", b"\x89PNG\r\n\x1a\n0", "image/png")}
        )
    r = await dave_client.post(f"/api/p/visits/{v.id}/photos", json={"kind": "after", "file_id": up.json()["id"]})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "file_not_found"
    mine = await dave_client.post(
        "/api/files", data={"kind": "visit_before"}, files={"file": ("b.png", b"\x89PNG\r\n\x1a\n0", "image/png")}
    )
    wrong = await dave_client.post(f"/api/p/visits/{v.id}/photos", json={"kind": "after", "file_id": mine.json()["id"]})
    assert wrong.status_code == 422
    ok = await dave_client.post(f"/api/p/visits/{v.id}/photos", json={"kind": "before", "file_id": mine.json()["id"]})
    assert ok.status_code == 200 and len(ok.json()["before_photos"]) == 1


async def test_send_tom_tells_the_customer_and_tom_sees_only_that_visit(app, dave_client, db, world):
    tom = await add_tom(db, world.dave)
    visits = await Visits(db).for_booking(world.booking.id)
    first, second = visits[0], visits[1]
    r = await dave_client.post(f"/api/p/visits/{first.id}/send-helper", json={"helper_user_id": tom.id})
    assert r.status_code == 200, r.text
    assert r.json()["performer"] == "helper" and r.json()["performer_name"] == "Tom H."
    msg = await db["outbox"].find_one({"template_id": "helper_coming"})
    assert msg and "so Tom H., their helper, is coming instead" in msg["body"]
    stored = await Visits(db).get(first.id)
    assert stored.provider_id == world.dave.id, "Dave is still the one paid"

    async with client_for(app, db, TOM_PHONE) as tc:
        assert (await tc.get(f"/api/p/visits/{first.id}")).status_code == 200
        assert (await tc.get(f"/api/p/visits/{second.id}")).status_code == 404
        day = (await tc.get("/api/p/today", params={"date": first.local_date.isoformat()})).json()
        assert [i["visit_id"] for i in day["items"]] == [first.id] and day["helpers"] == []
        for path in ("/api/p/earnings", "/api/p/tax", "/api/p/profile", "/api/p/own-customers"):
            assert (await tc.get(path)).status_code == 403, path
        sent = await tc.post(f"/api/p/visits/{first.id}/send-helper", json={"helper_user_id": tom.id})
        assert sent.status_code == 403


async def test_a_helper_who_isnt_ready_cant_be_sent(dave_client, db, world):
    tom = await add_tom(db, world.dave, status="checking")
    r = await dave_client.post(f"/api/p/visits/{world.first.id}/send-helper", json={"helper_user_id": tom.id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "helper_not_ready"


async def test_today_shows_another_day_when_asked(dave_client, db, world):
    day = world.first.local_date
    r = await dave_client.get("/api/p/today", params={"date": day.isoformat()})
    assert r.status_code == 200 and not r.json()["is_today"]
    assert [i["visit_id"] for i in r.json()["items"]] == [world.first.id]
    nothing = await dave_client.get("/api/p/today", params={"date": (day - timedelta(days=60)).isoformat()})
    assert nothing.json()["items"] == []
