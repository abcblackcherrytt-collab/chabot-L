"""
ユーザーリポジトリ
ユーザーの管理と認証操作を行うリポジトリクラスを定義します。
"""

import logging
from typing import Optional, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.base_user_repository import BaseUserRepository

logger = logging.getLogger(__name__)


class UserRepository(BaseRepository[User], BaseUserRepository):
    """
    ユーザーリポジトリ

    ユーザーの管理と認証操作を行います。
    BaseUserRepositoryを実装してFirestoreとの互換性を持ちます。
    """

    def __init__(self, db: AsyncSession):
        """
        ユーザーリポジトリを初期化します

        Args:
            db: 非同期データベースセッション
        """
        super().__init__(User, db)

    async def get_by_email(self, email: str) -> User | None:
        """
        メールアドレスによるユーザーの取得

        Args:
            email: ユーザーメールアドレス

        Returns:
            ユーザー、または存在しない場合はNone
        """
        statement = select(User).where(User.email == email)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        hashed_password: str,
        role: str = "user",
    ) -> User:
        """
        新規ユーザーの作成

        Args:
            email: ユーザーメールアドレス
            hashed_password: ハッシュ化されたパスワード
            role: ユーザーロール（デフォルト: "user"）

        Returns:
            作成されたユーザー
        """
        return await self.create(
            {
                "email": email,
                "hashed_password": hashed_password,
                "role": role,
            }
        )

    async def authenticate(
        self,
        email: str,
        plain_password: str,
    ) -> User | None:
        """
        ユーザー認証を行います

        Args:
            email: ユーザーメールアドレス
            plain_password: 平文パスワード

        Returns:
            認証に成功したユーザー、または失敗時はNone
        """
        from app.core.security import verify_password

        user = await self.get_by_email(email)
        if not user:
            return None

        if not user.is_active:
            return None

        if not verify_password(plain_password, user.hashed_password):
            return None

        return user

    async def is_email_exists(self, email: str) -> bool:
        """
        メールアドレスが既に存在するかを確認します

        Args:
            email: チェックするメールアドレス

        Returns:
            メールアドレスが存在すればTrue
        """
        return (await self.get_by_email(email)) is not None

    async def find_by_line_user_id(self, line_user_id: str) -> User | None:
        """
        LINE ユーザーID でユーザーを検索（Phase 2）

        Args:
            line_user_id: LINE ユーザーID

        Returns:
            ユーザー、存在しない場合は None
        """
        statement = select(User).where(User.line_user_id == line_user_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def create_line_user(
        self,
        line_user_id: str,
        display_name: str = "",
        email: str | None = None,
    ) -> User:
        """
        LINE ユーザーを新規作成（Email/Password 不要・Phase 2）

        Args:
            line_user_id: LINE ユーザーID
            display_name: 表示名
            email: メールアドレス（任意）

        Returns:
            作成されたユーザー
        """
        return await self.create(
            {
                "line_user_id": line_user_id,
                "display_name": display_name,
                "email": email,
                "role": "user",
            }
        )

    # ===== BaseUserRepository インターフェース実装 =====
    # Firestoreとの互換性を持つメソッド

    async def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        IDでユーザーを検索します（BaseUserRepository実装）

        Args:
            user_id: ユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        try:
            user = await self.get(user_id)
            if user:
                return {
                    'id': user.id,
                    'line_user_id': user.line_user_id,
                    'email': user.email,
                    'display_name': user.display_name,
                    'role': user.role,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'updated_at': user.updated_at.isoformat() if user.updated_at else None,
                }
            return None
        except Exception as e:
            logger.error(f"Error finding user by id: {e}")
            return None

    async def get_subscription_plan(self, user_id: str) -> str:
        """
        ユーザーのサブスクリプションプランを取得します（BaseUserRepository実装）

        Args:
            user_id: ユーザーID

        Returns:
            サブスクリプションプラン（'free', 'basic', 'pro'）
        """
        try:
            user = await self.get(user_id)
            if user and hasattr(user, 'subscriptions') and user.subscriptions:
                # 最新のサブスクリプションを取得
                subscription = sorted(
                    user.subscriptions,
                    key=lambda s: s.created_at if s.created_at else datetime.min,
                    reverse=True
                )[0]
                return subscription.plan if subscription else 'free'
            return 'free'
        except Exception as e:
            logger.error(f"Error getting subscription plan: {e}")
            return 'free'

    async def update_subscription_plan(self, user_id: str, plan: str) -> Dict[str, Any]:
        """
        サブスクリプションプランを更新します（BaseUserRepository実装）

        Args:
            user_id: ユーザーID
            plan: 新しいプラン（'free', 'basic', 'pro'）

        Returns:
            更新後のサブスクリプションデータ
        """
        try:
            from app.models.subscription import Subscription
            from sqlalchemy import select
            from datetime import datetime

            # ユーザーの最新サブスクリプションを取得
            result = await self.db.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            subscription = result.scalar_one_or_none()

            if subscription:
                # 既存のサブスクリプションを更新
                subscription.plan = plan
                subscription.status = 'active' if plan == 'free' else subscription.status
                subscription.updated_at = datetime.utcnow()
                await self.db.commit()
                await self.db.refresh(subscription)

                return {
                    'id': subscription.id,
                    'user_id': subscription.user_id,
                    'plan': subscription.plan,
                    'status': subscription.status
                }
            else:
                # 新規サブスクリプション作成
                new_subscription = Subscription(
                    user_id=user_id,
                    plan=plan,
                    status='active',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                self.db.add(new_subscription)
                await self.db.commit()
                await self.db.refresh(new_subscription)

                return {
                    'id': new_subscription.id,
                    'user_id': new_subscription.user_id,
                    'plan': new_subscription.plan,
                    'status': new_subscription.status
                }

        except Exception as e:
            logger.error(f"Error updating subscription plan: {e}")
            raise

    async def is_active(self, user_id: str) -> bool:
        """
        ユーザーがアクティブかどうかを確認します（BaseUserRepository実装）

        Args:
            user_id: ユーザーID

        Returns:
            アクティブならTrue、そうでなければFalse
        """
        try:
            user = await self.get(user_id)
            return user.is_active if user else False
        except Exception as e:
            logger.error(f"Error checking user active status: {e}")
            return False

    async def deactivate_user(self, user_id: str) -> None:
        """
        ユーザーを非アクティブ化します（退会処理、BaseUserRepository実装）

        Args:
            user_id: ユーザーID
        """
        try:
            from datetime import datetime

            user = await self.get(user_id)
            if user:
                user.is_active = False
                user.updated_at = datetime.utcnow()
                await self.db.commit()
                logger.info(f"Deactivated user: {user_id}")
        except Exception as e:
            logger.error(f"Error deactivating user: {e}")
            raise

    async def find_by_line_user_id_dict(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        """
        LINEユーザーIDでユーザーを検索し、辞書形式で返します（BaseUserRepository互換）

        Args:
            line_user_id: LINEユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        user = await self.find_by_line_user_id(line_user_id)
        if user:
            return {
                'id': user.id,
                'line_user_id': user.line_user_id,
                'email': user.email,
                'display_name': user.display_name,
                'role': user.role,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'updated_at': user.updated_at.isoformat() if user.updated_at else None,
            }
        return None


    # ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
    # Stripe 顧客管理関連メソッド実装

    async def find_by_stripe_customer_id(self, stripe_customer_id: str) -> User | None:
        """
        Stripe カスタマーID でユーザーを検索

        Args:
            stripe_customer_id: Stripe カスタマーID

        Returns:
            ユーザー、存在しない場合は None
        """
        statement = select(User).where(User.stripe_customer_id == stripe_customer_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def update_stripe_customer_id(self, user_id: str, stripe_customer_id: str) -> None:
        """
        ユーザーに Stripe カスタマーID を紐付け

        Args:
            user_id: ユーザーID
            stripe_customer_id: Stripe カスタマーID
        """
        try:
            from datetime import datetime

            user = await self.get(user_id)
            if user:
                user.stripe_customer_id = stripe_customer_id
                user.updated_at = datetime.utcnow()
                await self.db.commit()
                logger.info(f"Updated stripe_customer_id for user: {user_id}")
        except Exception as e:
            logger.error(f"Error updating stripe_customer_id: {e}")
            raise

    async def get_stripe_customer_id(self, user_id: str) -> str | None:
        """
        ユーザーの Stripe カスタマーID を取得

        Args:
            user_id: ユーザーID

        Returns:
            Stripe カスタマーID、存在しない場合は None
        """
        try:
            user = await self.get(user_id)
            return user.stripe_customer_id if user else None
        except Exception as e:
            logger.error(f"Error getting stripe_customer_id: {e}")
            return None

    #
    # 呼び出し元:
    #   - line_service._handle_follow_event [Phase 2 マーカー A4]
    #   - line_service._handle_message_event [Phase 2 マーカー A2]
    #   - line_service._handle_unfollow_event [Phase 2 マーカー A6]
    #   - auth_line callback [Phase 2 マーカー C1]
    #   - stripe_service 各 Webhook ハンドラ [Phase 2 マーカー G2-G6]
    # ===================================================================
