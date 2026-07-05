# Chabot (LINE版) プロジェクト計画・タスク

> **メタ**
> - 生成日: 2026-07-03（todo.txt / REMAINING_TASKS.md / ROADMAP.md / DEPLOY_BLOCKERS.md を統合）
> - 前提プロジェクト: GCP = `takahashi-451312` / リージョン = `asia-northeast1`
> - 注意: 本ファイルに実際のシークレット値は記載しない（取得元・設定先のみ）
> - 進捗は `[ ]`=未対応 / `[x]` `[✅]`=完了 で管理。コードマーカーは `grep -rn "\[Phase 2" app/` で抽出可能。

---

## 📋 クイックリファレンス（エージェント作業用）

### Phase 構成一覧

| Phase | ゴール | Stripe | DB | 主な設定タスク ID |
|---|---|---|---|---|
| **1**（現在）| 友だち追加だけでボット動作 | なし | なし | A4 / B1-B2 / C1-C4,C6 / E1,E3,E4,E6,E7,E8 / F1 |
| **2**（後続）| モックプランで回数制限・コーパス切替を動かす | **不使用**（モック判定）| Cloud SQL 有効化 | A1-A3 / C7 / D0-D2 / E2 / F2 |
| **3**（後続）| 実決済フレームワーク・退会処理 | **サンドボックス→本番** | 既存 DB 利用 | B3 / C5 / E5 |

依存: **Phase 1 → Phase 2（DB 基盤）→ Phase 3（実 Stripe）**

### よく使うコマンド

```bash
# コード中の Phase 2 マーカー（DB/回数/コーパス系=A2/A4/B2/C1/C2/H1/H5/I2 と Stripe/退会系=A6/A7/G1-G6/H2-H4/E1/I1 の両方を含む歴史的マーカー）を抽出
grep -rn "\[Phase 2" app/

# Phase 帰属は本ファイルの「5. コード実装マーカー対応表」で判定（マーカー表記はコード未変更のため Phase 2 のまま）
```

### 主要ディレクトリ

- `app/services/` — line_service / rag_service / stripe_service / auth_service
- `app/api/v1/` — webhooks/{line,stripe} / auth_line / chat
- `app/models/` — User / Subscription / UsageDaily / Conversation / RefreshToken / RagPermission / StripeEvent（7種・定義済み）
- `app/core/` — config / deps / security
- `alembic/versions/` — da7afce18552（初期）+ b3f2a1c8e9d4（LINE/Subscription系5テーブル）

---

## 1. Phase 構成と全体像

### 1.1 各 Phase の定義

**Phase 1（現在）**: Stripe/DB なしで「友だち追加だけでボットが使える」状態
- follow=ウェルカム送信 / message=RAG応答 / unfollow=ログのみ
- LINE Login=都時JWT（非永続）/ Chat API=JWT認証のみ（サブスクゲートなし）
- Stripe Webhook ルータは登録済みだが Stripe 側未設定のため実イベントは来ない

**Phase 2（後続）**: DB 整備 + モックプラン（Stripe 不使用）
- Cloud SQL を繋ぎ、モックプランで「チャット回数制限・プラン判定・コーパス切替」を動かす
- Stripe は使わない（プランは固定/デバッグ切替のモック判定）
- 回数上限は既存シード値（free=10/basic=100/pro=500）を踏襲

**Phase 3（後続）**: 実 Stripe 決済フレームワーク + 退会処理
- Stripe サンドボックスで「実際のプラン登録・退会処理」を検証し、本番化する
- Stripe 関連コード・モデル・マイグレーションは削除せず保持済み（Phase 3 で有効化）

### 1.2 旧 Phase 2 → 新 Phase 2 / Phase 3 再分類マップ

旧 todo.txt/REMAINING_TASKS.md の「Phase 2」を以下の通り再分類。

- **新 Phase 2（DB + モック）**: マーカー `A2(回数判定のみ) / A4 / B2 / C1 / C2 / H1 / H5 / I2` ＋ 設定 `[A1-A3][C7][D0-D1][D2]` ＋ 環境変数 `DATABASE_URL`
- **新 Phase 3（実 Stripe）**: マーカー `A6 / A7 / G1 / G2 / G3 / G4 / G5 / G6 / H2 / H3 / H4 / E1 / D2(本番ゲート) / I1` ＋ 設定 `[B3][C5][E5]` ＋ 環境変数 `STRIPE_*`
- **両 Phase にまたがる**:
  - `D2`（require_active_subscription）: Phase 2=「常に許可・回数判定のみ（モック）」→ Phase 3=「is_active_paid() でゲート（本番）」
  - `A2`（_handle_message_event）: Phase 2=「回数判定ゲート」→ Phase 3=「サブスク検証ゲートを追加」

### 1.3 進め方の目安

1. **Phase 2** は [P2-7] Vertex AI 実 API 統合を先行 → [P2-1] DB 基盤 → [P2-3] ユーザー永続化 → [P2-5] 回数判定 → [P2-6] コーパス切替の順で検証
2. Phase 2 でモックプランの回数制限・コーパス切替が想定通り動くことを確認してから Phase 3 へ
3. **Phase 3** はサンドボックスで [P3-1]→[P3-2][P3-3] の登録/解約フローを検証 → [P3-6] 退会処理が正しくユーザー無効化することを確かめてから [P3-7] 本番化

---

## 2. 🔴 Phase 1（現在）: デプロイと稼働

### 2.1 デプロイブロック項目（← 元 DEPLOY_BLOCKERS.md）

Phase 1 デプロイ（main push → GitHub Actions）は **「Authenticate to Google Cloud」ステップで失敗** 中。

- [ ] **ブロック1: GitHub Secrets 未設定（デプロイ不可・ユーザー作業）**
  - ⚠️ todo.txt/REMAINING_TASKS.md の「前提（完了）」に完了と記載されていたが、実態は未設定
  - 設定コマンド（リポジトリ root で実行）:
    ```bash
    gh secret set GCP_PROJECT_ID --body "takahashi-451312"
    gh secret set GCP_SERVICE_ACCOUNT --body "chabot-sa@takahashi-451312.iam.gserviceaccount.com"
    gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/742113528510/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider"
    gh secret set GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT --body "github-actions-deploy@takahashi-451312.iam.gserviceaccount.com"
    ```
  - 設定後: GitHub Actions の最新失敗 run を Re-run（または空コミット push）でデプロイ再走
- [ ] **ブロック2: 既存テスト31件失敗（Phase 2 で解消）**
  - CI「Run tests」は `continue-on-error` で許容済み（Phase 1 デプロイは通る）
  - 主な失敗: `tests/integration/test_api/test_auth.py` / `test_repositories/test_refresh_token.py` / `test_services/test_rag_service.py` / `test_clients/test_vertex_ai.py`
  - 解消後は deploy.yml の `Run tests` から `continue-on-error: true` を外す

### 2.2 完了済み前提（再設定不要）

- [✅] GCP プロジェクト / 課金 / 必要なAPI有効化（Cloud Run/Artifact Registry/Cloud SQL/Secret Manager/Vertex AI/Cloud Scheduler/Logging/IAM Credentials）
- [✅] Artifact Registry リポジトリ（`chabot-repo`）
- [✅] Cloud Run 用サービスアカウント（`chabot-sa`）+ IAM ロール4件（secretAccessor / cloudsql.client / aiplatform.user / logging.logWriter）
- [✅] Workload Identity Federation（GitHub Actions → GCP）: `github-actions-pool` / `github-actions-provider`
- [✅] GitHub Secrets（GCP_PROJECT_ID / GCP_WORKLOAD_IDENTITY_PROVIDER / GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT / GCP_SERVICE_ACCOUNT）※ 2.1 ブロック1を参照（実態は未設定の可能性）
- [✅] Alembic マイグレーションファイル作成（初期 + LINE/Subscription系）
- [✅] Secret Manager 登録済み: line-channel-secret / line-channel-access-token / line-login-channel-id / line-login-channel-secret（本番値）、stripe-secret-key / stripe-webhook-secret / stripe-publishable-key（テスト値）
- [✅] 旧 Discord 用シークレット削除済み（DISCORD_BOT_TOKEN 等）
- [✅] .env クリーンアップ済み（LINE 設定追加、GOOGLE_PROJECT_ID 修正）

### 2.3 Phase 1 必須タスク（Stripe/DB なしでボットを動かす）

#### [A] GCP インフラ
- [ ] **A4. Vertex AI RAG コーパス作成 & ナレッジ登録**【Phase 1 必須・ボット応答に必要】
  - Vertex AI Search / RAG でコーパス作成 → コーパスIDを控える
  - ドキュメント/FAQ 等のナレッジソースを登録
  - ※ 作成したコーパスIDは [C4] の google-corpus-id に使用
  - ※ Phase 1 でも未設定だと message イベントがフォールバック応答になる

#### [B] 外部サービスでの取得と設定
- [✅] **B1. LINE Developers でプロバイダー & チャネル作成**
  - [✅] B1-1. Messaging API チャネル（Channel Secret / Access Token 設定済み・※長期トークンは定期更新）
  - [✅] B1-2. LINE Login (v2.1, OIDC) チャネル（Channel ID / Secret 設定済み）
- [ ] **B2. LINE Webhook / Callback URL 設定**【Phase 1・URLはデプロイ後に確定】
  - [ ] B2-1. Messaging API: Webhook URL `https://<Cloud Run URL>/api/v1/webhooks/line` / 「Webhook の利用」オン / 「自動応答メッセージ」オフ / 「友だち追加挨拶」オフ
  - [ ] B2-2. LINE Login: Callback URL `https://<Cloud Run URL>/api/v1/auth/line/callback`（config.py の LINE_LOGIN_CALLBACK_URL と完全一致）

#### [C] Secret Manager 登録（未登録分）
> 登録コマンド: `echo -n "値" | gcloud secrets create <名前> --data-file=-`
- [✅] C1. line-channel-secret（本番値）
- [✅] C2. line-channel-access-token（※有効期限あり・定期更新時は再設定）
- [✅] C3. line-login-channel-id / line-login-channel-secret（本番値）
- [ ] **C4. google-project-id = takahashi-451312 / google-location = asia-northeast1 / google-corpus-id = <A4 のコーパスID>**【Phase 1：RAG 用】
- [ ] **C6. jwt-secret-keys**【Phase 1：Chat API 認証用】
  - 生成: `python -c "import secrets; print(secrets.token_urlsafe(64))"`（ローテーション用に複数をカンマ区切りで可）

#### [E] 環境変数（.env / Cloud Run）の本番値化
- [ ] **E1. DEBUG=False / APP_ENV=production**【Phase 1】
- [ ] **E3. JWT_SECRET_KEYS = [C6] で生成した値**【Phase 1】
- [ ] **E4. LINE_* 全5変数 = [B1][B2] で取得/設定した値**【Phase 1】
- [ ] **E6. GOOGLE_PROJECT_ID = takahashi-451312 / GOOGLE_LOCATION = asia-northeast1 / GOOGLE_CORPUS_ID = <A4 のコーパスID>**【Phase 1】
- [ ] **E7. LINE_LOGIN_CALLBACK_URL = <Cloud Run URL>/api/v1/auth/line/callback**【Phase 1】
- [ ] **E8. CORS_ALLOWED_ORIGINS = 本番フロントドメイン**【Phase 1・現在は localhost のみ → 本番URLに変更】

#### [F] セットアップスクリプト実行
- [ ] **F1. setup_workload_identity.sh 実行**（SA の IAM ロール付与確認用）【Phase 1】
  ```bash
  export PROJECT_ID=takahashi-451312 REGION=asia-northeast1 \
         SERVICE_NAME=chabot-service \
         SERVICE_ACCOUNT=chabot-sa@takahashi-451312.iam.gserviceaccount.com
  ./scripts/setup_workload_identity.sh
  ```

#### その他 Phase 1 コード（推奨・後回し可）
- [ ] security.py: RS256 署名検証の本番実装【Phase 1 推奨（LINE Login 用）】
  - https://api.line.me/oauth2/v2.1/certs から JWKS 公開鍵を取得し、ID トークンの署名を検証（現在はクレーム検証のみ・TODO 箇所）
- [x] ヘルスチェックエンドポイント（`/health`）実装確認【Phase 1・deploy.yml が成功判定に使用】

### 2.4 デプロイ後の作業（Phase 1）

1. Cloud Run の URL 確定 → LINE Webhook URL / Callback URL に設定（[B2]）
2. 動作確認: 友だち追加 → メッセージ送信 → RAG 応答
   - RAG 応答には GOOGLE_CORPUS_ID が正しい corpus を指す必要あり（未設定だとフォールバック定型文）
3. （必要なら）CORS_ALLOWED_ORIGINS を Cloud Run の環境変数に設定（LINE Webhook サーバー間には影響しない・ブラウザから LINE Login を使う場合は本番ドメイン）

### 2.5 推奨する実行順序（Phase 1）

1. [B1] LINE Developers でチャネル作成（完了済み）
2. [A4] Vertex AI RAG コーパス作成（★ボット応答に必須・本リスト外の別作業）
3. [C4][C6] Google / JWT の Secret Manager 登録
4. [E1,E3,E4,E6,E7,E8] 環境変数を本番値化（DATABASE_URL/STRIPE_* は不要）
5. Cloud Run へデプロイ → URL 確定
6. [B2] 確定 URL で LINE Webhook / LINE Callback を設定
7. [F1] setup_workload_identity.sh 実行
8. 動作確認（友だち追加 → メッセージ → RAG 応答）

---

## 3. 🟦 Phase 2（後続）: DB + モックプラン（Stripe 不使用）

> [ゴール] Cloud SQL に接続し、モックプランでチャット回数制限とプラン別コーパス切替を検証。Stripe は扱わない。
> [前提] モデル7種・マイグレーション2本・`RagPermission`（daily_message_limit/rag_corpus_id/model_name カラム）は既定義済み。

### 3.1 インフラ・設定タスク

#### [A] GCP インフラ（DB 基盤）
- [ ] ★【Phase 2】**A1. Cloud SQL (PostgreSQL 16) インスタンス新規作成**
  - ⚠️ 既存 chabot-dev は SUSPENDED / us-west1-a / PG18 で要件不一致 → 新規作成
  - インスタンス名: chabot-postgres / リージョン: asia-northeast1 / PG16 / db-f1-micro(開発)・db-custom-1-3840(本番) / プライベートIP・自動バックアップ有効化
  ```bash
  gcloud sql instances create chabot-postgres \
    --database-version=POSTGRES_16 --region=asia-northeast1 \
    --tier=db-custom-1-3840 --backup-start-time=15:00 \
    --enable-point-in-time-recovery
  ```
- [ ] ★【Phase 2】**A2. データベース & ユーザー作成**
  ```bash
  gcloud sql databases create chabot --instance=chabot-postgres
  gcloud sql users create chabot_user --instance=chabot-postgres --password="<強力なパスワード>"
  ```
- [ ] ★【Phase 2】**A3. VPC Access Connector 作成**（Cloud Run → Cloud SQL 接続用・⚠️ asia-northeast1 にコネクタなし）
  ```bash
  gcloud compute networks vpc-access connectors create chabot-connector \
    --region=asia-northeast1 --range=10.8.0.0/28 --network=default
  ```
- [ ] Cloud Run の Cloud SQL 接続設定を deploy.yml で復帰（`--set-cloudsql-instances` と `DATABASE_URL=database-url`）

#### [C] Secret Manager（DB）
- [ ] ★【Phase 2】**C7. database-url**（Cloud SQL unix socket 形式）
  - `postgresql+asyncpg://chabot_user:<password>@/chabot?host=/cloudsql/takahashi-451312:asia-northeast1:chabot-postgres`

#### [D] データベース・マイグレーション
- [ ] ★【Phase 2】**D0. ローカル開発DBのスキーマ再構築**（2026-07-02 コード修正に伴う）
  - ⚠️ 初期マイグレ da7afce18552 を直接修正（User.id/FK を String(36) 統一、line_user_id nullable）→ 既存ローカル DB は再構築が必要
  - PostgreSQL 起動後、DB を DROP → CREATE、または `alembic downgrade base` → `alembic upgrade head`
  - テストデータは `scripts/seed_test_data.py` で再投入可 / ローカルDBパスワード（旧PW）のローテーション推奨（git履歴に残存）
- [ ] ★【Phase 2】**D1. 初回デプロイ前に Cloud SQL でマイグレーション実行**（⚠️ deploy.yml にステップ無い → 手動）
  ```bash
  cloud_sql_proxy -instances=takahashi-451312:asia-northeast1:chabot-postgres=tcp:5432 &
  export DATABASE_URL="postgresql+asyncpg://chabot_user:<password>@localhost:5432/chabot"
  alembic upgrade head
  ```
- [ ] ★【Phase 2】**D2. rag_permissions テーブルへプラン別権限のシードデータ挿入**（⚠️ マイグレーションに含まれない → 手動 INSERT）
  ```sql
  INSERT INTO rag_permissions
    (plan, rag_corpus_id, model_name, max_input_tokens, max_output_tokens,
     daily_message_limit, enabled)
  VALUES
    ('free',  ..., 'gemini-1.5-flash',  4000,  4000,  10,  true),
    ('basic', ..., 'gemini-1.5-flash', 16000,  8000, 100,  true),
    ('pro',   ..., 'gemini-1.5-pro',   32000, 16000, 500,  true);
  ```

#### [E] 環境変数（DB）
- [ ] ★【Phase 2】**E2. DATABASE_URL = [C7] と同じ本番値**

#### [F] セットアップスクリプト（DB 必須）
- [ ] ★【Phase 2】**F2. setup_cloud_scheduler.sh 実行**（トークンクリーンアップ ジョブ・毎日 AM3:00(JST) に /api/v1/admin/cleanup-tokens をPOST）
  ```bash
  export PROJECT_ID=takahashi-451312 REGION=asia-northeast1 \
         SERVICE_NAME=chabot-service \
         SERVICE_ACCOUNT=chabot-sa@takahashi-451312.iam.gserviceaccount.com
  ./scripts/setup_cloud_scheduler.sh
  ```
- [ ] deploy.yml に pre-deploy マイグレーションジョブ追加（DB 必須・Cloud SQL Proxy で実行・ジョブ分離）
- [ ] Cloud Scheduler トークンクリーンアップジョブの OIDC 認証を Cloud Run 側で検証

### 3.2 コード実装タスク

#### [P2-1] Cloud SQL インフラ整備
- 上記 [A1][A2][A3][C7] を実施

#### [P2-2] DB 接続の有効化
- [x] **[2026-07-05 ローカル検証]** `app/server.py` lifespan で `init_db()`/`close_db()` 呼び出し **[Phase 2 マーカー I2]**
- [x] **[2026-07-05]** `app/models/__init__.py` のエクスポート不備を是正（User/RefreshToken のみ → 全7モデル追加）
- [ ] **[本番]** Cloud Run は DB 未接続のため未デプロイ（init_db 有効化・line_service db 注入はローカル専用・Cloud SQL 整備後に Phase 2 デプロイ）

#### [P2-3] LINE Webhook / Login フローの DB 連携（ユーザー永続化）
- [x] **[2026-07-05 ローカル検証]** follow: ユーザー作成（未存在）+ free サブスク → `app/services/line_service.py` _handle_follow_event **[Phase 2 マーカー A4]**
  - `UserRepository.find_by_line_user_id` / `create_line_user` を実装 **[H1]**
  - ※ Stripe 顧客作成（G1）・is_active=True 再有効化は Phase 3
- [ ] LINE Login callback: ユーザー永続化 → `app/api/v1/auth_line.py:213-235` **[Phase 2 マーカー C1/C2]**
  - 現状の「仮 UUID 都度発行」を DB 検索した既存 ID に切替 / RefreshTokenRepository 保存

#### [P2-4] モックプラン判定
- [ ] 全ユーザーを固定モックプラン（例: free・デバッグで切替可）として扱う
- [ ] `app/core/deps.py:89-105` の require_active_subscription **[Phase 2 マーカー D2]** を「常に許可（回数判定のみ）」のモック挙動に
- [ ] Subscription.is_active_paid() / is_restricted()（app/models/subscription.py）は Phase 3 まで未使用 **[Phase 2 マーカー H2]**

#### [P2-5] チャット回数判定（中核）
- [ ] UsageDaily の更新・集計サービス/リポジトリを **【新設】**（現状なし）
- [ ] 1日のメッセージ数を UsageDaily.message_count で集計し、RagPermission.daily_message_limit（free=10/basic=100/pro=500）と照合
- [ ] 制限超過時は `app/api/v1/webhooks/line.py:50` で RAG クエリせず制限メッセージを返却 **[Phase 2 マーカー B2]**

#### [P2-6] プラン別コーパス切替
- [x] **[2026-07-05 ローカル検証]** `RagPermissionRepository`（get_by_plan）を新設 **[Phase 2 マーカー H5]**
- [x] **[2026-07-05]** RAGService.query / VertexAIClient.query が corpus_id/model_name 引数で動的切替（line_user_id → User → Subscription.plan → RagPermission 経路を検証済み）
- [x] **[2026-07-05]** webhooks/line.py は BackgroundTasks 内で `async_session_maker` で DB 取得、chat.py は current_user から plan 解決
- [ ] Conversation テーブルに plan_at_request / rag_corpus_id / トークン使用量を記録

#### [P2-7] ✅ 前提: Vertex AI 実 API 統合（Phase 1 で完了）
- [x] **[2026-07-05]** `app/clients/vertex_ai.py` をモック → 実 API（vertexai.rag GA SDK）に置換済み
- ※ コーパス切替の検証に必須（ローカル検証で確認済み）

#### Phase 2 の運用タスク
- [ ] G6. state/nonce をインメモリ(_state_store)から Redis/Memorystore へ移行（推奨・Cloud Run マルチインスタンス）

---

## 4. 🟪 Phase 3（後続）: 実 Stripe 決済フレームワーク + 退会処理

> [ゴール] Stripe サンドボックス（テストモード）でプラン登録・退会フローを検証し、本番化。Phase 2 の DB 基盤をそのまま利用。
> [前提] `app/clients/stripe.py` に StripeClient（create_customer/Webhook 検証等）実装済み。`app/services/stripe_service.py` に Webhook ハンドラ5種（現状すべてログのみ）。Stripe Webhook ルータは `app/server.py:110` で登録済み。

### 4.1 インフラ・設定タスク

#### [B] Stripe 本番設定
- [ ] ★【Phase 3】**B3. Stripe 本番設定**
  - [ ] B3-1. 商品 & 価格(Price)を作成 → 価格ID(price_...) を控える
  - [ ] B3-2. Webhook エンドポイント登録（本番URL）
    - URL: `https://<Cloud Run URL>/api/v1/webhooks/stripe`
    - イベント: customer.subscription.created/updated/deleted, invoice.paid, invoice.payment_failed
    - Signing secret(whsec_...) を取得 → [C5] stripe-webhook-secret 更新
  - [ ] B3-3. 本番モードへ切替（テスト→ライブ）: sk_live_... / pk_live_... → [C5] 更新

#### [C] Secret Manager（Stripe 本番）
- [ ] ★【Phase 3】**C5. stripe-secret-key / stripe-webhook-secret / stripe-publishable-key**（B3 で取得したライブ値に更新）

#### [E] 環境変数（Stripe）
- [ ] ★【Phase 3】**E5. STRIPE_* 全3変数 = [B3] のライブ値**

### 4.2 コード実装タスク

#### [P3-1] Stripe サンドボックス（テストモード）設定
- Stripe Dashboard で商品/価格/Webhook エンドポイント（テストURL）作成 / テストキー（sk_test_/whsec_）取得

#### [P3-2] プラン登録フレームワーク
- [ ] postback action=subscribe で Stripe Checkout セッション生成 → `app/services/line_service.py:262` **[Phase 2 マーカー A7]**
- [ ] create_customer 呼び出し連携（follow/初回ログイン時）→ `app/services/stripe_service.py:45` **[Phase 2 マーカー G1]**
- [ ] User.stripe_customer_id へ顧客ID書込 **[Phase 2 マーカー H3]**

#### [P3-3] Stripe Webhook ハンドラの DB 連携（現状すべてログのみ）
- [ ] `_handle_invoice_paid`: Subscription の請求期間更新 **[Phase 2 マーカー G2]**
- [ ] `_handle_invoice_payment_failed`: 支払い失敗の LINE 通知 **[Phase 2 マーカー G3]**
- [ ] `_handle_subscription_created`: Subscription レコード作成 **[Phase 2 マーカー G4]**
- [ ] `_handle_subscription_updated`: status/plan 更新・is_restricted 連携 **[Phase 2 マーカー G5]**
- [ ] `_handle_subscription_deleted`: 解約処理 **[Phase 2 マーカー G6]**

#### [P3-4] 決済冪等性の DB 永続化
- [ ] `app/clients/stripe.py:62` のインメモリ辞書 → StripeEvent テーブルへ移行 **[Phase 2 マーカー H4]**
  - ※ Cloud Run はステートレス/マルチインスタンスのため、インメモリでは再起動で冪等性が失われる

#### [P3-5] 本番ゲート有効化
- [ ] require_active_subscription を本番化（is_active_paid() でゲート・未契約は 403）**[Phase 2 マーカー D2]**
- [ ] `app/api/v1/chat.py:97` の Depends(get_current_user) → Depends(require_active_subscription) **[Phase 2 マーカー E1]**
- [ ] message イベントにサブスク検証ゲート追加 **[Phase 2 マーカー A2]**
- [ ] Subscription.is_active_paid / is_restricted を有効化 **[Phase 2 マーカー H2]**

#### [P3-6] 退会時処理
- [ ] unfollow（LINE 友だち解除）: is_active=False ＋ リフレッシュトークン全削除 → `app/services/line_service.py:224` **[Phase 2 マーカー A6]**
- [ ] subscription_deleted（Stripe 解約）: ユーザー無効化 ＋ トークン全削除 ＋ LINE Push 通知 → `app/services/stripe_service.py:533` **[Phase 2 マーカー G6]**
  - customer_id → User 検索 / is_active = False / refresh_tokens 全削除 / LINE Push 通知送信

#### [P3-7] 本番 Stripe 設定
- 上記 [B3][C5][E5] を実施 / `app/core/config.py:55-57` のプレースホルダ（sk_test_*/whsec_*/pk_test_*）を Secret Manager から注入 **[Phase 2 マーカー I1]**

---

## 5. コード実装マーカー対応表

> コード中の `# [Phase 2 ...]` マーカー（`grep -rn "\[Phase 2" app/`）と実装タスクの対応。
> コード内のマーカー表記は `[Phase 2 マーカー Xn]` のまま（歴史的経緯・コード未変更）。Phase 帰属は以下で判定。

### 5.1 🟦 Phase 2（DB + モック）のマーカー

| マーカー | ファイル | タスク |
|---|---|---|
| A4 | `app/services/line_service.py` | `_handle_follow_event`: ユーザー作成/再有効化（モック判定・Stripe 顧客作成は Phase 3 の G1 に後回し）|
| B2 | `app/api/v1/webhooks/line.py` | `_process_line_events`: 回数判定結果で RAG クエリを分岐（制限超過で制限メッセージ）|
| C1 | `app/api/v1/auth_line.py` | callback: UserRepository でユーザー永続化 ＋ RefreshTokenRepository 保存 |
| C2 | `app/api/v1/auth_line.py` | 仮 UUID を DB 検索した既存 ID に置換 |
| D2 | `app/core/deps.py` | `require_active_subscription`（Phase 2 は「常に許可・回数判定のみ」のモック挙動）|
| H1 | `app/repositories/user.py` | find_by_line_user_id / find_by_stripe_customer_id / update_stripe_customer_id を追加 |
| H5 | `app/models/rag_permission.py` | プラン別 RAG 制限（シードは [D2]）|
| I2 | `app/server.py` lifespan | DB 接続（init_db）の初期化を追加 ＋ models/__init__ のエクスポート是正 |

**Phase 2 で新設（マーカーなし・土台のみ既存）**: UsageDaily 更新・集計サービス/リポジトリ / RagPermission.rag_corpus_id 読み取りリポジトリ / vertex_ai.py 実 API 統合

### 5.2 🟪 Phase 3（実 Stripe）のマーカー

| マーカー | ファイル | タスク |
|---|---|---|
| A2 | `app/services/line_service.py` | `_handle_message_event`: サブスク検証ゲート（Subscription.is_active_paid）を追加 ※回数判定は Phase 2 |
| A6 | `app/services/line_service.py` | `_handle_unfollow_event`: is_active=False ＋ リフレッシュトークン全削除（退会）|
| A7 | `app/services/line_service.py` | postback `action=subscribe`: Stripe Checkout / Customer Portal 誘導 |
| E1 | `app/api/v1/chat.py` | `send_message` の Depends を require_active_subscription に差し替え |
| G1 | `app/services/stripe_service.py` | `create_customer`: follow / 初回ログイン時に呼び出し |
| G2 | `app/services/stripe_service.py` | `_handle_invoice_paid`: Subscription の請求期間更新 |
| G3 | `app/services/stripe_service.py` | `_handle_invoice_payment_failed`: 支払い失敗の LINE 通知 |
| G4 | `app/services/stripe_service.py` | `_handle_subscription_created`: Subscription レコード作成 |
| G5 | `app/services/stripe_service.py` | `_handle_subscription_updated`: Subscription.status 更新 |
| G6 | `app/services/stripe_service.py` | `_handle_subscription_deleted`: is_active=False ＋ トークン全削除 ＋ LINE 通知（退会）|
| H2 | `app/models/subscription.py` | is_active_paid / is_restricted を require_active_subscription から使用 |
| H3 | `app/models/user.py` | stripe_customer_id カラムに顧客IDを書き込み |
| H4 | `app/models/stripe_event.py` | stripe_service の冪等性を DB 永続化 |
| I1 | `app/core/config.py` | Stripe 設定を本番値に（Secret Manager から注入）|
| D2 | `app/core/deps.py` | require_active_subscription を is_active_paid() でゲート（本番化）|

### 5.3 再開手順

**Phase 2 再開手順**:
1. `grep -rn "\[Phase 2" app/` で全マーカーを抽出
2. 上記 Phase 2 表と突き合わせ、ブロックマーカー内の疑似コードを実装に置換
3. 先に Vertex AI 実 API 統合（vertex_ai.py）を行い、コーパス切替を検証可能にする
4. DB 基盤 → ユーザー永続化（A4/C1）→ 回数判定（B2/D2モック）→ コーパス切替（H5）の順で構築

**Phase 3 再開手順**:
1. Stripe サンドボックス（テストモード）で商品/価格/Webhook を設定
2. 上記 Phase 3 表のマーカー（A6/A7/G1-G6/E1/H2-H4/I1）を実装
3. require_active_subscription（D2）を本番化 → chat.py（E1）→ message（A2 サブスクゲート）の順で構築
4. 退会フロー（unfollow A6 / subscription_deleted G6）の E2E を検証してから本番キー切替

---

## 6. 🟡 推奨タスク（Phase 共通・安定性・UX 向上）

### セッション管理
- [ ] auth_line.py: state/nonce の保存をインメモリから Redis 等に移行（現在は _state_store 辞書・サーバー再起動で消失・Cloud Run は共有ストレージ必須）
- [ ] Redis / Cloud Memorystore の導入検討

### レート制限
- [ ] LINE Webhook エンドポイントにレート制限を追加（同一ユーザーからの大量メッセージ対策・slowapi 等のライブラリ導入検討）
- [ ] Auth エンドポイントにレート制限を追加

### BaseClient 修正
- [ ] base.py: `_handle_response` で HTTP ステータスコードチェックを追加（現在は response.json() を直接呼び出し・非200でクラッシュの可能性）
- [ ] response オブジェクトそのものを処理するよう修正

### リクエストサイズ制限
- [ ] server.py: リクエストボディサイズ上限ミドルウェアを追加（例: Content-Length > 1MB を拒否）

### TrustedHost ミドルウェア
- [ ] server.py: TrustedHostMiddleware を有効化（現在はインポートのみで add_middleware されていない）

### ドメイン / SSL
- [ ] Cloud Run カスタムドメインマッピング + DNS(A/AAAA)
  ```bash
  gcloud run domain-mappings create --service=chabot-service \
    --domain=chatbot.example.com --region=asia-northeast1
  ```
- [ ] HTTPS リダイレクトの確認

### モニタリング / ロギング
- [ ] Cloud Logging による構造化ログ出力（google-cloud-logging は requirements.txt 含むが未使用）
- [ ] Cloud Monitoring アラート（5xx / レイテンシ / インスタンス数）
- [ ] Cloud Trace によるリクエストトレーシング（任意）

### バックアップ / 障害対応
- [ ] Cloud SQL 自動バックアップのスケジュール確認 / PITR 有効化
- [ ] ロールバック手順の文書化
  ```bash
  gcloud run services update-traffic chabot-service \
    --to-revisions=<REVISION>=100 --region=asia-northeast1
  ```

### その他
- [ ] G7. リッチメニュー作成（LINE Official Account Manager）

---

## 7. 🟢 任意機能拡張

### LINE 機能拡張
- [ ] LIFF（LINE内ブラウザアプリ）対応（初回ログインをLINE内で完結）
- [ ] リッチメニュー API による動的メニュー切り替え（サブスクリプション状態に応じた表示）
- [ ] Flex Message / クイックリプライ / 画像・ファイル送信

### Stripe 機能拡張
- [ ] Stripe Customer Portal 導入（ユーザー自身でプラン変更・解約・自前UI不要）
- [ ] Stripe Billing の無料トライアル対応
- [ ] 複数プラン（Basic/Premium等）対応

### テスト
- [ ] LINE Webhook のインテグレーションテスト追加
- [ ] LINE Login コールバックフローの E2E テスト
- [ ] Stripe 解約 → 自動ログアウトの E2E テスト
- [ ] セキュリティテスト（署名なしリクエスト拒否・改ざん検知）

### インフラ（高度）
- [ ] Cloud Run min instances を 1 に設定（コールドスタート回避）
- [ ] Cloud Armor による WAF 保護
- [ ] 複数リージョン展開（ディザスタリカバリ）

---

## 8. ✅ 完了済み（参照用）

### 2026-07-02 コード修正対応（code_issues.md の調査で発見・対応完了）
- [x] Stripe クライアントの非同期化（同期SDKの await による即停止バグ）→ [H2]
- [x] DBスキーマ整合: User.id を String(36) UUID に統一、_generate_user_id(37文字) を廃止 → [H5]
- [x] line_user_id を nullable=True に統一（Email/Password・LINE 両ユーザー型を許容）→ [H6]
- [x] refresh_tokens.id/user_id を String(36) に統一、FK参照整合を解消 → [M7]
  - ※ 副次: auth_service.py の JTI 生成（refresh_jti/access_jti）を36文字UUIDに短縮
- [x] aiosqlite を requirements-dev.txt に追加、CI で requirements-dev.txt をインストール → [H10]
- [x] seed_test_data.py のDBパスワード平文ハードコードを settings.database_url に変更 → [H11]
  - ⚠️ git履歴に残存する旧DBパスワードのローテーションが別途必要（文字列は伏せ字）
- [x] deps.py の payload["sub"] 直接アクセスを .get + 401処理に変更 → [M24]
- [x] test_stripe*.py の pre-existing バグ9件を修正（H2 検証完了）
- [x] 検証: pytest 75 passed / alembic upgrade head が PostgreSQL 16 で成功 / autogenerate でスキーマ差分ゼロ確認

> ※ ローカル開発DBはスキーマ変更（初期マイグレ直接修正）により再構築が必要 → [D0] 参照

### 2026-07-05 Phase 2 モックプラン検証（ローカル PG・コーパス動的切替）
- [x] ローカル PostgreSQL（docker `chabot-postgres`）で `alembic upgrade head` + rag_permissions seed（free/basic → shoulder コーパス `1766660099138387968`・gemini-2.5-flash）
- [x] [P2-2] server.py lifespan で init_db/close_db 有効化・models/__init__.py に全7モデルエクスポート
- [x] [P2-3] follow で User 作成 + free サブスク（UserRepository.find_by_line_user_id / create_line_user）
- [x] [P2-6] RagPermissionRepository 新設・RAGService/VertexAIClient.query が corpus_id/model_name を動的受領・webhooks/line.py と chat.py で plan→corpus_id 解決
- [x] 検証: follow → User 作成、message → plan=free で corpus_id 解決、手動 basic 昇格 → plan=basic に切替を確認（1コーパス検証・応答内容は同じ・plan 解決ログで確認）

#### ⚠️ Phase 2 ローカル検証 以降の残タスク（本番化・機能拡充）
- [ ] **[本番 DB]** Cloud SQL (PostgreSQL 16) 整備 [A1-A3/C7] → DATABASE_URL Secret 登録 → deploy.yml の Cloud SQL 接続復帰 → Phase 2 デプロイ（現在 init_db 有効化・line_service db 注入はローカル専用・本番 Cloud Run では DB 未接続でエラーになるため未デプロイ）
- [ ] **[テスト]** test_line_service.py の9件が process_webhook_event(event, db) シグネチャ変更で失敗中 → Phase 2 で db mock を渡すよう修正
- [ ] **[P2-3 続]** LINE Login callback（auth_line.py C1/C2）のユーザー永続化・RefreshToken 保存
- [ ] **[P2-4]** require_active_subscription（deps.py D2）のモック実装
- [ ] **[P2-5]** チャット回数判定（UsageDaily 集計サービス/リポジトリ新設・RagPermission.daily_message_limit 照合）
- [ ] **[P2-6 続]** Conversation テーブルに plan_at_request / rag_corpus_id / トークン使用量を記録
- [ ] **[Phase 3]** Stripe 実決済・イベント型フック（subscription.updated/deleted・invoice.payment_failed）でプラン更新・退会処理
