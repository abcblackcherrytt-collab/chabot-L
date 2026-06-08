"""
失効トークンクリーンアップスクリクト
定期的な実行で古い失効トークンを削除します。
"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.core.config import settings
from app.services.auth_service import AuthService


async def cleanup_expired_tokens(days_old: int = 30) -> int:
    """
    古い失効トークンをクリーンアップします

    Args:
        days_old: 何日前より古いトークンを削除するか

    Returns:
        削除したトークンの件数
    """
    # データベースエンジンを作成
    engine = create_async_engine(settings.database_url, echo=False)

    # セッションを作成
    async with AsyncSession(engine) as db:
        # 認証サービスを初期化
        auth_service = AuthService(db)

        # クリーンアップ実行
        deleted_count = await auth_service.cleanup_expired_tokens(days_old)

        print(f"✅ Deleted {deleted_count} expired tokens older than {days_old} days")

        return deleted_count


def main():
    """
    メイン関数
    """
    parser = argparse.ArgumentParser(
        description="Clean up expired refresh tokens"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Delete tokens revoked more than this many days ago (default: 30)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        print(f"Starting cleanup of tokens older than {args.days} days...")
        print(f"Database URL: {settings.database_url}")
        print(f"App Environment: {settings.app_env}")

    try:
        # 非同期で実行
        deleted_count = asyncio.run(cleanup_expired_tokens(args.days))

        if args.verbose:
            print(f"✅ Cleanup completed successfully")

        sys.exit(0)
    except Exception as e:
        print(f"❌ Error during cleanup: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
