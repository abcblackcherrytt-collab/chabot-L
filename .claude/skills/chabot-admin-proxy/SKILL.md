---
name: chabot-admin-proxy
description: Chabot管理コンソール（chabot-admin / Cloud Run）をブラウザで開くためのローカル認証プロキシを起動する。ユーザーが「管理画面を開いて」「管理UIを見たい」「管理コンソールを使いたい」「admin proxyを起動」等を自然言語で頼んだときに使用する。
---

# Chabot 管理コンソールプロキシ

管理コンソール `chabot-admin` はCloud RunのIAMで保護されている（run_iam認証モード）。
ブラウザから直接開くことはできず、リポジトリ同梱のローカルプロキシ経由で開く。
プロキシは chabot-sa の権限借用でaudience一致のIDトークンを発行する。

## 前提（一度だけ設定済み）

- gcloud が管理者アカウント（abc.blackcherry.tt@gmail.com）で認証済みであること
- そのアカウントへ chabot-sa の `roles/iam.serviceAccountTokenCreator` が付与済み
- Firestore `admin_admins` に `chabot-sa@takahashi-451312.iam.gserviceaccount.com` が登録済み
- リポジトリの venv（google-auth入り）があること

## 手順

1. 認証とvenvの確認:

   ```bash
   gcloud auth list --filter=status:ACTIVE --format='value(account)'
   ls venv/bin/python
   ```

   認証がない場合は `gcloud auth login` を案内する。

2. プロキシをバックグラウンドセッションで起動する:

   ```bash
   ./scripts/start_admin_proxy.sh
   ```

   `admin-proxy: http://localhost:8080/admin ->` の表示を待つ。

3. 動作確認してからユーザーへ伝える:

   - ブラウザで `http://localhost:8080/admin` を開く（ログイン不要・プロキシが認証）
   - 終了したいときはその旨を言ってもらえればプロキシのセッションを終了する

## トラブルシュート

- **403 / PERMISSION_DENIED**: gcloudの認証アカウントに chabot-sa への
  tokenCreator権限がない。プロジェクトオーナーで `gcloud auth login` し直す。
- **401 + reason=invalid_bearer_token**: プロキシが付与したトークンのaudienceと
  サービスの `ADMIN_RUN_IAM_AUDIENCES` が不一致。デプロイ設定を確認する。
- **401 + allowlist由来**: Firestore `admin_admins/chabot-sa@...` が無効化されている。
- **ポート衝突**: `ADMIN_PROXY_PORT=8081 ./scripts/start_admin_proxy.sh` で変更する。
- **google.authが見つからない**: venv/bin/python がない場合。`python3 -m venv venv && venv/bin/pip install -r requirements.txt` を案内する。

## 関連

- プロキシ本体: `scripts/admin_proxy.py`（chabot-sa権限借用・トークンキャッシュ付き）
- 認証実装: `app/core/admin_security.py`（run_iamモード）
- デプロイ先: Cloud Run `chabot-admin`（asia-northeast1 / プロジェクト takahashi-451312）

