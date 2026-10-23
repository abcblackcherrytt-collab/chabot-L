# プロジェクト管理ログ

## 未実施・進行中

### #004 未実施 — Vertex AI RAGコーパスの重複解消
- 登録日時: 2026-10-20 15:15 JST
- 内容: chabot_ankleコーパス（2267637179171733504）内の重複文書（ankle_journal.md 2件）を1件へ削減する。後から作成されたchabot_insoleコーパス（8413080345695485952）を削除し、正本（3097425410514747392）へ統一する。
- 対象: Vertex AI RAG Corpus（Google Cloudプロジェクト takahashi-451312 / us-central1）
- 備考: いずれも削除を伴うため、ユーザー承認を得てから実行する。

### #003 未実施 — カテゴリ別コーパスIDの環境変数設定とデプロイ
- 登録日時: 2026-10-20 15:15 JST
- 内容: Cloud Run（chabot-service / chabot-admin）の環境変数 GOOGLE_CORPUS_IDS_BY_CATEGORY に Basic/Pro用のカテゴリ別コーパスID（例: shoulder:1495705249682292736,knee:1172699519767281664,hip:1140048422468845568,ankle:2267637179171733504,elbow:8569298957769900032,gait:7748236450704916480,insole:3097425410514747392,physics:9077079815755923456,physiology:3675293537701724160,secure:380347460326785024,spine:1665843678964350976）を設定し、カテゴリ分類を本番へ反映する。
- 対象: Cloud Run 環境変数、デプロイ設定
- 備考: 未設定でもエラーにならず、従来のプラン別コーパスで動作する。

## 実施済み(新しい順)

### #005 実施済み — 管理統計の廃止とユーザー検索限定化
- 実施日時: 2026-10-23 12:56 JST
- 変更内容: LINE質問成功・上限拒否・クーポン成否・要望受付に伴う `admin_daily_stats` 書き込みを停止し、統計リポジトリ・管理API・管理画面の集計タブを削除。ユーザー画面は初期表示時にFirestoreを読まず、表示名前方一致・LINE user ID完全一致・内部ユーザーID完全一致の検索実行後だけ最大20件を表示する方式へ変更。既存の統計データは削除していない。
- 対象: app/api/v1/webhooks/line.py, app/services/line_service.py, app/admin_api.py, app/services/admin_service.py, app/repositories/firestore_admin_user_repository.py, app/admin_server.py, app/static/admin/admin.js, docs/admin-console-design.md, tests/unit
- 検証: 関連52件・全unit 273件（既知PostgreSQL Refresh Token除外）が合格。compileall、node --check、git diff --check成功。本番未反映。
- 本番反映: コミット 3f12a47（セッション強化・カテゴリ別コーパス選択とあわせてデプロイ）、GitHub Actions run 39898007438 成功で chabot-service へ100%反映（/health 200・デプロイ後ERRORログ0件）。同一コミットのCI構築イメージで chabot-admin-00020-sxp へ100%トラフィック反映（ready=True・未認証 /health 403でIAM保護確認）。

### #002 実施済み — Jevカテゴリ分類とカテゴリ別RAGコーパス選択の実装
- 実施日時: 2026-10-20 15:15 JST
- 変更内容: Jev入力ゲート（挨拶・お礼・対象外）通過後の質問を、rag_source/source の11カテゴリ（shoulder/knee/hip/ankle/elbow/gait/insole/physics/physiology/secure/spine）へ分類する classify_category を追加。Freeは常にfree用コーパス、Basic/Proは新環境変数 GOOGLE_CORPUS_IDS_BY_CATEGORY（"category:corpus_id" カンマ区切り）に対応するカテゴリ別コーパスへ検索を切替える。分類の信頼度しきい値は jev_category_confidence_threshold（既定0.60）で、低信頼・unknown・Jev未設定・障害時はプラン既定コーパスへフォールバック。LINE経路とWeb API（/message）の両方に適用し、LINE結果ペイロードへ category を追加。
- 対象: app/clients/vertex_ai.py, app/core/config.py, app/services/rag_service.py, app/services/line_service.py, app/api/v1/chat.py, tests/unit/test_clients/test_vertex_ai.py
- 検証: 追加テスト6件を含む関連テスト77件が合格。tests/unit 全体は、本変更と無関係な作業ツリー既存の状態（app/repositories/firestore_conversation_repository.py の削除済み・未コミット）によりchat.pyのインポートで失敗する。

### #001 実施済み — クーポン表示簡素化と旧Price互換判定の実装
- 実施日時: 2026-10-09 09:05 JST
- 変更内容: 管理UIクーポン発行フォームの見出しと説明文を削除。値上げ時のグランドファザーリング対応として get_plan_from_price_id が legacy Price ID 環境変数（STRIPE_BASIC_LEGACY_PRICE_IDS / STRIPE_PRO_LEGACY_PRICE_IDS）も判定対象に含めるよう修正。Checkout新規作成は現行Price IDのみ使用。
- 対象: app/static/admin/admin.js, app/core/pricing.py, .env.example, tests/unit/test_pricing.py
- 本番反映: コミット 46f3f5c、GitHub Actions run 37862710138 成功、chabot-service-00054-rkj（/health 200）・chabot-admin-00017-d5k（イメージdigest照合済み）へ100%トラフィック反映、ERRORログ0件確認
