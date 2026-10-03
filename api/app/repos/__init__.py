"""Repositories, one module per collection. ALL lists every repo for index creation."""

import contextlib

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

from app.repos.audit_log import AuditLog
from app.repos.base import Repo
from app.repos.bookings import Bookings
from app.repos.categories import Categories, CategoryGroups, DocumentTypes, ExcludedJobs
from app.repos.customers import Customers
from app.repos.disputes import Disputes
from app.repos.expenses import Expenses
from app.repos.files import Files
from app.repos.job_requests import JobRequests
from app.repos.ledger_entries import LedgerEntries
from app.repos.messages import Messages, MessageThreads
from app.repos.mileage_logs import MileageLogs
from app.repos.offers import Offers
from app.repos.outbox import Outbox
from app.repos.own_customer_invites import OwnCustomerInvites
from app.repos.pricing_versions import PricingVersions
from app.repos.providers import Providers, TaxIdentities
from app.repos.quotes import Quotes
from app.repos.ratings import Ratings
from app.repos.series import SeriesRepo
from app.repos.time_off import TimeOffRepo
from app.repos.users import LoginCodes, MagicLinks, Sessions, Users
from app.repos.visits import Visits

ALL: list[type[Repo]] = [
    Users,
    Sessions,
    LoginCodes,
    MagicLinks,
    Customers,
    Providers,
    TaxIdentities,
    Categories,
    CategoryGroups,
    DocumentTypes,
    ExcludedJobs,
    PricingVersions,
    Quotes,
    JobRequests,
    Offers,
    Bookings,
    SeriesRepo,
    Visits,
    Ratings,
    Disputes,
    MessageThreads,
    Messages,
    Outbox,
    LedgerEntries,
    MileageLogs,
    Expenses,
    TimeOffRepo,
    OwnCustomerInvites,
    AuditLog,
    Files,
]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Create every collection and its indexes (at start-up and before seeding), so no
    transaction ever has to create a collection."""
    existing = set(await db.list_collection_names())
    for name in sorted(({r.model.COLLECTION for r in ALL} | {"counters"}) - existing):
        with contextlib.suppress(CollectionInvalid, OperationFailure):  # another process made it first
            await db.create_collection(name)
    for repo_cls in ALL:
        if repo_cls.indexes:
            await db[repo_cls.model.COLLECTION].create_indexes(repo_cls.indexes)


__all__ = [
    "ALL",
    "AuditLog",
    "Bookings",
    "Categories",
    "CategoryGroups",
    "Customers",
    "Disputes",
    "DocumentTypes",
    "ExcludedJobs",
    "Expenses",
    "Files",
    "JobRequests",
    "LedgerEntries",
    "LoginCodes",
    "MagicLinks",
    "MessageThreads",
    "Messages",
    "MileageLogs",
    "Offers",
    "Outbox",
    "OwnCustomerInvites",
    "PricingVersions",
    "Providers",
    "Quotes",
    "Ratings",
    "SeriesRepo",
    "Sessions",
    "TaxIdentities",
    "TimeOffRepo",
    "Users",
    "Visits",
    "ensure_indexes",
]
