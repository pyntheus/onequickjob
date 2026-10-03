"""Tax data key rotation, the steps of `make rotate-tax-key`:

    python -m app.cli.tax_keys add --env-file ../.env      (host) a new key, made current; old keys kept
    python -m app.cli.tax_keys reencrypt                   (api container) re-seal every older value
    python -m app.cli.tax_keys retire --env-file ../.env   (host) drop the old keys, once reencrypt passed

Between add and retire every key stays in TAX_DATA_KEYS, so old values can be read while
they're re-encrypted. reencrypt fails (and make stops before retire) unless no value is left
under an older key. Only key ids are ever printed, never keys.
"""

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings, parse_tax_keys
from app.core.crypto import SEALED_FIELDS, reseal
from app.core.db import Db, connect

KEYS, CURRENT = "TAX_DATA_KEYS", "TAX_DATA_KEY_CURRENT"


def _get(lines: list[str], name: str) -> str:
    return next((line.split("=", 1)[1].strip() for line in lines if line.startswith(f"{name}=")), "")


def _set(lines: list[str], name: str, value: str) -> list[str]:
    if any(line.startswith(f"{name}=") for line in lines):
        return [f"{name}={value}" if line.startswith(f"{name}=") else line for line in lines]
    return [*lines, f"{name}={value}"]


def _write(path: Path, lines: list[str]) -> None:
    """Replace the file atomically, keeping its permissions (.env is 0600)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _joined(keys: dict[str, bytes]) -> str:
    return ",".join(f"{kid}:{key.decode()}" for kid, key in keys.items())


def add_key(path: Path) -> str:
    """Append a new key to TAX_DATA_KEYS and make it current. Returns its id."""
    lines = path.read_text().splitlines()
    keys = parse_tax_keys(_get(lines, KEYS))
    n = max((int(m[1]) for kid in keys if (m := re.fullmatch(r"k(\d+)", kid))), default=0) + 1
    kid = f"k{n}"
    keys[kid] = Fernet.generate_key()
    _write(path, _set(_set(lines, KEYS, _joined(keys)), CURRENT, kid))
    return kid


def retire_keys(path: Path) -> list[str]:
    """Keep only the current key in TAX_DATA_KEYS. Returns the ids removed."""
    lines = path.read_text().splitlines()
    keys, current = parse_tax_keys(_get(lines, KEYS)), _get(lines, CURRENT)
    if current not in keys:
        raise SystemExit(f"{CURRENT} ({current!r}) isn't in {KEYS}: nothing retired")
    _write(path, _set(lines, KEYS, _joined({current: keys[current]})))
    return [kid for kid in keys if kid != current]


def _older(current: str, fields: tuple[str, ...]) -> dict:
    """Documents holding a value sealed with any key but the current one."""
    other = {"$type": "string", "$not": re.compile(f"^{re.escape(current)}:")}
    return {"$or": [{f: other} for f in fields]}


async def reencrypt(db: Db, s: Settings) -> tuple[int, int]:
    """Re-seal every value not under the current key. Returns (values re-sealed, values still
    under an older key). Each record is a compare-and-set on the values it read, so a record
    changed meanwhile is left alone (and counted as left over if it still needs doing)."""
    done = 0
    for coll, fields in SEALED_FIELDS.items():
        async for doc in db[coll].find(_older(s.tax_data_key_current, fields)):
            changes = {f: new for f in fields if isinstance(doc.get(f), str) and (new := reseal(doc[f], s))}
            res = await db[coll].update_one({"_id": doc["_id"], **{f: doc[f] for f in changes}}, {"$set": changes})
            done += len(changes) * res.modified_count
    left = 0
    for coll, fields in SEALED_FIELDS.items():
        left += await db[coll].count_documents(_older(s.tax_data_key_current, fields))
    return done, left


async def _reencrypt_main() -> int:
    s = get_settings()
    async with connect(s) as (_, db):
        done, left = await reencrypt(db, s)
    print(f"Re-encrypted {done} tax values in {s.mongo_db} with key {s.tax_data_key_current}.")
    if left:
        print(f"{left} records still hold values under an older key: run it again.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.tax_keys", description=__doc__)
    parser.add_argument("step", choices=["add", "reencrypt", "retire"])
    parser.add_argument("--env-file", type=Path, default=Path("../.env"))
    args = parser.parse_args(argv)
    if args.step == "add":
        kid = add_key(args.env_file)
        print(f"Added tax data key {kid} and made it current; the older keys stay until re-encryption completes.")
    elif args.step == "retire":
        old = retire_keys(args.env_file)
        print(f"Retired tax data keys: {', '.join(old) or 'none'}. Update your password manager's TAX_DATA_KEYS.")
    else:
        return asyncio.run(_reencrypt_main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
