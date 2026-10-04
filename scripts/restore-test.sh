#!/usr/bin/env bash
# make restore-test: restore the latest backup into a scratch database (<MONGO_DB>_restore_test),
# compare the document count of every collection with the live database, then drop the scratch
# database (always, even on failure). Exits non-zero if the restore fails, a collection is
# missing, or a count differs. Counts only match exactly if nothing was written since the backup:
# for an exact check, run make backup-now first.
set -euo pipefail
cd "$(dirname "$0")/.."
MONGO_DB="${MONGO_DB:-$(grep -E '^MONGO_DB=' .env | cut -d= -f2-)}"
BACKUP_DIR="${BACKUP_DIR:-/srv/oqj/backups}"
SCRATCH="${MONGO_DB}_restore_test"
case "$MONGO_DB" in oqj*) ;; *) echo "refusing: $MONGO_DB is not a OneQuickJob database" >&2; exit 1 ;; esac

latest="$(ls -1t "$BACKUP_DIR"/"$MONGO_DB"-*.archive.gz 2>/dev/null | head -1 || true)"
[ -n "$latest" ] || { echo "No backups of $MONGO_DB in $BACKUP_DIR. Run make backup-now." >&2; exit 1; }

drop_scratch() { docker exec oqj-mongo mongosh --quiet "$SCRATCH" --eval 'db.dropDatabase()' >/dev/null; }
trap drop_scratch EXIT
drop_scratch

echo "Restoring $(basename "$latest") into $SCRATCH..."
docker exec -i oqj-mongo mongorestore --archive --gzip --quiet --drop \
  --nsFrom="${MONGO_DB}.*" --nsTo="${SCRATCH}.*" < "$latest"

docker exec oqj-mongo mongosh --quiet --eval "
  const live = db.getSiblingDB('$MONGO_DB'), restored = db.getSiblingDB('$SCRATCH');
  const names = [...new Set([...live.getCollectionNames(), ...restored.getCollectionNames()])]
    .filter((n) => !n.startsWith('system.')).sort();
  let bad = 0, total = 0;
  print('collection'.padEnd(26) + 'live'.padStart(8) + 'restored'.padStart(10));
  for (const n of names) {
    const a = live.getCollection(n).countDocuments({}), b = restored.getCollection(n).countDocuments({});
    total += b;
    const flag = a === b ? '' : '   DIFFERENT';
    if (a !== b) bad++;
    print(n.padEnd(26) + String(a).padStart(8) + String(b).padStart(10) + flag);
  }
  print('');
  if (total === 0) { print('The restore is empty.'); quit(1); }
  if (bad) { print(bad + ' collection(s) differ (written since the backup? run make backup-now first).'); quit(1); }
  print('All ' + names.length + ' collections match (' + total + ' documents).');
"
echo "make restore-test: OK ($(basename "$latest") restores; scratch database dropped)"
