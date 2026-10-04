"""Shared state and helpers for the seed.

Every document the seed writes carries `_seed: true` (the models ignore it). A run first
resets the demo: it deletes the previous run's seeded documents and everything demo runs
created (see cleanup.py for the little it keeps), then writes the seeded documents again with
the same deterministic ids (app.core.ids.seed_id), so running it twice leaves the same data.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from app.adapters.address.fake import ADDRESSES as FAKE_ADDRESSES
from app.core.config import Settings
from app.core.db import Db
from app.core.geo import district_of
from app.core.ids import seed_id
from app.core.timeutil import london_datetime, to_london
from app.models.categories import Category
from app.models.common import Address, Doc
from app.models.customers import Customer
from app.models.pricing_versions import PricingVersion
from app.models.providers import Provider
from app.models.users import User
from app.seed.paths import SEED_DIR

SEED_FLAG = "_seed"


def read(name: str) -> dict[str, Any]:
    return json.loads((SEED_DIR / name).read_text())


def sid(*parts: object) -> str:
    """Deterministic id for a seeded document."""
    return seed_id(":".join(str(p) for p in parts))


def mulberry32(seed: int):
    """The prototype's PRNG, bit for bit (32-bit unsigned arithmetic)."""
    mask = 0xFFFFFFFF
    state = seed & mask

    def imul(a: int, b: int) -> int:
        return (a * b) & mask

    def rnd() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & mask
        t = imul(state ^ (state >> 15), 1 | state)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & mask) ^ t
        return ((t ^ (t >> 14)) & mask) / 4294967296

    return rnd


class Writer:
    """Collects seeded documents and inserts them per collection, flagged as seeded.

    Models are converted at flush time, so changes made after add() (a rating id on a
    visit, a thread id on a booking) are still written."""

    def __init__(self, db: Db):
        self.db = db
        self.pending: dict[str, list[Doc | dict[str, Any]]] = defaultdict(list)
        self.ids: dict[str, set[str]] = defaultdict(set)

    def add(self, doc: Doc) -> Doc:
        self._track(doc.COLLECTION, doc.id)
        self.pending[doc.COLLECTION].append(doc)
        return doc

    def add_raw(self, collection: str, raw: dict[str, Any]) -> None:
        self._track(collection, raw["_id"])
        self.pending[collection].append(raw)

    def _track(self, collection: str, id_: str) -> None:
        if id_ in self.ids[collection]:
            raise ValueError(f"seed wrote {collection}/{id_} twice")
        self.ids[collection].add(id_)

    async def flush(self) -> None:
        for collection, docs in self.pending.items():
            raws = [{**(d.to_mongo() if isinstance(d, Doc) else d), SEED_FLAG: True} for d in docs]
            if raws:
                await self.db[collection].insert_many(raws, ordered=True)
        self.pending = defaultdict(list)


@dataclass
class Ctx:
    db: Db
    s: Settings
    now: datetime
    w: Writer
    people: dict[str, Any]
    scenario: dict[str, Any]
    cats: dict[str, Category] = field(default_factory=dict)
    pricing: PricingVersion | None = None
    addresses: dict[str, Address] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    customers: dict[str, Customer] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)
    admins: dict[str, User] = field(default_factory=dict)
    booking_refs: int = 0
    request_refs: int = 2100
    visit_address: dict[str, Address] = field(default_factory=dict)
    visits: list[Any] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)

    @property
    def today(self) -> date:
        return to_london(self.now).date()

    def day(self, days_ago: int) -> date:
        return self.today - timedelta(days=days_ago)

    def at(self, day: date, hhmm: str) -> datetime:
        hh, mm = (int(x) for x in hhmm.split(":"))
        return london_datetime(day, time(hh, mm))

    def ago(self, minutes: float = 0, days: float = 0) -> datetime:
        return self.now - timedelta(minutes=minutes, days=days)

    def next_booking_ref(self) -> str:
        """Seeded bookings use B-0001 upwards; the app's own start at B-1101."""
        self.booking_refs += 1
        return f"B-{self.booking_refs:04d}"

    def next_request_ref(self) -> str:
        """Seeded booked (history) requests use R-2101 upwards; the demo's open ones keep the
        prototype's R-2284..R-2294; the app's own start at R-2301."""
        self.request_refs += 1
        return f"R-{self.request_refs}"

    def address(self, key: str) -> Address:
        if key in self.addresses:
            return self.addresses[key]
        if key in FAKE_ADDRESSES:
            self.addresses[key] = FAKE_ADDRESSES[key]
            return self.addresses[key]
        raw = self.people["addresses"][key]
        a = Address(
            line1=raw["line1"],
            locality=raw["locality"],
            town=raw["town"],
            postcode=raw["postcode"],
            district=district_of(raw["postcode"]),
            uprn=raw["uprn"],
            lat=raw["lat"],
            lng=raw["lng"],
            label=f"{raw['line1']}, {raw['locality']}, {raw['postcode']}",
        )
        self.addresses[key] = a
        return a

    def customer_address(self, key: str) -> Address:
        return self.customers[key].addresses[0]

    def timestamps(self, dt: datetime) -> dict[str, datetime]:
        return {"created_at": dt, "updated_at": dt}
