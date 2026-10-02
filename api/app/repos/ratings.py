"""ratings. Owner: L1."""

from pymongo import DESCENDING

from app.models.ratings import Rating
from app.repos.base import Repo, idx


class Ratings(Repo[Rating]):
    model = Rating
    indexes = [idx("visit_id", unique=True), idx("provider_id", ("created_at", DESCENDING))]
