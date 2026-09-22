"""HTTPレスポンスの共通セキュリティヘッダー。"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """ブラウザ向けの基本的な防御ヘッダーを付与する。"""

    def __init__(
        self,
        app,
        *,
        referrer_policy: str = "strict-origin-when-cross-origin",
        no_store: bool = False,
    ) -> None:
        """サービスごとのReferrer/Cache方針を受け取る。"""
        super().__init__(app)
        self.referrer_policy = referrer_policy
        self.no_store = no_store

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """レスポンスへセキュリティヘッダーを追加する。"""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = self.referrer_policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        if self.no_store:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response
