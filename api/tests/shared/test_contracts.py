"""Contracts the lanes build on: every endpoint is typed, every lane endpoint is a 501
stub until its lane implements it, and lanes have their own routers."""

import inspect

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.core.routes import api_routes
from app.main import create_app
from tests.conftest import make_settings

APP = create_app(make_settings())
ROUTES = list(api_routes(APP))
FILE_RESPONSES = {"/api/p/tax/pack.csv", "/api/p/tax/pack.html", "/api/admin/hmrc-export.csv"}
NO_CONTENT = {"/api/auth/logout", "/api/p/expenses/{expense_id}", "/api/p/time-off/{time_off_id}"}
IMPLEMENTED_IN_F = {
    "/api/p/requests/{ref}/accept",
    "/api/p/requests/{ref}/counter",
    "/api/c/offers/{offer_id}/accept",
    "/api/c/offers/{offer_id}/decline",
    "/api/admin/outbox",
}
LANE_PREFIX = {"/api/c/": "L1", "/api/p/": "L2", "/api/admin/": "L3", "/api/payments/": "L3"}


def lane_of(path: str) -> str | None:
    return next((lane for prefix, lane in LANE_PREFIX.items() if path.startswith(prefix)), None)


def test_route_count_is_plausible():
    assert len(ROUTES) > 100


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_every_endpoint_has_typed_models(route: APIRoute):
    if route.path in FILE_RESPONSES:
        assert route.responses[200]["content"], "file responses declare their media type"
    elif route.path in NO_CONTENT:
        assert route.status_code == 204
    else:
        assert route.response_model is not None, f"{route.path} needs a response model"
    if route.body_field is not None and route.path != "/api/files":
        body = route.body_field.field_info.annotation
        assert isinstance(body, type) and issubclass(body, BaseModel), f"{route.path} body must be a Pydantic model"
        extra = body.model_config.get("extra")
        assert extra == "forbid", f"{route.path}: request bodies reject unknown fields"


LANE_ROUTES = [r for r in ROUTES if lane_of(r.path) and r.path not in IMPLEMENTED_IN_F]


@pytest.mark.parametrize("route", LANE_ROUTES, ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
async def test_lane_endpoints_are_501_stubs_owned_by_their_lane(route: APIRoute):
    lane = lane_of(route.path)
    assert any(t.startswith(lane) for t in route.tags), f"{route.path} is tagged with its lane {lane}"
    params = {name: None for name in inspect.signature(route.endpoint).parameters}
    with pytest.raises(HTTPException) as e:
        await route.endpoint(**params)
    assert e.value.status_code == 501
    assert e.value.detail["lane"] == lane


async def test_a_stub_answers_501_over_http(client, db):
    from tests.conftest import sign_in

    await sign_in(client, db, "07700 900456")
    r = await client.get("/api/c/requests")
    assert r.status_code in (404, 501)  # no customer profile yet -> 404 from the dependency
    r = await client.get("/api/p/signup")
    assert r.status_code == 501 and r.json()["detail"] == {
        "code": "not_implemented",
        "message": "Not built yet. Lane L2 implements this endpoint.",
        "lane": "L2",
    }


def test_lane_routers_live_in_lane_packages():
    for r in LANE_ROUTES:
        module = r.endpoint.__module__
        lane = lane_of(r.path)
        expected = {"L1": "app.customer", "L2": "app.provider", "L3": ("app.admin", "app.payments")}[lane]
        assert module.startswith(expected), f"{r.path} is defined in {module}"


def test_openapi_schema_builds_and_documents_errors():
    schema = APP.openapi()
    assert "ErrorResponse" in schema["components"]["schemas"]
    assert schema["paths"]["/api/quotes"]["post"]["responses"]["422"]
