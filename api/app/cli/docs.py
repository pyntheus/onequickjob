"""Generate docs from code so they can't drift.

python -m app.cli.docs notifications   > docs/spec/notifications.md
"""

import re
import sys

from app.cli import offline_settings
from app.services import templates

LANE_TITLES = {
    "F": "Shared (sent by foundation code, or by any lane)",
    "L1": "L1 Customer",
    "L2": "L2 Provider",
    "L3": "L3 Admin and payments",
}
CHANNEL_NAMES = {"sms": "Text", "whatsapp": "WhatsApp", "email": "Email"}


def notifications() -> str:
    out = [
        "# Notifications: the outbox template catalogue",
        "",
        "Generated from `api/app/services/templates.py` by `make docs`. Do not edit by hand.",
        "",
        "Nothing is ever sent. Every message is rendered and written to the `outbox` collection with its",
        "channel, recipient, template id, rendered body and related ids (`app.services.notify.notify`).",
        "The demo Outbox drawer shows the latest messages; admins search them all at `/admin/outbox`.",
        "",
        "Rules for message copy: UK English; texts start with the brand; say who the agreement is with",
        "where it matters; never promise or guarantee anything; links are full URLs built from",
        "`PUBLIC_BASE_URL`. Sections are grouped by the lane that writes the code that sends each one.",
        "Every template is in the catalogue file, including the ones the lanes added (folded in by the",
        "shared-fixes session); add new ones there.",
        "",
        f"{len(templates.all_templates())} templates.",
        "",
    ]
    for lane, title in LANE_TITLES.items():
        rows = [t for t in templates.all_templates() if t.lane == lane]
        if not rows:
            continue
        out += [f"## {title}", "", "| Template | Channels | To | Trigger |", "|---|---|---|---|"]
        for t in rows:
            channels = ", ".join(CHANNEL_NAMES[c] for c in t.channels)
            out.append(f"| `{t.id}` | {channels} | {t.audience} | {t.trigger} |")
        out.append("")
        for t in rows:
            out.append(f"**`{t.id}`**" + (f" (subject: {t.subject})" if t.subject else ""))
            out.append("")
            out.append("> " + t.body.replace("\n", "\n> "))
            out.append("")
            out.append("Placeholders: " + ", ".join(f"`{p}`" for p in t.placeholders))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


API_INTRO = """# API

Generated from the FastAPI routes by `make docs`; the intro is in `api/app/cli/docs.py`. Live,
typed docs are at `/api/docs` and the OpenAPI schema at `/api/openapi.json`; the web's types
in `web/src/api/schema.d.ts` come from it (`make types`).

## Conventions

- Everything is under `/api`. JSON in and out; request bodies reject unknown fields (422).
- **Auth**: the `oqj_session` cookie (httpOnly, Secure, SameSite=Lax) from
  `POST /api/auth/verify`, `/api/auth/magic` or (demo) `/api/demo/switch`. Customer endpoints
  need the customer role (most also a customers record), provider endpoints the provider role
  (helpers act for their provider), admin endpoints the admin role. Not signed in is a 403 with
  the code `not_signed_in`, never a 401 (decisions.md A25): no route answers 401, and clients
  check the code, not the status.
- **Errors**: `{"detail": {"code": "...", "message": "...", "lane": ..., "extra": {...}}}`.
  `message` is UK English copy you can show; branch on `code`. Validation errors are FastAPI's
  standard 422.
- **Money** is integer pence in fields ending `_pence`; fee splits come from `money.py`.
  **Dates** are ISO `YYYY-MM-DD` (London); **datetimes** are UTC ISO 8601.
- **Stubs**: every lane endpoint exists with its final request and response models and answers
  `501 {"detail": {"code": "not_implemented", "lane": "L1"}}` until its lane builds it.
  Implement the body; keep the method, path and models, or change them additively and say so.
- **Ownership**: the Lane column. "F" endpoints are built and owned by foundations; lanes don't
  edit them (request changes in `docs/spec/contract-changes/<lane>.md`).
"""

LANE_OF_TAG = {"L1": "L1", "L2": "L2", "L3": "L3"}


def _model_name(t) -> str:
    if t is None:
        return ""
    if isinstance(t, type) and not getattr(t, "__args__", None):
        return t.__name__
    return re.sub(r"[\w.]+\.(\w+)", r"\1", str(t)).replace("NoneType", "None")


def api() -> str:
    from app.core.routes import api_routes
    from app.main import create_app

    app = create_app(offline_settings())
    rows: dict[str, list[str]] = {}
    sections = {
        "F": "Shared, built in foundations (F)",
        "L1": "L1 Customer (/api/c)",
        "L2": "L2 Provider (/api/p)",
        "L3": "L3 Admin and payments (/api/admin, /api/payments)",
    }
    for r in api_routes(app):
        tag = (r.tags or ["shared"])[0]
        lane = next((v for k, v in LANE_OF_TAG.items() if tag.startswith(k)), "F")
        method = ",".join(sorted(m for m in r.methods if m != "HEAD"))
        body = r.body_field.field_info.annotation if r.body_field is not None else None
        req = _model_name(body) if body is not None and r.path != "/api/files" else ("multipart" if body else "")
        resp = (
            _model_name(r.response_model)
            if r.response_model is not None
            else ("file" if r.status_code == 200 else str(r.status_code))
        )
        doc = (r.endpoint.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ")
        doc = " ".join(doc.split())
        cells = [f"`{method}`", f"`{r.path}`", req, resp, doc]
        rows.setdefault(lane, []).append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    out = [API_INTRO.rstrip(), ""]
    for lane, title in sections.items():
        out += [f"## {title}", "", "| Method | Path | Request | Response | Notes |", "|---|---|---|---|---|"]
        out += rows.get(lane, [])
        out.append("")
    total = sum(len(v) for v in rows.values())
    out.append(f"{total} endpoints.")
    return "\n".join(out) + "\n"


# Who owns each collection's schema and repo, and who else writes it (through which functions).
OWNERS: dict[str, tuple[str, str]] = {
    "users": ("F", "F (auth creates; Users.add_role); L2 sign-up adds the provider role; L3 suspends"),
    "sessions": ("F", "F only (services.auth)"),
    "login_codes": ("F", "F only (services.auth)"),
    "magic_links": ("F", "F mints and consumes; L1 (job alerts) and L2 (helper invites) mint via create_magic_link"),
    "customers": ("L1", "L1; F test factories; L1 invite acceptance creates own-customer customers"),
    "providers": (
        "L2",
        "L2 (self-service, sign-up); L3 via Providers.set_document / set_helper_document / set_helper_status / "
        "set_status, and patch(payment_account) on account.updated, admin onboarding and Check status; "
        "services.lifecycle activates (A19); L1 via apply_rating",
    ),
    "tax_identities": ("L2", "L2 writes (sign-up, sealed); L3 reads for the HMRC export"),
    "categories": ("L3", "Seed only in the prototype (viewing only); L3 owns future editing"),
    "category_groups": ("L3", "Seed only"),
    "document_types": ("L3", "Seed only"),
    "excluded_jobs": ("L3", "Seed only"),
    "pricing_versions": ("L3", "L3 drafts and approves; seed inserts version 1"),
    "quotes": ("F", "F (POST /api/quotes); L1 sets request_id"),
    "job_requests": (
        "L1",
        "L1 creates, cancels and answers raises; F marketplace claims (status open -> booked) and withdraws a "
        "waiting raise (A16); L2 records views and creates cover requests; L3 proposes raises (app.services."
        "guide_raises.propose)",
    ),
    "offers": ("F", "F marketplace (counter, accept, decline, lapse)"),
    "bookings": (
        "F",
        "F services.bookings.create_booking (marketplace, L1's invite acceptance, L2's own customers); L1 cancels "
        "and changes frequency; app.payments.charging completes a one-off once its visit is paid",
    ),
    "series": ("F", "F creates; L1 pauses, changes frequency, cancels; F task tops up the horizon"),
    "visits": (
        "L2",
        "F creates (services.schedule / bookings); L2 starts, photos, finishes, helper, cover; "
        "L1 skips; L3 writes charge state from webhooks and refunds",
    ),
    "ratings": ("L1", "L1"),
    "disputes": ("L3", "L1 opens (stage 0); L3 runs them; L2 may add the provider's reply"),
    "message_threads": ("F", "F creates booking threads; L3 creates dispute threads; everyone posts via Messages.post"),
    "messages": ("F", "Every lane via Messages.post"),
    "outbox": ("F", "Every lane via services.notify.notify only"),
    "ledger_entries": ("L2", "L2 via services.ledger.record_charge / record_tip; L3 via record_refund"),
    "mileage_logs": ("L2", "L2"),
    "expenses": ("L2", "L2"),
    "time_off": ("L2", "L2"),
    "own_customer_invites": ("L2", "L2 creates (and records blocked attempts); L1 accepts"),
    "plan_changes": ("L1", "L1 (app.customer.plan_changes): asked, answered by the provider's link, lapsed (A10)"),
    "payment_events": ("L3", "L3 (app.payments.webhooks): each Stripe event once, with its outcome"),
    "payment_refunds": ("L3", "L3 (app.payments.refunds): each refund's intent, gateway result and fee return"),
    "payment_attempts": ("L3", "L3 (app.payments.charging): each charge attempt's intent, by idempotency key"),
    "audit_log": ("F", "Every lane via services.audit.audit (admin actions, pricing, money changes)"),
    "files": ("F", "F (POST /api/files) for every lane"),
}
EXTRA_COLLECTIONS = {
    "counters": ("F", "core.ids.next_ref: {_id: request, booking or dispute; seq}, atomic $inc for human refs"),
    "address_cache": ("F", "Ideal Postcodes resolutions by suggestion id, so a chosen address is paid for once"),
    "fake_gateway": ("L3", "The fake PaymentGateway's own state (accounts, setups, charges, refunds); no other code"),
}


def _type_str(annotation) -> str:
    text = re.sub(r"[\w.]+\.(\w+)", r"\1", str(annotation)).replace("NoneType", "None")
    text = re.sub(r"Annotated\[(\w+), .*\]", r"\1", text)
    if isinstance(annotation, type):
        text = annotation.__name__
    return text.replace("|", "\\|")


def _fields(model) -> list[str]:
    from pydantic import BaseModel

    rows = []
    for name, f in model.model_fields.items():
        out_name = "_id" if name == "id" else name
        t = _type_str(f.annotation)
        desc = (f.description or "").replace("|", "\\|")
        default = "" if f.is_required() else " (optional)" if f.default is None else ""
        rows.append(f"| `{out_name}` | {t}{default} | {desc} |")
        ann = f.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            pass
    return rows


def domain() -> str:
    from pydantic import BaseModel

    from app.repos import ALL

    out = [
        "# Domain: collections",
        "",
        "Generated from the Pydantic models (`api/app/models/`) and repositories (`api/app/repos/`) by",
        "`make docs`; ownership is maintained in `api/app/cli/docs.py`. Conventions:",
        "",
        "- `_id` is a 24-hex string (a fresh ObjectId's hex); references store the same string.",
        "- Money is integer pence in fields ending `_pence`; `SignedPence` may be negative (refunds).",
        "- Datetimes are timezone-aware UTC. `IsoDate` fields are London calendar dates stored as",
        "  `YYYY-MM-DD` strings. Phones are E.164.",
        "- Seeded documents carry `_seed: true` (ignored by the models). `make seed` resets the demo:",
        "  it removes what demo runs created and writes the seeded documents again (decisions.md A21).",
        "- **Owner** decides the schema and adds repo functions; changes by anyone else go through",
        "  `docs/spec/contract-changes/<lane>.md`. **Writers** lists who else writes and how.",
        "- One repository class per collection in `api/app/repos/` (the catalogue's four are in",
        "  `categories.py`, threads and messages in `messages.py`, users with sessions, codes and links",
        "  in `users.py`). A lane needing a new read-only query on a collection it doesn't own writes it",
        "  in its own package using `Repo(db).coll`.",
        "",
        "## Summary",
        "",
        "| Collection | Owner | Writers |",
        "|---|---|---|",
    ]
    embedded: dict[str, type] = {}
    sections = []
    for repo in ALL:
        model = repo.model
        name = model.COLLECTION
        owner, writers = OWNERS.get(name, ("?", "?"))
        out.append(f"| `{name}` | {owner} | {writers} |")
        own_doc = model.__dict__.get("__doc__") or ""
        if "BaseModel" in own_doc or not own_doc.strip():
            own_doc = sys.modules[model.__module__].__doc__ or ""
        doc = " ".join(own_doc.strip().split("\n\n")[0].split())
        sec = [
            f"## `{name}`",
            "",
            *([doc, ""] if doc else []),
            f"Model `{model.__module__}.{model.__name__}`; repo `{repo.__module__}.{repo.__name__}`. Owner {owner}.",
            "",
            "| Field | Type | Notes |",
            "|---|---|---|",
        ]
        sec += _fields(model)
        idx_rows = []
        for ix in repo.indexes:
            doc = ix.document
            keys = ", ".join(f"{k}{'' if v == 1 else ' desc'}" for k, v in doc["key"].items())
            flags = []
            if doc.get("unique"):
                flags.append("unique")
            if "partialFilterExpression" in doc:
                flags.append(f"partial {doc['partialFilterExpression']}")
            if "expireAfterSeconds" in doc:
                flags.append(f"TTL {doc['expireAfterSeconds']}s")
            idx_rows.append(f"- `{keys}`" + (f" ({'; '.join(flags)})" if flags else ""))
        sec += ["", "Indexes:" if idx_rows else "Indexes: `_id` only.", *idx_rows, ""]
        sections.append("\n".join(sec))
        for f in model.model_fields.values():
            for t in re.findall(r"\b([A-Z]\w+)\b", str(f.annotation)):
                mod = __import__(model.__module__, fromlist=[t])
                obj = getattr(mod, t, None)
                if isinstance(obj, type) and issubclass(obj, BaseModel) and not hasattr(obj, "COLLECTION"):
                    embedded[t] = obj
    for name, (owner, desc) in EXTRA_COLLECTIONS.items():
        out.append(f"| `{name}` | {owner} | {desc} |")
    out += ["", *sections, "## Embedded value objects", ""]
    for name in sorted(embedded):
        model = embedded[name]
        out += [f"### `{name}`", "", "| Field | Type | Notes |", "|---|---|---|", *_fields(model), ""]
    return "\n".join(out).rstrip() + "\n"


COMMANDS = {"notifications": notifications, "api": api, "domain": domain}

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what not in COMMANDS:
        sys.exit("usage: python -m app.cli.docs notifications|api")
    sys.stdout.write(COMMANDS[what]())
