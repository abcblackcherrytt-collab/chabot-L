"""
Firestoreユーザーリポジトリ
Firestoreをデータベースバックエンドとして使用するユーザーリポジトリ実装です。
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync
from app.repositories.base_user_repository import BaseUserRepository

logger = logging.getLogger(__name__)


class FirestoreUserRepository(BaseUserRepository):
    """
    Firestoreユーザーリポジトリ

    Firestoreをデータベースとして使用する実装です。
    """

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化します"""
        self.db = client or get_firestore_client_sync()
        logger.info("Firestore user repository initialized")

    async def find_by_line_user_id(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        """
        LINEユーザーIDでユーザーを検索します

        Args:
            line_user_id: LINEユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        try:
            docs = await self.db.collection('users')\
                .where('line_user_id', '==', line_user_id)\
                .limit(1)\
                .get()

            for doc in docs:
                user_data = doc.to_dict()
                user_data['id'] = doc.id
                logger.debug(f"User found by line_user_id: {line_user_id}")
                return user_data

            logger.debug(f"User not found: {line_user_id}")
            return None

        except Exception as e:
            logger.error(f"Error finding user by line_user_id: {e}")
            raise

    async def create_line_user(
        self,
        line_user_id: str,
        display_name: str = "",
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        LINEユーザーを新規作成します

        Args:
            line_user_id: LINEユーザーID
            display_name: 表示名
            email: メールアドレス（任意）

        Returns:
            作成されたユーザーデータの辞書
        """
        try:
            now = datetime.utcnow()
            user_id = str(uuid.uuid4())

            user_data = {
                'id': user_id,
                'line_user_id': line_user_id,
                'display_name': display_name or f"User_{line_user_id[:8]}",
                'email': email,
                'subscription_plan': 'free',
                'subscription_status': 'active',
                'is_active': True,
                'role': 'user',
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }

            # ユーザードキュメント作成
            await self.db.collection('users').document(user_id).set(user_data)

            logger.info(f"Created new user: {user_id} (line_user_id: {line_user_id})")
            return user_data

        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    async def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        IDでユーザーを検索します

        Args:
            user_id: ユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        try:
            doc = await self.db.collection('users').document(user_id).get()

            if doc.exists:
                user_data = doc.to_dict()
                user_data['id'] = doc.id
                logger.debug(f"User found by id: {user_id}")
                return user_data

            logger.debug(f"User not found: {user_id}")
            return None

        except Exception as e:
            logger.error(f"Error finding user by id: {e}")
            raise

    async def get_subscription_plan(self, user_id: str) -> str:
        """
        ユーザーのサブスクリプションプランを取得します

        Args:
            user_id: ユーザーID

        Returns:
            サブスクリプションプラン（'free', 'basic', 'pro'）
        """
        user_data = await self.find_by_id(user_id)
        if user_data:
            return user_data.get('subscription_plan', 'free')

        return 'free'

    async def update_subscription_plan(self, user_id: str, plan: str) -> Dict[str, Any]:
        """
        サブスクリプションプランを更新します

        Args:
            user_id: ユーザーID
            plan: 新しいプラン（'free', 'basic', 'pro'）

        Returns:
            更新後のユーザーデータ
        """
        try:
            doc_ref = self.db.collection('users').document(user_id)

            # 更新データ
            update_data = {
                'subscription_plan': plan,
                'updated_at': datetime.utcnow().isoformat()
            }

            # プラン変更に応じてステータスも更新
            if plan == 'free':
                update_data['subscription_status'] = 'active'

            await doc_ref.update(update_data)

            # 更新後のデータを取得
            doc = await doc_ref.get()
            if not doc.exists:
                raise LookupError(f"User not found after plan update: {user_id}")
            updated_data = doc.to_dict()
            updated_data['id'] = doc.id

            logger.info(f"Updated subscription plan for user {user_id} to {plan}")
            return updated_data

        except Exception as e:
            logger.error(f"Error updating subscription plan: {e}")
            raise

    async def update_subscription_data(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Stripe Webhookから許可されたサブスクリプション項目だけを更新する。"""
        allowed_fields = {
            "subscription_plan",
            "subscription_status",
            "stripe_subscription_id",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "last_invoice_id",
            "last_invoice_status",
            "last_payment_at",
            "payment_failed_at",
        }
        invalid_fields = set(updates) - allowed_fields
        if invalid_fields:
            raise ValueError(
                "Unsupported subscription fields: "
                + ", ".join(sorted(invalid_fields))
            )

        update_data = dict(updates)
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.collection("users").document(user_id).update(update_data)
        logger.info("Updated Stripe subscription state for user %s", user_id)

    async def is_active(self, user_id: str) -> bool:
        """
        ユーザーがアクティブかどうかを確認します

        Args:
            user_id: ユーザーID

        Returns:
            アクティブならTrue、そうでなければFalse
        """
        user_data = await self.find_by_id(user_id)
        if user_data:
            return user_data.get('is_active', False)

        return False

    async def deactivate_user(self, user_id: str) -> None:
        """
        ユーザーを非アクティブ化します（退会処理）

        Args:
            user_id: ユーザーID
        """
        try:
            doc_ref = self.db.collection('users').document(user_id)

            await doc_ref.update({
                'is_active': False,
                'updated_at': datetime.utcnow().isoformat()
            })

            logger.info(f"Deactivated user: {user_id}")

        except Exception as e:
            logger.error(f"Error deactivating user: {e}")
            raise

    async def activate_user(self, user_id: str) -> None:
        """再フォローした既存ユーザーを有効化する。"""
        try:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.collection('users').document(user_id).update({
                'is_active': True,
                'deactivated_at': None,
                'reactivated_at': now,
                'updated_at': now,
            })
            logger.info(f"Activated user: {user_id}")
        except Exception as e:
            logger.error(f"Error activating user: {e}")
            raise

    # ===== Stripe 顧客管理関連メソッド =====

    async def find_by_stripe_customer_id(self, stripe_customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Stripe カスタマーID でユーザーを検索します

        Args:
            stripe_customer_id: Stripe カスタマーID

        Returns:
            ユーザーデータの辞書、存在しない場合は None
        """
        try:
            docs = await self.db.collection('users')\
                .where('stripe_customer_id', '==', stripe_customer_id)\
                .limit(1)\
                .get()

            for doc in docs:
                user_data = doc.to_dict()
                user_data['id'] = doc.id
                logger.debug(f"User found by stripe_customer_id: {stripe_customer_id}")
                return user_data

            logger.debug(f"User not found by stripe_customer_id: {stripe_customer_id}")
            return None

        except Exception as e:
            logger.error(f"Error finding user by stripe_customer_id: {e}")
            raise

    async def update_stripe_customer_id(self, user_id: str, stripe_customer_id: str) -> None:
        """
        ユーザーに Stripe カスタマーID を紐付けます

        Args:
            user_id: ユーザーID
            stripe_customer_id: Stripe カスタマーID
        """
        try:
            doc_ref = self.db.collection('users').document(user_id)

            await doc_ref.update({
                'stripe_customer_id': stripe_customer_id,
                'updated_at': datetime.utcnow().isoformat()
            })

            logger.info(f"Updated stripe_customer_id for user {user_id}")

        except Exception as e:
            logger.error(f"Error updating stripe_customer_id: {e}")
            raise

    async def get_stripe_customer_id(self, user_id: str) -> Optional[str]:
        """
        ユーザーの Stripe カスタマーID を取得します

        Args:
            user_id: ユーザーID

        Returns:
            Stripe カスタマーID、存在しない場合は None
        """
        user_data = await self.find_by_id(user_id)
        if user_data:
            return user_data.get('stripe_customer_id')

        return None
