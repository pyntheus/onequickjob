#!/usr/bin/env bash
# make check: fail if anything other than sshd (22) and Caddy (80, 443) is reachable on a
# public interface. Docker publishes ports around ufw, so container port bindings are
# checked directly as well as host sockets.
set -euo pipefail

DOCKER="${DOCKER:-docker}"
ALLOWED_HOST_PORTS=" 22 80 443 "
fail=0

is_loopback() {
  local a="${1%%%*}"          # drop %iface suffix
  a="${a#[}"; a="${a%]}"
  [[ "$a" == 127.* || "$a" == "::1" ]]
}

echo "Host sockets on public interfaces:"
while read -r netid _state _rq _sq local _peer _rest; do
  addr="${local%:*}"; port="${local##*:}"
  if is_loopback "$addr"; then continue; fi
  if [[ "$ALLOWED_HOST_PORTS" == *" $port "* ]]; then
    echo "  ok      $netid $local"
  else
    echo "  EXPOSED $netid $local"; fail=1
  fi
done < <(ss -H -tuln)

echo "Container port bindings:"
while IFS='|' read -r name ports; do
  [[ -z "$name" ]] && continue
  IFS=',' read -ra maps <<< "$ports"
  for m in "${maps[@]}"; do
    m="${m# }"
    [[ "$m" != *"->"* ]] && continue          # exposed inside Docker only, not published
    host="${m%%->*}"; hostaddr="${host%:*}"; hostport="${host##*:}"
    if is_loopback "$hostaddr"; then
      echo "  ok      $name $m"
    elif [[ "$name" == "oqj-caddy" && ( "$hostport" == "80" || "$hostport" == "443" ) ]]; then
      echo "  ok      $name $m"
    else
      echo "  EXPOSED $name $m"; fail=1
    fi
  done
done < <($DOCKER ps --format '{{.Names}}|{{.Ports}}')

if $DOCKER ps --format '{{.Names}}|{{.Ports}}' | grep -q '^oqj-mongo|.*->'; then
  echo "  EXPOSED oqj-mongo publishes a port"; fail=1
fi

if [[ $fail -ne 0 ]]; then
  echo "make check: FAILED. Only Caddy (80, 443) and sshd may listen publicly." >&2
  exit 1
fi
echo "make check: OK. Only sshd and Caddy are public; everything else is loopback or Docker-internal."
