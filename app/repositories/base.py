"""
ベースリポジトリ
すべてのリポジトリが継承するベースクラスを定義します。
"""

from typing import Any, Generic, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

# モデルのジェネリック型
ModelType = TypeVar("ModelType", bound=Base)

# スキーマのジェネリック型
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class BaseRepository(Generic[ModelType]):
    """
    ベースリポジトリ

    すべてのリポジトリが継承するベースクラスです。
    基本的なCRUD操作を提供します。
    """

    def __init__(self, model: Type[ModelType], db: AsyncSession):
        """
        ベースリポジトリを初期化します

        Args:
            model: SQLAlchemyモデルクラス
            db: 非同期データベースセッション
        """
        self.model = model
        self.db = db

    async def get(self, id: str) -> ModelType | None:
        """
        IDによる単一エンティティの取得

        Args:
            id: エンティティのID

        Returns:
            エンティティ、または存在しない場合はNone
        """
        statement = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ModelType]:
        """
        全エンティティの取得（ページネーション対応）

        Args:
            skip: スキップする件数
            limit: 取得する最大件数

        Returns:
            エンティティのリスト
        """
        statement = select(self.model).offset(skip).limit(limit)
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def create(self, obj_in: dict[str, Any]) -> ModelType:
        """
        新規エンティティの作成

        Args:
            obj_in: 作成するエンティティのデータ

        Returns:
            作成されたエンティティ
        """
        db_obj = self.model(**obj_in)
        self.db.add(db_obj)
        await self.db.flush()
        await self.db.refresh(db_obj)
        return db_obj

    async def update(
        self,
        id: str,
        obj_in: dict[str, Any],
    ) -> ModelType | None:
        """
        エンティティの更新

        Args:
            id: エンティティのID
            obj_in: 更新するデータ

        Returns:
            更新されたエンティティ、または存在しない場合はNone
        """
        statement = (
            update(self.model)
            .where(self.model.id == id)  # type: ignore[attr-defined]
            .values(**obj_in)
            .returning(self.model)
        )
        result = await self.db.execute(statement)
        await self.db.flush()

        updated_obj = result.scalar_one_or_none()
        if updated_obj:
            await self.db.refresh(updated_obj)
        return updated_obj

    async def delete(self, id: str) -> bool:
        """
        エンティティの削除

        Args:
            id: エンティティのID

        Returns:
            削除に成功すればTrue、存在しない場合はFalse
        """
        statement = delete(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.db.execute(statement)
        return result.rowcount > 0

    async def exists(self, id: str) -> bool:
        """
        エンティティの存在確認

        Args:
            id: エンティティのID

        Returns:
            存在すればTrue、それ以外はFalse
        """
        statement = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]
        result = await self.db.execute(statement)
        return result.scalar_one_or_none() is not None
