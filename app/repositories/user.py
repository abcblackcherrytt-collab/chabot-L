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
