"""Pricing versions: one admin drafts, a different admin approves; the old live version is
retired; quotes keep the version they used. Calibration suggestions from recorded visits."""

import pytest

from app.repos import PricingVersions, Quotes
from app.seed.run import seed
from tests.admin.conftest import ok
from tests.conftest import make_settings, sign_in

OVERGROWN = {"category_id": "mowing", "path": "growth.overgrown", "after": 2.4}


async def quote(client, grass: str = "overgrown") -> dict:
    r = await client.post(
        "/api/quotes", json={"category_id": "mowing", "answers": {"grassState": grass}, "lawn": {"band": "large"}}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_draft_then_a_different_admin_approves(jo, sam, db, catalogue):
    v1 = await PricingVersions(db).live()
    assert v1 and v1.version == 1
    before = await quote(jo)
    drafted = ok(
        await jo.post(
            "/api/admin/pricing/versions",
            json={"based_on": v1.id, "changes": [OVERGROWN], "notes": "First cuts run long"},
        ),
        201,
    )
    assert (drafted["version"], drafted["status"], drafted["created_by_name"]) == (2, "draft", "Jo Morgan")
    assert drafted["changes"] == [{**OVERGROWN, "before": 1.9}] and drafted["can_approve"] is False
    # The draft changes nothing yet. (Overgrown grass makes the first cut dearer.)
    assert (await quote(jo))["result"]["first_pence"] == before["result"]["first_pence"]

    r = await jo.post(f"/api/admin/pricing/versions/{drafted['id']}/approve")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "same_admin"
    listed = ok(await sam.get("/api/admin/pricing/versions"))
    assert [(v["version"], v["status"], v["can_approve"]) for v in listed] == [(2, "draft", True), (1, "live", False)]

    live = ok(await sam.post(f"/api/admin/pricing/versions/{drafted['id']}/approve"))
    assert (live["status"], live["approved_by_name"], live["created_by_name"]) == ("live", "Sam Patel", "Jo Morgan")
    retired = await PricingVersions(db).get(v1.id)
    assert retired and retired.status == "retired" and retired.retired_at
    after = await quote(jo)
    assert after["pricing_version"] == 2 and after["result"]["first_pence"] > before["result"]["first_pence"]
    kept = await Quotes(db).get(before["id"])
    assert kept and kept.pricing_version == 1  # a quote keeps the version it used
    actions = [a["action"] async for a in db["audit_log"].find().sort("at", 1)]
    assert actions == ["pricing.drafted", "pricing.approved"]
    r = await sam.post(f"/api/admin/pricing/versions/{drafted['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_draft"


async def test_a_draft_from_a_retired_version_must_be_redone(jo, sam, db, catalogue):
    v1 = await PricingVersions(db).live()
    assert v1
    a = ok(await jo.post("/api/admin/pricing/versions", json={"based_on": v1.id, "changes": [OVERGROWN]}), 201)
    b = ok(
        await jo.post(
            "/api/admin/pricing/versions",
            json={"based_on": v1.id, "changes": [{"category_id": "hedges", "path": "per_m_mins.above", "after": 6.5}]},
        ),
        201,
    )
    ok(await sam.post(f"/api/admin/pricing/versions/{a['id']}/approve"))
    r = await sam.post(f"/api/admin/pricing/versions/{b['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_draft"
    assert (await PricingVersions(db).live()).version == 2  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"category_id": "nope", "path": "x", "after": 1}, "has no prices for nope"),
        ({"category_id": "mowing", "path": "growth.missing", "after": 1}, "has no setting growth.missing"),
        ({"category_id": "mowing", "path": "growth", "after": 1}, "is a group of settings"),
        ({"category_id": "mowing", "path": "growth.overgrown", "after": -1}, "must be a number of at least 0"),
        ({"category_id": "mowing", "path": "growth.overgrown", "after": "2"}, "must be a number"),
        ({"category_id": "mowing", "path": "hourly_pence", "after": 4550.5}, "money in whole pence"),
        ({"category_id": "mowing", "path": "growth.overgrown", "after": 1.9}, "is already 1.9"),
        ({"category_id": "clearance", "path": "base_pence.boot", "after": 0}, "would cost nothing"),
    ],
)
async def test_bad_changes_are_refused(jo, db, catalogue, change, why):
    v1 = await PricingVersions(db).live()
    r = await jo.post("/api/admin/pricing/versions", json={"based_on": v1.id, "changes": [change]})  # type: ignore[union-attr]
    assert r.status_code == 422 and why in r.json()["detail"]["message"], r.text
    assert await PricingVersions(db).count({}) == 1


async def test_calibration_on_the_seeded_history(client, db):
    await seed(db, make_settings())
    await sign_in(client, db, "07700 900901")  # Jo, the seeded admin
    jo = client
    d = ok(await jo.get("/api/admin/pricing/calibration"))
    assert d["live_version"] == 1 and len(d["points"]) > 70
    segs = {r["segment"]: r for r in d["table"]}
    assert {"mowing", "first", "hedges", "clearance"} <= set(segs)
    assert segs["first"]["jobs"] == 12 and segs["first"]["median_overrun"] > 0.2
    assert segs["clearance"]["countered"] > 0.5 and segs["clearance"]["median_counter_uplift_pence"] == 3500
    by_id = {s["id"]: s for s in d["suggestions"]}
    first = by_id["first:time:growth.overgrown"]
    assert first["title"] == "First cuts take much longer than we estimate"
    assert first["change"]["before"] == 1.9 and first["change"]["after"] > 1.9
    assert "clearance:price:base_pence.boot" in by_id
    assert all(s["change"]["after"] != s["change"]["before"] for s in d["suggestions"])
    # "Draft this change" is a normal draft of the live version.
    live = await PricingVersions(db).live()
    change = {k: first["change"][k] for k in ("category_id", "path", "after")}
    ok(await jo.post("/api/admin/pricing/versions", json={"based_on": live.id, "changes": [change]}), 201)  # type: ignore[union-attr]
