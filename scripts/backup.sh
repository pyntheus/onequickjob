#!/usr/bin/env bash
# Back up the demo database: a gzipped mongodump archive in BACKUP_DIR (default /srv/oqj/backups).
# Run nightly at 03:00 Europe/London by the systemd timer oqj-backup.timer (make backup-timer)
# and on demand by make backup-now. Archives older than 14 days are removed.
#
# A restore also needs TAX_DATA_KEYS (Hasan's password manager): tax identifiers in the dump are
# encrypted with it, and the key is not in the backup. See README.md, "Backups and restores".
set -euo pipefail
cd "$(dirname "$0")/.."
MONGO_DB="${MONGO_DB:-$(grep -E '^MONGO_DB=' .env | cut -d= -f2-)}"
BACKUP_DIR="${BACKUP_DIR:-/srv/oqj/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
case "$MONGO_DB" in oqj*) ;; *) echo "refusing to back up $MONGO_DB: not a OneQuickJob database" >&2; exit 1 ;; esac

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"  # customer and provider data
# One backup at a time: the nightly timer and make backup-now can overlap, and a second run
# must never unpause the APIs the first has paused. The lock is held until this script exits.
exec 9>"$BACKUP_DIR/.backup.lock"
flock -w 300 9 || { echo "Another backup has been running for 5 minutes: not starting a second." >&2; exit 1; }

stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
out="$BACKUP_DIR/${MONGO_DB}-${stamp}.archive.gz"
umask 077

# mongodump reads one collection after another, so a write landing meanwhile (a charge and its
# ledger entries, say) could be half in the archive. Every API writing to this database (dev and
# production-style; their periodic tasks run inside them) is paused for the dump, which takes a
# second or two: requests wait, nothing fails. Only the containers this run paused are unpaused,
# however the dump ends; one somebody else paused stays paused (and is quiet anyway).
paused=()
resume() { [ ${#paused[@]} -eq 0 ] || docker unpause "${paused[@]}" >/dev/null 2>&1 || true; }
trap resume EXIT
for c in $(docker ps --format '{{.Names}}' | grep -E '^oqj-.+-api$' || true); do
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$c" | grep -qx "MONGO_DB=$MONGO_DB" || continue
  [ "$(docker inspect -f '{{.State.Paused}}' "$c")" = false ] || continue
  docker pause "$c" >/dev/null
  paused+=("$c")
done
docker exec oqj-mongo mongodump --db="$MONGO_DB" --archive --gzip --quiet > "$out.partial"
resume
trap - EXIT
mv "$out.partial" "$out"
# Docker counts a container unhealthy from its unpause until its next healthcheck (up to 15s):
# wait for that, so a make status straight after a backup tells the truth.
for c in ${paused[@]+"${paused[@]}"}; do
  for _ in $(seq 1 30); do
    h="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c")"
    if [ "$h" = healthy ] || [ "$h" = none ]; then break; fi
    sleep 1
  done
done

# Keep 14 days: an archive is removed once it's 14 or more days old (find counts whole days).
find "$BACKUP_DIR" -maxdepth 1 -name "${MONGO_DB}-*.archive.gz" -mtime "+$((KEEP_DAYS - 1))" -print -delete |
  sed 's/^/Removed old backup /'
find "$BACKUP_DIR" -maxdepth 1 -name '*.partial' -mmin +120 -delete
echo "Backed up $MONGO_DB to $out ($(du -h "$out" | cut -f1))"
