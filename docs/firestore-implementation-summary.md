# Firestoreベース実装の概要

## 実装完了内容

### 1. Firestoreユーザーリポジトリの拡張
- **ファイル**: `app/repositories/firestore_user_repository.py`
- **機能**:
  - Stripe顧客ID管理メソッド追加
    - `find_by_stripe_customer_id()` - Stripe顧客IDでユーザー検索
    - `update_stripe_customer_id()` - Stripe顧客ID紐付け
    - `get_stripe_customer_id()` - Stripe顧客ID取得

### 2. 抽象基底クラスの拡張
- **ファイル**: `app/repositories/base_user_repository.py`
- **機能**: Stripe関連メソッドのインターフェース定義を追加

### 3. PostgreSQL版リポジトリの実装
- **ファイル**: `app/repositories/user.py`
- **機能**: Firestore版と同じStripe関連メソッドを実装してインターフェース統一

### 4. RAG権限リポジトリのFirestore版
- **ファイル**: `app/repositories/firestore_rag_permission_repository.py`
- **機能**:
  - プラン別コーパスID・モデル名の取得
  - 全プラン設定の取得・作成・更新・削除

### 5. LINEサービスの拡張
- **ファイル**: `app/services/line_service.py`
- **機能**:
  - データベースバックエンドに応じたRAG権限リポジトリの動的切り替え
  - メッセージ処理でプラン別コーパス・モデルを解決

### 6. セットアップ・テストスクリプト
- **初期データセットアップ**: `scripts/setup_firestore_data.py`
  - free/basic/proプランのRAG権限設定をFirestoreに作成
- **動作テスト**: `scripts/test_plan_corpus_switching.py`
  - プラン別コーパス切替の動作確認
  - Stripe顧客ID紐付けの動作確認
  - ユーザー有効/無効化の動作確認
- **データクリーンアップ**: `scripts/cleanup_test_data.py`
  - テストデータの削除・一覧表示

## データ構造

### Firestore コレクション構造

**users コレクション**:
```json
{
  "id": "UUID",
  "line_user_id": "LINEユーザーID",
  "display_name": "表示名",
  "email": "メールアドレス（任意）",
  "stripe_customer_id": "Stripe顧客ID（任意）",
  "subscription_plan": "free/basic/pro",
  "subscription_status": "active/canceled/...",
  "is_active": true/false,
  "role": "user",
  "created_at": "ISO日時",
  "updated_at": "ISO日時"
}
```

**rag_permissions コレクション**:
```json
{
  "id": "UUID",
  "plan": "free/basic/pro",
  "rag_corpus_id": "コーパスID",
  "model_name": "モデル名",
  "max_input_tokens": 数値,
  "max_output_tokens": 数値,
  "daily_message_limit": 数値,
  "enabled": true/false,
  "created_at": "ISO日時",
  "updated_at": "ISO日時"
}
```

## 使用方法

### 1. 環境設定
`.env`ファイルでFirestoreを使用するように設定：
```bash
database_backend=firestore
firestore_project_id=takahashi-451312
```

### 2. 初期データセットアップ
```bash
python scripts/setup_firestore_data.py
```

### 3. 動作テスト
```bash
python scripts/test_plan_corpus_switching.py
```

### 4. テストデータのクリーンアップ
```bash
# テストユーザー一覧表示
python scripts/cleanup_test_data.py --list

# テストユーザー一括削除
python scripts/cleanup_test_data.py --all-test-users

# 特定ユーザー削除
python scripts/cleanup_test_data.py --user-id USER_ID
```

## プラン別コーパス切り替えの仕組み

1. LINEメッセージ受信時:
   - LINEユーザーIDでユーザー検索
   - ユーザーのサブスクリプションプランを取得
   - プランに応じたRAG権限（コーパスID・モデル名）を解決
   - 解決したコーパスとモデルでRAG応答生成

2. プラン変更時:
   - `update_subscription_plan()`でプラン更新
   - 次回メッセージから新しいプランのコーパスが使用される

## 依存関係

既に `requirements.txt` に追加済み:
```
google-cloud-firestore>=2.19.0
```

## 次のステップ

1. 実際のFirestoreプロジェクトIDとコーパスIDを設定
2. Stripeウェブフックとの連携テスト
3. 本番環境へのデプロイ準備
