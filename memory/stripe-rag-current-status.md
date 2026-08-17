---
name: stripe-rag-current-status
description: Stripe決済とRAGコーパス構成の現在の実装状況
metadata:
  type: project
---

## Stripe決済実装状況

### 進捗サマリー
- **Phase 1**: 友だち追加だけでボット動作（Stripe/DB なし）
- **Phase 2**: DB + モックプラン（Stripe 不使用、ローカル検証済み）
- **Phase 3**: 宾 Stripe 決済（コード準備完了、未有効化）

### 既に実装済みのコード
1. **StripeClient** (`app/clients/stripe.py`): 非対応応化、Webhook署名検証、冪等性管理
2. **StripeService** (`app/services/stripe_service.py`): 5種Webhookハンドラ（invoice.paid/failed, subscription.created/updated/deleted）
3. **Subscriptionモデル**: `is_active_paid()`, `is_restricted()` メソッド実装済み

### Phase 3 で有効化予定
- DB連携のあるWebhook処理
- 退会処理（is_active=False + トークン全削除 + LINE通知）
- 冪等性管理のDB永続化（StripeEventテーブル使用）

## RAGコーパス構成状況

### 既に実装済み
1. **RagPermissionモデル** (`app/models/rag_permission.py`)
   - plan → rag_corpus_id, model_name, daily_message_limit のマッピング
   - ローカル検証済み（2026-07-05）

2. **RAGService** (`app/services/rag_service.py`)
   - corpus_id, model_name 引数で動的切替可能
   - Vertex AI 実API統合済み

### 専門領域別コーパス拡張方針
1. **RagPermission拡張**: domainカラム追加（shoulder, knee, spine等）
2. **クエリ分類レイヤー新設**: ルールベース or 軽量LLMで専門領域判定
3. **コーパスID命名規則**: `{plan}_{domain}_corpus` 例: basic_shoulder_corpus

### 返答速度への影響
- **DBオーバーヘッド**: 無視できる（<5ms、インデックス済み）
- **クエリ分類**: 軽量LLM分類でも <100ms、ルールベースなら <10ms
- **RAG自体**: Gemini Flashが前提（～1-2秒）
- **結論**: 構成変更による速度劣化は最小限
