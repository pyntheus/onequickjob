from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.address.base import AddressLookup
from app.adapters.address.fake import FakeAddressLookup
from app.adapters.address.ideal_postcodes import IdealPostcodesLookup
from app.core.config import Settings


def make_address_lookup(settings: Settings, db: AsyncDatabase) -> AddressLookup:
    """Ideal Postcodes when IDEAL_POSTCODES_KEY is set, otherwise the fake."""
    if settings.address_lookup == "ideal_postcodes":
        return IdealPostcodesLookup(settings.ideal_postcodes_key, settings.ideal_postcodes_base_url, db)
    return FakeAddressLookup()
