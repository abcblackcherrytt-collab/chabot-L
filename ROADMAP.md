================================================================================
Chabot (LINE版) — Phase 2 / Phase 3 ロードマップ
================================================================================
生成日       : 2026-07-03
前提プロジェクト : GCP = takahashi-451312 / リージョン = asia-northeast1
注意         : 本ファイルは Phase 2 / Phase 3 の「全体予定（何を・なぜ・どこで）」を
              まとめるもの。個別の設定手順・コマンドは todo.txt、コード実装の詳細は
              REMAINING_TASKS.md の各セクション・マーカー対応表を参照のこと。
              本ファイルに実際のシークレット値は記載しない。
================================================================================


■ Phase 構成の全体像（3層・依存関係）
================================================================================
Phase 1（現在・稼働準備中）
  → Stripe/DB なしで「友だち追加だけでボットが使える」状態。詳細は todo.txt 参照。

Phase 2（後続・DB + モックプラン）          ← 本ファイルの主題(1)
  → Cloud SQL を繋ぎ、モックプランで「回数制限・プラン判定・コーパス切替」を動かす。
    Stripe は使わない（プランは固定/デバッグ切替のモック判定）。

Phase 3（後続・実 Stripe 決済フレームワーク） ← 本ファイルの主題(2)
  → Stripe サンドボックスで「実際のプラン登録・退会処理」を検証し、本番化する。

依存: Phase 1 → Phase 2（DB 基盤）→ Phase 3（実 Stripe）
備考: 旧 Phase 2（todo.txt/REMAINING_TASKS.md の旧定義）を「DB+モック（新 Phase 2）」
      と「実 Stripe（新 Phase 3）」に分割再編成した。マーカーの再分類マップは末尾参照。


■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
■ Phase 2: DB 整備 + モックプラン（Stripe 不使用）
■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
[ゴール] Cloud SQL に接続し、モックプランでチャット回数制限と
         プラン別コーパス切替を検証する。Stripe 決済は扱わない。

[前提・既存資産] モデル 7 種（User/Subscription/UsageDaily/Conversation/
                RefreshToken/RagPermission/StripeEvent）とマイグレーション 2 本は
                既に定義済み（alembic/versions/）。RagPermission に
                daily_message_limit / rag_corpus_id / model_name カラムも既定義。

--------------------------------------------------------------------------------
[P2-1] Cloud SQL（PostgreSQL 16）インフラ整備
--------------------------------------------------------------------------------
  - インスタンス chabot-postgres / PG16 / db-custom-1-3840（本番）
  - VPC Access Connector（asia-northeast1）/ DATABASE_URL（unix socket 形式）
  - deploy.yml の --set-cloudsql-instances と DATABASE_URL=database-url を復帰
  ※ 詳細コマンドは todo.txt [A1][A2][A3][C7] / REMAINING_TASKS.md「GCP インフラ構築」

--------------------------------------------------------------------------------
[P2-2] DB 接続の有効化
--------------------------------------------------------------------------------
  - app/server.py:60 lifespan で init_db() を呼び出し（[Phase 2 マーカー I2]）
  - app/models/__init__.py のエクスポート不備を是正（現状 User/RefreshToken のみ →
    Subscription/UsageDaily/Conversation/RagPermission/StripeEvent を追加）
  - 初回デプロイ前に Cloud SQL で alembic upgrade head（todo.txt [D1]）

--------------------------------------------------------------------------------
[P2-3] LINE Webhook / Login フローの DB 連携（ユーザー永続化）
--------------------------------------------------------------------------------
  - follow: ユーザー作成/再有効化 → app/services/line_service.py:173（[マーカー A4]）
    ※ UserRepository.find_by_line_user_id / create を実装。
      シグネチャは app/repositories/user.py:111-131 に既記載（[マーカー H1]）
  - LINE Login callback: ユーザー永続化 → app/api/v1/auth_line.py:213-235（[マーカー C1/C2]）
    ※ 現状の「仮 UUID 都度発行」を DB 検索した既存 ID に切替

--------------------------------------------------------------------------------
[P2-4] モックプラン判定
--------------------------------------------------------------------------------
  - 全ユーザーを固定のモックプラン（例: free。デバッグ用に切替可）として扱う
  - app/core/deps.py:89-105 の require_active_subscription（[マーカー D2]）は、
    Phase 2 では「常に許可（回数判定のみ実施）」のモック挙動にする
  - Subscription.is_active_paid() / is_restricted()（app/models/subscription.py）は
    Phase 3 まで未使用（[マーカー H2]）

--------------------------------------------------------------------------------
[P2-5] チャット回数判定（Phase 2 の中核）
--------------------------------------------------------------------------------
  - UsageDaily モデルは既存だが、これを更新・集計するサービス/リポジトリが
    まだ無い → 【新設】（usage_repository.py / usage_service.py 相当）
  - 1日のメッセージ数を UsageDaily.message_count で集計し、
    RagPermission.daily_message_limit（free=10 / basic=100 / pro=500）と照合
  - 制限超過時は app/api/v1/webhooks/line.py:50 で RAG クエリせず
    制限メッセージを返却（[マーカー B2]）
  ※ シード値（free=10/basic=100/pro=500）は todo.txt [D2] の INSERT を踏襲

--------------------------------------------------------------------------------
[P2-6] プラン別コーパス切替
--------------------------------------------------------------------------------
  - RagPermission.rag_corpus_id / model_name を読むリポジトリを【新設】（[マーカー H5]）
  - app/services/rag_service.py:35 の RAGService.query が、
    ユーザーのプランに応じて corpus_id を切り替えて VertexAIClient に渡す
    ※ VertexAIClient は __init__ で corpus_id を引数取り済み（app/clients/vertex_ai.py:59）
  - app/models/conversation.py の Conversation テーブルに
    plan_at_request / rag_corpus_id / トークン使用量を記録

--------------------------------------------------------------------------------
[P2-7] ⚠️ 前提: Vertex AI 実 API 統合
--------------------------------------------------------------------------------
  - 現状 app/clients/vertex_ai.py:292 は完全モック（固定のフォールバック応答）
  - コーパス切替の検証には実 API 呼び出しが必要 → Phase 2 の先行タスクとして実装
  - Phase 1 でも GOOGLE_CORPUS_ID 未設定だとフォールバック応答になる点に注意


■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
■ Phase 3: 実 Stripe 決済フレームワーク + 退会処理
■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
[ゴール] Stripe サンドボックス（テストモード）でプラン登録・退会フローを検証し、
         本番キーに切替えて稼働する。Phase 2 の DB 基盤をそのまま利用。

[前提・既存資産] app/clients/stripe.py に StripeClient（create_customer /
                Webhook 検証等）実装済み。app/services/stripe_service.py に
                Webhook ハンドラ 5 種（現状すべてログのみ）。Stripe Webhook
                ルータは app/server.py:110 で登録済み（Phase 1 では実イベント不来）。

--------------------------------------------------------------------------------
[P3-1] Stripe サンドボックス（テストモード）設定
--------------------------------------------------------------------------------
  - Stripe Dashboard で商品/価格（Price）を作成 → 価格ID(price_...) を控える
  - Webhook エンドポイント登録（テストURL）・Signing secret(whsec_...) 取得
  - イベント: customer.subscription.created/updated/deleted, invoice.paid,
              invoice.payment_failed
  ※ 詳細は todo.txt [B3] / REMAINING_TASKS.md「Stripe 連携」

--------------------------------------------------------------------------------
[P3-2] プラン登録フレームワーク
--------------------------------------------------------------------------------
  - postback action=subscribe で Stripe Checkout セッション生成 →
    app/services/line_service.py:262（[マーカー A7]）
  - create_customer 呼び出し連携 → app/services/stripe_service.py:45（[マーカー G1]）
  - follow/初回ログイン時に Stripe 顧客を作成し User.stripe_customer_id に書込（[マーカー H3]）

--------------------------------------------------------------------------------
[P3-3] Stripe Webhook ハンドラの DB 連携（現状すべてログのみ）
--------------------------------------------------------------------------------
  - _handle_invoice_paid          : Subscription の請求期間更新（[マーカー G2]）
  - _handle_invoice_payment_failed: 支払い失敗の LINE 通知（[マーカー G3]）
  - _handle_subscription_created  : Subscription レコード作成（[マーカー G4]）
  - _handle_subscription_updated  : status/plan 更新・is_restricted 連携（[マーカー G5]）
  - _handle_subscription_deleted  : 解約処理（[マーカー G6]）
  ※ app/services/stripe_service.py:356-565 の各 _handle_* メソッド

--------------------------------------------------------------------------------
[P3-4] 決済冪等性の DB 永続化
--------------------------------------------------------------------------------
  - app/clients/stripe.py:62 のインメモリ辞書 → StripeEvent テーブルへ移行（[マーカー H4]）
    ※ Cloud Run はステートレス/マルチインスタンスのため、インメモリでは
      再起動で冪等性が失われる。DB 永続化が必須。

--------------------------------------------------------------------------------
[P3-5] 本番ゲート有効化
--------------------------------------------------------------------------------
  - require_active_subscription を本番化（[マーカー D2]）
    → Subscription.is_active_paid() でゲート、未契約は 403
  - app/api/v1/chat.py:97 の Depends(get_current_user) を
    Depends(require_active_subscription) に差し替え（[マーカー E1]）
  - message イベントのサブスク検証ゲートも有効化（[マーカー A2]）

--------------------------------------------------------------------------------
[P3-6] 退会時処理
--------------------------------------------------------------------------------
  - unfollow（LINE 友だち解除）: is_active=False ＋ リフレッシュトークン全削除 →
    app/services/line_service.py:224（[マーカー A6]）
  - subscription_deleted（Stripe 解約）: ユーザー無効化 ＋ トークン全削除 ＋
    LINE Push 通知 → app/services/stripe_service.py:533（[マーカー G6]）

--------------------------------------------------------------------------------
[P3-7] 本番 Stripe 設定（サンドボックス検証後）
--------------------------------------------------------------------------------
  - ライブキー（sk_live_/pk_live_）取得・Secret Manager 登録・環境変数化
  - app/core/config.py:55-57 のプレースホルダ（sk_test_*/whsec_*/pk_test_*）を
    Secret Manager から注入（[マーカー I1]）
  ※ todo.txt [B3][C5][E5] / REMAINING_TASKS.md「Stripe 連携」


■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
■ 旧 Phase 2 → 新 Phase 2 / Phase 3 再分類マップ
■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
旧 todo.txt/REMAINING_TASKS.md の「Phase 2」を以下の通り再分類した。

[新 Phase 2（DB + モック）に分類]
  - コードマーカー: A2(回数判定のみ) / A4 / B2 / C1 / C2 / H1 / H5 / I2
  - 設定タスク:    [A1][A2][A3][C7][D0][D1]（DB 基盤）/ [D2]（RagPermission シード）
  - 環境変数:      DATABASE_URL（todo.txt [E2]）

[新 Phase 3（実 Stripe）に分類]
  - コードマーカー: A6 / A7 / G1 / G2 / G3 / G4 / G5 / G6 / H2 / H3 / H4 / E1 /
                    D2(本番ゲート) / I1
  - 設定タスク:    [B3][C5][E5]（Stripe 本番）
  - 環境変数:      STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET（todo.txt [E5]）

[両 Phase にまたがる（注意）]
  - マーカー D2（require_active_subscription）: Phase 2 は「常に許可（モック）」、
    Phase 3 で「is_active_paid() でゲート（本番）」に昇格
  - マーカー A2（_handle_message_event）: Phase 2 は「回数判定ゲート」、
    Phase 3 で「サブスク検証ゲート」を追加

※ todo.txt 旧「Phase 2 統合チェックリスト [P2-A〜G]」は新 Phase 2/3 の両ブロックに分割。
※ REMAINING_TASKS.md 旧「Phase 2 コード実装マーカー対応表」は Phase 2/3 の2表に再編成。


■ 進め方の目安
================================================================================
1. Phase 2 は [P2-7] Vertex AI 実 API 統合を先行させ、[P2-1]→[P2-2]→[P2-3] で DB 基盤と
   ユーザー永続化を整え、[P2-5] 回数判定 → [P2-6] コーパス切替 の順で検証する。
2. Phase 2 でモックプランの回数制限・コーパス切替が想定通り動くことを確認してから Phase 3 へ。
3. Phase 3 はサンドボックスで [P3-1]→[P3-2][P3-3] の登録/解約フローを検証し、
   [P3-6] 退会処理が正しくユーザー無効化することを確かめてから [P3-7] 本番化。
================================================================================
