"""files: metadata for everything in the FileStore. Owner: F."""

from app.models.system import StoredFile
from app.repos.base import Repo, idx


class Files(Repo[StoredFile]):
    model = StoredFile
    touch_updated_at = False
    indexes = [idx("owner_user_id", "created_at"), idx("path", unique=True)]
