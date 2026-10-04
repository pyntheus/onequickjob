#!/usr/bin/env bash
# make e2e: the Playwright journeys and accessibility checks (e2e/) against the production-style
# stack, at phone (375px) and desktop widths. The demo is re-seeded before each width (the
# journeys use seeded people and change them) and once more at the end, so it's left clean.
# Runs in the cached Playwright image; the site's basic auth comes from .env and is passed by
# variable name only, never on a command line.
#   make e2e                       both widths, every spec
#   make e2e ARGS="tests/a-*.ts"   some specs;  E2E_PROJECTS=phone make e2e   one width
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble"
PROJECTS="${E2E_PROJECTS:-phone desktop}"
E2E_USER="$(grep -E '^BASIC_AUTH_USER=' .env | cut -d= -f2-)"
E2E_PASS="$(grep -E '^BASIC_AUTH_PASSWORD=' .env | cut -d= -f2- | sed -e "s/^'//" -e "s/'$//")"
SITE_HOST="$(grep -E '^SITE_HOST=' .env | cut -d= -f2-)"
export E2E_USER E2E_PASS E2E_BASE_URL="${E2E_BASE_URL:-https://${SITE_HOST:-dev.onequickjob.co.uk}}"

[ "$(docker inspect -f '{{.State.Health.Status}}' oqj-prod-api 2>/dev/null)" = healthy ] ||
  { echo "The production-style stack isn't running: make prod-up" >&2; exit 1; }

run() {
  docker run --rm --network host --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e npm_config_cache=/tmp/.npm \
    -e E2E_USER -e E2E_PASS -e E2E_BASE_URL -v "$PWD/e2e:/e2e" -w /e2e "$IMAGE" "$@"
}
[ -d e2e/node_modules/@playwright/test ] || run npm ci --no-audit --no-fund

status=0
for project in $PROJECTS; do
  echo "== $project: re-seeding the demo"
  make --no-print-directory seed >/dev/null 2>&1 || { echo "make seed failed" >&2; exit 1; }
  # Each width keeps its own failure screenshots and traces (e2e/results/<width>).
  run npx playwright test --project="$project" --output="results/$project" "$@" || status=1
done
echo "== leaving the demo freshly seeded"
make --no-print-directory seed >/dev/null 2>&1 || { echo "make seed failed" >&2; exit 1; }
exit $status
