"""
LINE Login エンドポイント
LINE Login v2.1（OIDC準拠）によるユーザー認証を提供します。
"""

import logging
import secrets
import urllib.parse
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, verify_line_id_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/line", tags=["LINE Auth"])

# 一時 state 保存（本番では Redis 等のセッションストアを使用）
# TODO: Redis / Cloud Memorystore に移行
_state_store: Dict[str, str] = {}
_nonce_store: Dict[str, str] = {}

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
    _state_store[state] = "pending"

    # nonce パラメータ生成（リプレイ攻撃対策）
    nonce = secrets.token_urlsafe(32)
    _nonce_store[state] = nonce

    # PKCE code_verifier / code_challenge 生成
    code_verifier = secrets.token_urlsafe(64)

    params = {
        "response_type": "code",
        "client_id": settings.line_login_channel_id,
        "redirect_uri": settings.line_login_callback_url,
        "state": state,
        "scope": "profile openid email",
        "nonce": nonce,
        "code_verifier": code_verifier,
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

    if state not in _state_store:
        raise HTTPException(
            status_code=401,
            detail="Expired or invalid state parameter",
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
    id_payload = verify_line_id_token(
        id_token=id_token,
        channel_id=settings.line_login_channel_id,
    )

    if not id_payload:
        raise HTTPException(
            status_code=401,
            detail="ID token verification failed",
        )

    # nonce 検証（リプレイ攻撃対策）
    expected_nonce = _nonce_store.pop(state, None)
    received_nonce = id_payload.get("nonce", "")
    if expected_nonce and received_nonce != expected_nonce:
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

    # TODO: DB でユーザー検索・作成
    # user = await user_repository.find_by_line_user_id(line_user_id)
    # if not user:
    #     user = await user_repository.create(
    #         id=str(uuid.uuid4()),
    #         email=email,
    #         hashed_password=get_password_hash(secrets.token_urlsafe(32)),
    #         line_user_id=line_user_id,
    #     )

    # 仮のユーザー情報（DB実装後に置き換え）
    user_id = str(uuid.uuid4())

    # JWT 発行
    jti = str(uuid.uuid4())
    access_token, access_expires = create_access_token(
        user_id=user_id,
        email=email,
        jti=jti,
        additional_claims={"line_user_id": line_user_id},
    )

    refresh_jti = str(uuid.uuid4())
    refresh_token, refresh_expires = create_refresh_token(
        user_id=user_id,
        email=email,
        jti=refresh_jti,
    )

    # クリーンアップ
    _state_store.pop(state, None)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": int(
            (access_expires - __import__("datetime").datetime.now(__import__("datetime").timezone.utc)).total_seconds()
        ),
        "user": {
            "id": user_id,
            "line_user_id": line_user_id,
            "display_name": display_name,
            "email": email,
        },
    }
