# Chabot

FastAPI + Vertex AI RAG + LINE Bot + Stripe を組み合わせた AI チャットボットサービス。

## 機能

- **FastAPI**: 高速な非同期APIサーバー
- **Vertex AI RAG**: Google Cloud Vertex AI を使用したRAG（検索拡張生成）
- **LINE Bot**: LINE Messaging API との統合
- **Stripe**: 決済処理統合
- **JWT認証**: セキュアな認証システム
- **PostgreSQL**: データベース管理

## 技術スタック

- **Python**: 3.11+
- **FastAPI**: 0.104.0+
- **SQLAlchemy**: 2.0.0+（非同期対応）
- **Alembic**: データベースマイグレーション
- **PostgreSQL**: 16+
- **Google Cloud**: Vertex AI, Secret Manager, Cloud Run

## ローカル開発環境セットアップ

### 前提条件

- Python 3.11+
- PostgreSQL 16+
- Docker
- Docker Compose
- Google Cloud SDK

### インストール手順

1. リポジトリをクローン

```bash
git clone <repository-url>
cd chabot
```

2. 仮想環境を作成

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. 依存関係をインストール

```bash
pip install -r requirements.txt
```

4. 環境変数を設定

```bash
cp .env.example .env
# .envファイルを編集して必要な値を設定
```

5. PostgreSQLを起動

```bash
docker run -d \
  --name chabot-postgres \
  -e POSTGRES_USER=root \
  -e POSTGRES_PASSWORD=your-password \
  -e POSTGRES_DB=chabot \
  -p 5432:5432 \
  postgres:16-alpine
```

6. データベースマイグレーションを実行

```bash
alembic upgrade head
```

7. サーバーを起動

```bash
uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

8. APIドキュメントにアクセス

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 環境変数

| 変数名 | 説明 | デフォルト値 |
|--------|------|--------------|
| `APP_NAME` | アプリケーション名 | `chabot` |
| `APP_ENV` | 環境（development/production） | `development` |
| `DEBUG` | デバッグモード | `True` |
| `DATABASE_URL` | データベース接続URL | `postgresql+asyncpg://user:password@localhost:5432/chabot` |
| `JWT_SECRET_KEYS` | JWTシークレットキー（カンマ区切り） | - |
| `LINE_CHANNEL_SECRET` | LINE Messaging API チャネルシークレット | - |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API チャネルアクセストークン | - |
| `LINE_LOGIN_CHANNEL_ID` | LINE Login チャネルID | - |
| `LINE_LOGIN_CHANNEL_SECRET` | LINE Login チャネルシークレット | - |
| `STRIPE_SECRET_KEY` | Stripeシークレットキー | - |
| `GOOGLE_PROJECT_ID` | Google CloudプロジェクトID | - |
| `GOOGLE_CORPUS_ID` | Vertex AIコーパスID | - |

詳細は [`.env.example`](.env.example) を参照してください。

## デプロイ

### Cloud Run へのデプロイ

1. Google Secret Manager にシークレットを登録

```bash
gcloud secrets create line-channel-secret --data-file="line-channel-secret.txt"
gcloud secrets create line-channel-access-token --data-file="line-channel-access-token.txt"
gcloud secrets create stripe-secret-key --data-file="stripe-secret-key.txt"
# ... 他のシークレットも同様に登録
```

2. GitHub Secrets を設定

- `GCP_PROJECT_ID`
- `GCP_SERVICE_ACCOUNT`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT`

3. main ブランチにプッシュ

GitHub Actions が自動的にデプロイを実行します。

### 手動デプロイ

```bash
# Docker イメージをビルド
docker build -t chabot:latest .

# Artifact Registry にプッシュ
gcloud auth configure-docker asia-northeast1-docker.pkg.dev
docker tag chabot:latest asia-northeast1-docker.pkg.dev/PROJECT_ID/chabot-repo/chabot:latest
docker push asia-northeast1-docker.pkg.dev/PROJECT_ID/chabot-repo/chabot:latest

# Cloud Run にデプロイ
gcloud run deploy chabot-service \
  --image=asia-northeast1-docker.pkg.dev/PROJECT_ID/chabot-repo/chabot:latest \
  --region=asia-northeast1 \
  --platform=managed \
  --allow-unauthenticated
```

## テスト

```bash
# ユニットテスト
pytest tests/unit/ -v

# 統合テスト
pytest tests/integration/ -v

# カバレッジレポート
pytest --cov=app tests/
```

## プロジェクト構造

```
chabot/
├── app/
│   ├── api/              # APIルート
│   ├── clients/          # 外部APIクライアント
│   ├── core/             # 設定・セキュリティ
│   ├── db/               # データベース関連
│   ├── models/           # データベースモデル
│   ├── repositories/     # データアクセス
│   ├── schemas/          # Pydanticスキーマ
│   ├── services/         # ビジネスロジック
│   └── server.py         # FastAPIアプリケーション
├── alembic/              # データベースマイグレーション
├── tests/                # テストコード
├── .github/              # GitHub Actions
├── Dockerfile
├── requirements.txt
└── README.md
```

## ライセンス

MIT License

## 貢献

プルリクエストをお待ちしています。
