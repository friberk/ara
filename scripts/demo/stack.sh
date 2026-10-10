#!/usr/bin/env bash
# Isolated Compose project for recording the demo video (ARA-113).
# It runs beside the dev stack on its own ports and volumes; only "ara-demo" is ever touched.
set -euo pipefail

PROJECT=ara-demo
API_PORT=8012
FRONTEND_PORT=5182

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
root="$(dirname "$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)")"
env_file="${DEMO_ENV_FILE:-$root/.env}"

if [[ "$PROJECT" != "ara-demo" ]]; then
  echo "refusing to manage project '$PROJECT'; this script only manages ara-demo" >&2
  exit 2
fi
if [[ ! -f "$env_file" ]]; then
  echo "missing $env_file (run python3 scripts/bootstrap.py and add the OpenAI and OpenAlex keys)" >&2
  exit 2
fi

# Shell values win over the env file, which pins the dev ports and origins.
export COMPOSE_PROJECT_NAME="$PROJECT"
export API_PORT FRONTEND_PORT
export CORS_ORIGINS="[\"http://localhost:$FRONTEND_PORT\",\"http://127.0.0.1:$FRONTEND_PORT\"]"

compose() {
  docker compose --project-directory "$repo" -f "$repo/compose.yaml" --env-file "$env_file" -p "$PROJECT" "$@"
}

wait_ready() {
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:$API_PORT/health/ready" >/dev/null 2>&1 &&
      curl -fsS "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1; then
      echo "ara-demo is ready: http://localhost:$FRONTEND_PORT (API $API_PORT)"
      return 0
    fi
    sleep 2
  done
  echo "ara-demo did not become ready" >&2
  compose ps >&2
  return 1
}

case "${1:-}" in
  reset)
    # Empty database, object store and Redis: no papers, chats or search history.
    compose down --volumes --remove-orphans
    compose up -d --wait
    wait_ready
    ;;
  up)
    compose up -d --wait
    wait_ready
    ;;
  restart)
    # Restarts every service, database included; the volumes and their data stay.
    compose stop
    compose up -d --wait
    wait_ready
    ;;
  down)
    compose down
    ;;
  ps)
    compose ps
    ;;
  logs)
    shift
    if [[ $# -eq 0 ]]; then set -- api worker; fi
    compose logs --tail "${TAIL:-100}" "$@"
    ;;
  *)
    echo "usage: $0 reset|up|restart|down|ps|logs [services]" >&2
    exit 2
    ;;
esac
