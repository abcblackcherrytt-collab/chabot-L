"""
認証依存関係モジュール
FastAPIのDependsで使用する認証・認可の共通関数を定義します。
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.pricing import resolve_effective_plan
from app.db.session import get_optional_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.repositories.firestore_user_repository import FirestoreUserRepository
from app.repositories.base_user_repository import BaseUserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer認証
security = HTTPBearer()


def get_user_repository(
    db: Annotated[Optional[AsyncSession], Depends(get_optional_db)]
) -> BaseUserRepository:
    """
    データベースバックエンドに応じたユーザーリポジトリを返します

    Args:
        db: データベースセッション（PostgreSQL時のみ使用）

    Returns:
        BaseUserRepository実装（FirestoreUserRepositoryまたはUserRepository）
    """
    if settings.database_backend == "firestore":
        return FirestoreUserRepository()
    elif settings.database_backend == "postgresql":
        if db is None:
            raise RuntimeError("PostgreSQL session is not available")
        return UserRepository(db)
    else:
        raise ValueError(f"Unsupported database backend: {settings.database_backend}")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    user_repo: Annotated[BaseUserRepository, Depends(get_user_repository)],
) -> User:
    """
    JWTから現在のユーザーを取得します

    AuthorizationヘッダーからJWTを取得し、署名・期限・失効状態を検証します。

    Phase 1（現在）: JWT 有効性 ＋ user.is_active のみ検証。
      サブスクリプション検証は行わない（後で有効化）。
    Phase 2: require_active_subscription を追加しサブスク必須化（下記マーカー参照）。

    Args:
        credentials: HTTP Bearer認証情報
        user_repo: ユーザーリポジトリ（FirestoreまたはPostgreSQL）

    Returns:
        認証されたユーザー

    Raises:
        HTTPException: 認証失敗時
    """
    # JWT検証はDBセッション不要（decode_tokenはロジックのみ）
    from app.core.security import decode_token

    # アクセストークンを検証
    payload = decode_token(credentials.credentials)

    if not payload:
        logger.warning("Invalid access token attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # トークンタイプを確認
    token_type = payload.get("type")
    if token_type != "access":
        logger.warning(f"Invalid token type: {token_type}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        logger.warning("Access token payload missing 'sub' claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_id = payload.get("sid")
    auth_version = payload.get("auth_version")

    # リポジトリ経由でユーザー取得
    if settings.database_backend == "firestore":
        # セッション基盤検証（Firestore構成）。セッション失効・認証世代は
        # Access Tokenにも即時に適用する。旧形式（sid無し）のAccess Tokenは
        # 移行期間の対象外として拒否し、Cookieからの自動更新で復帰できる。
        if not session_id or auth_version is None:
            logger.warning("Access token without session claims rejected")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        from app.repositories.firestore_auth_session_repository import (
            FirestoreAuthSessionRepository,
        )

        try:
            session = await FirestoreAuthSessionRepository().get(session_id)
        except Exception as exc:
            # Firestore障害では認可を通さない（fail closed）。
            logger.error(
                "Auth session lookup failed: error_type=%s",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable",
            )

        if (
            not session
            or session.get("user_id") != user_id
            or session.get("revoked_at")
        ):
            logger.warning("Auth session is missing or revoked")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        session_expires_at = session.get("expires_at")
        if isinstance(session_expires_at, str):
            from datetime import datetime as _datetime

            try:
                session_expires_at = _datetime.fromisoformat(session_expires_at)
            except ValueError:
                session_expires_at = None
        if session_expires_at is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if session_expires_at.tzinfo is None:
            from datetime import timezone as _timezone

            session_expires_at = session_expires_at.replace(tzinfo=_timezone.utc)
        if session_expires_at <= datetime.now(timezone.utc):
            logger.warning("Auth session expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if int(session.get("auth_version") or 0) != int(auth_version):
            logger.warning("Auth session version mismatch")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Firestoreの場合は辞書形式で取得
        user_dict = await user_repo.find_by_id(user_id)
        if not user_dict:
            logger.warning("Authenticated user was not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user_dict.get('is_active', False):
            logger.warning("Inactive user attempted access")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 全失効（revoke-all / unfollow / 管理者無効化）で更新された
        # 認証世代と一致しないトークンは無効扱いにする。
        if int(user_dict.get("auth_version") or 0) != int(auth_version):
            logger.warning("User auth version mismatch for access token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 辞書からUserオブジェクトクト作成（簡易実装）
        created_at = user_dict.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        updated_at = user_dict.get('updated_at')
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        user = User(
            id=user_dict['id'],
            line_user_id=user_dict.get('line_user_id'),
            email=user_dict.get('email'),
            display_name=user_dict.get('display_name'),
            role=user_dict.get('role', 'user'),
            is_active=user_dict.get('is_active', True),
            created_at=created_at,
            updated_at=updated_at,
        )
        # 管理者override・service等を含む実効プランへ統一し、公開APIと
        # LINE経路で同じプラン解決を使う。
        user.subscription_plan = resolve_effective_plan(user_dict)
        return user

    else:
        # PostgreSQLの場合は既存のロジック
        user = await user_repo.get(user_id)

        if not user:
            logger.warning("Authenticated user was not found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            logger.warning("Inactive user attempted access")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user


# ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
# Phase 2 で以下の依存関数をこの位置に定義し、サブスク必須のゲートとする:
#
#   async def require_active_subscription(
#       current_user: Annotated[User, Depends(get_current_user)],
#   ) -> User:
#       """有効なサブスク必須。未契約/期限切れは 403 を返す。"""
#       if not any(s.is_active_paid() for s in current_user.subscriptions):
#           raise HTTPException(
#               status_code=status.HTTP_403_FORBIDDEN,
#               detail="Active subscription required",
#           )
#       return current_user
#
# 使用先: app/api/v1/chat.py send_message の Depends を差し替え [Phase 2 マーカー E1]
# 関連: app/models/subscription.py is_active_paid() [Phase 2 マーカー H2]
# ===================================================================


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
        logger.warning("Non-admin user attempted admin access")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user
