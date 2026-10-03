"""Ideal Postcodes, used when IDEAL_POSTCODES_KEY is set.

  search:  GET /v1/autocomplete/addresses?query=...           free
  resolve: GET /v1/autocomplete/addresses/{id}/gbr             costs one lookup credit

Resolved addresses are cached in Mongo (address_cache) so choosing the same address
twice doesn't spend a second credit. The key is sent from the server only.
"""

from typing import Any, Literal

import httpx
from pymongo.asynchronous.database import AsyncDatabase

from app.adapters.address.base import AddressLookupError, AddressSuggestion
from app.core.geo import district_of
from app.core.timeutil import utcnow
from app.models.common import Address

CACHE = "address_cache"


class IdealPostcodesLookup:
    name: Literal["ideal_postcodes"] = "ideal_postcodes"

    def __init__(
        self, api_key: str, base_url: str, db: AsyncDatabase, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.db = db
        self.transport = transport

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=8, transport=self.transport) as client:
                r = await client.get(path, params={**params, "api_key": self.api_key})
        except httpx.HTTPError as e:
            raise AddressLookupError("Address lookup is unavailable") from e
        if r.status_code == 404:
            return {}
        if r.status_code != 200:
            raise AddressLookupError(f"Address lookup failed ({r.status_code})")
        return r.json()

    async def search(self, query: str, *, limit: int = 8) -> list[AddressSuggestion]:
        data = await self._get("/v1/autocomplete/addresses", {"query": query, "limit": limit})
        hits = (data.get("result") or {}).get("hits") or []
        return [AddressSuggestion(id=str(h["id"]), label=str(h["suggestion"])) for h in hits[:limit]]

    async def resolve(self, suggestion_id: str) -> Address | None:
        cached = await self.db[CACHE].find_one({"_id": suggestion_id})
        if cached:
            return Address.model_validate(cached["address"])
        data = await self._get(f"/v1/autocomplete/addresses/{suggestion_id}/gbr", {})
        r = data.get("result")
        if not r:
            return None
        line2 = ", ".join(x for x in (r.get("line_2"), r.get("line_3")) if x)
        locality = r.get("dependant_locality") or r.get("dependent_locality") or ""
        address = Address(
            line1=r.get("line_1") or "",
            line2=line2,
            locality=locality,
            town=r.get("post_town") or "",
            postcode=r["postcode"],
            district=district_of(r["postcode"]),
            uprn=str(r["uprn"]) if r.get("uprn") else None,
            lat=float(r["latitude"]),
            lng=float(r["longitude"]),
            label=", ".join(x for x in (r.get("line_1"), locality or r.get("post_town"), r["postcode"]) if x),
        )
        await self.db[CACHE].update_one(
            {"_id": suggestion_id},
            {"$set": {"address": address.model_dump(mode="python"), "cached_at": utcnow()}},
            upsert=True,
        )
        return address
