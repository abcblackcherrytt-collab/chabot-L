Chabot LINE 残タスクリスト
============================
最終更新: 2026-06-08

## 🔴 必須（本番稼働前に完了させること）

### LINE Developers 設定
- [ ] LINE Developers アカウント登録（https://developers.line.biz）
- [ ] プロバイダー作成
- [ ] Messaging API チャネル作成
  - [ ] Channel Secret 取得 → .env の LINE_CHANNEL_SECRET に設定
  - [ ] Channel Access Token（長期）取得 → .env の LINE_CHANNEL_ACCESS_TOKEN に設定
  - [ ] Webhook URL 設定 → https://<Cloud Run URL>/api/v1/webhooks/line
  - [ ] 「Webhook の利用」をオン
  - [ ] 「自動応答メッセージ」をオフ
  - [ ] 「友だち追加挨拶」をオフ（またはカスタムメッセージ設定）
- [ ] LINE Login チャネル作成（または同一チャネルで有効化）
  - [ ] Channel ID 取得 → .env の LINE_LOGIN_CHANNEL_ID に設定
  - [ ] Channel Secret 取得 → .env の LINE_LOGIN_CHANNEL_SECRET に設定
  - [ ] コールバックURL設定 → .env の LINE_LOGIN_CALLBACK_URL に設定
  - [ ] BOT プロンプト設定（任意）
- [ ] リッチメニュー作成（LINE Official Account Manager で設定）

### データベース
- [ ] Alembic マイグレーション作成
  ```bash
  alembic revision --autogenerate -m "add line_user_id to users"
  alembic upgrade head
  ```
- [ ] マイグレーション内容確認（line_user_id カラムが users テーブルに追加されること）

### セキュリティ（重要）
- [ ] security.py: RS256 署名検証の本番実装
  - https://api.line.me/oauth2/v2.1/certs から JWKS 公開鍵を取得
  - ID トークンの署名を公開鍵で検証するロジックを実装
  - 現在はクレーム検証のみで署名検証がスキップされている（TODOコメント箇所）
- [ ] .env の JWT_SECRET_KEYS を本番用ランダム値に更新
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
- [ ] Stripe Webhook Secret を本番用に更新

### Stripe 連携
- [ ] Stripe Dashboard で Webhook エンドポイント登録
  - URL: https://<Cloud Run URL>/api/v1/webhooks/stripe
  - イベント: customer.subscription.created, customer.subscription.updated, customer.subscription.deleted, invoice.paid, invoice.payment_failed
- [ ] Stripe 商品・価格（Price）を作成
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

## 🟡 推奨（安定性・UX向上）

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

### インフラ
- [ ] Google Secret Manager に LINE シークレットを登録
  - line-channel-secret
  - line-channel-access-token
  - line-login-channel-id
  - line-login-channel-secret
- [ ] Cloud Run の環境変数/シークレット設定を更新
- [ ] 本番デプロイ後の動作確認（LINE Developers Console の Webhook tester 使用）
- [ ] Cloud Scheduler のトークンクリーンアップジョブ更新
