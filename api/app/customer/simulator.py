"""DEMO_MODE only: "Simulate local responses" on the Finding someone local screen.

There are no real providers in the prototype, so this plays two seeded ones: the nearest who
can take the job suggests guide + 20% after a few seconds, and the next accepts the guide
price shortly after. Both act through the real offer endpoints (POST /api/p/requests/{ref}/
counter and /accept) over an in-process HTTP client signed in as that provider, never by
writing to the database, so everything they do is exactly what a real provider's tap does:
the customer can accept the counter first, keep waiting, or lose it to the guide acceptance.
"""

import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, status

from app.core.config import Settings
from app.core.db import Db
from app.core.errors import fail
from app.core.geo import miles_between
from app.core.rounding import D, round_to_pound
from app.customer.schemas import SimulationStarted
from app.models.categories import Category
from app.models.job_requests import JobRequest
from app.models.providers import Provider
from app.repos.providers import Providers
from app.repos.users import Users
from app.services.auth import create_session, end_session
from app.services.eligibility import can_take

COUNTER_AFTER = 4  # seconds after the tap: the nearest provider suggests a price
ACCEPT_AFTER = 15  # seconds after the tap: the next accepts the guide price
COUNTER_RATIO = D("1.2")
COUNTER_REASONS = ["It'll take longer than the estimate"]
COUNTER_MESSAGE = "From the description it'll take a bit longer than the estimate. This covers the extra time."

log = logging.getLogger("oqj.simulator")
_running: dict[str, asyncio.Task] = {}


@dataclass(frozen=True)
class Plan:
    counterer: Provider | None
    accepter: Provider
    counter_pence: int | None


def running(request_id: str) -> bool:
    task = _running.get(request_id)
    return task is not None and not task.done()


def task_for(request_id: str) -> asyncio.Task | None:
    """The running simulation, for tests to await."""
    return _running.get(request_id)


async def candidates(db: Db, req: JobRequest, cat: Category) -> list[Provider]:
    """Seeded providers (Switch user people) who can take the job, nearest first."""
    seeded = {u.id for u in await Users(db).demo_users()}
    out = [
        p
        for p in await Providers(db).with_skill(cat.id)
        if p.user_id in seeded
        and can_take(p, cat).ok
        and (req.direct_provider_id is None or p.id == req.direct_provider_id)
    ]

    def miles(p: Provider) -> float:
        return miles_between(p.home.location.lat, p.home.location.lng, req.address.lat, req.address.lng)

    return sorted(out, key=miles)


def plan_for(req: JobRequest, providers: list[Provider]) -> Plan:
    if not providers:
        fail(status.HTTP_409_CONFLICT, "no_demo_providers", "No seeded provider can take this job to simulate it.")
    if len(providers) == 1 or req.direct_provider_id:
        return Plan(counterer=None, accepter=providers[0], counter_pence=None)
    return Plan(
        counterer=providers[0], accepter=providers[1], counter_pence=round_to_pound(req.guide_pence * COUNTER_RATIO)
    )


@contextlib.asynccontextmanager
async def as_provider(app: FastAPI, db: Db, s: Settings, provider: Provider) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client on the API itself, signed in as the provider with a demo session that ends
    when the step does."""
    user = await Users(db).get(provider.user_id)
    assert user is not None, provider.user_id
    token = await create_session(db, s, user, "demo", "OneQuickJob demo simulator")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://simulator.internal",
            headers={"Cookie": f"{s.cookie_name}={token}"},
        ) as client:
            yield client
    finally:
        await end_session(db, s, token)


async def _run(app: FastAPI, db: Db, s: Settings, ref: str, plan: Plan) -> None:
    waited = 0
    try:
        if plan.counterer is not None:
            await asyncio.sleep(COUNTER_AFTER)
            waited = COUNTER_AFTER
            async with as_provider(app, db, s, plan.counterer) as c:
                r = await c.post(
                    f"/api/p/requests/{ref}/counter",
                    json={"price_pence": plan.counter_pence, "reasons": COUNTER_REASONS, "message": COUNTER_MESSAGE},
                )
                log.info("simulator: %s countered %s: %s", plan.counterer.short, ref, r.status_code)
        await asyncio.sleep(max(0, ACCEPT_AFTER - waited))
        async with as_provider(app, db, s, plan.accepter) as c:
            r = await c.post(f"/api/p/requests/{ref}/accept")
            log.info("simulator: %s accepted %s: %s", plan.accepter.short, ref, r.status_code)
    except Exception:
        log.exception("simulator failed for %s", ref)


async def start(app: FastAPI, db: Db, s: Settings, req: JobRequest, cat: Category) -> SimulationStarted:
    if req.status != "open":
        fail(status.HTTP_409_CONFLICT, "not_open", "This request isn't open any more.")
    if running(req.id):
        fail(status.HTTP_409_CONFLICT, "already_simulating", "Local responses are already on their way.")
    plan = plan_for(req, await candidates(db, req, cat))
    task = asyncio.create_task(_run(app, db, s, req.ref, plan), name=f"simulate-{req.ref}")
    _running[req.id] = task
    task.add_done_callback(lambda t: _running.pop(req.id, None) if _running.get(req.id) is t else None)
    first = plan.counterer or plan.accepter
    return SimulationStarted(
        provider_short=first.short,
        counter_in_seconds=math.ceil(COUNTER_AFTER) if plan.counterer else 0,
        accept_in_seconds=math.ceil(ACCEPT_AFTER),
    )
