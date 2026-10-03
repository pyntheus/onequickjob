"""mileage_logs. Owner: L2."""

from app.models.records import MileageLog
from app.repos.base import Repo, idx


class MileageLogs(Repo[MileageLog]):
    model = MileageLog
    indexes = [idx("provider_id", "local_date", unique=True), idx("tax_year", "provider_id")]
