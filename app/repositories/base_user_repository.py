"""
抽象ユーザーリポジトリ
データベースバックエンドに依存しないユーザーリポジトリの抽象クラスを定義します。
FirestoreとCloud SQLの切り替えを可能にするための抽象化レイヤーです。
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseUserRepository(ABC):
    """
    抽象ユーザーリポジトリ

    FirestoreとCloud SQLの両方で実装するインターフェースを定義します。
    """

    @abstractmethod
    async def find_by_line_user_id(self, line_user_id: str) -> Optional[Dict[str, Any]]:
        """
        LINEユーザーIDでユーザーを検索します

        Args:
            line_user_id: LINEユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def find_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        IDでユーザーを検索します

        Args:
            user_id: ユーザーID

        Returns:
            ユーザーデータの辞書、存在しない場合はNone
        """
        pass

    @abstractmethod
    async def get_subscription_plan(self, user_id: str) -> str:
        """
        ユーザーのサブスクリプションプランを取得します

        Args:
            user_id: ユーザーID

        Returns:
            サブスクリプションプラン（'free', 'basic', 'pro'）
        """
        pass

    @abstractmethod
    async def update_subscription_plan(self, user_id: str, plan: str) -> Dict[str, Any]:
        """
        サブスクリプションプランを更新します

        Args:
            user_id: ユーザーID
            plan: 新しいプラン（'free', 'basic', 'pro'）

        Returns:
            更新後のサブスクリプションデータ
        """
        pass

    @abstractmethod
    async def is_active(self, user_id: str) -> bool:
        """
        ユーザーがアクティブかどうかを確認します

        Args:
            user_id: ユーザーID

        Returns:
            アクティブならTrue、そうでなければFalse
        """
        pass

    @abstractmethod
    async def deactivate_user(self, user_id: str) -> None:
        """
        ユーザーを非アクティブ化します（退会処理）

        Args:
            user_id: ユーザーID
        """
        pass

    @abstractmethod
    async def activate_user(self, user_id: str) -> None:
        """既存ユーザーを再フォロー時に再有効化する。"""
        pass

    # ===== Stripe 顧客管理関連メソッド =====

    @abstractmethod
    async def find_by_stripe_customer_id(self, stripe_customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Stripe カスタマーID でユーザーを検索します

        Args:
            stripe_customer_id: Stripe カスタマーID

        Returns:
            ユーザーデータの辞書、存在しない場合は None
        """
        pass

    @abstractmethod
    async def update_stripe_customer_id(self, user_id: str, stripe_customer_id: str) -> None:
        """
        ユーザーに Stripe カスタマーID を紐付けます

        Args:
            user_id: ユーザーID
            stripe_customer_id: Stripe カスタマーID
        """
        pass

    @abstractmethod
    async def get_stripe_customer_id(self, user_id: str) -> Optional[str]:
        """
        ユーザーの Stripe カスタマーID を取得します

        Args:
            user_id: ユーザーID

        Returns:
            Stripe カスタマーID、存在しない場合は None
        """
        pass
