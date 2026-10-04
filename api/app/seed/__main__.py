"""make seed: python -m app.seed [--reset]

Seeds this worktree's database (MONGO_DB) with the demo data. Without --reset it resets the demo
(removes what demo runs created; keeps admins' pricing versions) and is idempotent: run it as
often as you like. --reset drops the whole database first.
"""

import argparse
import asyncio
import sys

from app.core.config import Settings, get_settings
from app.core.db import connect
from app.seed.run import format_summary, seed


async def main_async(argv: list[str], settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop the database before seeding")
    args = parser.parse_args(argv)
    s = settings or get_settings()
    async with connect(s) as (client, db):
        if args.reset:
            names = sorted(await db.list_collection_names())
            print(f"Dropping database {db.name} ({len(names)} collections: {', '.join(names) or 'none'})")
            await client.drop_database(db.name)
        summary = await seed(db, s)
    print(format_summary(summary))
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async(sys.argv[1:])))


if __name__ == "__main__":
    main()
