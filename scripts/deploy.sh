#!/usr/bin/env bash
# Ship the committed tree to the demo server, rebuild it and check health through Caddy (ARA-107).
# Usage: SITE_HOST=<public hostname> scripts/deploy.sh <user@host>
# The server keeps its own .env (secrets, COMPOSE_FILE, SITE_ADDRESS) in DEPLOY_DIR.
set -euo pipefail

target="${1:?Usage: SITE_HOST=<hostname> scripts/deploy.sh <user@host>}"
site="${SITE_HOST:?Set SITE_HOST to the public hostname}"
directory="${DEPLOY_DIR:-/opt/ara}"
revision="$(git rev-parse HEAD)"

git archive --format=tar HEAD |
  ssh "$target" "rm -rf ara-staging && mkdir ara-staging && tar -x -C ara-staging"

ssh "$target" "set -e
rsync -a --delete --exclude=/.env ara-staging/ $directory/
echo $revision > $directory/REVISION
cd $directory
docker compose -f compose.yaml -f compose.deploy.yaml up -d --build --wait --remove-orphans
docker image prune -f > /dev/null
curl -fsS --retry 12 --retry-delay 5 --retry-all-errors --resolve $site:443:127.0.0.1 https://$site/health/ready"
