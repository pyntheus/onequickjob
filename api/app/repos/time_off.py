"""time_off. Owner: L2."""

from app.models.provider_ops import TimeOff
from app.repos.base import Repo, idx


class TimeOffRepo(Repo[TimeOff]):
    model = TimeOff
    indexes = [idx("provider_id", "from_date")]
