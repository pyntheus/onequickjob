#!/usr/bin/env bash
# make status: the OneQuickJob containers and their health, then the production-style API's health
# directly (loopback) and through Caddy with the basic auth from .env, and the web app's shell.
# Exits non-zero if anything is down. The password is never printed or put on a command line:
# curl reads it from stdin.
set -uo pipefail
cd "$(dirname "$0")/.."
SITE_HOST="${SITE_HOST:-dev.onequickjob.co.uk}"
PROD_API_PORT="${PROD_API_PORT:-8090}"
fail=0

user="$(grep -E '^BASIC_AUTH_USER=' .env | cut -d= -f2-)"
pass="$(grep -E '^BASIC_AUTH_PASSWORD=' .env | cut -d= -f2- | sed -e "s/^'//" -e "s/'$//")"

echo "Containers:"
docker ps -a --filter name='^oqj-' --format '  {{.Names}}\t{{.Status}}' | sort
for c in oqj-mongo oqj-caddy oqj-prod-api; do
  state="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$c" 2>/dev/null || echo missing)"
  case "$state" in
    "running healthy" | "running no-healthcheck") ;;
    *) echo "  PROBLEM $c: $state"; fail=1 ;;
  esac
done

# Caddy sends /api to the production-style API (an older .env could still name the dev API).
upstream="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' oqj-caddy 2>/dev/null | sed -n 's/^CADDY_API_UPSTREAM=//p')"
printf 'Caddy sends /api to: %s' "${upstream:-?}"
if [ "$upstream" = oqj-prod-api:8000 ]; then echo; else
  echo " (expected oqj-prod-api:8000: fix or remove CADDY_API_UPSTREAM in .env, then make infra-up)"; fail=1
fi

# /api/health answers 200 even when the API can't reach Mongo ("degraded"): read the body.
healthy() { grep -q '"status":"ok"' <<<"$1" && grep -q '"db":"ok"' <<<"$1"; }
printf 'API, direct (127.0.0.1:%s): ' "$PROD_API_PORT"
if out="$(curl -fsS --max-time 5 "http://127.0.0.1:${PROD_API_PORT}/api/health")" && healthy "$out"; then echo "$out"
else echo "DOWN ${out:-}"; fail=1; fi

through_caddy() {  # path -> body (basic auth from stdin, the public name resolved to this machine)
  printf 'user = "%s:%s"\n' "$user" "$pass" |
    curl -K - -fsS --max-time 10 --resolve "${SITE_HOST}:443:127.0.0.1" "https://${SITE_HOST}$1"
}
printf 'API, through Caddy (https://%s/api/health): ' "$SITE_HOST"
if out="$(through_caddy /api/health)" && healthy "$out"; then echo "$out"; else echo "DOWN ${out:-}"; fail=1; fi
printf 'Web app, through Caddy (https://%s/p): ' "$SITE_HOST"
shell="$(through_caddy /p || true)"
if grep -q '<div id="root">' <<<"$shell" && ! grep -q '/@vite/client' <<<"$shell"; then echo "served (built)"
else echo "NOT SERVED (or not the built app)"; fail=1; fi
printf 'Without the password: '
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve "${SITE_HOST}:443:127.0.0.1" "https://${SITE_HOST}/")"
if [ "$code" = 401 ]; then echo "401, as it should be"; else echo "$code (expected 401)"; fail=1; fi

if [ "$fail" -ne 0 ]; then echo "make status: PROBLEMS (see above)" >&2; exit 1; fi
echo "make status: OK"
