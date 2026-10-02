"""Build domain records directly through the repos for tests (L1's create-request endpoint
is a stub in foundations)."""

from datetime import date

from app.core.ids import next_ref
from app.core.timeutil import utcnow
from app.models.common import Address, GeoPoint
from app.models.customers import Customer, CustomerPayment, SavedCard
from app.models.job_requests import Broadcast, JobRequest, RequestEvent, When
from app.models.providers import Home, Provider, ProviderDocument
from app.models.users import User
from app.repos import Customers, JobRequests, Providers, Users
from app.services.quotes import create_quote
from tests.conftest import make_settings

HAZLEMERE = Address(
    line1="12 Orchard Way",
    locality="Hazlemere",
    town="High Wycombe",
    postcode="HP15 7QT",
    district="HP15",
    uprn="999000000001",
    lat=51.6541,
    lng=-0.7139,
    label="12 Orchard Way, Hazlemere, HP15 7QT",
)


async def make_user(db, name: str, phone: str, roles: list[str]) -> User:
    user = User(name=name, phone=phone, roles=roles)  # type: ignore[arg-type]
    await Users(db).insert(user)
    return user


async def make_provider(
    db,
    name: str,
    phone: str,
    skills: list[str],
    docs: list[str] | None = None,
    status: str = "active",
    days: list[str] | None = None,
) -> Provider:
    user = await make_user(db, name, phone, ["provider"])
    first, last = name.split(" ", 1)
    held = [
        "identity",
        *(docs if docs is not None else ["insurance", "waste_carrier", "ladder_cover", "dbs_basic", "pet_cover"]),
    ]
    p = Provider(
        user_id=user.id,
        name=name,
        short=f"{first} {last[0]}.",
        initials=first[0] + last[0],
        home=Home(postcode="HP15 7AB", district="HP15", area="Hazlemere", location=GeoPoint(lat=51.656, lng=-0.716)),
        travel_radius_miles=4,
        working_days=days or ["mon", "tue", "wed", "thu", "fri", "sat"],
        skills=skills,
        documents=[ProviderDocument(type=t, status="verified", expires_on=date(2030, 1, 1)) for t in held],  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
    )
    await Providers(db).insert(p)
    return p


async def make_customer(db, name: str = "Sarah Whitfield", phone: str = "+447700900123") -> Customer:
    user = await make_user(db, name, phone, ["customer"])
    c = Customer(
        user_id=user.id,
        name=name,
        addresses=[HAZLEMERE],
        joined_via="platform",
        payment=CustomerPayment(
            gateway="fake",
            gateway_customer_id="cus_fake_test",
            setup_status="succeeded",
            card=SavedCard(brand="visa", last4="4242", exp_month=12, exp_year=2028),
        ),
    )
    await Customers(db).insert(c)
    return c


async def make_request(
    db, customer: Customer, category_id: str = "mowing", answers: dict | None = None, lawn: dict | None = None
) -> JobRequest:
    from app.adapters.area.base import AreaInput

    s = make_settings()
    q = await create_quote(
        db,
        s,
        category_id=category_id,
        answers=answers or {},
        lawn=AreaInput(**(lawn or {"band": "large"})) if category_id == "mowing" else None,
        address=HAZLEMERE,
        user_id=customer.user_id,
    )
    now = utcnow()
    req = JobRequest(
        ref=await next_ref(db, "request"),
        customer_id=customer.id,
        category_id=category_id,
        quote_id=q.id,
        pricing_version_id=q.pricing_version_id,
        answers=q.answers,
        measure=q.measure,
        address=HAZLEMERE,
        approx=GeoPoint(lat=51.65, lng=-0.71),
        when=When(days="weekdays", time="morning"),
        recurring=q.answers.get("frequency", "oneoff") != "oneoff" and "frequency" in q.answers,
        frequency=q.answers.get("frequency"),
        guide_pence=q.result.price_pence,
        first_pence=q.result.first_pence,
        mins=q.result.mins,
        first_mins=q.result.first_mins,
        unit=q.result.unit,
        broadcast=Broadcast(at=now, provider_ids=[]),
        events=[RequestEvent(at=now, kind="created")],
    )
    await JobRequests(db).insert(req)
    return req
