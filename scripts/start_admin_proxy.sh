#!/bin/sh
# Chabot管理コンソール（chabot-admin）へのローカル認証プロキシを起動する。
# 使い方: ./scripts/start_admin_proxy.sh  （ポート変更: ADMIN_PROXY_PORT=8081）

set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PY="$DIR/venv/bin/python"
[ -x "$PY" ] || PY=python3

exec "$PY" "$DIR/scripts/admin_proxy.py"

