"""The shared endpoints implemented in foundations."""

import httpx
import pytest

from app.adapters.address.ideal_postcodes import IdealPostcodesLookup
from app.main import create_app
from app.repos import Quotes, Users
from tests.conftest import make_settings, sign_in
from tests.factories import make_user


async def test_health_and_config(client):
    h = (await client.get("/api/health")).json()
    assert h["status"] == "ok" and h["db"] == "ok"
    cfg = (await client.get("/api/config")).json()
    assert cfg["demo_mode"] is True and cfg["brand"] == "OneQuickJob"
    assert cfg["fees"] == {"standard_percent": 15, "own_customer_percent": 5, "own_customer_min_pence": 100}
    assert cfg["payments"]["gateway"] == "fake" and cfg["address_lookup"] == "fake"


async def test_categories(client, catalogue):
    data = (await client.get("/api/categories")).json()
    assert len(data["categories"]) == 15 and all(c["status"] == "live" for c in data["categories"])
    assert [g["id"] for g in data["groups"]] == ["outside", "inside", "help"]
    assert len(data["excluded"]) == 10 and data["excluded"][0]["name"] == "Gas and boilers"
    mowing = (await client.get("/api/categories/mowing")).json()
    assert mowing["measure"] == "lawn" and mowing["pricing_model"] == "lawn_area_v1"
    assert [f["key"] for f in mowing["intake"]] == ["grassState", "waste", "access", "frequency"]
    assert (await client.get("/api/categories/boilers")).status_code == 404


async def test_area_options_are_the_manual_bands(client):
    opts = (await client.get("/api/area/options")).json()
    assert opts["estimator"] == "manual_bands_v0"
    assert [(b["id"], b["area_m2"]) for b in opts["bands"]] == [
        ("small", 40),
        ("medium", 85),
        ("large", 190),
        ("very_large", 350),
    ]
    assert opts["bands"][0]["comparison"] == "About a double garage"
    assert [a["label"] for a in opts["adjustments"]] == ["Looks smaller", "About right", "Looks bigger"]


async def test_quote_mowing_large_band(client, db, catalogue):
    r = await client.post("/api/quotes", json={"category_id": "mowing", "answers": {}, "lawn": {"band": "large"}})
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["result"]["price_pence"] == 3100 and q["result"]["unit"] == "a visit"
    assert q["measure"] == {
        "estimator": "manual_bands_v0",
        "area_m2": 190,
        "band": "large",
        "adjust": "right",
        "detail": None,
    }
    assert q["fee"] == {
        "mode": "standard",
        "rate_percent": 15,
        "price_pence": 3100,
        "fee_pence": 465,
        "provider_pence": 2635,
    }
    assert q["confidence"]["label"] == "Usually close" and q["confidence"]["bars"] == 3
    assert q["pricing_version"] == 1
    assert q["duration_text"] == "39 minutes"
    stored = await Quotes(db).get(q["id"])
    assert stored.pricing_version_id == q["pricing_version_id"], "every quote records its version"


async def test_quote_adjustments_and_first_visit(client, catalogue):
    r = await client.post(
        "/api/quotes",
        json={
            "category_id": "mowing",
            "answers": {"grassState": "overgrown"},
            "lawn": {"band": "large", "adjust": "bigger"},
        },
    )
    q = r.json()
    assert q["measure"]["area_m2"] == 228
    assert q["result"]["first_pence"] > q["result"]["price_pence"]
    assert q["result"]["first_reason"] == "The grass needs extra time to get back under control."
    assert q["first_fee"]["fee_pence"] == round(q["result"]["first_pence"] * 15 / 100)


@pytest.mark.parametrize(
    ("category", "price", "first"),
    [("windows", 2200, 3300), ("cleaning", 6600, 8800), ("deepclean", 20400, None), ("techhelp", 2500, None)],
)
async def test_quote_golden_over_http(client, catalogue, category, price, first):
    q = (await client.post("/api/quotes", json={"category_id": category})).json()
    assert (q["result"]["price_pence"], q["result"]["first_pence"]) == (price, first)


async def test_quote_errors(client, catalogue):
    r = await client.post("/api/quotes", json={"category_id": "mowing"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "lawn_size_needed"
    r = await client.post("/api/quotes", json={"category_id": "hedges", "answers": {"height": "giant"}})
    assert r.json()["detail"]["code"] == "invalid_answer" and r.json()["detail"]["extra"]["key"] == "height"
    r = await client.post("/api/quotes", json={"category_id": "hedges", "answers": {"colour": "green"}})
    assert r.status_code == 422
    r = await client.post(
        "/api/quotes", json={"category_id": "flatpack", "answers": {"items": {"small": 0, "medium": 0, "large": 0}}}
    )
    assert r.json()["detail"]["code"] == "nothing_to_price"
    r = await client.post("/api/quotes", json={"category_id": "hedges", "answers": {"length": 3.5}})
    assert r.status_code == 422
    assert (await client.post("/api/quotes", json={"category_id": "boilers"})).status_code == 404


async def test_planned_categories_are_never_bookable(client, db, catalogue):
    await db["categories"].update_one({"_id": "oven"}, {"$set": {"status": "planned"}})
    r = await client.post("/api/quotes", json={"category_id": "oven"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_bookable"
    assert "oven" not in [c["id"] for c in (await client.get("/api/categories")).json()["categories"]]


async def test_quote_without_a_live_pricing_version(client, db, catalogue):
    await db["pricing_versions"].delete_many({})
    r = await client.post("/api/quotes", json={"category_id": "hedges"})
    assert r.status_code == 503


async def test_fake_address_lookup(client):
    hits = (await client.get("/api/address/search", params={"q": "orchard hazlemere"})).json()
    assert hits == [{"id": "fake_01", "label": "12 Orchard Way, Hazlemere, HP15 7QT"}]
    addr = (await client.get("/api/address/fake_01")).json()
    assert addr["uprn"] and addr["district"] == "HP15" and addr["locality"] == "Hazlemere"
    assert (await client.get("/api/address/nope")).status_code == 404
    assert (await client.get("/api/address/search", params={"q": "x"})).status_code == 422


async def test_ideal_postcodes_adapter_spends_a_credit_only_on_resolve_and_caches(db):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.params["api_key"] == "ak_test"
        if request.url.path == "/v1/autocomplete/addresses":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "hits": [
                            {"id": "paf_1", "suggestion": "12 Orchard Way, Hazlemere, High Wycombe, HP15", "udprn": 1}
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "result": {
                    "line_1": "12 Orchard Way",
                    "line_2": "",
                    "line_3": "",
                    "dependant_locality": "Hazlemere",
                    "post_town": "High Wycombe",
                    "postcode": "HP15 7QT",
                    "uprn": "100081234567",
                    "latitude": 51.6541,
                    "longitude": -0.7139,
                }
            },
        )

    lookup = IdealPostcodesLookup("ak_test", "https://api.ideal-postcodes.co.uk", db, httpx.MockTransport(handler))
    hits = await lookup.search("12 orchard")
    assert hits[0].id == "paf_1"
    a1 = await lookup.resolve("paf_1")
    a2 = await lookup.resolve("paf_1")
    assert a1 == a2 and a1.uprn == "100081234567" and a1.area == "Hazlemere" and a1.district == "HP15"
    assert calls == ["/v1/autocomplete/addresses", "/v1/autocomplete/addresses/paf_1/gbr"], "resolved once"


async def test_admin_outbox_requires_admin_and_searches(client, db):
    await client.post("/api/auth/code", json={"identifier": "07700 900111"})
    await client.post("/api/auth/code", json={"identifier": "pat@example.com"})
    assert (await client.get("/api/admin/outbox")).status_code == 401
    await sign_in(client, db, "07700 900999")
    assert (await client.get("/api/admin/outbox")).status_code == 403
    await Users(db).add_role((await Users(db).by_phone("+447700900999")).id, "admin")
    page = (await client.get("/api/admin/outbox")).json()
    assert len(page["items"]) == 3 and page["next_before"] is None
    only_email = (await client.get("/api/admin/outbox", params={"channel": "email"})).json()["items"]
    assert [m["recipient"]["email"] for m in only_email] == ["pat@example.com"]
    found = (await client.get("/api/admin/outbox", params={"q": "+447700900111"})).json()["items"]
    assert len(found) == 1
    p1 = (await client.get("/api/admin/outbox", params={"limit": 2})).json()
    p2 = (await client.get("/api/admin/outbox", params={"limit": 2, "before": p1["next_before"]})).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1


async def test_demo_endpoints(client, db):
    sarah = await make_user(db, "Sarah Whitfield", "+447700900123", ["customer"])
    await db["users"].update_one({"_id": sarah.id}, {"$set": {"demo_key": "sarah"}})
    other = await make_user(db, "Not Seeded", "+447700900124", ["customer"])
    users = (await client.get("/api/demo/users")).json()
    assert [u["demo_key"] for u in users] == ["sarah"] and users[0]["home_path"] == "/account"
    r = await client.post("/api/demo/switch", json={"user_id": sarah.id})
    assert r.status_code == 200 and (await client.get("/api/auth/me")).json()["name"] == "Sarah Whitfield"
    assert (await client.post("/api/demo/switch", json={"user_id": other.id})).status_code == 404
    await client.post("/api/auth/code", json={"identifier": "07700 900123"})
    drawer = (await client.get("/api/demo/outbox")).json()
    assert drawer[0]["template_id"] == "login_code" and "sign-in code" in drawer[0]["body"]


async def test_demo_endpoints_vanish_when_demo_mode_is_off(db):
    app = create_app(make_settings(demo_mode=False))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as c,
    ):
        assert (await c.get("/api/config")).json()["demo_mode"] is False
        assert (await c.get("/api/demo/users")).status_code == 404
        assert (await c.get("/api/demo/outbox")).status_code == 404
        assert (await c.post("/api/demo/switch", json={"user_id": "x"})).status_code == 404


async def test_file_upload(client, db, tmp_path, app):
    files = {"file": ("after.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")}
    assert (await client.post("/api/files", files=files, data={"kind": "visit_after"})).status_code == 401
    await sign_in(client, db, "07700 900456")
    r = await client.post("/api/files", files=files, data={"kind": "visit_after"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["url"].startswith("/files/visit_after/") and out["url"].endswith(".jpg") and out["size"] == 12
    assert await db["files"].count_documents({}) == 1
    bad = await client.post(
        "/api/files", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, data={"kind": "other"}
    )
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "file_rejected"
