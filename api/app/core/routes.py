"""Walk every APIRoute in an app (FastAPI 0.14x keeps included routers as wrappers)."""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute


def api_routes(app: FastAPI) -> Iterator[APIRoute]:
    stack = list(app.routes)
    while stack:
        r = stack.pop(0)
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            stack[:0] = list(r.original_router.routes)
