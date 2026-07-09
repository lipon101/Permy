#!/usr/bin/env bash
# Permy — one-command deploy helper for Render / Fly / Railway.
#
# Usage:
#   ./deploy/render.sh   # deploy to Render (free-tier friendly)
#   ./deploy/fly.sh      # deploy to Fly.io
#
# Both paths: build the Docker image, run schema + seed on first deploy, then
# the platform serves uvicorn. Cron (daily ingest) is configured in the
# platform dashboard — see docs/OPS.md for the per-city schedule.
set -euo pipefail

TARGET="${1:-render}"

case "$TARGET" in
  render)
    echo "→ Render deploy"
    echo "  1. Push to GitHub (Render builds from the Dockerfile on push)."
    echo "  2. In Render dashboard: New → Web Service → connect repo → Plan: Free."
    echo "  3. Set env vars (PERMY_ENV=prod, PERMY_API_KEYS, PERMY_WEBHOOK_SECRET, PERMY_BASE_URL)."
    echo "  4. New → PostgreSQL (Free) → link to web service (DATABASE_URL auto-injected)."
    echo "  5. In the web service shell, run once:"
    echo "       psql \"\$DATABASE_URL\" -f permy/db/schema.sql"
    echo "       python -m permy.scripts.seed"
    echo "  6. New → Cron Job → 'permy-ingest austin-tx nyc-ny chicago-il sf-ca seattle-wa la-ca miami-fl orlando-fl fortworth-tx' → daily 06:00 UTC."
    echo "  7. Smoke: curl https://<your-service>.onrender.com/v1/health"
    ;;
  fly)
    echo "→ Fly.io deploy"
    if ! command -v fly >/dev/null 2>&1; then
      echo "  Install flyctl first: curl -L https://fly.io/install.sh | sh"
      exit 1
    fi
    fly deploy --remote-only
    echo "  → set secrets: fly secrets set PERMY_ENV=prod PERMY_API_KEYS=$(openssl rand -hex 24) PERMY_WEBHOOK_SECRET=$(openssl rand -hex 32)"
    echo "  → create PG:  fly postgres create  (then fly attach)"
    echo "  → run schema: fly ssh console -C 'psql \$DATABASE_URL -f permy/db/schema.sql'"
    echo "  → seed:       fly ssh console -C 'python -m permy.scripts.seed'"
    echo "  → cron:       fly cron create --command 'permy-ingest austin-tx nyc-ny chicago-il sf-ca seattle-wa la-ca miami-fl orlando-fl fortworth-tx' --schedule '0 6 * * *'"
    ;;
  *)
    echo "Unknown target: $TARGET (use 'render' or 'fly')"
    exit 1
    ;;
esac
