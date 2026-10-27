#!/usr/bin/env bash
# Build and ship Pace to the server.
#
#   ./deploy.sh            test, build, upload, restart
#   ./deploy.sh --no-test  skip the test suites
#
# The target comes from .deploy.env (gitignored; see .deploy.env.example), so
# no server address lives in the repo. The server side (systemd units, nginx,
# the Kanidm client) is declared in the NixOS config, not here.
set -euo pipefail
cd "$(dirname "$0")"

[[ -f .deploy.env ]] || { echo "Missing .deploy.env. Copy .deploy.env.example and fill it in." >&2; exit 1; }
# shellcheck disable=SC1091
source .deploy.env
: "${DEPLOY_HOST:?set in .deploy.env}" "${DEPLOY_USER:?set in .deploy.env}"
: "${DEPLOY_APP_DIR:?set in .deploy.env}" "${DEPLOY_WEB_DIR:?set in .deploy.env}"
target="$DEPLOY_USER@$DEPLOY_HOST"

if [[ "${1:-}" != "--no-test" ]]; then
  echo "==> Tests"
  (cd backend && { [[ -x .venv/bin/pytest ]] || { uv venv -q .venv && uv pip install -q -e '.[dev]'; }; } && .venv/bin/pytest -q)
  (cd frontend && npx vitest run)
fi

echo "==> Building the web app"
(cd frontend && npm ci --silent && npm run build)

echo "==> Uploading"
ssh "$target" "mkdir -p '$DEPLOY_APP_DIR/backend'"
rsync -az --delete --exclude '__pycache__' backend/pace/ "$target:$DEPLOY_APP_DIR/backend/pace/"
# As in Foodlog: hashed assets first, index.html last, then prune, so a page
# mid-load never gets a shell pointing at missing files.
rsync -az --exclude 'index.html' frontend/dist/ "$target:$DEPLOY_WEB_DIR/"
rsync -az frontend/dist/index.html "$target:$DEPLOY_WEB_DIR/"
rsync -az --delete frontend/dist/ "$target:$DEPLOY_WEB_DIR/"

echo "==> Restarting"
ssh "$target" 'sudo systemctl restart pace-web pace-worker && systemctl is-active pace-web pace-worker'
echo "Deployed."
