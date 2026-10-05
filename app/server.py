"""
FastAPIアプリケーション
メインのアプリケーション定義とルーター設定
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth_router, chat_router, stripe_webhook_router, subscription_router
from app.api.v1.auth_line import router as line_auth_router
from app.api.v1.invite import router as invite_router
from app.api.v1.webhooks.line import router as line_webhook_router
from app.core.config import settings
from app.core.firestore import close_firestore_client, get_firestore_client
from app.core.http_security import SecurityHeadersMiddleware
from app.services.line_service import LineService
from app.services.rag_service import RAGService


# ロギング設定
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    アプリケーションの寿命管理

    起動時にRAG/LINEサービスを初期化し、
    シャットダウン時にリソースを解放します。

    現在は Firestore を使用するため、PostgreSQL 接続は起動時に初期化しません。
    PostgreSQL を再開する場合は、バックエンド設定に応じた初期化を追加します。
    """
    # 起動時の処理
    logger.info(f"Starting {settings.app_name} ({settings.app_env})")

    if settings.database_backend == "firestore":
        await get_firestore_client()

    # RAGサービスを初期化（アプリケーション全体で再利用）
    logger.info("Initializing RAG service...")
    app.state.rag_service = RAGService()
    logger.info("RAG service initialized")

    # LINEサービスを初期化（アプリケーション全体で再利用）
    logger.info("Initializing LINE service...")
    app.state.line_service = LineService()
    logger.info("LINE service initialized")

    yield

    # シャットダウン時の処理
    logger.info(f"Shutting down {settings.app_name}")
    # LINE クライアントのHTTP接続を閉じる
    if hasattr(app.state, "line_service") and app.state.line_service:
        await app.state.line_service.client.close()
    if settings.database_backend == "firestore":
        await close_firestore_client()


def create_app() -> FastAPI:
    """FastAPIアプリケーションを生成する。

    本番（APP_ENV=production）ではOpenAPIスキーマとdocs UIを無効化し、
    エンドポイント構成の外部露出を防ぐ。管理アプリ（admin_server）と同じ方針。
    """
    docs_disabled = settings.app_env == "production"
    fastapi_app = FastAPI(
        title=settings.app_name,
        description="Chabot LINE API",
        version=settings.api_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if docs_disabled else "/docs",
        redoc_url=None if docs_disabled else "/redoc",
        openapi_url=None if docs_disabled else "/openapi.json",
    )

    # CORSミドルウェア設定（環境変数から許可オリジンを取得）
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # HTTPセキュリティヘッダーミドルウェア
    fastapi_app.add_middleware(SecurityHeadersMiddleware)

    # ルーター登録
    fastapi_app.include_router(auth_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(line_auth_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(chat_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(subscription_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(invite_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(line_webhook_router, prefix=f"/api/{settings.api_version}")
    fastapi_app.include_router(stripe_webhook_router, prefix=f"/api/{settings.api_version}")

    @fastapi_app.get("/")
    async def root():
        """ルートエンドポイント"""
        return {
            "app": settings.app_name,
            "version": settings.api_version,
            "status": "running",
        }

    @fastapi_app.get("/health")
    async def health_check():
        """ヘルスチェックエンドポイント"""
        return {"status": "healthy"}

    return fastapi_app


# FastAPIアプリケーション作成
app = create_app()
