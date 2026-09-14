#!/bin/sh
# Block until a TCP port on the host accepts a connection, or time out.
#
#   sh scripts/wait_for_port.sh <host> <port> [timeout_seconds]
#
# Used by `make e2e` and by CI to gate a test run on the compose stack being
# reachable, instead of sleeping a guessed number of seconds.

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "usage: $0 <host> <port> [timeout_seconds]" >&2
    exit 2
fi

host="$1"
port="$2"
timeout="${3:-60}"

case "$timeout" in
    ''|*[!0-9]*) echo "timeout must be a whole number of seconds, got '$timeout'" >&2; exit 2 ;;
esac

probe() {
    if command -v nc >/dev/null 2>&1; then
        nc -z "$host" "$port" >/dev/null 2>&1
    else
        # /dev/tcp is a bash/zsh feature; fall back to it only when nc is absent.
        (exec 3<>"/dev/tcp/$host/$port") >/dev/null 2>&1
    fi
}

elapsed=0
while [ "$elapsed" -lt "$timeout" ]; do
    if probe; then
        echo "$host:$port is accepting connections after ${elapsed}s"
        exit 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

echo "timed out after ${timeout}s waiting for $host:$port" >&2
exit 1
