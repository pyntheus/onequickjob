#!/usr/bin/env bash
# make backup-timer: install the nightly backup as a systemd timer (system-wide, so it runs
# whether or not anyone is logged in). Needs sudo for /etc/systemd/system; the backup itself runs
# as you (you're in the docker group). Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$(pwd)"
user="$(id -un)"
for unit in oqj-backup.service oqj-backup.timer; do
  sed -e "s|@USER@|$user|g" -e "s|@ROOT@|$root|g" "infra/systemd/$unit" |
    sudo install -m 644 /dev/stdin "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now oqj-backup.timer
systemctl list-timers oqj-backup.timer --no-pager
