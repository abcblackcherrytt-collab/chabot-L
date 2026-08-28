"""認証セッションCookieの設定を一元管理する。"""

from fastapi import Response

from app.core.config import settings


REFRESH_TOKEN_COOKIE_NAME = "chabot_refresh_token"


def _cookie_path() -> str:
    """認証エンドポイントだけへ送信するCookieパスを返す。"""
    return f"/api/{settings.api_version}/auth"


def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    """Refresh TokenをJavaScriptから読めない永続Cookieへ保存する。"""
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
        path=_cookie_path(),
        secure=not settings.debug,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_refresh_token_cookie(response: Response) -> None:
    """ブラウザに保存されたRefresh Token Cookieを削除する。"""
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path=_cookie_path(),
        secure=not settings.debug,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
