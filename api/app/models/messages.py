"""message_threads and messages. Owner: F; every lane posts through app.repos.messages."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.common import Model, Role, Timestamped


class Participant(Model):
    user_id: str
    role: Role
    name: str


class MessageThread(Timestamped):
    COLLECTION: ClassVar[str] = "message_threads"

    kind: Literal["booking", "dispute", "support"]
    booking_id: str | None = None
    dispute_id: str | None = None
    participants: list[Participant]
    last_message_at: datetime | None = None
    last_message_preview: str = ""


class Message(Timestamped):
    COLLECTION: ClassVar[str] = "messages"

    thread_id: str
    sender_user_id: str | None = Field(description="None for system messages")
    sender_role: Role | Literal["system"]
    body: str
    attachments: list[str] = Field(default_factory=list, description="File ids")
    read_by: list[str] = Field(default_factory=list)
