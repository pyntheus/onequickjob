"""series (recurring plans). Owner: F creates; L1 pauses, changes and cancels; L2 reads."""

from app.models.bookings import Series
from app.repos.base import Repo, idx


class SeriesRepo(Repo[Series]):
    model = Series
    indexes = [idx("booking_id", unique=True), idx("provider_id", "status"), idx("customer_id")]
