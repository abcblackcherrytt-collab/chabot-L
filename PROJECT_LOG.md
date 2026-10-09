# プロジェクト管理ログ

## 未実施・進行中

（なし）

## 実施済み(新しい順)

### #001 実施済み — クーポン表示簡素化と旧Price互換判定の実装
- 実施日時: 2026-10-09 09:05 JST
- 変更内容: 管理UIクーポン発行フォームの見出しと説明文を削除。値上げ時のグランドファザーリング対応として get_plan_from_price_id が legacy Price ID 環境変数（STRIPE_BASIC_LEGACY_PRICE_IDS / STRIPE_PRO_LEGACY_PRICE_IDS）も判定対象に含めるよう修正。Checkout新規作成は現行Price IDのみ使用。
- 対象: app/static/admin/admin.js, app/core/pricing.py, .env.example, tests/unit/test_pricing.py
