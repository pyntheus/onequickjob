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
from tests.provider.conftest import TOM_PHONE, add_tom, book, checked_docs, client_for, move_to_today


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


async def test_a_helper_added_in_the_app_cant_accept_or_counter_for_the_provider(app, dave_client, db, world):
    """Codex review (high), A17: a helper added in the app is linked to the provider by helper_of,
    which gets them the provider's visits and nothing more: the shared offer endpoints refuse
    them; they still see their own visits and add their documents."""
    from app.repos import Providers, Users
    from tests.factories import make_request

    r = await dave_client.post("/api/p/helpers", json={"name": "Tom Hughes", "phone": "07700 900220"})
    assert r.status_code == 201, r.text
    assert (await Users(db).by_phone(TOM_PHONE)).helper_of == world.dave.id
    req = await make_request(db, world.customer)
    async with client_for(app, db, TOM_PHONE) as tc:
        for r in (
            await tc.post(f"/api/p/requests/{req.ref}/accept"),
            await tc.post(f"/api/p/requests/{req.ref}/counter", json={"price_pence": 3700}),
        ):
            assert r.status_code == 403 and r.json()["detail"]["code"] == "helpers_cant"
        home = await tc.get("/api/p/home")
        assert home.status_code == 200 and home.json()["helper"] is True and home.json()["new_jobs"] == []
        assert (await tc.get("/api/p/jobs")).status_code == 403
        assert (await tc.get("/api/p/today")).json()["items"] == []
        assert (await tc.get("/api/p/documents")).status_code == 200
    assert (await db["job_requests"].find_one({"_id": req.id}))["status"] == "open"
    tom = (await Providers(db).get(world.dave.id)).helpers[0]
    await db["providers"].update_one(
        {"_id": world.dave.id, "helpers.user_id": tom.user_id}, {"$set": {"helpers.$.status": "removed"}}
    )
    async with client_for(app, db, TOM_PHONE) as tc:
        assert (await tc.get("/api/p/home")).status_code == 403, "a removed helper loses access"


async def test_a_helper_needs_the_documents_the_job_needs(dave_client, db, world, catalogue):
    """Codex review (high): a helper whose basic DBS check has run out can't be sent to a
    cleaning visit; with it in date, they can."""
    from datetime import date

    from app.models.providers import ProviderDocument

    tom = await add_tom(db, world.dave)
    _, cleaning = await book(db, world.customer, world.dave, category="cleaning")

    async def set_docs(dbs_expires: date) -> None:
        docs = [
            ProviderDocument(
                type=t, status="verified", expires_on=dbs_expires if t == "dbs_basic" else date(2030, 1, 1)
            )
            for t in ("identity", "insurance", "dbs_basic")
        ]
        await db["providers"].update_one(
            {"_id": world.dave.id, "helpers.user_id": tom.id},
            {"$set": {"helpers.$.documents": [d.model_dump(mode="python") for d in docs]}},
        )

    await set_docs(london_today() - timedelta(days=1))
    r = await dave_client.post(f"/api/p/visits/{cleaning.id}/send-helper", json={"helper_user_id": tom.id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "helper_missing_documents"
    await set_docs(london_today() + timedelta(days=200))
    ok = await dave_client.post(f"/api/p/visits/{cleaning.id}/send-helper", json={"helper_user_id": tom.id})
    assert ok.status_code == 200, ok.text


async def test_a_ready_helper_with_no_documents_is_never_trusted(db, world, catalogue):
    """A17: a helper needs every document the job needs on record, in DEMO_MODE too (the seed's
    Tom now has his, so the demo needs no exception)."""
    from app.provider.helpers import ready_helper
    from app.repos import Providers

    tom = await add_tom(db, world.dave, docs=())
    p = await Providers(db).get(world.dave.id)
    with pytest.raises(HTTPException) as e:
        ready_helper(p, tom.id, catalogue["mowing"])
    assert e.value.detail["code"] == "helper_missing_documents"


async def test_a_helper_cant_start_a_visit_taken_away_meanwhile(db, world, monkeypatch):
    """Codex re-check (high): the start is re-checked in its transaction and guarded on the
    visit's performer, so a helper authorised a moment ago can't start a visit that's just been
    sent to someone else, or start anything once removed."""
    from app.models.providers import Helper
    from app.models.users import User
    from app.repos import Providers, Users
    from tests.provider.test_finish import _cu

    tom = await add_tom(db, world.dave)
    jim = User(name="Jim Hughes", phone="+447700900221", roles=[], helper_of=world.dave.id)
    await Users(db).insert(jim)
    jim_helper = Helper(user_id=jim.id, name="Jim Hughes", status="ready", documents=checked_docs())
    await Providers(db).update(world.dave.id, {}, push={"helpers": jim_helper.model_dump()})
    s = make_settings()
    owner = Acting(provider=await Providers(db).get(world.dave.id), cu=_cu(await Users(db).get(world.dave.user_id)))
    await round_mod.send_helper(db, s, owner, world.first.id, tom.id)
    p = await Providers(db).get(world.dave.id)
    as_tom = Acting(provider=p, cu=_cu(tom), as_helper=next(h for h in p.helpers if h.user_id == tom.id))
    seen = await round_mod.visit_for(db, as_tom, world.first.id)  # Tom is authorised...
    await round_mod.send_helper(db, s, owner, world.first.id, jim.id)  # ...then it goes to Jim

    async def stale(*_a, **_k):
        return seen  # the read made just before the reassignment

    monkeypatch.setattr(round_mod, "visit_for", stale)
    with pytest.raises(HTTPException) as e:
        await round_mod.start_visit(db, s, as_tom, world.first.id)
    assert e.value.status_code == 409, "the guarded update refuses: it's Jim's visit now"
    assert (await Visits(db).get(world.first.id)).status == "scheduled"
    monkeypatch.undo()

    await round_mod.send_helper(db, s, owner, world.first.id, tom.id)
    await db["providers"].update_one(
        {"_id": world.dave.id, "helpers.user_id": tom.id}, {"$set": {"helpers.$.status": "removed"}}
    )
    with pytest.raises(HTTPException):
        await round_mod.start_visit(db, s, as_tom, world.first.id)  # removed since authorised
    assert (await Visits(db).get(world.first.id)).status == "scheduled"
