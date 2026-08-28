"""
認証APIエンドポイント
ログイン、ログアウト、トークンリフレッシュ、全トークン即時失効のエンドポイントを定義します。
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

from app.core.config import settings
from app.core.auth_cookies import (
    REFRESH_TOKEN_COOKIE_NAME,
    clear_refresh_token_cookie,
    set_refresh_token_cookie,
)
from app.core.security import decode_token
from app.core.deps import get_current_user
from app.db.session import get_db, get_optional_db
from app.schemas.auth import (
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RevokeAllTokensRequest,
    RevokeAllTokensResponse,
    UserResponse,
)
from app.services.auth_service import AuthService
from app.services.firestore_auth_service import FirestoreAuthService

router = APIRouter(prefix="/auth", tags=["認証"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "認証失敗",
        },
    },
)
async def login(
    request: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """
    ユーザーログインを行います

    メールアドレスとパスワードで認証を行い、アクセストークンとリフレッシュトークンを返します。
    """
    auth_service = AuthService(db)

    # ログイン処理
    result = await auth_service.login(request.email, request.password)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, tokens = result

    return LoginResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "トークン無効",
        },
    },
)
async def refresh_token(
    http_request: Request,
    response: Response,
    db: Annotated[AsyncSession | None, Depends(get_optional_db)],
    request: RefreshTokenRequest | None = Body(default=None),
) -> RefreshTokenResponse:
    """
    リフレッシュトークンで新しいアクセストークンを取得します

    リフレッシュトークンは使用後に失効し、新しいリフレッシュトークンが発行されます。
    """
    cookie_token = http_request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    refresh_token_value = cookie_token or (request.refresh_token if request else None)
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(refresh_token_value)
    if payload and payload.get("provider") == "line":
        tokens = await FirestoreAuthService().refresh(refresh_token_value)
    elif db is not None:
        result = await AuthService(db).refresh_token(refresh_token_value)
        tokens = result[0] if result else None
    else:
        tokens = None

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    set_refresh_token_cookie(response, tokens["refresh_token"])
    return RefreshTokenResponse(
        access_token=tokens["access_token"],
        refresh_token=None if cookie_token else tokens["refresh_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "無効なリクエスト",
        },
    },
)
async def logout(
    http_request: Request,
    response: Response,
    db: Annotated[AsyncSession | None, Depends(get_optional_db)],
    request: LogoutRequest | None = Body(default=None),
) -> LogoutResponse:
    """
    ユーザーログアウトを行います

    リフレッシュトークンを失効させます。
    """
    refresh_token_value = http_request.cookies.get(REFRESH_TOKEN_COOKIE_NAME) or (
        request.refresh_token if request else None
    )
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh token is required",
        )

    payload = decode_token(refresh_token_value)
    if payload and payload.get("provider") == "line":
        success = await FirestoreAuthService().logout(refresh_token_value)
    elif db is not None:
        success = await AuthService(db).logout(refresh_token_value)
    else:
        success = False

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid refresh token",
        )

    clear_refresh_token_cookie(response)
    return LogoutResponse(message="Logged out successfully")


@router.post(
    "/revoke-all",
    response_model=RevokeAllTokensResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "認証されていない",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "権限がない",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "ユーザーが存在しない",
        },
    },
)
async def revoke_all_tokens(
    request: RevokeAllTokensRequest,
    db: Annotated[AsyncSession | None, Depends(get_optional_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RevokeAllTokensResponse:
    """
    ユーザーの全トークンを即時失効させます

    パスワード変更時やアカウント停止時に使用します。
    本人または管理者のみ実行可能です。
    """
    import logging
    logger = logging.getLogger(__name__)
    if settings.database_backend == "firestore":
        firestore_auth = FirestoreAuthService()
        target_user = await firestore_auth.user_repository.find_by_id(request.user_id)
    else:
        if db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session is unavailable",
            )
        from app.repositories.user import UserRepository

        target_user = await UserRepository(db).get(request.user_id)

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 認可チェック: 本人または管理者のみ許可
    is_admin = current_user.role == "admin"
    is_self = current_user.id == request.user_id

    if not (is_self or is_admin):
        logger.warning(
            "Unauthorized token revocation attempt: user_id=%s attempted to revoke tokens for user_id=%s",
            current_user.id,
            request.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only revoke your own tokens",
        )

    # 全トークン失効処理
    if settings.database_backend == "firestore":
        revoked_count = await firestore_auth.token_repository.revoke_all_user_tokens(
            request.user_id
        )
    else:
        revoked_count = await AuthService(db).revoke_all_user_tokens(request.user_id)

    # 監査ログ記録
    logger.info(
        "All tokens revoked for user_id=%s by user_id=%s (is_admin=%s, revoked_count=%s)",
        request.user_id,
        current_user.id,
        is_admin,
        revoked_count,
    )

    return RevokeAllTokensResponse(
        revoked_count=revoked_count,
        message=f"Revoked {revoked_count} tokens for user",
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "認証失敗",
        },
    },
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """
    現在のユーザー情報を取得します

    アクセストークンを使用して現在のユーザー情報を取得します。
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
