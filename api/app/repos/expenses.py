"""expenses. Owner: L2."""

from app.models.records import Expense
from app.repos.base import Repo, idx


class Expenses(Repo[Expense]):
    model = Expense
    indexes = [idx("provider_id", "local_date"), idx("tax_year", "provider_id")]
