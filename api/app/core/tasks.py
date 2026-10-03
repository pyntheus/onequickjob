"""Periodic background tasks (reminders, horizon top-ups), run inside the API.

Each lane registers tasks from its own package (app/<lane>/tasks.py) with @periodic;
main.py imports those modules so registration happens at start-up. Tasks must be
idempotent: they may run more than once and on more than one worktree's API (each
against its own database). Disabled in tests (TASKS_ENABLED=false).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.config import Settings
from app.core.db import Db

log = logging.getLogger("oqj.tasks")

type TaskFn = Callable[[Db, Settings], Awaitable[None]]


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    every_seconds: int
    fn: TaskFn


REGISTRY: dict[str, PeriodicTask] = {}


def periodic(name: str, every_seconds: int) -> Callable[[TaskFn], TaskFn]:
    def wrap(fn: TaskFn) -> TaskFn:
        REGISTRY[name] = PeriodicTask(name, every_seconds, fn)
        return fn

    return wrap


async def run_once(db: Db, s: Settings, names: list[str] | None = None) -> None:
    for t in REGISTRY.values():
        if names is None or t.name in names:
            try:
                await t.fn(db, s)
            except Exception:
                log.exception("task %s failed", t.name)


async def _loop(db: Db, s: Settings) -> None:
    last: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    while True:
        now = loop.time()
        for t in list(REGISTRY.values()):
            if now - last.get(t.name, -1e9) >= t.every_seconds:
                last[t.name] = now
                try:
                    await t.fn(db, s)
                except Exception:
                    log.exception("task %s failed", t.name)
        await asyncio.sleep(s.tasks_interval_seconds)


def start(db: Db, s: Settings) -> asyncio.Task | None:
    return asyncio.create_task(_loop(db, s), name="oqj-tasks") if s.tasks_enabled else None


async def stop(task: asyncio.Task | None) -> None:
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
