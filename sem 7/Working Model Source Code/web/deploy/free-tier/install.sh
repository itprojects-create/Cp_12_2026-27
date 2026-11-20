#!/usr/bin/env bash
# Run on a fresh Ubuntu 24.04 Always Free VM after transferring the private bundle.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo bash install.sh'; exit 1; fi
if [[ ! -f .env || ! -f secrets/web.env || ! -f secrets/agent.env ]]; then
  echo 'Missing generated deployment environment files'; exit 1
fi
if grep -Eq '^APP_DOMAIN=.*\.invalid$' .env; then
  echo 'Validation-only hostname: regenerate the bundle with the real public hostname'; exit 1
fi
if ! command -v docker >/dev/null; then
  . /etc/os-release
  [[ $ID == ubuntu ]] || { echo 'This installer supports Ubuntu only'; exit 1; }
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
chmod 700 secrets
chmod 600 secrets/*.env .env
docker compose config --quiet
# Sequential builds leave more RAM for the small free VM.
docker compose build agent
docker compose build web
mkdir -p state/agent-data state/fyers state/caddy-data state/caddy-config backups
agent_uid=$(docker compose run --rm --no-deps --entrypoint id agent -u)
agent_gid=$(docker compose run --rm --no-deps --entrypoint id agent -g)
chown -R "$agent_uid:$agent_gid" state/agent-data state/fyers backups
chmod 700 state/agent-data state/fyers backups
echo 'Images built. Containers are not started and cron is not installed.'
echo 'Finish the final data snapshot, local-worker handoff, DNS and auth redirects first.'
