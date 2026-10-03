"""Documents: uploads wait for checks; expiry comes from the shared rule (decisions.md A3: a
basic DBS check runs 12 months from its issue date); a renewal doesn't stop the provider working."""

from datetime import timedelta

from app.core.timeutil import add_months, london_today
from app.repos import Providers
from app.services.eligibility import can_take
from tests.admin.conftest import jo  # noqa: F401 (the signed-in admin client)
from tests.provider.conftest import TOM_PHONE, add_tom, client_for


async def _upload(client, kind: str = "document") -> str:
    r = await client.post(
        "/api/files", data={"kind": kind}, files={"file": ("doc.pdf", b"%PDF-1.4 test", "application/pdf")}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_a_dbs_upload_takes_its_expiry_from_the_issue_date(dave_client, db, dave):
    issued = london_today() - timedelta(days=20)
    file_id = await _upload(dave_client)
    r = await dave_client.post(
        "/api/p/documents", json={"type": "dbs_basic", "file_id": file_id, "issued_on": issued.isoformat()}
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["needs_issue_date"] and not doc["needs_expiry_date"]
    # Dave's current check is verified and in date, so the upload waits beside it as a renewal.
    assert doc["status"] == "verified" and doc["renewal"]["status"] == "pending"
    assert doc["renewal"]["expires_on"] == add_months(issued, 12).isoformat()
    assert doc["renewal"]["issued_on"] == issued.isoformat()


async def test_without_a_current_copy_the_upload_is_pending(dave_client, db, dave, catalogue):
    docs = [d for d in dave.documents if d.type != "dbs_basic"]
    await Providers(db).patch(dave.id, {"documents": [d.model_dump(mode="python") for d in docs]})
    issued = london_today() - timedelta(days=3)
    r = await dave_client.post(
        "/api/p/documents",
        json={"type": "dbs_basic", "file_id": await _upload(dave_client), "issued_on": issued.isoformat()},
    )
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["renewal"] is None
    assert r.json()["expires_on"] == add_months(issued, 12).isoformat()
    p = await Providers(db).get(dave.id)
    assert not can_take(p, catalogue["cleaning"]).ok, "pending isn't checked yet"


async def test_a_renewal_keeps_the_provider_eligible_while_it_is_checked(dave_client, db, dave, catalogue):
    soon = london_today() + timedelta(days=10)
    docs = [d.model_copy(update={"expires_on": soon}) if d.type == "dbs_basic" else d for d in dave.documents]
    await Providers(db).patch(dave.id, {"documents": [d.model_dump(mode="python") for d in docs]})
    listed = {d["type"]: d for d in (await dave_client.get("/api/p/documents")).json()}
    assert listed["dbs_basic"]["expiring_soon"] and listed["dbs_basic"]["days_left"] == 10
    await dave_client.post(
        "/api/p/documents",
        json={"type": "dbs_basic", "file_id": await _upload(dave_client), "issued_on": london_today().isoformat()},
    )
    p = await Providers(db).get(dave.id)
    assert sorted(d.status for d in p.documents if d.type == "dbs_basic") == ["pending", "verified"]
    assert can_take(p, catalogue["cleaning"]).ok


async def test_an_admin_checking_a_renewal_checks_the_upload_not_the_old_copy(dave_client, db, dave, jo):  # noqa: F811
    """L3's verify takes the first document of a type: the renewal, so its file and dates are
    the ones checked, and it replaces the old copy."""
    old = next(d for d in dave.documents if d.type == "insurance")
    until = london_today() + timedelta(days=400)
    fid = await _upload(dave_client)
    r = await dave_client.post(
        "/api/p/documents", json={"type": "insurance", "file_id": fid, "expires_on": until.isoformat()}
    )
    assert r.status_code == 201 and r.json()["renewal"]["status"] == "pending"
    detail = (await jo.get(f"/api/admin/providers/{dave.id}")).json()
    shown = next(d for d in detail["documents"] if d["type"] == "insurance")
    assert shown["status"] == "pending" and shown["expires_on"] == until.isoformat(), "the admin sees the upload"
    v = await jo.post(f"/api/admin/providers/{dave.id}/documents/insurance/verify", json={})
    assert v.status_code == 200, v.text
    [doc] = [d for d in (await Providers(db).get(dave.id)).documents if d.type == "insurance"]
    assert (doc.status, doc.file_id, doc.expires_on) == ("verified", fid, until) and doc.file_id != old.file_id


async def test_dates_are_checked_and_insurance_needs_its_expiry(dave_client, db, dave):
    fid = await _upload(dave_client)
    for body, code in [
        ({"type": "dbs_basic", "file_id": fid}, "date_needed"),
        ({"type": "insurance", "file_id": fid}, "date_needed"),
        (
            {"type": "insurance", "file_id": fid, "expires_on": (london_today() - timedelta(days=1)).isoformat()},
            "already_expired",
        ),
        (
            {"type": "dbs_basic", "file_id": fid, "issued_on": (london_today() + timedelta(days=1)).isoformat()},
            "issued_in_future",
        ),
    ]:
        r = await dave_client.post("/api/p/documents", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, body
    ok = await dave_client.post(
        "/api/p/documents",
        json={"type": "insurance", "file_id": fid, "expires_on": (london_today() + timedelta(days=300)).isoformat()},
    )
    assert ok.status_code == 201


async def test_only_your_own_upload_can_be_a_document(app, dave_client, db, dave):
    async with client_for(app, db, "+447700900997") as other:
        fid = await _upload(other)
    r = await dave_client.post("/api/p/documents", json={"type": "identity", "file_id": fid})
    assert r.status_code == 404
    photo = await _upload(dave_client, "visit_after")
    r = await dave_client.post("/api/p/documents", json={"type": "identity", "file_id": photo})
    assert r.status_code == 422


async def test_a_helpers_documents_are_their_own(app, db, dave):
    await add_tom(db, dave, status="invited")
    async with client_for(app, db, TOM_PHONE) as tc:
        fid = await _upload(tc)
        r = await tc.post("/api/p/documents", json={"type": "identity", "file_id": fid})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "pending"
        mine = {d["type"]: d["status"] for d in (await tc.get("/api/p/documents")).json()}
        assert mine["identity"] == "pending" and mine["insurance"] == "missing"
    p = await Providers(db).get(dave.id)
    tom = p.helpers[0]
    assert tom.status == "checking" and [d.type for d in tom.documents] == ["identity"]
    assert next(d for d in p.documents if d.type == "identity").status == "verified", "Dave's own are untouched"


async def test_profile_shows_missing_documents_for_new_skills(dave_client, db, dave):
    r = await dave_client.patch("/api/p/profile", json={"skills": ["mowing", "dogwalking"]})
    assert r.status_code == 200, r.text
    assert r.json()["missing_for_skills"] == []  # the test factory gives Dave every document
    docs = [d for d in dave.documents if d.type != "pet_cover"]
    await Providers(db).patch(dave.id, {"documents": [d.model_dump(mode="python") for d in docs]})
    prof = (await dave_client.get("/api/p/profile")).json()
    assert prof["missing_for_skills"] == ["pet_cover"]
    pet = next(d for d in prof["documents"] if d["type"] == "pet_cover")
    assert pet["status"] == "missing" and pet["required_for"] == ["Dog walking"]
    bad = await dave_client.patch("/api/p/profile", json={"skills": ["gas_boilers"]})
    assert bad.status_code == 422
    quiet = await dave_client.patch(
        "/api/p/profile",
        json={
            "alert_settings": {
                "sms": True,
                "whatsapp": True,
                "quiet_hours": True,
                "quiet_from": "25:00",
                "quiet_to": "08:00",
            }
        },
    )
    assert quiet.status_code == 422


async def test_adding_a_helper_texts_them_a_sign_up_link(dave_client, db, dave):
    r = await dave_client.post(
        "/api/p/helpers", json={"name": "Tom Hughes", "phone": "07700 900220", "relationship": "Son"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "invited" and r.json()["badges"] == []
    msg = await db["outbox"].find_one({"template_id": "helper_invite"})
    assert msg and "/p/me?t=" in msg["body"]
    taken = await dave_client.post("/api/p/helpers", json={"name": "Someone", "phone": "07700 900220"})
    assert taken.status_code == 409


async def test_a_new_provider_is_asked_for_insurance_before_choosing_jobs(client, db, catalogue):
    from tests.conftest import sign_in

    await sign_in(client, db, "07700 900212")
    await client.post("/api/p/signup/start", json={"name": "Ken Ashworth", "postcode": "HP15 7QT"})
    docs = {d["type"]: d for d in (await client.get("/api/p/documents")).json()}
    assert set(docs) == {"identity", "insurance"}, "every job needs insurance, so it's asked for straight away"
    assert docs["insurance"]["status"] == "missing" and docs["insurance"]["needs_expiry_date"]
