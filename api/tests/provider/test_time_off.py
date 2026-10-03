"""Time off: each affected visit covered locally, sent to a helper, or skipped, in one
transaction; cover through the normal offer flow; nobody taking it by the day before."""

from datetime import timedelta

from app.provider import cover as cover_mod
from app.provider import time_off as time_off_mod
from app.repos import JobRequests, SeriesRepo, TimeOffRepo, Visits
from app.services import marketplace
from tests.conftest import make_settings
from tests.factories import make_customer, make_provider
from tests.provider.conftest import MIKE_PHONE, add_tom, book, client_for, with_account


async def _week(db, dave):
    """Three regulars on Dave's next working day, and the week from that day."""
    sarah = await make_customer(db)
    margaret = await make_customer(db, "Margaret Turner", "+447700900133")
    robert = await make_customer(db, "Robert Brown", "+447700900131")
    visits = []
    for c in (sarah, margaret, robert):
        _, v = await book(db, c, dave, est_mins=30)
        visits.append(v)
    day = visits[0].local_date
    assert all(v.local_date == day for v in visits)
    return visits, {"from_date": day.isoformat(), "to_date": (day + timedelta(days=6)).isoformat()}


async def _outbox(db, template_id: str) -> list[dict]:
    return await db["outbox"].find({"template_id": template_id}).to_list()


async def test_book_a_week_off_with_cover_a_helper_and_a_skip(app, dave_client, db, dave):
    mike = await with_account(db, await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"]))
    tom = await add_tom(db, dave)
    (sarah_v, margaret_v, robert_v), dates = await _week(db, dave)

    preview = await dave_client.post("/api/p/time-off/preview", json=dates)
    assert preview.status_code == 200, preview.text
    assert {p["visit_id"] for p in preview.json()} >= {sarah_v.id, margaret_v.id, robert_v.id}
    assert all(p["cover_allowed"] for p in preview.json())

    arrangements = [{"visit_id": p["visit_id"], "action": "skip"} for p in preview.json()]
    plan = {sarah_v.id: {"action": "cover"}, margaret_v.id: {"action": "helper", "helper_user_id": tom.id}}
    for a in arrangements:
        a.update(plan.get(a["visit_id"], {}))
    r = await dave_client.post("/api/p/time-off", json={**dates, "arrangements": arrangements})
    assert r.status_code == 201, r.text
    off = r.json()
    assert off["status"] == "planned"
    by_visit = {a["visit_id"]: a for a in off["arrangements"]}
    assert by_visit[sarah_v.id]["state"] == "planned" and "Out for local cover" in by_visit[sarah_v.id]["detail"]
    assert by_visit[margaret_v.id]["detail"].startswith("Tom H. is doing it")
    assert by_visit[robert_v.id]["state"] == "arranged"

    covered = await Visits(db).get(sarah_v.id)
    assert covered.cover.state == "offered" and covered.provider_id == dave.id
    req = await JobRequests(db).get(covered.cover.request_id)
    assert req.cover_for_visit_id == sarah_v.id and req.guide_pence == sarah_v.price_pence and req.status == "open"
    assert req.broadcast.provider_ids == [mike.id], "eligible providers, never Dave himself"
    alert = (await _outbox(db, "cover_alert"))[0]
    assert alert["recipient"]["user_id"] == mike.user_id and f"/p/j/{req.ref}?t=" in alert["body"]
    assert (await Visits(db).get(margaret_v.id)).performer.kind == "helper"
    assert (await Visits(db).get(robert_v.id)).status == "skipped"
    assert len(await _outbox(db, "helper_coming")) == 1
    assert len(await _outbox(db, "visit_skipped")) == 1
    summary = (await _outbox(db, "time_off_arranged"))[0]["body"]
    assert "gone out for local cover" in summary and "Tom is doing" in summary and "is skipped" in summary

    # Mike takes the cover through the shared offer endpoint: that one visit is his, at 15%.
    async with client_for(app, db, MIKE_PHONE) as mc:
        taken = await mc.post(f"/api/p/requests/{req.ref}/accept")
    assert taken.status_code == 200, taken.text
    assert taken.json()["fee_pence"] == 450
    v = await Visits(db).get(sarah_v.id)
    assert v.provider_id == mike.id and v.performer.kind == "cover" and v.cover.original_provider_id == dave.id
    off_now = (await dave_client.get("/api/p/time-off")).json()[0]
    assert next(a for a in off_now["arrangements"] if a["visit_id"] == sarah_v.id)["detail"].startswith(
        "Mike R. is covering it"
    )
    # The plan carries on with Dave afterwards.
    series = await SeriesRepo(db).get(v.series_id)
    assert series.provider_id == dave.id


async def test_cover_nobody_takes_is_skipped_the_day_before(dave_client, db, dave):
    await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    visits, dates = await _week(db, dave)
    arrangements = [{"visit_id": v.id, "action": "cover"} for v in visits]
    r = await dave_client.post("/api/p/time-off", json={**dates, "arrangements": arrangements})
    assert r.status_code == 201, r.text
    day_before = visits[0].local_date - timedelta(days=2)
    assert await cover_mod.expire_uncovered(db, make_settings(), day_before) == 0, "too early to give up"
    assert await cover_mod.expire_uncovered(db, make_settings(), visits[0].local_date - timedelta(days=1)) == 3
    for v in visits:
        stored = await Visits(db).get(v.id)
        assert stored.status == "skipped" and stored.skipped_reason == "No cover found"
    assert len(await _outbox(db, "visit_skipped")) == 3
    assert len(await _outbox(db, "cover_not_found")) == 3
    assert await JobRequests(db).count({"cover_for_visit_id": {"$type": "string"}, "status": "expired"}) == 3
    await time_off_mod.housekeeping(db, make_settings())
    off = (await TimeOffRepo(db).find({}))[0]
    assert {a.state for a in off.arrangements} == {"failed"}
    assert await cover_mod.expire_uncovered(db, make_settings(), visits[0].local_date) == 0, "once only"


async def test_a_cover_taken_meanwhile_isnt_given_up_on(dave_client, db, dave):
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    visits, dates = await _week(db, dave)
    arrangements = [{"visit_id": v.id, "action": "cover" if v is visits[0] else "skip"} for v in visits]
    await dave_client.post("/api/p/time-off", json={**dates, "arrangements": arrangements})
    req = await JobRequests(db).find_one({"cover_for_visit_id": visits[0].id})
    await marketplace.accept_at_guide(db, make_settings(), req.ref, mike)
    assert await cover_mod.expire_uncovered(db, make_settings(), visits[0].local_date) == 0
    assert (await Visits(db).get(visits[0].id)).status == "scheduled"


async def test_each_visit_needs_a_choice_and_time_off_cant_overlap(dave_client, db, dave):
    visits, dates = await _week(db, dave)
    some = [{"visit_id": visits[0].id, "action": "skip"}]
    r = await dave_client.post("/api/p/time-off", json={**dates, "arrangements": some})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "choose_each"
    every = [{"visit_id": v.id, "action": "skip"} for v in visits]
    assert (await dave_client.post("/api/p/time-off", json={**dates, "arrangements": every})).status_code == 201
    again = await dave_client.post("/api/p/time-off", json={**dates, "arrangements": []})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "overlaps"


async def test_a_customer_who_doesnt_want_cover_isnt_offered_it(dave_client, db, dave):
    visits, dates = await _week(db, dave)
    await SeriesRepo(db).update(visits[0].series_id, {"cover_when_away": False})
    preview = {p["visit_id"]: p for p in (await dave_client.post("/api/p/time-off/preview", json=dates)).json()}
    assert preview[visits[0].id]["cover_allowed"] is False
    arrangements = [{"visit_id": v.id, "action": "cover"} for v in visits]
    r = await dave_client.post("/api/p/time-off", json={**dates, "arrangements": arrangements})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "cover_not_wanted"
    assert await JobRequests(db).count({}) == 0 and await TimeOffRepo(db).count({}) == 0


async def test_cancelling_withdraws_cover_and_gives_the_visit_back(dave_client, db, dave):
    await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    visits, dates = await _week(db, dave)
    arrangements = [{"visit_id": v.id, "action": "cover" if v is visits[0] else "skip"} for v in visits]
    off = (await dave_client.post("/api/p/time-off", json={**dates, "arrangements": arrangements})).json()
    r = await dave_client.delete(f"/api/p/time-off/{off['id']}")
    assert r.status_code == 204
    v = await Visits(db).get(visits[0].id)
    assert v.cover.state == "none" and v.status == "scheduled"
    assert (await JobRequests(db).find_one({"cover_for_visit_id": visits[0].id})).status == "cancelled"
    assert (await Visits(db).get(visits[1].id)).status == "skipped", "customers who were told stay told"
    assert (await dave_client.delete(f"/api/p/time-off/{off['id']}")).status_code == 409


async def test_get_cover_for_one_visit(dave_client, db, world):
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    r = await dave_client.post(f"/api/p/visits/{world.first.id}/cover")
    assert r.status_code == 200, r.text
    v = await Visits(db).get(world.first.id)
    assert v.cover.state == "offered"
    again = await dave_client.post(f"/api/p/visits/{world.first.id}/cover")
    assert again.status_code == 409
    start = await dave_client.post(f"/api/p/visits/{world.first.id}/start")
    assert start.status_code == 409, "a visit out for cover isn't started by its regular"
    assert mike


async def test_time_off_beyond_six_weeks_still_finds_the_regular_visits(dave_client, db, dave):
    """Codex review (high): plans only exist six weeks ahead; time off further away must still
    see (and arrange) every regular visit in it."""
    customer = await make_customer(db)
    _, first = await book(db, customer, dave, frequency="weekly")
    start = first.local_date + timedelta(weeks=9)
    dates = {"from_date": start.isoformat(), "to_date": (start + timedelta(days=6)).isoformat()}
    assert await Visits(db).count({"local_date": {"$gte": dates["from_date"]}}) == 0, "not materialised yet"
    preview = (await dave_client.post("/api/p/time-off/preview", json=dates)).json()
    assert len(preview) == 1 and preview[0]["local_date"] == start.isoformat()
    r = await dave_client.post(
        "/api/p/time-off", json={**dates, "arrangements": [{"visit_id": preview[0]["visit_id"], "action": "skip"}]}
    )
    assert r.status_code == 201, r.text
    assert (await Visits(db).get(preview[0]["visit_id"])).status == "skipped"


async def test_a_visit_booked_into_time_off_later_can_be_arranged(dave_client, db, dave):
    """Codex review: visits that appear in the range after it was arranged show as not arranged,
    the provider is texted once, and they can be arranged the same way."""
    from app.provider import time_off as time_off_mod

    visits, dates = await _week(db, dave)
    every = [{"visit_id": v.id, "action": "skip"} for v in visits]
    off = (await dave_client.post("/api/p/time-off", json={**dates, "arrangements": every})).json()
    assert off["unarranged"] == []
    late_customer = await make_customer(db, "Denise Walsh", "+447700900141")
    _, late = await book(db, late_customer, dave, frequency="oneoff", from_day=visits[0].local_date)
    assert late.local_date > visits[0].local_date + timedelta(days=6), "new first visits avoid time off"
    # A later visit landing in the range (a plan's horizon top-up does this): move it there.
    from datetime import time

    from app.core.timeutil import london_datetime

    day = visits[0].local_date + timedelta(days=2)
    late = await Visits(db).update(
        late.id, {"local_date": day.isoformat(), "scheduled_start": london_datetime(day, time(15, 0))}
    )
    listed = (await dave_client.get("/api/p/time-off")).json()[0]
    assert [u["visit_id"] for u in listed["unarranged"]] == [late.id]
    for _ in range(2):
        await time_off_mod.housekeeping(db, make_settings())
    assert len(await _outbox(db, "time_off_unarranged")) == 1
    r = await dave_client.post(
        f"/api/p/time-off/{off['id']}/arrange", json={"arrangements": [{"visit_id": late.id, "action": "skip"}]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["unarranged"] == [] and len(r.json()["arrangements"]) == len(visits) + 1
    assert (await Visits(db).get(late.id)).status == "skipped"


async def test_cover_for_a_visit_that_isnt_happening_is_closed(dave_client, db, world, app):
    """Codex review (medium, mitigation): a customer skipping a visit that's out for cover; the
    shared accept doesn't check it (contract-changes/L2.md), so L2 closes the request and doesn't
    offer it."""
    mike = await make_provider(db, "Mike Reynolds", MIKE_PHONE, ["mowing"])
    await dave_client.post(f"/api/p/visits/{world.first.id}/cover")
    req = await JobRequests(db).find_one({"cover_for_visit_id": world.first.id})
    await Visits(db).update(world.first.id, {"status": "skipped"})  # the customer skipped it (L1)
    async with client_for(app, db, MIKE_PHONE) as mc:
        assert (await mc.get("/api/p/jobs")).json() == []
        o = (await mc.get(f"/api/p/requests/{req.ref}")).json()
        assert not o["can_take"] and "isn't happening any more" in " ".join(o["not_eligible_reasons"])
    assert await cover_mod.close_dead_covers(db) == 1
    assert (await JobRequests(db).get(req.id)).status == "expired"
    assert mike
