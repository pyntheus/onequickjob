"""The Notifier adapter has one implementation, the outbox: see app.services.notify.

There is deliberately no SMS, WhatsApp or email sender in this codebase. Adding one is
an external service and needs a decision first (CLAUDE.md).
"""

from app.services.notify import notify

__all__ = ["notify"]
