"""
ユーザーリポジトリ
ユーザーの管理と認証操作を行うリポジトリクラスを定義します。
"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """
    ユーザーリポジトリ

    ユーザーの管理と認証操作を行います。
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


    # ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
    # Phase 2 で以下のメソッドをこのクラスに追加（実装は置かない）:
    #
    #   async def find_by_line_user_id(self, line_user_id: str) -> User | None:
    #       """LINE ユーザーID でユーザーを検索"""
    #
    #   async def find_by_stripe_customer_id(self, customer_id: str) -> User | None:
    #       """Stripe カスタマーID でユーザーを検索"""
    #
    #   async def update_stripe_customer_id(
    #       self, user_id: str, customer_id: str
    #   ) -> None:
    #       """ユーザーに Stripe カスタマーID を紐付け"""
    #
    # 呼び出し元:
    #   - line_service._handle_follow_event [Phase 2 マーカー A4]
    #   - line_service._handle_message_event [Phase 2 マーカー A2]
    #   - line_service._handle_unfollow_event [Phase 2 マーカー A6]
    #   - auth_line callback [Phase 2 マーカー C1]
    #   - stripe_service 各 Webhook ハンドラ [Phase 2 マーカー G2-G6]
    # ===================================================================
