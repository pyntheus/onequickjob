"""AddressLookup: postcode and address search through a backend proxy.

The Ideal Postcodes key never reaches the browser: the web calls /api/address/search
(free autocomplete) and /api/address/{id} (the paid lookup, made once per chosen
address and cached). Every resolved address carries its UPRN.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

from app.models.common import Address


class AddressSuggestion(BaseModel):
    id: str
    label: str


class AddressLookupError(RuntimeError):
    pass


class AddressLookup(Protocol):
    name: Literal["fake", "ideal_postcodes"]

    async def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]: ...

    async def resolve(self, suggestion_id: str) -> Address | None: ...
