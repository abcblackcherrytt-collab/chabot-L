# Chabot プロジェクト開発ガイド

このドキュメントは、Chabot プロジェクトの開発者向けガイドです。

## プロジェクト概要

Chabot は FastAPI + Vertex AI RAG + LINE Bot + Stripe を組み合わせた AI チャットボットサービスです。

- **FastAPI**: 高速な非同期APIサーバー
- **Vertex AI RAG**: Google Cloud Vertex AI を使用したRAG（検索拡張生成）
- **LINE Bot**: LINE Messaging API によるユーザーとの対話
- **LINE Login**: LINEアカウントによるユーザー認証（OIDC準拠）
- **Stripe**: サブスクリプション決済処理（※ Phase 2 で有効化。Phase 1 は Stripe/DB なしで友だち追加だけで動作 → 詳細は `todo.txt` / `REMAINING_TASKS.md` の Phase 分け、およびコード内 `# [Phase 2]` マーカー参照）

## 技術スタック

- **Python**: 3.11+
- **FastAPI**: 0.104.0+（非同期対応）
- **SQLAlchemy**: 2.0.0+（非同期ORM）
- **Alembic**: データベースマイグレーション
- **PostgreSQL**: 16+
- **Google Cloud**: Vertex AI, Secret Manager, Cloud Run
- **LINE**: Messaging API, LINE Login v2.1 (OIDC)

## プロジェクト構造

```
chabot/
├── app/
│   ├── api/                  # APIルート
│   │   └── v1/              # v1 APIエンドポイント
│   ├── clients/             # 外部APIクライアント
│   ├── core/                # 設定・セキュリティ
│   ├── db/                  # データベース関連
│   ├── models/              # データベースモデル
│   ├── repositories/        # データアクセス
│   ├── schemas/             # Pydanticスキーマ
│   ├── services/            # ビジネスロジック
│   └── server.py            # FastAPIアプリケーション
├── alembic/                 # データベースマイグレーション
├── tests/                   # テストコード
├── .github/                 # GitHub Actions
├── Dockerfile
├── requirements.txt
└── README.md
```

## 開発環境セットアップ

### 前提条件

- Python 3.11+
- PostgreSQL 16+
- Docker
- Google Cloud SDK

### セットアップ手順

1. 仮想環境を作成

```bash
python3 -m venv venv
source venv/bin/activate
```

2. 依存関係をインストール

```bash
pip install -r requirements.txt
```

3. 環境変数を設定

```bash
cp .env.example .env
# .envファイルを編集
```

4. PostgreSQLを起動

```bash
docker run -d \
  --name chabot-postgres \
  -e POSTGRES_USER=root \
  -e POSTGRES_PASSWORD=your-password \
  -e POSTGRES_DB=chabot \
  -p 5432:5432 \
  postgres:16-alpine
```

5. データベースマイグレーションを実行

```bash
alembic upgrade head
```

6. サーバーを起動

```bash
uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

## コーディング規約

### 一般的な規約

- **Python**: PEP 8 準拠
- **型ヒント**: 関数には必ず型ヒントを付与
- **ドキュメント**: モジュール・クラス・関数にはdocstringを記述
- **非同期**: データベースアクセス・外部API呼び出しは非同期関数を使用

### 例

```python
"""ユーザーリポジトリ"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User


class UserRepository:
    """ユーザーのデータアクセスオブジェクト"""

    async def find_by_email(
        self,
        db: AsyncSession,
        email: str,
    ) -> Optional[User]:
        """
        メールアドレスでユーザーを検索

        Args:
            db: データベースセッション
            email: メールアドレス

        Returns:
            ユーザー、存在しない場合はNone
        """
        # 実装
```

### アーキテクチャパターン

- **レイヤードアーキテクチャ**: API → Service → Repository → Model
- **依存性注入**: FastAPIのDependsを使用
- **エラーハンドリング**: 統一された例外処理

## 開発ワークフロー

### 新機能の追加

1. モデルを定義（`app/models/`）
2. マイグレーションを作成（`alembic revision --autogenerate`）
3. リポジトリを作成（`app/repositories/`）
4. サービスを作成（`app/services/`）
5. APIエンドポイントを作成（`app/api/v1/`）
6. テストを作成（`tests/`）

### マイグレーション

```bash
# マイグレーションを作成
alembic revision --autogenerate -m "説明"

# マイグレーションを適用
alembic upgrade head

# マイグレーションをロールバック
alembic downgrade -1
```

### テスト

```bash
# ユニットテスト
pytest tests/unit/ -v

# 統合テスト
pytest tests/integration/ -v

# カバレッジレポート
pytest --cov=app tests/
```

## 環境変数

### 必須設定

> Phase 1（友だち追加だけでボットを動かす）と Phase 2（Stripe + SQL 管理）で必要な変数が異なります。

**Phase 1 必須**（Stripe/DB なしで動作）:

- `JWT_SECRET_KEYS`: JWTシークレットキー
- `LINE_CHANNEL_SECRET`: LINE Messaging API チャネルシークレット
- `LINE_CHANNEL_ACCESS_TOKEN`: LINE Messaging API チャネルアクセストークン
- `LINE_LOGIN_CHANNEL_ID`: LINE Login チャネルID
- `LINE_LOGIN_CHANNEL_SECRET`: LINE Login チャネルシークレット

**Phase 2 必須**（Stripe + SQL 管理の有効化時・後で設定）:

- `DATABASE_URL`: データベース接続URL
- `STRIPE_SECRET_KEY`: Stripeシークレットキー
- `STRIPE_WEBHOOK_SECRET`: Stripe Webhook 署名シークレット

### オプション設定

- `DEBUG`: デバッグモード（本番ではFalse）
- `CORS_ALLOWED_ORIGINS`: CORS許可オリジン

詳細は [`.env.example`](.env.example) を参照してください。

## デプロイ

### Cloud Run へのデプロイ

main ブランチにプッシュすると、GitHub Actions が自動的にデプロイを実行します。

### 手動デプロイ

```bash
# Docker イメージをビルド
docker build -t chabot:latest .

# Cloud Run にデプロイ
gcloud run deploy chabot-service \
  --image=chabot:latest \
  --region=asia-northeast1 \
  --platform=managed
```

## トラブルシューティング

### データベース接続エラー

- PostgreSQLが起動しているか確認: `docker ps`
- 接続URLが正しいか確認: `.env`の`DATABASE_URL`

### マイグレーションエラー

- Alembicの状態を確認: `alembic current`
- マイグレーション履歴を確認: `alembic history`

## 参考資料

- [FastAPIドキュメント](https://fastapi.tiangolo.com/)
- [SQLAlchemyドキュメント](https://docs.sqlalchemy.org/)
- [Alembicドキュメント](https://alembic.sqlalchemy.org/)
