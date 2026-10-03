"""The FastAPI app. Owner: F. Lanes add endpoints to their own routers, never here.

uvicorn builds it with `app.main:create_app --factory`, so importing this module reads no
settings: the app (and its secrets check) exists only when something starts it.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Lane task modules register their @periodic tasks on import.
import app.admin.tasks
import app.customer.tasks
import app.provider.tasks
import app.shared.tasks  # noqa: F401 (imported for its @periodic registrations, like the three above)
from app.admin.router import router as admin_router
from app.core import tasks
from app.core.config import Settings, get_settings
from app.core.db import check_db_name, make_client
from app.core.errors import Conflict, conflict_handler
from app.customer.router import router as customer_router
from app.payments.router import router as payments_router
from app.provider.router import router as provider_router
from app.repos import ensure_indexes
from app.shared.marketplace_routes import router as marketplace_router
from app.shared.routes import VERSION
from app.shared.routes import router as shared_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = make_client(s)
        db = client[check_db_name(s.mongo_db)]
        app.state.client, app.state.db = client, db
        await ensure_indexes(db)
        runner = tasks.start(db, s)
        try:
            yield
        finally:
            await tasks.stop(runner)
            await client.close()

    app = FastAPI(
        title="OneQuickJob API",
        version=VERSION,
        description="Contracts for the OneQuickJob prototype. Lanes: see docs/spec/api.md.",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = s
    app.add_exception_handler(Conflict, conflict_handler)  # domain conflicts from below the routers: 409
    # Order matters only for identical paths; the shared marketplace endpoints come first.
    for r in (shared_router, marketplace_router, customer_router, provider_router, admin_router, payments_router):
        app.include_router(r)
    if s.serve_files:
        # check_dir=False: the volume may be empty at start; the FileStore creates folders.
        app.mount(s.files_url_prefix, StaticFiles(directory=s.files_dir, check_dir=False), name="files")
    return app
