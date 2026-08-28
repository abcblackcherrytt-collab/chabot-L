"""Firestore版LINE Login認証サービスのテスト。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.security import decode_token
from app.services import firestore_auth_service as auth_module
from app.services.firestore_auth_service import FirestoreAuthService


@pytest.mark.asyncio
async def test_issue_tokens_reuses_persisted_user_id(monkeypatch) -> None:
    """LINE Loginのたびに仮UUIDを発行せずFirestoreユーザーIDをJWTへ使うこと。"""
    monkeypatch.setattr(auth_module, "hash_token", lambda token: "hashed")
    user_repository = MagicMock()
    token_repository = MagicMock()
    token_repository.create = AsyncMock()
    service = FirestoreAuthService(user_repository, token_repository)

    tokens = await service.issue_tokens(
        {
            "id": "persisted-user",
            "email": "user@example.com",
            "role": "user",
        },
        "U123",
    )

    access_payload = decode_token(tokens["access_token"])
    refresh_payload = decode_token(tokens["refresh_token"])
    assert access_payload["sub"] == "persisted-user"
    assert refresh_payload["sub"] == "persisted-user"
    assert refresh_payload["provider"] == "line"
    token_repository.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_rotates_saved_line_token(monkeypatch) -> None:
    """保存済みRefresh Tokenを検証して新トークンへローテーションすること。"""
    monkeypatch.setattr(auth_module, "hash_token", lambda token: "hashed")
    monkeypatch.setattr(auth_module, "verify_token_hash", lambda token, hashed: True)
    user_repository = MagicMock()
    user_repository.find_by_id = AsyncMock(
        return_value={
            "id": "persisted-user",
            "email": "user@example.com",
            "role": "user",
            "is_active": True,
        }
    )
    token_repository = MagicMock()
    token_repository.create = AsyncMock()
    token_repository.get_by_id = AsyncMock()
    token_repository.revoke_token = AsyncMock(return_value=True)
    service = FirestoreAuthService(user_repository, token_repository)
    original = await service.issue_tokens(
        {
            "id": "persisted-user",
            "email": "user@example.com",
            "role": "user",
        },
        "U123",
    )
    original_payload = decode_token(original["refresh_token"])
    token_repository.get_by_id.return_value = {
        "id": original_payload["jti"],
        "user_id": "persisted-user",
        "token_hash": "hashed",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "is_revoked": False,
    }

    rotated = await service.refresh(original["refresh_token"])

    assert rotated is not None
    assert rotated["refresh_token"] != original["refresh_token"]
    token_repository.revoke_token.assert_awaited_once_with(original_payload["jti"])


@pytest.mark.asyncio
async def test_revoke_all_user_tokens_delegates_to_repository() -> None:
    """unfollow時の全セッション失効をリポジトリへ委譲すること。"""
    token_repository = MagicMock()
    token_repository.revoke_all_user_tokens = AsyncMock(return_value=2)
    service = FirestoreAuthService(MagicMock(), token_repository)

    revoked_count = await service.revoke_all_user_tokens("user-1")

    assert revoked_count == 2
    token_repository.revoke_all_user_tokens.assert_awaited_once_with("user-1")
