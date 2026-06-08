"""
認証依存関係モジュール
FastAPIのDependsで使用する認証・認可の共通関数を定義します。
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer認証
security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    JWTから現在のユーザーを取得します

    AuthorizationヘッダーからJWTを取得し、署名・期限・失効状態を検証します。

    Args:
        credentials: HTTP Bearer認証情報
        db: データベースセッション

    Returns:
        認証されたユーザー

    Raises:
        HTTPException: 認証失敗時
    """
    auth_service = AuthService(db)
    payload = await auth_service.verify_access_token(credentials.credentials)

    if not payload:
        logger.warning(f"Invalid access token attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    user = await user_repo.get(payload["sub"])

    if not user:
        logger.warning(f"User not found: {payload['sub']}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning(f"Inactive user attempt: {user.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    管理者のみアクセス可能

    Args:
        current_user: 現在のユーザー

    Returns:
        認証された管理者ユーザー

    Raises:
        HTTPException: 管理者でない場合
    """
    if current_user.role != "admin":
        logger.warning(f"Non-admin user attempted admin access: {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user
