"""
Unit tests for Refresh Token Repository
リフレッシュトークンリポジトリのユニットテスト
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

from app.models.refresh_token import RefreshToken
from app.repositories.refresh_token import RefreshTokenRepository


class TestRefreshTokenRepository:
    """リフレッシュトークンリポジトリのテストクラス"""

    @pytest.mark.asyncio
    async def test_create_token(self, db_session):
        """
        トークン作成が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        expires_at = datetime.utcnow() + timedelta(days=7)
        token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_123",
            "jti": "jti_123",
            "token_type": "refresh",
            "expires_at": expires_at,
        })

        assert token.user_id == "user123"
        assert token.token_hash == "hashed_token_123"
        assert token.jti == "jti_123"
        assert token.token_type == "refresh"
        assert token.revoked_at is None

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session):
        """
        IDによるトークン取得が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # トークンを作成
        created_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_123",
            "jti": "jti_123",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # IDで取得
        retrieved_token = await repo.get_by_id(created_token.id)

        assert retrieved_token is not None
        assert retrieved_token.id == created_token.id
        assert retrieved_token.jti == "jti_123"

    @pytest.mark.asyncio
    async def test_get_by_jti(self, db_session):
        """
        JTIによるトークン取得が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # トークンを作成
        await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_123",
            "jti": "jti_123",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # JTIで取得
        token = await repo.get_by_jti("jti_123")

        assert token is not None
        assert token.jti == "jti_123"
        assert token.user_id == "user123"

    @pytest.mark.asyncio
    async def test_get_valid_tokens_by_user_id(self, db_session):
        """
        ユーザーIDによる有効なトークン一覧取得が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # 有効なトークンを作成
        await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_1",
            "jti": "jti_1",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # 別の有効なトークンを作成
        await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_2",
            "jti": "jti_2",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # 失効したトークンを作成
        revoked_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_3",
            "jti": "jti_3",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })
        await repo.revoke_token(revoked_token.id)

        # 有効なトークンを取得
        valid_tokens = await repo.get_valid_tokens_by_user_id(user.id)

        assert len(valid_tokens) == 2
        assert all(token.revoked_at is None for token in valid_tokens)

    @pytest.mark.asyncio
    async def test_revoke_token(self, db_session):
        """
        トークンの失効が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # トークンを作成
        token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_123",
            "jti": "jti_123",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # トークンを失効
        await repo.revoke_token(token.id)

        # 失効を確認
        revoked_token = await repo.get_by_id(token.id)
        assert revoked_token.revoked_at is not None
        assert revoked_token.revoked_at <= datetime.utcnow()

    @pytest.mark.asyncio
    async def test_rotate_token(self, db_session):
        """
        トークンのローテーションが成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # トークンを作成
        old_token = await repo.create(
            user_id=user.id,
            token_hash="hashed_token_old",
            jti="jti_old",
            token_type="refresh",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        # 新トークンを作成
        new_token = await repo.rotate_token(
            old_token=old_token,
            new_token_hash="hashed_token_new",
            new_jti="jti_new",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )

        # 新トークンを確認
        assert new_token.jti == "jti_new"
        assert new_token.token_hash == "hashed_token_new"
        assert new_token.user_id == user.id

        # 旧トークンの失効を確認
        old_token_reloaded = await repo.get_by_id(old_token.id)
        assert old_token_reloaded.revoked_at is not None

    @pytest.mark.asyncio
    async def test_delete_expired_tokens(self, db_session):
        """
        有効期限切れのトークン削除が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # 有効なトークンを作成
        valid_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_valid",
            "jti": "jti_valid",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # 有効期限切れのトークンを作成
        expired_token_1 = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_expired1",
            "jti": "jti_expired1",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() - timedelta(days=1),
        })

        expired_token_2 = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_expired2",
            "jti": "jti_expired2",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() - timedelta(days=2),
        })

        # 有効期限切れのトークンを削除
        deleted_count = await repo.delete_expired_tokens()

        assert deleted_count == 2

        # 有効なトークンが残っていることを確認
        remaining_token = await repo.get_by_id(valid_token.id)
        assert remaining_token is not None

        # 有効期限切れのトークンが削除されていることを確認
        expired_token_1_reloaded = await repo.get_by_id(expired_token_1.id)
        expired_token_2_reloaded = await repo.get_by_id(expired_token_2.id)
        assert expired_token_1_reloaded is None
        assert expired_token_2_reloaded is None

    @pytest.mark.asyncio
    async def test_cleanup_revoked_tokens(self, db_session):
        """
        失効トークンのクリーンアップが成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # 有効なトークンを作成
        valid_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_valid",
            "jti": "jti_valid",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # 30日前に失効したトークンを作成
        old_revoked_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_old_revoked",
            "jti": "jti_old_revoked",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })
        old_revoked_token.revoked_at = datetime.utcnow() - timedelta(days=30)
        await db_session.commit()

        # 1日前に失効したトークンを作成
        recent_revoked_token = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_recent_revoked",
            "jti": "jti_recent_revoked",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })
        recent_revoked_token.revoked_at = datetime.utcnow() - timedelta(days=1)
        await db_session.commit()

        # 30日以上前に失効したトークンをクリーンアップ
        deleted_count = await repo.cleanup_revoked_tokens(days=30)

        assert deleted_count == 1

        # 有効なトークンと最近失効したトークンが残っていることを確認
        assert await repo.get_by_id(valid_token.id) is not None
        assert await repo.get_by_id(recent_revoked_token.id) is not None

        # 30日前に失効したトークンが削除されていることを確認
        assert await repo.get_by_id(old_revoked_token.id) is None

    @pytest.mark.asyncio
    async def test_revoke_all_user_tokens(self, db_session):
        """
        ユーザーの全トークンの失効が成功することをテスト
        """
        user = MagicMock()
        user.id = "user123"

        repo = RefreshTokenRepository(db_session)

        # 複数のトークンを作成
        token_1 = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_1",
            "jti": "jti_1",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        token_2 = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_2",
            "jti": "jti_2",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        token_3 = await repo.create({
            "user_id": user.id,
            "token_hash": "hashed_token_3",
            "jti": "jti_3",
            "token_type": "refresh",
            "expires_at": datetime.utcnow() + timedelta(days=7),
        })

        # 全トークンを失効
        revoked_count = await repo.revoke_all_user_tokens(user.id)

        assert revoked_count == 3

        # 全トークンが失効していることを確認
        assert (await repo.get_by_id(token_1.id)).revoked_at is not None
        assert (await repo.get_by_id(token_2.id)).revoked_at is not None
        assert (await repo.get_by_id(token_3.id)).revoked_at is not None
