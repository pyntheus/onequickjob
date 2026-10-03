"""audit_log. Owner: F. Written only by app.services.audit."""

from pymongo import DESCENDING

from app.models.system import AuditEntry
from app.repos.base import Repo, idx


class AuditLog(Repo[AuditEntry]):
    model = AuditEntry
    touch_updated_at = False
    indexes = [idx(("at", DESCENDING)), idx("action", ("at", DESCENDING)), idx("actor.user_id")]
