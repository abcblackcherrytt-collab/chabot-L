"""
リフレッシュトークンリポジトリ
リフレッシュトークンの管理と失効操作を行うリポジトリクラスを定義します。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """
    リフレッシュトークンリポジトリ

    リフレッシュトークンの管理と失効操作を行います。
    ログアウト、トークンリフレッシュ、定期的なクリーンアップをサポートします。
    """

    def __init__(self, db: AsyncSession):
        """
        リフレッシュトークンリポジトリを初期化します

        Args:
            db: 非同期データベースセッション
        """
        super().__init__(RefreshToken, db)

    async def get_by_id(self, token_id: str) -> RefreshToken | None:
        """
        トークンIDによるリフレッシュトークンの取得

        Args:
            token_id: トークンID（JTI）

        Returns:
            リフレッシュトークン、または存在しない場合はNone
        """
        statement = select(RefreshToken).where(RefreshToken.id == token_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_user_id(
        self,
        user_id: str,
        include_revoked: bool = False,
    ) -> list[RefreshToken]:
        """
        ユーザーIDによるリフレッシュトークンの取得

        Args:
            user_id: ユーザーID
            include_revoked: 失効トークンを含めるか

        Returns:
            リフレッシュトークンのリスト
        """
        statement = select(RefreshToken).where(RefreshToken.user_id == user_id)
        if not include_revoked:
            statement = statement.where(RefreshToken.is_revoked == False)

        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def get_valid_tokens_by_user_id(
        self,
        user_id: str,
    ) -> list[RefreshToken]:
        """
        ユーザーIDによる有効なリフレッシュトークンの取得

        Args:
            user_id: ユーザーID

        Returns:
            有効なリフレッシュトークンのリスト
        """
        statement = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.is_revoked == False)
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
        )

        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def revoke_token(self, token_id: str) -> bool:
        """
        トークンを失効させます

        Args:
            token_id: トークンID（JTI）

        Returns:
            失効に成功すればTrue、存在しない場合はFalse
        """
        token = await self.get_by_id(token_id)
        if not token:
            return False

        token.revoke()
        return True

    async def revoke_all_user_tokens(
        self,
        user_id: str,
    ) -> int:
        """
        ユーザーの全トークンを失効させます

        パスワード変更時やアカウント停止時に使用します。

        Args:
            user_id: ユーザーID

        Returns:
            失効したトークンの件数
        """
        statement = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.is_revoked == False)
            .values(
                is_revoked=True,
                revoked_at=datetime.now(timezone.utc),
            )
        )

        result = await self.db.execute(statement)
        return result.rowcount

    async def rotate_token(
        self,
        old_token_id: str,
        new_token_data: dict,
    ) -> RefreshToken | None:
        """
        トークンをローテーションします

        旧トークンを失効し、新トークンを作成します。

        Args:
            old_token_id: 旧トークンID
            new_token_data: 新トークンのデータ

        Returns:
            新しいリフレッシュトークン、または失敗時はNone
        """
        # 旧トークンを失効
        await self.revoke_token(old_token_id)

        # 新トークンを作成
        return await self.create(new_token_data)

    async def delete_expired_tokens(
        self,
        before_date: datetime | None = None,
    ) -> int:
        """
        有効期限切れのトークンを削除します

        定期的なクリーンアップジョブで使用します。

        Args:
            before_date: この日時より前のトークンを削除（省略時は現在時刻）

        Returns:
            削除したトークンの件数
        """
        if before_date is None:
            before_date = datetime.now(timezone.utc)

        statement = (
            delete(RefreshToken)
            .where(RefreshToken.expires_at < before_date)
            .where(RefreshToken.is_revoked == True)
        )

        result = await self.db.execute(statement)
        return result.rowcount

    async def cleanup_revoked_tokens(
        self,
        days_old: int = 30,
    ) -> int:
        """
        古い失効トークンをクリーンアップします

        Args:
            days_old: 何日前より古いトークンを削除するか

        Returns:
            削除したトークンの件数
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

        statement = (
            delete(RefreshToken)
            .where(RefreshToken.revoked_at < cutoff_date)
            .where(RefreshToken.is_revoked == True)
        )

        result = await self.db.execute(statement)
        return result.rowcount

    async def is_token_valid(
        self,
        token_id: str,
        token_hash: str,
    ) -> bool:
        """
        トークンが有効かどうかをチェックします

        Args:
            token_id: トークンID（JTI）
            token_hash: トークンのハッシュ値

        Returns:
            トークンが有効であればTrue、それ以外はFalse
        """
        statement = (
            select(RefreshToken)
            .where(RefreshToken.id == token_id)
            .where(RefreshToken.token_hash == token_hash)
            .where(RefreshToken.is_revoked == False)
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
        )

        result = await self.db.execute(statement)
        return result.scalar_one_or_none() is not None

    async def get_all_revoked_tokens_dict(
        self,
    ) -> dict[str, datetime]:
        """
        全失効トークンの辞書を取得します

        JWT検証時にトークンの失効状態を高速にチェックするために使用します。
        注意: 認証必須APIが増えるとDB負荷が増えるため、代わりにis_token_revoked()を使用してください。

        Returns:
            {トークンID: 失効日時} の辞書
        """
        statement = select(RefreshToken).where(RefreshToken.is_revoked == True)
        result = await self.db.execute(statement)
        tokens = result.scalars().all()

        return {token.id: token.revoked_at for token in tokens if token.revoked_at}

    async def is_token_revoked(
        self,
        token_id: str,
    ) -> bool:
        """
        トークンが失効しているかをJTI単体で確認します

        認証時のパフォーマンスを最適化するために、全失効トークンを取得せずに
        JTI単体で失効状態を確認します。

        Args:
            token_id: トークンID（JTI）

        Returns:
            トークンが失効していればTrue、それ以外はFalse
        """
        statement = (
            select(RefreshToken.is_revoked)
            .where(RefreshToken.id == token_id)
            .where(RefreshToken.is_revoked == True)
        )

        result = await self.db.execute(statement)
        return result.scalar_one_or_none() is not None

    async def count_valid_tokens_by_user(
        self,
        user_id: str,
    ) -> int:
        """
        ユーザーの有効なトークン数をカウントします

        Args:
            user_id: ユーザーID

        Returns:
            有効なトークンの数
        """
        statement = (
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.is_revoked == False)
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
        )

        result = await self.db.execute(statement)
        return result.scalar_one()

    async def revoke_oldest_tokens(
        self,
        user_id: str,
        keep_count: int,
    ) -> int:
        """
        ユーザーの最も古いトークンを失効させます

        指定された数だけ最新のトークンを残し、それより古いトークンを失効させます。
        複数端末ログインの上限管理に使用します。

        Args:
            user_id: ユーザーID
            keep_count: 残すトークンの数

        Returns:
            失効したトークンの件数
        """
        # 有効なトークンIDを古い順に取得（エンティティ全体ではなくIDのみ）
        ids_statement = (
            select(RefreshToken.id)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.is_revoked == False)
            .where(RefreshToken.expires_at > datetime.now(timezone.utc))
            .order_by(RefreshToken.created_at.asc())
        )

        result = await self.db.execute(ids_statement)
        all_ids = [row[0] for row in result.all()]

        revoke_count = max(0, len(all_ids) - keep_count)
        if revoke_count == 0:
            return 0

        # 古いトークンを一括で失効
        revoke_ids = all_ids[:revoke_count]
        statement = (
            update(RefreshToken)
            .where(RefreshToken.id.in_(revoke_ids))
            .values(
                is_revoked=True,
                revoked_at=datetime.now(timezone.utc),
            )
        )
        result = await self.db.execute(statement)
        return result.rowcount
