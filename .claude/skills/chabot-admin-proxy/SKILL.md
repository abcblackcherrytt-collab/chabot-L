---
name: chabot-admin-proxy
description: Chabot管理コンソール（chabot-admin / Cloud Run）をブラウザで開くためのcloud-run-proxyを起動する。ユーザーが「管理画面を開いて」「管理UIを見たい」「管理コンソールを使いたい」「admin proxyを起動」等を自然言語で頼んだときに使用する。
---

# Chabot 管理コンソールプロキシ

管理コンソール `chabot-admin` はCloud RunのIAMで保護されている（run_iam認証モード）。
ブラウザから直接開くことはできず、cloud-run-proxy をローカルで起動して開く。

## 前提

- gcloud が管理者アカウントで認証済みであること
- Node.js / npx が使えること
- 管理者のメールアドレスが Firestore `admin_admins/{email}`（enabled: true）に登録済みであること

## 手順

1. 認証とnodeの確認:

   ```bash
   gcloud auth list --filter=status:ACTIVE --format='value(account)'
   node --version
   ```

   認証がない場合は `gcloud auth login` を案内する。

2. プロキシをバックグラウンドセッションで起動する（リポジトリのスクリプトを使用）:

   ```bash
   ./scripts/start_admin_proxy.sh
   ```

   初回は npx がパッケージを取得するため数十秒かかる。
   `Proxy serving at` のような表示を待ってから次へ進む。

3. ユーザーへ伝える:

   - ブラウザで `http://localhost:8080/admin` を開く
   - 終了したいときはその旨を言ってもらえればプロキシのセッションを終了する

## トラブルシュート

- **403 / 起動失敗（PERMISSION_DENIED）**: 認証アカウントにこのサービスの呼び出し権限がない。
  プロジェクト オーナー権限のあるアカウントで `gcloud auth login` し直す。
- **ポート衝突**: 環境変数 `ADMIN_PROXY_PORT=8081 ./scripts/start_admin_proxy.sh` 等で変更する。
- **画面に「管理者として認証されていません」**: Bearerトークンが届いていない、
  `ADMIN_RUN_IAM_AUDIENCES` 設定とプロキシのサービスURLが一致していない、
  または Firestore `admin_admins` にメールが未登録のいずれか。
- **セッションCookieが消失する**: cloud-run-proxy 既定の http://localhost は
  モダンブラウザでセキュアコンテキストとして扱われる。古いブラウザの場合は Chrome/Firefox/Safari の最新版を使う。

## 関連

- 認証実装: `app/core/admin_security.py`（run_iamモード）
- デプロイ先: Cloud Run `chabot-admin`（asia-northeast1 / プロジェクト takahashi-451312）

