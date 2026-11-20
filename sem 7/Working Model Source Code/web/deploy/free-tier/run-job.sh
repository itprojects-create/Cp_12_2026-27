#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
case "${1:-}" in
  settle|daily|tournament|catchup|status) ;;
  *) echo 'Unsupported forecast job'; exit 1 ;;
esac
# Prevent overlapping scheduled jobs on this machine.
exec 9>/var/lock/quantplus-forecast.lock
flock -n 9 || exit 0
docker compose exec -T agent python -B -m quantplus_intelligence.forecast.jobs "$@"
