"""FileStore: local disk under FILES_DIR (a mounted volume), served at /files/ by Caddy
behind the same basic auth (and by the API in development, for SSH-tunnelled lanes).

Paths are random and unguessable; the files collection records who uploaded what and
why. Only images and PDFs, up to FILES_MAX_BYTES.
"""

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.core.ids import new_token
from app.core.timeutil import utcnow
from app.models.common import Related
from app.models.system import FileKind, StoredFile

ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "application/pdf": "pdf",
}


class FileRejected(ValueError):
    pass


class LocalFileStore:
    def __init__(self, settings: Settings):
        self.root = Path(settings.files_dir)
        self.prefix = settings.files_url_prefix.rstrip("/")
        self.max_bytes = settings.files_max_bytes

    def check(self, content_type: str, size: int) -> str:
        ext = ALLOWED_TYPES.get(content_type)
        if ext is None:
            raise FileRejected("Please upload a photo (JPEG, PNG, WebP or HEIC) or a PDF.")
        if size == 0:
            raise FileRejected("That file is empty.")
        if size > self.max_bytes:
            raise FileRejected(f"That file is too big. The limit is {self.max_bytes // (1024 * 1024)} MB.")
        return ext

    async def save(
        self,
        data: bytes,
        *,
        content_type: str,
        kind: FileKind,
        owner_user_id: str,
        original_name: str = "",
        related: Related | None = None,
    ) -> StoredFile:
        ext = self.check(content_type, len(data))
        now = utcnow()
        rel = f"{kind}/{now:%Y/%m}/{new_token(18)}.{ext}"
        target = self.root / rel
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        return StoredFile(
            kind=kind,
            owner_user_id=owner_user_id,
            path=rel,
            url=f"{self.prefix}/{rel}",
            content_type=content_type,
            size=len(data),
            original_name=original_name[:120],
            related=related or Related(),
            created_at=now,
        )


def make_file_store(settings: Settings) -> LocalFileStore:
    return LocalFileStore(settings)
