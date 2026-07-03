# Phase 1 デプロイのブロック項目と残作業

生成: 2026-07-03

## 現状サマリ

Phase 1 デプロイ（main push → GitHub Actions）は **「Authenticate to Google Cloud」ステップで失敗** 中。
原因は **GitHub Secrets が4つとも未設定**（`gh secret list` が空を確認済み）。

コード側で対応済みの修正（コミット `33009a9`, `90d75b0` 等）:
- `app/db/session.py`: SQLite（テスト用）の pool 引数エラーを解消
- `deploy.yml`: Run tests に `continue-on-error` を追加（既存31件失敗を許容）
- `deploy.yml`: `workload_identity_service_account` → `service_account`（auth@v2 対応）
- `deploy.yml`: Cloud SQL 参照・DATABASE_URL を Phase 2 用に分離
- `deploy.yml`: Secret Manager 参照名の不整合修正（JWT_SECRET_KEYS / GOOGLE_CORPUS_ID）

GCP 側リソースは実在確認済み（Workload Identity Pool/Provider、Service Account 2件）。
**残るは GitHub Secrets の設定のみ** です。

---

## 🔴 ブロック1: GitHub Secrets 未設定（デプロイ不可・ユーザー作業）

> ⚠️ `todo.txt` / `REMAINING_TASKS.md` の「前提（完了）」に GitHub Secrets 完了と記載されていましたが、**実態は未設定** でした。

### 設定する値（GCP 側で実在確認済み）

| Secret 名 | 値 |
|---|---|
| `GCP_PROJECT_ID` | `takahashi-451312` |
| `GCP_SERVICE_ACCOUNT` | `chabot-sa@takahashi-451312.iam.gserviceaccount.com` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/742113528510/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider` |
| `GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT` | `github-actions-deploy@takahashi-451312.iam.gserviceaccount.com` |

### 設定コマンド（リポジトリ root で実行）

```bash
gh secret set GCP_PROJECT_ID --body "takahashi-451312"
gh secret set GCP_SERVICE_ACCOUNT --body "chabot-sa@takahashi-451312.iam.gserviceaccount.com"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/742113528510/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider"
gh secret set GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT --body "github-actions-deploy@takahashi-451312.iam.gserviceaccount.com"
```

### 設定後の再デプロイ

GitHub Actions の最新失敗 run を **Re-run**（または空コミット push）でデプロイが走る。

```bash
# 直近 run の再実行
gh run rerun <RUN_ID>
```

---

## 🟡 ブロック2: 既存テスト31件失敗（Phase 2 で解消）

CI の「Run tests」ステップは `continue-on-error` で許容済み（**Phase 1 デプロイは通る**）。
ただし31件の既存テスト失敗が残っている（本変更と無関係）。Phase 2 で解消すること。

主な失敗対象:
- `tests/integration/test_api/test_auth.py`（email/password 認証）
- `tests/unit/test_repositories/test_refresh_token.py`
- `tests/unit/test_services/test_rag_service.py`
- `tests/unit/test_clients/test_vertex_ai.py`

解消後は `deploy.yml` の `Run tests` ステップから `continue-on-error: true` を外す。

---

## デプロイ後の作業（Phase 1）

1. **Cloud Run の URL 確定** → LINE Webhook URL / Callback URL に設定（todo.txt [B2]）
   - Webhook URL: `https://<Cloud Run URL>/api/v1/webhooks/line`
   - Callback URL: `https://<Cloud Run URL>/api/v1/auth/line/callback`
2. **動作確認**: 友だち追加 → メッセージ送信 → RAG 応答
   - RAG 応答には `GOOGLE_CORPUS_ID`（Secret Manager）が正しい corpus を指す必要あり
   - 未設定だと message がフォールバック定型文になる
3. **(必要なら) CORS_ALLOWED_ORIGINS** を Cloud Run の環境変数に設定
   - 現状は config.py のデフォルト（localhost）。LINE Webhook（サーバー間）には影響しない
   - ブラウザから LINE Login を使う場合は本番ドメインを設定

---

## Phase 2（後続）の主な作業（参考）

コード中の `# [Phase 2 ...]` マーカー（`grep -rn "\[Phase 2" app/`）と todo.txt / REMAINING_TASKS.md の Phase 2 セクション参照:
- Cloud SQL 作成 → `deploy.yml` の `--set-cloudsql-instances` と `DATABASE_URL=database-url` を復帰
- Stripe 本番設定（商品/価格/Webhook/ライブキー）
- follow/message/auth_line の DB 連携（[Phase 2] マーカー A2/A4/A6/C1）
- `require_active_subscription`（[Phase 2] マーカー D2）→ chat.py のゲート化
- Stripe Webhook ハンドラの DB 連携（[Phase 2] マーカー G2-G6）
