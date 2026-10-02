"""Shared endpoints, implemented in foundations (F): health, config, auth, demo, catalogue,
quotes, address lookup, outbox, files. Lanes don't edit this file (docs/spec/lanes.md)."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from pymongo.errors import PyMongoError

from app.adapters.address.base import AddressLookup, AddressLookupError, AddressSuggestion
from app.adapters.area import make_area_estimator
from app.adapters.area.base import AreaOptions
from app.adapters.files import FileRejected, make_file_store
from app.core.config import Settings
from app.core.db import Db, get_db
from app.core.deps import CurrentUser, address_dep, current_user, current_user_optional, require_admin, settings_dep
from app.core.errors import ERROR_RESPONSES, fail, not_found
from app.models.categories import Category
from app.models.common import Address, Related
from app.models.system import FileKind, OutboxMessage
from app.repos.categories import Categories, CategoryGroups, DocumentTypes, ExcludedJobs
from app.repos.files import Files
from app.repos.outbox import Outbox
from app.repos.quotes import Quotes
from app.repos.users import Users
from app.services import auth as auth_service
from app.services import wording
from app.services.quotes import CONFIDENCE_BARS, CONFIDENCE_COPY, create_quote
from app.shared.me import build_me, clear_session_cookie, home_path, set_session_cookie
from app.shared.schemas import (
    Catalogue,
    CodeRequest,
    CodeSent,
    ConfidenceCopy,
    DemoUser,
    FeeConfig,
    FileOut,
    Health,
    MagicRequest,
    MagicResult,
    Me,
    OutboxItem,
    OutboxPage,
    PaymentsConfig,
    PublicConfig,
    QuoteOut,
    QuoteRequest,
    SwitchRequest,
    VerifyRequest,
)

router = APIRouter(prefix="/api", responses=ERROR_RESPONSES)
SettingsDep = Annotated[Settings, Depends(settings_dep)]
DbDep = Annotated[Db, Depends(get_db)]
VERSION = "0.1.0"


# ------------------------------------------------------------------------- health, config
@router.get("/health", tags=["shared"])
async def health(request: Request, db: DbDep, s: SettingsDep) -> Health:
    try:
        await db.command("ping")
        db_ok = True
    except PyMongoError:
        db_ok = False
    return Health(
        status="ok" if db_ok else "degraded", db="ok" if db_ok else "down", version=VERSION, instance=s.mongo_db
    )


@router.get("/config", tags=["shared"])
async def public_config(s: SettingsDep) -> PublicConfig:
    return PublicConfig(
        brand=s.brand,
        demo_mode=s.demo_mode,
        public_base_url=s.public_base_url,
        fees=FeeConfig(
            standard_percent=int(s.fee_standard_rate * 100),
            own_customer_percent=int(s.fee_own_rate * 100),
            own_customer_min_pence=s.fee_own_min_pence,
        ),
        payments=PaymentsConfig(gateway=s.payment_gateway, publishable_key=s.stripe_publishable_key or None),
        address_lookup=s.address_lookup,
        area_estimator=s.area_estimator,
    )


# ------------------------------------------------------------------------- auth
@router.post("/auth/code", tags=["shared: auth"], status_code=status.HTTP_202_ACCEPTED)
async def auth_code(body: CodeRequest, db: DbDep, s: SettingsDep) -> CodeSent:
    """Send a 6-digit sign-in code to a phone (as a text) or email. It lands in the outbox."""
    ident, row = await auth_service.issue_code(db, s, body.identifier)
    return CodeSent(
        channel=ident.channel,
        sent_to=ident.masked,
        expires_in_seconds=int((row.expires_at - row.created_at).total_seconds()),
    )


@router.post("/auth/verify", tags=["shared: auth"])
async def auth_verify(body: VerifyRequest, request: Request, response: Response, db: DbDep, s: SettingsDep) -> Me:
    """Check the code; sets the session cookie. Creates a customer account for a new number or email."""
    user = await auth_service.verify_code(db, s, body.identifier, body.code, body.name)
    token = await auth_service.create_session(db, s, user, "code", request.headers.get("user-agent", ""))
    set_session_cookie(response, s, token)
    return await build_me(db, user)


@router.post("/auth/magic", tags=["shared: auth"])
async def auth_magic(
    body: MagicRequest, request: Request, response: Response, db: DbDep, s: SettingsDep
) -> MagicResult:
    """Sign in from a single-use link (job alerts: /p/j/R-2301?t=...)."""
    user, target = await auth_service.consume_magic_link(db, s, body.token)
    token = await auth_service.create_session(db, s, user, "magic", request.headers.get("user-agent", ""))
    set_session_cookie(response, s, token)
    return MagicResult(me=await build_me(db, user), next=target)


@router.post("/auth/logout", tags=["shared: auth"], status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(request: Request, db: DbDep, s: SettingsDep) -> Response:
    await auth_service.end_session(db, s, request.cookies.get(s.cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, s)
    return response


@router.get("/auth/me", tags=["shared: auth"])
async def auth_me(db: DbDep, cu: Annotated[CurrentUser, Depends(current_user)]) -> Me:
    return await build_me(db, cu.user)


# ------------------------------------------------------------------------- demo (DEMO_MODE only)
def require_demo(s: SettingsDep) -> None:
    if not s.demo_mode:
        not_found("That page")


DEMO_GROUP = {"customer": "Customers", "provider": "Providers", "admin": "Admins"}


@router.get("/demo/users", tags=["shared: demo"], dependencies=[Depends(require_demo)])
async def demo_users(db: DbDep) -> list[DemoUser]:
    """Seeded people for the Switch user menu."""
    out: list[DemoUser] = []
    for u in await Users(db).demo_users():
        group = (
            "Helpers"
            if u.helper_of
            else "Admins"
            if "admin" in u.roles
            else ("Providers" if "provider" in u.roles else "Customers")
        )
        desc = "Helper" if u.helper_of else ", ".join(r.capitalize() for r in u.roles)
        out.append(
            DemoUser(
                user_id=u.id,
                demo_key=u.demo_key or "",
                name=u.name,
                roles=u.roles,
                group=group,
                description=desc,
                home_path=home_path(u.roles, bool(u.helper_of)),
            )
        )
    order = {"Customers": 0, "Providers": 1, "Helpers": 2, "Admins": 3}
    return sorted(out, key=lambda d: (order[d.group], d.demo_key))


@router.post("/demo/switch", tags=["shared: demo"], dependencies=[Depends(require_demo)])
async def demo_switch(body: SwitchRequest, request: Request, response: Response, db: DbDep, s: SettingsDep) -> Me:
    """Sign in as a seeded user without a code. Only seeded (demo_key) users, only in DEMO_MODE."""
    user = await Users(db).get(body.user_id)
    if user is None or not user.demo_key:
        not_found("That demo user")
    await auth_service.end_session(db, s, request.cookies.get(s.cookie_name))
    token = await auth_service.create_session(db, s, user, "demo", request.headers.get("user-agent", ""))
    set_session_cookie(response, s, token)
    return await build_me(db, user)


CODE = re.compile(r"\b\d{6}\b")


def _outbox_item(m: OutboxMessage, *, redact_codes: bool = False) -> OutboxItem:
    body = m.body
    if redact_codes and m.template_id == "login_code":
        body = CODE.sub("••••••", body)
    return OutboxItem(
        id=m.id,
        channel=m.channel,
        recipient=m.recipient,
        template_id=m.template_id,
        subject=m.subject,
        body=body,
        related=m.related,
        created_at=m.created_at,
        not_before=m.not_before,
    )


@router.get("/demo/outbox", tags=["shared: demo"], dependencies=[Depends(require_demo)])
async def demo_outbox(db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 30) -> list[OutboxItem]:
    """The latest messages, for the Outbox drawer (login codes included: it's a prototype)."""
    return [_outbox_item(m) for m in await Outbox(db).latest(limit)]


# ------------------------------------------------------------------------- outbox (admin)
@router.get("/admin/outbox", tags=["shared: outbox"])
async def admin_outbox(
    db: DbDep,
    s: SettingsDep,
    _: Annotated[CurrentUser, Depends(require_admin)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    channel: Annotated[str | None, Query(pattern="^(sms|whatsapp|email)$")] = None,
    template_id: str | None = None,
    user_id: str | None = None,
    before: Annotated[str | None, Query(description="id of the last item on the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> OutboxPage:
    """Every message, newest first, searchable. L3 builds the admin view on this."""
    items = await Outbox(db).search(
        q=q, channel=channel, template_id=template_id, user_id=user_id, before_id=before, limit=limit
    )
    # Outside DEMO_MODE, staff never see live sign-in codes.
    items_out = [_outbox_item(m, redact_codes=not s.demo_mode) for m in items]
    return OutboxPage(items=items_out, next_before=items[-1].id if len(items) == limit else None)


# ------------------------------------------------------------------------- catalogue
@router.get("/categories", tags=["shared: catalogue"])
async def categories(db: DbDep) -> Catalogue:
    """Live categories with intake schemas, groups, document types and the jobs we never list."""
    return Catalogue(
        groups=await CategoryGroups(db).all(),
        categories=await Categories(db).live(),
        document_types=await DocumentTypes(db).all(),
        excluded=await ExcludedJobs(db).all(),
    )


@router.get("/categories/{category_id}", tags=["shared: catalogue"])
async def category(category_id: str, db: DbDep) -> Category:
    cat = await Categories(db).get(category_id)
    if cat is None:
        not_found("That kind of job")
    return cat


# ------------------------------------------------------------------------- quotes
@router.get("/area/options", tags=["shared: quotes"])
async def area_options(s: SettingsDep) -> AreaOptions:
    """How the lawn step asks for size (manual bands for v0)."""
    return await make_area_estimator(s).options(None)


def _quote_out(q) -> QuoteOut:
    label, default_note = CONFIDENCE_COPY[q.result.confidence]
    return QuoteOut(
        id=q.id,
        category_id=q.category_id,
        answers=q.answers,
        measure=q.measure,
        pricing_version=q.pricing_version,
        pricing_version_id=q.pricing_version_id,
        result=q.result,
        fee=q.fee,
        first_fee=q.first_fee,
        confidence=ConfidenceCopy(
            level=q.result.confidence,
            bars=CONFIDENCE_BARS[q.result.confidence],
            label=label,
            note=q.result.conf_note or default_note,
        ),
        duration_text=wording.duration_text(q.result.mins),
        first_duration_text=wording.duration_text(q.result.first_mins) if q.result.first_mins else None,
        created_at=q.created_at,
    )


@router.post("/quotes", tags=["shared: quotes"], status_code=status.HTTP_201_CREATED)
async def quote(
    body: QuoteRequest, db: DbDep, s: SettingsDep, cu: Annotated[CurrentUser | None, Depends(current_user_optional)]
) -> QuoteOut:
    """Price a job from the live pricing version. No account needed. The quote is stored with the version used."""
    q = await create_quote(
        db,
        s,
        category_id=body.category_id,
        answers=body.answers,
        lawn=body.lawn,
        address=body.address,
        user_id=cu.id if cu else None,
    )
    return _quote_out(q)


@router.get("/quotes/{quote_id}", tags=["shared: quotes"])
async def get_quote(quote_id: str, db: DbDep) -> QuoteOut:
    q = await Quotes(db).get(quote_id)
    if q is None:
        not_found("That quote")
    return _quote_out(q)


# ------------------------------------------------------------------------- address lookup proxy
@router.get("/address/search", tags=["shared: address"])
async def address_search(
    lookup: Annotated[AddressLookup, Depends(address_dep)], q: Annotated[str, Query(min_length=2, max_length=100)]
) -> list[AddressSuggestion]:
    """Suggestions as the customer types (free with Ideal Postcodes)."""
    try:
        return await lookup.search(q)
    except AddressLookupError as e:
        fail(status.HTTP_502_BAD_GATEWAY, "address_lookup_failed", "We couldn't look that up just now.", why=str(e))


@router.get("/address/{suggestion_id}", tags=["shared: address"])
async def address_resolve(suggestion_id: str, lookup: Annotated[AddressLookup, Depends(address_dep)]) -> Address:
    """The full address with UPRN and coordinates (the paid lookup; cached)."""
    try:
        found = await lookup.resolve(suggestion_id)
    except AddressLookupError as e:
        fail(status.HTTP_502_BAD_GATEWAY, "address_lookup_failed", "We couldn't look that up just now.", why=str(e))
    if found is None:
        not_found("That address")
    return found


# ------------------------------------------------------------------------- files
@router.post("/files", tags=["shared: files"], status_code=status.HTTP_201_CREATED)
async def upload_file(
    db: DbDep,
    s: SettingsDep,
    cu: Annotated[CurrentUser, Depends(current_user)],
    file: Annotated[UploadFile, File(description="Image or PDF")],
    kind: Annotated[FileKind, Form()],
    visit_id: Annotated[str | None, Form()] = None,
    request_id: Annotated[str | None, Form()] = None,
    dispute_id: Annotated[str | None, Form()] = None,
) -> FileOut:
    """Upload a photo or document to the FileStore. Returns its id and URL (served behind basic auth)."""
    store = make_file_store(s)
    data = await file.read(s.files_max_bytes + 1)
    try:
        stored = await store.save(
            data,
            content_type=file.content_type or "",
            kind=kind,
            owner_user_id=cu.id,
            original_name=file.filename or "",
            related=Related(visit_id=visit_id, request_id=request_id, dispute_id=dispute_id),
        )
    except FileRejected as e:
        fail(status.HTTP_422_UNPROCESSABLE_CONTENT, "file_rejected", str(e))
    await Files(db).insert(stored)
    return FileOut(id=stored.id, kind=stored.kind, url=stored.url, content_type=stored.content_type, size=stored.size)
