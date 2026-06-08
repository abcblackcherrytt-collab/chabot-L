"""
認証サービス
JWTトークンの生成・検証・失効管理を行うサービスを定義します。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession


class TokenResponse(TypedDict):
    """トークンレスポンス"""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class JWTPayload(TypedDict):
    """JWTペイロード"""
    sub: str
    email: str
    type: str
    jti: str
    exp: int
    role: str | None

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_token_hash,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository


class AuthService:
    """
    認証サービス

    JWTトークンの生成・検証・失効管理を行います。
    ログイン、ログアウト、トークンリフレッシュ、全トークンの即時失効を提供します。
    """

    def __init__(self, db: AsyncSession):
        """
        認証サービスを初期化します

        Args:
            db: 非同期データベースセッション
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.token_repo = RefreshTokenRepository(db)

    async def login(
        self,
        email: str,
        password: str,
    ) -> tuple[User, TokenResponse] | None:
        """
        ユーザーログインを行います

        複数端末ログインの上限（3端末）を適用します。
        上限を超える場合、最も古いトークンから失効させます。

        Args:
            email: ユーザーメールアドレス
            password: 平文パスワード

        Returns:
            (ユーザー, トークン情報) のタプル、または認証失敗時はNone
            トークン情報には access_token と refresh_token が含まれます
        """
        # ユーザー認証
        user = await self.user_repo.authenticate(email, password)
        if not user:
            return None

        # 複数端末ログインの上限管理（3端末）
        MAX_ACTIVE_SESSIONS = 3
        current_token_count = await self.token_repo.count_valid_tokens_by_user(user.id)

        if current_token_count >= MAX_ACTIVE_SESSIONS:
            # 最も古いトークンを失効させて新しいトークンのための空きを作る
            revoke_count = await self.token_repo.revoke_oldest_tokens(
                user.id,
                keep_count=MAX_ACTIVE_SESSIONS - 1,
            )

        # JTI（JWT ID）を生成
        access_jti = f"access_{uuid.uuid4().hex}"
        refresh_jti = f"refresh_{uuid.uuid4().hex}"

        # アクセストークンを作成
        access_token, access_expires_at = create_access_token(
            user_id=user.id,
            email=user.email,
            jti=access_jti,
            additional_claims={"role": user.role},
        )

        # リフレッシュトークンを作成
        refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user.id,
            email=user.email,
            jti=refresh_jti,
        )

        # リフレッシュトークンをデータベースに保存
        refresh_token_hash = hash_token(refresh_token)
        await self.token_repo.create(
            {
                "id": refresh_jti,
                "user_id": user.id,
                "token_hash": refresh_token_hash,
                "expires_at": refresh_expires_at,
                "is_revoked": False,
                "revoked_at": None,
            }
        )

        return (
            user,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
            },
        )

    async def logout(
        self,
        refresh_token: str,
    ) -> bool:
        """
        ユーザーログアウトを行います

        Args:
            refresh_token: リフレッシュトークン

        Returns:
            ログアウトに成功すればTrue、失敗時はFalse
        """
        # トークンをデコード
        payload = decode_token(refresh_token)
        if not payload:
            return False

        # トークンタイプを確認
        token_type = payload.get("type")
        if token_type != "refresh":
            return False

        # JTIを取得
        jti = payload.get("jti")
        if not jti:
            return False

        # トークンを失効
        return await self.token_repo.revoke_token(jti)

    async def refresh_token(
        self,
        refresh_token: str,
    ) -> tuple[TokenResponse, RefreshToken] | None:
        """
        リフレッシュトークンで新しいアクセストークンを取得します

        Args:
            refresh_token: リフレッシュトークン

        Returns:
            (新しいトークン情報, リフレッシュトークンエンティティ) のタプル、または失敗時はNone
        """
        # トークンをデコード
        payload = decode_token(refresh_token)
        if not payload:
            return None

        # トークンタイプを確認
        token_type = payload.get("type")
        if token_type != "refresh":
            return None

        # JTIとユーザー情報を取得
        jti = payload.get("jti")
        user_id = payload.get("sub")
        email = payload.get("email")

        if not jti or not user_id or not email:
            return None

        # リフレッシュトークンが存在し、有効かを確認
        existing_token = await self.token_repo.get_by_id(jti)
        if not existing_token:
            return None

        if not existing_token.is_valid():
            return None

        # トークンハッシュを確認（タイミング攻撃対策済みの検証方式を使用）
        if not verify_token_hash(refresh_token, existing_token.token_hash):
            return None

        # ユーザーを取得
        user = await self.user_repo.get(user_id)
        if not user or not user.is_active:
            return None

        # 新しいJTIを生成
        new_access_jti = f"access_{uuid.uuid4().hex}"
        new_refresh_jti = f"refresh_{uuid.uuid4().hex}"

        # 新しいアクセストークンを作成
        new_access_token, new_access_expires_at = create_access_token(
            user_id=user.id,
            email=user.email,
            jti=new_access_jti,
            additional_claims={"role": user.role},
        )

        # 新しいリフレッシュトークンを作成
        new_refresh_token, new_refresh_expires_at = create_refresh_token(
            user_id=user.id,
            email=user.email,
            jti=new_refresh_jti,
        )

        # 新しいリフレッシュトークンをデータベースに保存
        new_refresh_token_hash = hash_token(new_refresh_token)
        new_token_entity = await self.token_repo.create(
            {
                "id": new_refresh_jti,
                "user_id": user.id,
                "token_hash": new_refresh_token_hash,
                "expires_at": new_refresh_expires_at,
                "is_revoked": False,
                "revoked_at": None,
            }
        )

        # 旧トークンを失効（ローテーション）
        await self.token_repo.revoke_token(jti)

        return (
            {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "Bearer",
                "expires_in": settings.jwt_access_token_expire_minutes * 60,
            },
            new_token_entity,
        )

    async def verify_access_token(
        self,
        access_token: str,
    ) -> JWTPayload | None:
        """
        アクセストークンを検証します

        Args:
            access_token: アクセストークン

        Returns:
            デコードされたトークンペイロード、または検証失敗時はNone
        """
        # トークンをデコード
        payload = decode_token(access_token)
        if not payload:
            return None

        # トークンタイプを確認
        token_type = payload.get("type")
        if token_type != "access":
            return None

        # JTIを取得
        jti = payload.get("jti")
        if not jti:
            return None

        # アクセストークンはステートレスで短命のため、
        # 失効管理はリフレッシュトークンのみで行う
        return cast("JWTPayload", payload)

    async def revoke_all_user_tokens(
        self,
        user_id: str,
    ) -> int:
        """
        ユーザーの全トークンを即時失効させます

        パスワード変更時やアカウント停止時に使用します。

        Args:
            user_id: ユーザーID

        Returns:
            失効したトークンの件数
        """
        return await self.token_repo.revoke_all_user_tokens(user_id)

    async def cleanup_expired_tokens(
        self,
        days_old: int = 30,
    ) -> int:
        """
        古い失効トークンをクリーンアップします

        定期的なクリーンアップジョブで使用します。

        Args:
            days_old: 何日前より古いトークンを削除するか

        Returns:
            削除したトークンの件数
        """
        return await self.token_repo.cleanup_revoked_tokens(days_old)
