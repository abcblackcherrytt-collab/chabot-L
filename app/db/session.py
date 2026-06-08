"""
データベースセッション管理
非同期データベースセッションの管理を行います。
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text

from app.core.config import settings

# 非同期エンジンを作成
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # 開発環境ではSQLをログに出力
    pool_pre_ping=True,  # 接続プールの健全性チェック
    pool_size=20,  # 最大接続数
    max_overflow=10,  # 追加接続数（ピーク時）
    pool_timeout=30,  # 接続タイムアウト（秒）
    pool_recycle=3600,  # 接続リサイクル（秒）
)

# 非同期セッションファクトリーを作成
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # コミット後にセッションを無効化しない
    autocommit=False,  # 自動コミットを無効化
    autoflush=False,  # 自動フラッシュを無効化
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    データベースセッションを取得する依存関係関数

    FastAPIのDependsで使用することで、リクエストごとに新しいセッションが作成され、
    リクエスト終了時に自動的にクローズされます。

    Yields:
        非同期データベースセッション
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    データベース接続を初期化します

    アプリケーション起動時に実行します。
    """
    async with engine.begin() as conn:
        # 接続を確立してエラーをチェック
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """
    データベース接続を閉じます

    アプリケーション終了時に実行します。
    """
    await engine.dispose()
