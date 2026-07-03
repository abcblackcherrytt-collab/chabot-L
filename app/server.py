"""
FastAPIアプリケーション
メインのアプリケーション定義とルーター設定
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import auth_router, chat_router, stripe_webhook_router
from app.api.v1.auth_line import router as line_auth_router
from app.api.v1.webhooks.line import router as line_webhook_router
from app.core.config import settings
from app.services.line_service import LineService
from app.services.rag_service import RAGService


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    HTTPセキュリティヘッダーミドルウェア

    セキュリティ関連のHTTPヘッダーを追加します。
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # HTTPセキュリティヘッダーを追加
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        return response


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

    Phase 1（現在）: Stripe/DB を起動時に初期化しない（LINE ボットは DB なしで動作）。
    Phase 2: StripeService と DB 接続（init_db）の初期化をここに追加する接続ポイント。
    """
    # 起動時の処理
    logger.info(f"Starting {settings.app_name} ({settings.app_env})")

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


# FastAPIアプリケーション作成
app = FastAPI(
    title=settings.app_name,
    description="Chabot LINE API",
    version=settings.api_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# CORSミドルウェア設定（環境変数から許可オリジンを取得）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# HTTPセキュリティヘッダーミドルウェア
app.add_middleware(SecurityHeadersMiddleware)

# ルーター登録
app.include_router(auth_router, prefix=f"/api/{settings.api_version}")
app.include_router(line_auth_router, prefix=f"/api/{settings.api_version}")
app.include_router(chat_router, prefix=f"/api/{settings.api_version}")
app.include_router(line_webhook_router, prefix=f"/api/{settings.api_version}")
app.include_router(stripe_webhook_router, prefix=f"/api/{settings.api_version}")


@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "app": settings.app_name,
        "version": settings.api_version,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """ヘルスチェックエンドポイント"""
    return {"status": "healthy"}
