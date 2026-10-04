"""A19: a provider signing up becomes active, and is texted, the moment the last required check is
done: ID, insurance, tax details, a payout account the gateway has enabled, and a basic DBS check if
a chosen job needs one. Audit-logged; admins can still suspend."""

from datetime import date

from app.core.timeutil import london_today
from app.models.providers import PaymentAccount, ProviderDocument, TaxDetails
from app.repos import Providers
from app.services import lifecycle
from tests.admin.conftest import jo, ok, verdict  # noqa: F401 (the signed-in admin client)
from tests.conftest import sign_in
from tests.factories import make_provider

ENABLED = PaymentAccount(gateway="fake", account_id="acct_fake_ken", status="enabled", payouts_enabled=True)
LATER = date(2030, 1, 1)


async def _ken(db, skills: list[str], *, tax: bool = True, account: bool = True, docs: tuple[str, ...] = ()):
    """Ken, signing up: identity uploaded and waiting for a check, plus whatever else is given."""
    ken = await make_provider(db, "Ken Ashworth", "+447700900212", skills, docs=[], status="signing_up")
    held = [ProviderDocument(type="identity", status="pending", file_id="f-id")] + [
        ProviderDocument(type=t, status="verified", expires_on=LATER)
        for t in docs  # type: ignore[arg-type]
    ]
    fields: dict = {"documents": [d.model_dump(mode="python") for d in held]}
    if tax:
        fields["tax"] = TaxDetails(complete=True, ni_masked="QQ •• •• •• C").model_dump(mode="python")
    if account:
        fields["payment_account"] = ENABLED.model_dump(mode="python")
    return await Providers(db).patch(ken.id, fields)


async def test_verifying_the_last_check_activates_texts_and_audits(jo, db, catalogue):  # noqa: F811
    ken = await _ken(db, ["mowing"], docs=("insurance",))
    assert await lifecycle.missing_checks(db, ken) == ["identity"]
    d = ok(await verdict(jo, f"/api/admin/providers/{ken.id}/documents/identity/verify", {}))
    assert d["status"] == "active"
    msgs = await db["outbox"].find({"template_id": "provider_activated"}).to_list()
    assert len(msgs) == 1 and msgs[0]["recipient"]["phone"] == "+447700900212"
    assert "you're all set, Ken. Your checks are done, so jobs near you will start coming through." in msgs[0]["body"]
    [entry] = await db["audit_log"].find({"action": "provider.activated"}).to_list()
    assert entry["target"]["provider_id"] == ken.id and entry["after"] == {"status": "active"}
    assert entry["actor"]["role"] == "admin"
    # Admins can still suspend.
    ok(await jo.post(f"/api/admin/providers/{ken.id}/suspend", json={"reason": "Checking a complaint"}))
    assert (await Providers(db).get(ken.id)).status == "suspended"


async def test_a_job_that_needs_dbs_waits_for_the_dbs_check(jo, db, catalogue):  # noqa: F811
    ken = await _ken(db, ["mowing", "cleaning"], docs=("insurance",))
    ok(await verdict(jo, f"/api/admin/providers/{ken.id}/documents/identity/verify", {}))
    ken = await Providers(db).get(ken.id)
    assert ken.status == "signing_up" and await lifecycle.missing_checks(db, ken) == ["dbs_basic"]
    d = ok(await jo.get(f"/api/admin/providers/{ken.id}"))
    assert "Becomes active automatically once these are done: basic DBS check" in d["issues"]
    issued = london_today().replace(day=1)
    await Providers(db).set_document(ken.id, ProviderDocument(type="dbs_basic", status="pending", file_id="f-dbs"))
    d = ok(
        await verdict(
            jo, f"/api/admin/providers/{ken.id}/documents/dbs_basic/verify", {"issued_on": issued.isoformat()}
        )
    )
    assert d["status"] == "active"


async def test_nothing_happens_while_a_check_is_left(jo, db, catalogue):  # noqa: F811
    ken = await _ken(db, ["mowing"], tax=False, docs=("insurance",))
    ok(await verdict(jo, f"/api/admin/providers/{ken.id}/documents/identity/verify", {}))
    assert (await Providers(db).get(ken.id)).status == "signing_up"
    assert await db["outbox"].count_documents({"template_id": "provider_activated"}) == 0


async def test_tax_details_or_a_payout_account_can_be_the_last_check(app, db, catalogue):
    """The provider's own steps in the sign-up flow (L2) activate them too."""
    from tests.conftest import new_client

    verified = ("identity", "insurance")
    ken = await _ken(db, ["mowing"], tax=False, docs=verified)
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900212", "Ken Ashworth")
        r = await c.put("/api/p/signup/tax", json={"ni_number": "QQ123456C", "date_of_birth": "1958-03-14"})
        assert r.status_code == 200, r.text
    assert (await Providers(db).get(ken.id)).status == "active"
    [entry] = await db["audit_log"].find({"action": "provider.activated"}).to_list()
    assert entry["actor"]["role"] == "provider"

    await db["providers"].delete_many({})
    await db["users"].delete_many({"phone": "+447700900212"})
    ken = await _ken(db, ["mowing"], account=False, docs=verified)
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900212", "Ken Ashworth")
        assert (await c.post("/api/p/signup/payment-account")).status_code == 200  # the fake: onboarding is instant
        assert (await Providers(db).get(ken.id)).status == "signing_up", "the account isn't enabled on record yet"
        checklist = (await c.get("/api/p/signup")).json()  # back from onboarding: synced
    assert checklist["status"] == "active" and checklist["payment_account_status"] == "enabled"
    assert await db["outbox"].count_documents({"template_id": "provider_activated"}) == 2


async def test_dropping_the_only_job_that_needed_dbs_can_complete_sign_up(app, db, catalogue):
    from tests.conftest import new_client

    ken = await _ken(db, ["mowing", "cleaning"], docs=("identity", "insurance"))
    assert await lifecycle.missing_checks(db, ken) == ["dbs_basic"]
    async with await new_client(app) as c:
        await sign_in(c, db, "07700 900212", "Ken Ashworth")
        r = await c.patch("/api/p/profile", json={"skills": ["mowing"]})
        assert r.status_code == 200, r.text
    assert (await Providers(db).get(ken.id)).status == "active"


async def test_only_a_provider_signing_up_is_activated(jo, db, catalogue):  # noqa: F811
    """A suspended provider stays suspended, however complete their checks."""
    ken = await _ken(db, ["mowing"], docs=("insurance",))
    await Providers(db).set_status(ken.id, "suspended", "Checking a complaint")
    ok(await verdict(jo, f"/api/admin/providers/{ken.id}/documents/identity/verify", {}))
    assert (await Providers(db).get(ken.id)).status == "suspended"
    assert await db["outbox"].count_documents({"template_id": "provider_activated"}) == 0
