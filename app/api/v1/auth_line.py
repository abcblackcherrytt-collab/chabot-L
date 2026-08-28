"""
LINE Login エンドポイント
LINE Login v2.1（OIDC準拠）によるユーザー認証を提供します。
"""

import logging
import base64
import hashlib
import secrets
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.auth_cookies import set_refresh_token_cookie
from app.core.config import settings
from app.core.security import verify_line_id_token
from app.services.firestore_auth_service import FirestoreAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/line", tags=["LINE Auth"])

LINE_AUTH_URL = "https://access.line.me/oauth2/v2.1/authorize"
LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"


@router.get("")
async def line_login(request: Request) -> RedirectResponse:
    """
    LINE Login 認証ページにリダイレクトします

    CSRF 対策の state パラメータと
    リプレイ攻撃対策の nonce パラメータを生成します。

    Returns:
        LINE 認証ページへのリダイレクト
    """
    # state パラメータ生成（CSRF対策）
    state = secrets.token_urlsafe(32)
    # nonce パラメータ生成（リプレイ攻撃対策）
    nonce = secrets.token_urlsafe(32)

    # PKCE code_verifier / code_challenge 生成
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    params = {
        "response_type": "code",
        "client_id": settings.line_login_channel_id,
        "redirect_uri": settings.line_login_callback_url,
        "state": state,
        "scope": "profile openid email",
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{LINE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    logger.info("Redirecting to LINE Login")

    response = RedirectResponse(url=auth_url, status_code=303)

    # state と code_verifier をCookieに保存（HttpOnly + Secure）
    response.set_cookie(
        key="line_login_state",
        value=state,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=600,  # 10分
    )
    response.set_cookie(
        key="line_code_verifier",
        value=code_verifier,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=600,
    )
    response.set_cookie(
        key="line_login_nonce",
        value=nonce,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=600,
    )

    return response


@router.get("/callback")
async def line_login_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """
    LINE Login コールバックを処理します

    認可コードをアクセストークンに交換し、
    ID トークンからユーザー情報を取得して JWT を発行します。

    Args:
        code: 認可コード
        state: CSRF対策のstateパラメータ
        error: エラーコード
        error_description: エラー説明

    Returns:
        認証結果（JWT アクセストークン・リフレッシュトークン）
    """
    # エラーレスポンスの処理
    if error:
        logger.warning(f"LINE Login error: {error} - {error_description}")
        raise HTTPException(
            status_code=400,
            detail=f"LINE Login failed: {error_description or error}",
        )

    # 必須パラメータの確認
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code or state parameter",
        )

    # state 検証（CSRF対策）
    cookie_state = request.cookies.get("line_login_state")
    if not cookie_state or cookie_state != state:
        logger.warning("State mismatch in LINE Login callback")
        raise HTTPException(
            status_code=401,
            detail="Invalid state parameter (possible CSRF attack)",
        )

    # 認可コードをトークンに交換
    import httpx

    code_verifier = request.cookies.get("line_code_verifier", "")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.line_login_callback_url,
        "client_id": settings.line_login_channel_id,
        "client_secret": settings.line_login_channel_secret,
    }

    if code_verifier:
        token_data["code_verifier"] = code_verifier

    async with httpx.AsyncClient() as http_client:
        token_response = await http_client.post(
            LINE_TOKEN_URL,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if token_response.status_code != 200:
        logger.error(
            f"LINE token exchange failed: {token_response.status_code}"
        )
        raise HTTPException(
            status_code=401,
            detail="Failed to exchange authorization code for token",
        )

    token_json = token_response.json()
    id_token = token_json.get("id_token", "")

    # ID トークン検証
    expected_nonce = request.cookies.get("line_login_nonce", "")
    if not expected_nonce:
        raise HTTPException(
            status_code=401,
            detail="Expired or invalid nonce",
        )

    id_payload = await verify_line_id_token(
        id_token=id_token,
        channel_id=settings.line_login_channel_id,
        nonce=expected_nonce,
    )

    if not id_payload:
        raise HTTPException(
            status_code=401,
            detail="ID token verification failed",
        )

    # nonce 検証（リプレイ攻撃対策）
    received_nonce = id_payload.get("nonce", "")
    if received_nonce != expected_nonce:
        logger.warning("Nonce mismatch in ID token")
        raise HTTPException(
            status_code=401,
            detail="Nonce verification failed (possible replay attack)",
        )

    # ユーザー情報取得
    line_user_id = id_payload.get("sub", "")
    display_name = id_payload.get("name", "")
    email = id_payload.get("email", f"line_{line_user_id}@chabot.local")

    if not line_user_id:
        raise HTTPException(
            status_code=400,
            detail="Missing LINE user ID in ID token",
        )

    logger.info(f"LINE Login successful: user={display_name}")

    auth_service = FirestoreAuthService()
    user = await auth_service.user_repository.find_by_line_user_id(line_user_id)
    if user is None:
        user = await auth_service.user_repository.create_line_user(
            line_user_id=line_user_id,
            display_name=display_name,
            email=email,
        )
    elif not user.get("is_active", False):
        raise HTTPException(status_code=403, detail="User account is inactive")

    tokens = await auth_service.issue_tokens(user, line_user_id)

    response = JSONResponse(
        content={
            "access_token": tokens["access_token"],
            "token_type": tokens["token_type"],
            "expires_in": tokens["expires_in"],
            "user": {
                "id": user["id"],
                "line_user_id": line_user_id,
                "display_name": user.get("display_name", display_name),
                "email": user.get("email", email),
            },
        }
    )
    set_refresh_token_cookie(response, tokens["refresh_token"])
    response.delete_cookie("line_login_state", path="/")
    response.delete_cookie("line_code_verifier", path="/")
    response.delete_cookie("line_login_nonce", path="/")
    return response
