Chabot LINE 残タスクリスト
============================
最終更新: 2026-06-11

## 🔴 必須（本番稼働前に完了させること）

### GCP インフラ構築
- [x] GCP プロジェクト作成（または既存プロジェクトの選定）
  - ✅ プロジェクト `takahashi-451312` 存在確認（gcloud 確認済み）
- [x] 課金設定を有効化
  - ✅ API が有効化されているため課金は有効と推測
- [x] 必要な API を有効化
  - [x] Cloud Run Admin API — ✅ 有効
  - [x] Artifact Registry API — ✅ 有効
  - [x] Cloud SQL Admin API — ✅ 有効
  - [x] Secret Manager API — ✅ 有効
  - [x] Vertex AI API — ✅ 有効
  - [x] Cloud Scheduler API — ✅ 有効
  - [x] Cloud Logging API — ✅ 有効
  - [x] IAM Credentials API — ✅ 有効
- [ ] Cloud SQL (PostgreSQL 16) インスタンス作成
  - ⚠️ `chabot-dev` が存在するが **SUSPENDED** 状態・リージョン `us-west1-a`（要: asia-northeast1）・PostgreSQL 18（要: 16）
  - [ ] インスタンス名: chabot-postgres（例）
  - [ ] リージョン: asia-northeast1
  - [ ] マシンタイプ: db-f1-micro（開発）db-custom-1-3840（本番）
  - [ ] 自動バックアップを有効化
  - [ ] プライベート IP を有効化（セキュリティ推奨）
  - [ ] データベース作成: `chabot`
  - [ ] データベースユーザー作成 & パスワード設定
- [x] Artifact Registry リポジトリ作成
  ✅ `chabot-repo` 作成済み（asia-northeast1、Docker形式）
  ```bash
  gcloud artifacts repositories create chabot-repo \
    --repository-format=docker \
    --location=asia-northeast1
  ```
- [ ] VPC コネクタ作成（Cloud Run → Cloud SQL 接続用）
  - ⚠️ asia-northeast1 にコネクタなし
  ```bash
  gcloud compute networks vpc-access connectors create chabot-connector \
    --region=asia-northeast1 \
    --range=10.8.0.0/28
  ```
- [x] Cloud Run の Cloud SQL 接続設定を deploy.yml に追加
  - ✅ `--set-cloudsql-instances` フラグを追加済み

### サービスアカウント & IAM
- [x] Cloud Run 用サービスアカウント作成
  - ✅ `chabot-sa@takahashi-451312.iam.gserviceaccount.com` 存在確認
- [x] 必要な IAM ロールを付与
  - ✅ 以下4ロールを `chabot-sa` に付与済み:
  - [x] `roles/secretmanager.secretAccessor` — Secret Manager 読み取り
  - [x] `roles/cloudsql.client` — Cloud SQL 接続
  - [x] `roles/aiplatform.user` — Vertex AI RAG 利用
  - [x] `roles/logging.logWriter` — Cloud Logging 書き込み
- [x] Workload Identity Federation 設定（GitHub Actions → GCP 認証）
  - [x] Workload Identity Pool 作成 — ✅ `github-actions-pool` 存在確認
  - [x] Workload Identity Provider 作成（GitHub OIDC）— ✅ `github-actions-provider` 存在確認
  - [x] サービスアカウントに GitHub リポジトリのバインディングを追加
    - ✅ `github-actions-deploy@takahashi-451312.iam.gserviceaccount.com` に `abcblackcherrytt-collab/chabot-L` をバインディング
      - `roles/iam.workloadIdentityUser` を `principalSet://.../attribute.repository/abcblackcherrytt-collab/chabot-L` に付与
      - Provider の `attribute_condition` にも `chabot-L` を追加（既存 `ai-podcast` / `python_quiz` は保持）

### GitHub Actions Secrets
- [x] `GCP_PROJECT_ID` — GCP プロジェクト ID
- [x] `GCP_WORKLOAD_IDENTITY_PROVIDER` — Workload Identity Provider のフルパス
- [x] `GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT` — GitHub Actions 用サービスアカウント
- [x] `GCP_SERVICE_ACCOUNT` — Cloud Run 用サービスアカウント

### Google Secret Manager 登録
deploy.yml の `--set-secrets` で参照される全シークレットを登録：

✅ LINE 関連4シークレットは登録済み。⚠️ 残り Stripe/JWT/Google/DB は未登録（.env の値はテスト用/プレースホルダーなので本番値の用意が必要）。✅ 旧 Discord 用シークレット（`DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `discord_api_base_url`, `discord_webhook_secret`, `APPLICATION_ID`, `PUBLIC_KEY`）は削除済み。

**LINE Messaging API:**
- [x] `line-channel-secret` — LINE Messaging API チャネルシークレット（✅ 登録済み）
- [x] `line-channel-access-token` — LINE Messaging API チャネルアクセストークン（長期）（✅ 登録済み）

**LINE Login (OIDC):**
- [x] `line-login-channel-id` — LINE Login チャネル ID（✅ 登録済み）
- [x] `line-login-channel-secret` — LINE Login チャネルシークレット（✅ 登録済み）

**Stripe:**
- [x] `stripe-secret-key` — Stripe シークレットキー（✅ テストキー `sk_test_...` で登録済み・本番切替時に `sk_live_...` に更新）
- [x] `stripe-webhook-secret` — Stripe Webhook 署名シークレット（✅ テスト値 `whsec_...` で登録済み・本番切替時に更新）
- [x] `stripe-publishable-key` — Stripe パブリッシャブルキー（✅ テストキー `pk_test_...` で登録済み・本番切替時に `pk_live_...` に更新）

**認証:**
- [ ] `jwt-secret-keys` — JWT 署名キー（カンマ区切りで複数対応）
  - ℹ️ .env にプレースホルダー `your-secret-key-1,your-secret-key-2` あり（本番値の生成が必要）
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```

**Google Cloud Vertex AI:**
- [ ] `google-project-id` — GCP プロジェクト ID
  - ℹ️ .env は `your-project-id`（プレースホルダー）— 実際は `takahashi-451312`
- [ ] `google-location` — Vertex AI リージョン（例: `asia-northeast1`）
  - ℹ️ .env に `asia-northeast1` 設定済み
- [ ] `google-corpus-id` — RAG コーパス ID
  - ℹ️ .env は `your-corpus-id`（プレースホルダー）

**データベース:**
- [ ] `database-url` — PostgreSQL 接続 URL
  - ℹ️ .env にローカル開発用URL `postgresql+asyncpg://root:...@localhost:5432/chabot` あり
  ```
  postgresql+asyncpg://<user>:<password>@/<db>?host=/cloudsql/<project>:<region>:<instance>
  ```

**登録コマンド例:**
```bash
echo -n "YOUR_SECRET_VALUE" | gcloud secrets create SECRET_NAME --data-file=-
```

### LINE Developers 設定
- [ ] LINE Developers アカウント登録（https://developers.line.biz）
- [ ] プロバイダー作成
- [ ] Messaging API チャネル作成
  - [ ] Channel Secret 取得 → Secret Manager の `line-channel-secret` に登録
  - [ ] Channel Access Token（長期）取得 → Secret Manager の `line-channel-access-token` に登録
  - [ ] Webhook URL 設定 → `https://<Cloud Run URL>/api/v1/webhooks/line`
  - [ ] 「Webhook の利用」をオン
  - [ ] 「自動応答メッセージ」をオフ
  - [ ] 「友だち追加挨拶」をオフ（またはカスタムメッセージ設定）
- [ ] LINE Login チャネル作成（または同一チャネルで有効化）
  - [ ] Channel ID 取得 → Secret Manager の `line-login-channel-id` に登録
  - [ ] Channel Secret 取得 → Secret Manager の `line-login-channel-secret` に登録
  - [ ] コールバックURL設定（本番URL）→ `https://<Cloud Run URL>/api/v1/auth/line/callback`
  - [ ] BOT プロンプト設定（任意）
- [ ] リッチメニュー作成（LINE Official Account Manager で設定）
- [ ] 本番チャネル審査申請（LINE Login を本番利用する場合）

### データベース
- [x] Alembic マイグレーション作成
  ```bash
  alembic revision --autogenerate -m "add line_user_id to users"
  alembic upgrade head
  ```
- [x] マイグレーション内容確認（line_user_id カラムが users テーブルに追加されること）
- [ ] 初回デプロイ前に Cloud SQL でマイグレーションを実行
  ```bash
  # Cloud SQL Proxy 経由で実行
  cloud_sql_proxy -instances=<PROJECT>:asia-northeast1:<INSTANCE>=tcp:5432 &
  alembic upgrade head
  ```

### セキュリティ（重要）
- [ ] security.py: RS256 署名検証の本番実装
  - https://api.line.me/oauth2/v2.1/certs から JWKS 公開鍵を取得
  - ID トークンの署名を公開鍵で検証するロジックを実装
  - 現在はクレーム検証のみで署名検証がスキップされている（TODOコメント箇所）
- [ ] Stripe Webhook Secret を本番用に更新
- [ ] CORS_ALLOWED_ORIGINS を本番URLに設定
  - Cloud Run の環境変数または Secret Manager に追加検討

### Stripe 連携
- [ ] Stripe Dashboard で Webhook エンドポイント登録（本番URL）
  - URL: `https://<Cloud Run URL>/api/v1/webhooks/stripe`
  - イベント: customer.subscription.created, customer.subscription.updated, customer.subscription.deleted, invoice.paid, invoice.payment_failed
- [ ] Stripe 商品・価格（Price）を作成
- [ ] Stripe 本番モードに切り替え
  - テストキー（`sk_test_...`）→ ライブキー（`sk_live_...`）
  - Secret Manager の各 Stripe シークレットを本番値に更新
- [ ] stripe_service.py: subscription_deleted ハンドラにDB操作を実装
  - customer_id → User 検索
  - is_active = False 更新
  - refresh_tokens 全削除
  - LINE Push 通知送信
- [ ] stripe_service.py: invoice_payment_failed ハンドラにDB操作を実装
  - LINE 通知送信（支払い失敗の警告）

### line_service.py の DB 連携
- [ ] _handle_follow_event: UserRepository でユーザー作成/再有効化を実装
- [ ] _handle_unfollow_event: UserRepository でユーザー無効化 + トークン削除を実装
- [ ] _handle_message_event: ユーザー検索 + サブスクリプション状態チェックを実装
  - is_active=False の場合は「契約が終了しています」メッセージを返す

### auth_line.py の DB 連携
- [ ] コールバックハンドラで UserRepository を使用してユーザー作成/取得
- [ ] RefreshTokenRepository でリフレッシュトークンをDB保存

### デプロイパイプライン
- [ ] deploy.yml に DB マイグレーションステップを追加
  - Cloud SQL Proxy を使用したマイグレーション実行
  - デプロイ前（pre-deploy）で実行するようジョブを分離
- [x] ヘルスチェックエンドポイント（`/health`）の実装確認
  - deploy.yml が `/health` を叩いてデプロイ成功を判定
- [ ] Cloud Scheduler トークンクリーンアップジョブの認証設定
  - OIDC トークンによる認証を Cloud Run 側で検証

## 🟡 推奨（安定性・UX向上）

> ✅ .env をクリーンアップ済み: LINE Messaging API / LINE Login 設定を追加、`GOOGLE_PROJECT_ID` を `takahashi-451312` に修正。

### セッション管理
- [ ] auth_line.py: state/nonce の保存をインメモリから Redis 等に移行
  - 現在は _state_store 辞書（サーバー再起動で消失）
  - Cloud Run はインスタンスが複数になるため、共有ストレージが必須
- [ ] Redis / Cloud Memorystore の導入検討

### レート制限
- [ ] LINE Webhook エンドポイントにレート制限を追加
  - 同一ユーザーからの大量メッセージ対策
  - slowapi 等のライブラリ導入検討
- [ ] Auth エンドポイントにレート制限を追加

### BaseClient 修正
- [ ] base.py: _handle_response で HTTP ステータスコードチェックを追加
  - 現在は response.json() を直接呼び出しており、非200レスポンスでクラッシュする可能性
- [ ] response オブジェクトそのものを処理するよう修正

### リクエストサイズ制限
- [ ] server.py: リクエストボディサイズ上限ミドルウェアを追加
  - 例: Content-Length > 1MB を拒否

### TrustedHost ミドルウェア
- [ ] server.py: TrustedHostMiddleware を有効化
  - 現在はインポートのみで add_middleware されていない

### ドメイン / SSL
- [ ] Cloud Run にカスタムドメインをマッピング
  ```bash
  gcloud run domain-mappings create \
    --service=chabot-service \
    --domain=chatbot.example.com \
    --region=asia-northeast1
  ```
- [ ] DNS レコード設定（A / AAAA）
- [ ] HTTPS リダイレクトの確認

### モニタリング / ロギング
- [ ] Cloud Logging による構造化ログ出力の実装
  - `google-cloud-logging` は requirements.txt に含まれているが未使用
- [ ] Cloud Monitoring アラート設定
  - エラーレート（5xx）のアラート
  - レイテンシのアラート
  - Cloud Run インスタンス数のアラート
- [ ] Cloud Trace によるリクエストトレーシング（任意）

### バックアップ / 障害対応
- [ ] Cloud SQL 自動バックアップのスケジュール確認
- [ ] ポイントインタイムリカバリの有効化
- [ ] ロールバック手順の文書化
  ```bash
  # Cloud Run ロールバック
  gcloud run services update-traffic chabot-service \
    --to-revisions=<REVISION>=100 \
    --region=asia-northeast1
  ```

## 🟢 任意（機能拡張）

### LINE 機能拡張
- [ ] LIFF（LINE内ブラウザアプリ）対応
  - 初回ログインをLINE内で完結させる
- [ ] リッチメニュー API による動的メニュー切り替え
  - サブスクリプション状態に応じたメニュー表示
- [ ] Flex Message によるリッチな回答表示
- [ ] クイックリプライ対応
- [ ] 画像・ファイル送信対応

### Stripe 機能拡張
- [ ] Stripe Customer Portal 導入（ユーザー自身でプラン変更・解約）
  - 自前UIが不要になり、開発コスト削減
- [ ] Stripe Billing の無料トライアル対応
- [ ] 複数プラン（Basic/Premium等）対応

### テスト
- [ ] LINE Webhook のインテグレーションテスト追加
- [ ] LINE Login コールバックフローのE2Eテスト
- [ ] Stripe 解約 → 自動ログアウトのE2Eテスト
- [ ] セキュリティテスト（署名なしリクエスト拒否、改ざん検知等）

### インフラ（高度）
- [ ] Cloud Run min instances を 1 に設定（コールドスタート回避）
- [ ] Cloud Armor による WAF 保護
- [ ] 複数リージョン展開（ディザスタリカバリ）

## 🆕 2026-07-02 追加対応（code_issues.md の調査で新規発見・対応完了）

> code_issues.md で実施した包括的コードレビューにより発見された問題のうち、
> 2026-07-02 に対応完了した項目。詳細・残タスクは code_issues.md 参照。

- [x] Stripe クライアントの非同期化（同期SDKの await による即停止バグ）→ [H2]
- [x] DBスキーマ整合: User.id を String(36) UUID に統一、_generate_user_id(37文字) を廃止 → [H5]
- [x] line_user_id を nullable=True に統一（Email/Password・LINE 両ユーザー型を許容）→ [H6]
- [x] refresh_tokens.id/user_id を String(36) に統一、FK参照整合を解消 → [M7]
      ※ 副次: auth_service.py の JTI 生成（refresh_jti/access_jti）を36文字UUIDに短縮
- [x] aiosqlite を requirements-dev.txt に追加、CI で requirements-dev.txt をインストール → [H10]
- [x] seed_test_data.py のDBパスワード平文ハードコードを settings.database_url に変更 → [H11]
      ⚠️ git履歴に残存する旧DBパスワードのローテーションが別途必要（文字列は伏せ字）
- [x] deps.py の payload["sub"] 直接アクセスを .get + 401処理に変更 → [M24]
- [x] test_stripe*.py の pre-existing バグ9件を修正（H2 検証完了）
- [x] 検証: pytest 75 passed / alembic upgrade head が PostgreSQL 16 で成功 / autogenerate でスキーマ差分ゼロ確認

※ ローカル開発DBはスキーマ変更（初期マイグレ直接修正）により再構築が必要 → todo.txt [D0] 参照
