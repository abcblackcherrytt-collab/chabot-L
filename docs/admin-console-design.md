# 管理コンソール設計（Phase 2.7）

> ステータス: 設計のみ。実装・デプロイは未実施。
> 関連: PROJECT_PLAN.md 2.6節、app/admin_server.py（ASGI入口のみ実装済み）。

## 1. 目的とスコープ

公開Bot（chabot-service）とは別の管理専用サービスとして、次をWeb画面で行えるようにする。

1. クーポンの発行・失効・状況確認
2. 無料アカウントの作成（登録URL発行とLINEユーザー直指定）
3. フリープランを含む日次回数上限の設定
4. 登録ユーザー一覧とプラン変更
5. 個別集計項目としてのアクティブユーザー数・メッセージ数の提示
6. 全ユーザーの質問と回答（Q&Aペア）の保管
7. LINEでの要望受付と、管理画面での要望確認・対応管理

本書は設計のみであり、Cloud Runサービス・リソースの実際の作成は行わない。

## 2. システム構成（Cloud Run URL）

- 公開Bot: 既存 chabot-service（変更なし。管理ルート混入禁止の回帰テスト済み）
- 管理サービス: 新規 chabot-admin（Cloud Run、asia-northeast1）
  - 入口: app.admin_server:app（実装済み・既定無効）
  - URL想定: https://chabot-admin-<hash>-an.a.run.app（カスタムドメイン任意）
  - --no-allow-unauthenticated、ingress internal-and-cloud-load-balancing
  - ブラウザ認証は HTTPS LB + Serverless NEG 経由の Cloud IAP とする（Cloud Run単体でのIAPはLB経由が必要）。IAP完了前の暫定運用はIAM invokeを管理者のみへ限定し、URLを非公開とする
- デプロイ: 専用workflow .github/workflows/deploy-admin.yml（設計のみ。公開Bot用deploy.ymlとは完全分離し、ワークフローとサービス名の誤設定をCIで検査する）
- ローカル開発: ADMIN_UI_ENABLED=True uvicorn app.admin_server:app --port 8001

## 3. 認証・認可

1. 前段: Cloud IAP（x-goog-iap-jwt-assertion 検証、audience = サービスURL）
2. 認可: 管理者allowlist（Firestore admin_admins/{email}。個人アカウントのみ、共有アカウント禁止）
3. 書込み保護: 全書込APIでCSRF token（サーバ発行・Session Cookie紐付け）と Origin/Referer 検証
4. セッション: IAPヘッダ検証後に短命セッションCookie（HttpOnly / Secure / SameSite=Strict）
5. 監査: 全操作を admin_audit_logs へ記録。本文・トークン・PIIは保存しない

## 4. Firestoreデータ設計（新規）

| コレクション | 主フィールド | 用途 |
|---|---|---|
| plan_settings/{plan} | daily_message_limit, published_revision, updated_by, updated_at | 日次回数上限（free/basic/pro） |
| coupons/{id} | code_sha256, kind, plan, duration_days, bonus_free_messages, max_redemptions, redeemed_count, expires_at, status, created_by, note | クーポン定義 |
| coupon_redemptions/{coupon_id}_{user_id} | redeemed_at, granted_plan, expires_at | 引き換え冪等性 |
| admin_invites/{id} | token_sha256, status, expires_at, created_by, consumed_by, consumed_at | 1回限り無料登録URL |
| admin_audit_logs/{auto} | actor, action, target_type, target_id, revision, result, timestamp | 監査 |
| admin_daily_stats/{yyyy-mm-dd} | message_count, active_users, denied_by_limit, coupon_redemptions, feedback_count | 個別集計（日次） |
| conversations/{auto} | user_id, question_text, answer_text, plan, question_type, answer_aspects, denied, created_at | 全ユーザーの質問・回答ペア保管 |
| feedback/{auto} | user_id, content, status, admin_note, handled_by, handled_at, created_at | LINE要望 |
| feedback_pending/{user_id} | expires_at | 要望受付モード中フラグ（TTL 10分） |

users（既存）へ追加: plan_override {plan, expires_at, source}（クーポン付与・管理者変更による優先プラン）。

## 5. プラン解決優先度（Bot側）

1. Stripe subscription（status=active）… 決済による正式プラン
2. plan_override（未期限切れ）… クーポン付与・管理者手動変更
3. free … 既定

- 期限切れは参照時に判定する（lazy expiry）。期限切れデータの更新は不要
- plan_override とStripe契約が競合する場合はStripeを優先し、管理画面に競合警告を表示
- 日次上限は plan_settings を60秒キャッシュで読み、欠損・不正時は app/core/pricing.py の 3/100/500 へフォールバック

## 6. 機能設計

### 6.1 クーポン発行

- 種別
  - plan_grant: 指定プラン（basic/pro）をN日間付与
  - bonus_messages: freeの当日回数をN回追加（日次でリセット）
- コード: Crockford Base32・8〜12桁・大文字・チェックディジット付き。平文は発行時のみ1回表示し、FirestoreにはSHA-256ハッシュのみ保存
- 制約: max_redemptions（全体上限）。ユーザーごと1回は coupon_redemptions の複合キーで保証。expires_at で期限
- 引き換え: ユーザーがLINEで「クーポン CODE」と送信 → 公開Botがハッシュ化・照合 → Firestore Transactionで redemption作成 + plan_override付与を原子的に実行 → 成功/失敗をLINEで返信
- 管理操作: 発行・一覧（引き換え数・残数）・失効。失効は新規引き換えの停止のみ（付与済み分は維持し、個別取消はユーザー編集で対応）
- セキュリティ: コードをログ・監査・URLへ出さない。引き換え試行はユーザーごとにレート制限（例: 10回/日）。連続失敗を admin_daily_stats へ記録

### 6.2 無料アカウント作成

2方式を併用する。

1. 登録URL発行（推奨）: admin_invites に1回限りURLを発行。トークンはURL fragmentで受け渡し、claim landingで短期セッションへ移行後、LINE Loginで本人確定 → Transactionで unused -> consumed + freeユーザー作成
2. LINEユーザー直指定: 管理者がLINE user IDを入力してfree作成。実在確認はMessaging APIのプロフィール取得で行い、未友だちならエラー。テスト・移行用

### 6.3 フリープラン回数設定

- 対象: free（必須）/ basic / pro（任意）
- 画面で daily_message_limit を編集。下書き保存 → 差分確認 → 反映（published_revision をTransactionで切替）→ 履歴から1クリックロールバック
- サーバ検証: 空欄不可、1〜999、revision不一致は競合エラー
- Bot反映は最大60秒。画面に「反映まで最大60秒」を明示

### 6.4 登録ユーザー一覧・プラン変更

- 一覧: Firestore pageToken逐次取得（offset禁止）。表示: 表示名 / プラン / 有効状態 / 当日利用回数 / 登録日。検索は表示名前方一致。LINE user ID・emailは詳細画面のみ、一覧ではマスク
- プラン変更: POST /users/{id}/plan（plan + reason必須）。plan_override を書き換え、監査へbefore/afterとreasonを記録。Stripe契約中ユーザーには確認ダイアログで競合警告
- 禁止: 会話本文・Stripe内部値の編集。ユーザーの削除は行わず is_active=false の無効化のみ（unfollowと同じ扱い）

### 6.5 個別集計（アクティブユーザー数・メッセージ数）

ダッシュボードのような統合画面は作らない。管理画面の「集計」項目として、目的別の数値だけを提示する。

- 表示指標: 期間（日次・週次・月次）別のアクティブユーザー数、メッセージ数。必要に応じて上限拒否数・クーポン引き換え数・要望件数も同じ集計項目内の個別指標として提示する
- データソース: Bot側で日次の使用カウント更新と同じタイミングで admin_daily_stats へ increment。集計期間の切替は既存ドキュメントの範囲集計で行い、集計用の事前計算は作らない
- 検索・抽出用途では users 一覧の当日利用回数、conversations の件数カウントを併用できる

### 6.6 会話保管（質問と回答のペア）

- 書き込み経路: 公開Botが回答送信に成功した後、conversations へ質問本文・回答本文を1ドキュメントで保存（plan、分類結果、否認フラグ、時刻も記録）。保存失敗でユーザーへの回答は止めず、失敗ログと再試行対象として記録する
- 保存範囲: 全ユーザー・全メッセージ（free/basic/pro共通）。回数上限で拒否されたものは denied=true で本文なしのメタデータのみ保存する
- プライバシー: 保存時に氏名・施設名らしきパターンを検知したら pii_suspected フラグを付ける（マスキングは回答品質を損なうため初期は検知のみ）。管理画面の初期版では本文を表示せず件数・メタデータ参照のみとし、本文閲覧は監査記録付きの個別権限として将来追加する（2.6節レビューの患者情報リスクを継承）
- 保持期間: 未決定（10節）。TTLポリシーまたは定期削除で制御できる構成にする

### 6.7 LINE要望の受付と確認

- 受付（LINE側）: クイックリプライ／リッチメニューに「要望を送る」を用意する。タップで feedback_pending/{user_id} を作成（TTL 10分）し、「この後のメッセージ1通を要望として受け付けます」と案内 → 次の1通を feedback へ保存 → 「受け付けました」と返信して受付モードを終了する。受付モード中の通常質問は一旦要望として扱われるため、案内文で取消方法（「やめる」と入力）も示す
- 制限: ユーザーごとに1日5通まで。管理用途を聞く選択肢（機能要望／不具合／その他）をquick replyで付ける
- 管理画面: 要望一覧（未対応／対応済みで絞込・新着順）、詳細（送信者の表示名と日時）、ステータス更新（対応済み）と管理メモ。ユーザーへの返信機能は初期版に含めない
- 監査: ステータス変更・メモ記録を admin_audit_logs へ保存。要望本文は監査ログへコピーしない

### 6.8 追加で設計した機能（新規）

1. 監査ログ閲覧: 全管理操作の時系列表示（actor/action/target/revision/結果のみ）
2. 設定ロールバック: plan_settings / prompt_configs の履歴管理・復元
3. クーポン引き換えBot経路: 管理画面単独では完結しないため公開Bot側処理として設計
4. レート制限・不正試行検知: クーポン引き換れ・要望送信・ログイン試行

## 7. API一覧（/api/v1/admin/*）

| メソッド | パス | 概要 |
|---|---|---|
| GET | /users | 一覧（pageToken / q / plan / status） |
| GET | /users/{id} | 詳細（PIIは管理者のみ・監査記録） |
| POST | /users/{id}/plan | プラン変更（reason必須） |
| POST | /users/{id}/deactivate | 無効化 |
| GET | /plan-settings | 上限設定一覧 |
| PUT | /plan-settings/{plan} | 下書き保存 |
| POST | /plan-settings/{plan}/publish | 反映（revision指定） |
| POST | /plan-settings/{plan}/rollback | 前revisionへ戻す |
| POST | /coupons | 発行（平文コードは初回のみ応答） |
| GET | /coupons | 一覧（引き換れ状況） |
| POST | /coupons/{id}/revoke | 失効 |
| POST | /invites | 無料登録URL発行 |
| GET | /invites | 一覧・状態 |
| POST | /users/free | LINE user ID直指定でfree作成 |
| GET | /audit-logs | 監査ログ |
| GET | /stats/active-users | 期間別アクティブユーザー数 |
| GET | /stats/messages | 期間別メッセージ数 |
| GET | /conversations | 保管済み会話の件数・メタデータ（本文は初期版で返さない） |
| GET | /feedback | 要望一覧（status絞込・新着順） |
| POST | /feedback/{id}/status | 対応ステータス更新（admin_note付き） |

## 8. セキュリティ要点（2.6節レビュー準拠）

- 全HTML/API: Cache-Control: no-store、Referrer-Policy: no-referrer、CSP、frame拒否、nosniff（SecurityHeadersMiddlewareで実装済み）
- PII（表示名・LINE ID・email）は詳細画面のみ、ログ・監査・例外へ出さない
- FirestoreはIAMで全体許可。管理サービスは専用SA + 最小権限。コレクション単位の境界とみなさない
- 招待トークン・クーポンコードはURL・ログ・履歴へ残さない（fragment + no-store + ハッシュ保存）
- 会話本文・要望本文の保管に伴い、患者情報混入の検知フラグ、管理画面での本文非表示（初期版）、保持期間設定を必須とする
- 書込みはCSRF token + Origin検証。全操作に監査
- データ保存リージョン（nam5）と国外処理の論点は2.6節の判断を継承

## 9. 実装フェーズ案

| マイルストーン | 内容 | 完了条件 |
|---|---|---|
| M1 | IAP認証・allowlist・監査基盤 | 未認証拒否・監査記録のE2E |
| M2 | ユーザー一覧・詳細・プラン変更 | ID差替え・CSRF否定系を含むE2E |
| M3 | plan_settings（回数設定・反映・ロールバック） | Bot側60秒反映とfallback確認 |
| M4 | クーポン（発行・Bot引き換れ・失効） | 並行引き換えで1ユーザー1回を保証 |
| M5 | 無料登録URL・個別集計・会話保管・要望管理 | URL単回消費・要望受付FLOW・会話保存のE2E |

## 10. 未決定事項（実装前に確定）

1. クーポンをStripeプロモーションコード（Checkout割引）と連携するか、本設計のapp内プラン付与のみか
2. bonus_messages（free当日回数追加）を初回リリースに含めるか
3. 管理者候補アカウント（email）と人数
4. chabot-admin の最小IAM（datastore.user を絞るか custom role を作るか）
5. conversations の保持期間（無期限／1年など）と、本文閲覧機能の要否
6. 要望受付の入口をクイックリプライとリッチメニューのどちらに固定するか、1通完結方式でよいか
