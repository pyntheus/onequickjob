#!/bin/sh
# Hash the basic-auth password from .env, then start Caddy. The plain password is not
# passed on to Caddy's process.
set -eu
: "${BASIC_AUTH_USER:?set BASIC_AUTH_USER in .env}"
: "${BASIC_AUTH_PASSWORD:?set BASIC_AUTH_PASSWORD in .env}"
BASIC_AUTH_HASH="$(caddy hash-password --plaintext "$BASIC_AUTH_PASSWORD")"
export BASIC_AUTH_HASH
unset BASIC_AUTH_PASSWORD
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
