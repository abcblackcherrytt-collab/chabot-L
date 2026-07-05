"""
RAG 権限リポジトリ
プラン別の RAG 設定（コーパスID・モデル・制限）の参照を提供します。

Phase 2: rag_permissions テーブルからプラン別の rag_corpus_id / model_name /
daily_message_limit 等を参照し、コーパス動的切替に使用する。
シードはテーブルに事前投入（PROJECT_PLAN.md D2）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_permission import RagPermission
from app.repositories.base import BaseRepository


class RagPermissionRepository(BaseRepository[RagPermission]):
    """
    RAG 権限リポジトリ

    プラン別の RAG 設定（rag_corpus_id / model_name / daily_message_limit 等）を
    参照します。
    """

    def __init__(self, db: AsyncSession):
        """
        RAG 権限リポジトリを初期化します

        Args:
            db: 非同期データベースセッション
        """
        super().__init__(RagPermission, db)

    async def get_by_plan(self, plan: str) -> RagPermission | None:
        """
        プラン名で RAG 権限を取得

        Args:
            plan: プラン名（free / basic / pro 等）

        Returns:
            RAG 権限、存在しない場合は None
        """
        statement = select(RagPermission).where(RagPermission.plan == plan)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()
