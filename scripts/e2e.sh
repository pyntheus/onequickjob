#!/usr/bin/env bash
# make e2e: the Playwright journeys and accessibility checks (e2e/) against the production-style
# stack, at phone (375px) and desktop widths. The demo is re-seeded before each width (the
# journeys use seeded people and change them) and once more at the end, so it's left clean.
# Runs in the cached Playwright image; the site's basic auth comes from .env and is passed by
# variable name only, never on a command line.
#   make e2e                       both widths, every spec
#   make e2e ARGS="tests/a-*.ts"   some specs;  E2E_PROJECTS=phone make e2e   one width
#   E2E_DEV=1 make e2e             against this worktree's dev server (http://localhost:WEB_PORT)
#                                  instead: for a lane that mustn't run make prod-up. There's no
#                                  Caddy there, so the basic-auth spec (x-basic-auth) is skipped.
# (Or E2E_BASE_URL=http://127.0.0.1:517N with COOKIE_SECURE=false in that lane's .env while it
# runs, and without x-basic-auth.spec.ts: E2E_DEV=1 needs neither, as Playwright's API client
# sends the Secure cookie to localhost.)
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble"
PROJECTS="${E2E_PROJECTS:-phone desktop}"
E2E_USER="$(grep -E '^BASIC_AUTH_USER=' .env | cut -d= -f2-)"
E2E_PASS="$(grep -E '^BASIC_AUTH_PASSWORD=' .env | cut -d= -f2- | sed -e "s/^'//" -e "s/'$//")"
SITE_HOST="$(grep -E '^SITE_HOST=' .env | cut -d= -f2-)"
E2E_DEV="${E2E_DEV:-}"
if [ -n "$E2E_DEV" ]; then
  WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2-)"
  # localhost, not 127.0.0.1: both the browser and Playwright's request context send the Secure
  # session cookie to it over plain HTTP (R27).
  E2E_BASE_URL="http://localhost:${WEB_PORT:?set WEB_PORT in .env}"
  curl -fsS -o /dev/null "$E2E_BASE_URL/api/health" ||
    { echo "This worktree's dev server isn't answering on $E2E_BASE_URL: make dev" >&2; exit 1; }
fi
export E2E_USER E2E_PASS E2E_DEV E2E_BASE_URL="${E2E_BASE_URL:-https://${SITE_HOST:-dev.onequickjob.co.uk}}"

[ -n "$E2E_DEV" ] || [ "$(docker inspect -f '{{.State.Health.Status}}' oqj-prod-api 2>/dev/null)" = healthy ] ||
  { echo "The production-style stack isn't running: make prod-up" >&2; exit 1; }

run() {
  docker run --rm --network host --ipc=host --user "$(id -u):$(id -g)" -e HOME=/tmp -e npm_config_cache=/tmp/.npm \
    -e E2E_USER -e E2E_PASS -e E2E_BASE_URL -e E2E_DEV -e CADDY_LOG -v "$PWD/e2e:/e2e" -w /e2e "$IMAGE" "$@"
}
[ -d e2e/node_modules/@playwright/test ] || run npm ci --no-audit --no-fund

# Caddy's access log from now on, for the basic-auth spec (x-basic-auth): it fails on a 401 in its
# run. Credentials and links' tokens are already out of it (the Caddyfile); deleted at the end.
mkdir -p e2e/results
CADDY_LOG=""
if [ -z "$E2E_DEV" ]; then
  access_log=e2e/results/caddy-access.log
  (umask 077; : > "$access_log")
  docker logs -f --since "$(date -u +%Y-%m-%dT%H:%M:%SZ)" oqj-caddy > "$access_log" 2>/dev/null &
  follower=$!
  trap 'kill "$follower" 2>/dev/null; rm -f "$access_log"' EXIT
  CADDY_LOG="/e2e/results/caddy-access.log"
fi
export CADDY_LOG

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
