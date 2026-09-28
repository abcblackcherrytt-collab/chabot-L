#!/bin/sh
# Chabot管理コンソール（chabot-admin）へのローカル認証プロキシを起動する。
# 使い方: ./scripts/start_admin_proxy.sh  （ポート変更: ADMIN_PROXY_PORT=8081）

set -eu

PROJECT_ID="${CHABOT_ADMIN_PROJECT_ID:-takahashi-451312}"
REGION="${CHABOT_ADMIN_REGION:-asia-northeast1}"
SERVICE="${CHABOT_ADMIN_SERVICE:-chabot-admin}"
PORT="${ADMIN_PROXY_PORT:-8080}"

echo "Starting admin console proxy: http://localhost:${PORT}/admin"
exec npx -y cloud-run-proxy \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service "$SERVICE" \
  --port "$PORT"
