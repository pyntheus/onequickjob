"""quotes. Owner: F (the quote endpoint); L1 links them to requests."""

from pymongo import DESCENDING

from app.models.quotes import Quote
from app.repos.base import Repo, idx


class Quotes(Repo[Quote]):
    model = Quote
    indexes = [idx(("created_at", DESCENDING)), idx("user_id"), idx("pricing_version_id")]
