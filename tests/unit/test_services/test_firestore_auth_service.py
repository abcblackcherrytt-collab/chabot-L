"""Firestore版LINE Login認証サービス（セッション基盤）のテスト。"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.security import create_refresh_token, decode_token
from app.services import firestore_auth_service as auth_module
from app.services.firestore_auth_service import FirestoreAuthService


def _user() -> dict:
    return {
        "id": "persisted-user",
        "email": "user@example.com",
        "line_user_id": "U123",
        "role": "user",
        "is_active": True,
        "auth_version": 0,
    }


def _repositories(monkeypatch, user=None):
    """セッション基盤の認証serviceとモックリポジトリ一式を返す。"""
    monkeypatch.setattr(auth_module, "hash_token", lambda token: f"hashed:{token}")
    monkeypatch.setattr(
        auth_module,
        "verify_token_hash",
        lambda token, hashed: hashed == f"hashed:{token}",
    )
    user_repository = MagicMock()
    user_repository.find_by_id = AsyncMock(return_value=user if user is not None else _user())
    user_repository.increment_auth_version = AsyncMock(return_value=1)
    token_repository = MagicMock()
    token_repository.create = AsyncMock()
    token_repository.get_by_id = AsyncMock()
    token_repository.revoke_token = AsyncMock(return_value=True)
    token_repository.revoke_all_user_tokens = AsyncMock(return_value=2)
    token_repository.collection_name = "refresh_tokens"

    sessions = {}
    session_repository = MagicMock()
    session_repository.collection_name = "auth_sessions"

    async def _create(session_data):
        sessions[session_data["id"]] = dict(session_data)

    session_repository.create = AsyncMock(side_effect=_create)

    async def _get(session_id):
        data = sessions.get(session_id)
        return dict(data) if data else None

    session_repository.get = AsyncMock(side_effect=_get)
    session_repository.revoke = AsyncMock(return_value=True)
    session_repository.revoke_all_for_user = AsyncMock(return_value=1)
    session_repository._store = sessions
    return user_repository, token_repository, session_repository


def _fake_db(monkeypatch, token_repository, session_repository, old_token_id):
    """Firestore Transactionを置き換える最小のフェイクを組み立てる。"""
    old_snapshot = MagicMock()
    old_snapshot.exists = True
    old_snapshot.to_dict.return_value = {"is_revoked": False, "consumed_at": None}
    old_ref = MagicMock()
    old_ref.get = AsyncMock(return_value=old_snapshot)
    new_ref = MagicMock()
    session_ref = MagicMock()

    token_collection = MagicMock()
    token_collection.document.side_effect = lambda doc_id: (
        old_ref if doc_id == old_token_id else new_ref
    )
    session_collection = MagicMock()
    session_collection.document.return_value = session_ref
    db = MagicMock()
    db.collection.side_effect = lambda name: (
        token_collection
        if name == token_repository.collection_name
        else session_collection
    )
    db.transaction.return_value = MagicMock()
    token_repository.db = db

    # @firestore.async_transactionalを素通しにして、フェイクtxで即実行する。
    monkeypatch.setattr(
        auth_module.firestore, "async_transactional", lambda fn: fn
    )
    return old_ref, new_ref, session_ref


@pytest.mark.asyncio
async def test_issue_tokens_binds_session_and_generation(monkeypatch) -> None:
    """発行トークンが共通sidと認証世代を持ち、PIIを含まないこと。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )

    tokens = await service.issue_tokens(_user(), "U123")

    access_payload = decode_token(tokens["access_token"])
    refresh_payload = decode_token(tokens["refresh_token"])
    assert access_payload["sub"] == "persisted-user"
    assert refresh_payload["provider"] == "line"
    assert access_payload["sid"] == refresh_payload["sid"]
    assert access_payload["auth_version"] == 0
    assert refresh_payload["auth_version"] == 0
    assert "email" not in access_payload
    assert "email" not in refresh_payload
    assert "line_user_id" not in access_payload
    assert "line_user_id" not in refresh_payload
    assert 0 < access_payload["exp"] - int(time.time()) <= 15 * 60
    session_repository.create.assert_awaited_once()
    session_data = session_repository.create.await_args.args[0]
    assert session_data["current_refresh_jti"] == refresh_payload["jti"]
    token_repository.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_rotates_atomically_and_keeps_session(monkeypatch) -> None:
    """更新は同一セッションで単回消費され、新トークンへ引き継がれること。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )
    original = await service.issue_tokens(_user(), "U123")
    original_payload = decode_token(original["refresh_token"])
    token_repository.get_by_id.return_value = {
        "id": original_payload["jti"],
        "user_id": "persisted-user",
        "token_hash": f"hashed:{original['refresh_token']}",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=20),
        "is_revoked": False,
        "consumed_at": None,
    }
    old_ref, new_ref, session_ref = _fake_db(
        monkeypatch, token_repository, session_repository, original_payload["jti"]
    )

    rotated = await service.refresh(original["refresh_token"])

    assert rotated is not None
    assert rotated["refresh_token"] != original["refresh_token"]
    new_payload = decode_token(rotated["refresh_token"])
    assert new_payload["sid"] == original_payload["sid"]
    # 旧トークン消費・新トークン作成・セッション指し替えが確定していること
    tx = token_repository.db.transaction.return_value
    old_update = tx.update.call_args_list[0]
    assert old_update.args[0] is old_ref
    assert old_update.args[1]["consumed_at"] is not None
    assert tx.set.call_args.args[0] is new_ref
    session_update = tx.update.call_args_list[1]
    assert session_update.args[0] is session_ref
    assert session_update.args[1][
        "current_refresh_jti"
    ] == new_payload["jti"]


@pytest.mark.asyncio
async def test_refresh_rejects_consumed_token(monkeypatch) -> None:
    """消費済みトークンからの更新は失敗し、後継を発行しないこと。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )
    original = await service.issue_tokens(_user(), "U123")
    token_repository.get_by_id.return_value = {
        "id": decode_token(original["refresh_token"])["jti"],
        "user_id": "persisted-user",
        "token_hash": f"hashed:{original['refresh_token']}",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=20),
        "is_revoked": False,
        "consumed_at": datetime.now(timezone.utc),
    }

    assert await service.refresh(original["refresh_token"]) is None


@pytest.mark.asyncio
async def test_authenticate_refresh_reuses_token_without_rotation(
    monkeypatch,
) -> None:
    """残存期間が十分なCookieは検証のみでトークンを消費しないこと。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )
    original = await service.issue_tokens(_user(), "U123")
    token_repository.get_by_id.return_value = {
        "id": decode_token(original["refresh_token"])["jti"],
        "user_id": "persisted-user",
        "token_hash": f"hashed:{original['refresh_token']}",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=25),
        "is_revoked": False,
        "consumed_at": None,
    }

    result = await service.authenticate_refresh(original["refresh_token"])

    assert result is not None
    assert result["refresh_token"] == original["refresh_token"]
    access_payload = decode_token(result["access_token"])
    assert access_payload["sid"] == decode_token(original["access_token"])["sid"]
    session_repository.create.assert_awaited_once()  # 移行で新セッションを作らない


@pytest.mark.asyncio
async def test_legacy_refresh_migrates_once_to_session(monkeypatch) -> None:
    """旧形式Refresh Tokenは一度だけ新セッションへ移行すること。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )
    legacy_token, _ = create_refresh_token(
        user_id="persisted-user",
        email="user@example.com",
        jti="legacy-jti",
        additional_claims={"provider": "line"},
    )
    token_repository.get_by_id.return_value = {
        "id": "legacy-jti",
        "user_id": "persisted-user",
        "token_hash": f"hashed:{legacy_token}",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=10),
        "is_revoked": False,
        "consumed_at": None,
    }
    old_ref, new_ref, session_ref = _fake_db(
        monkeypatch, token_repository, session_repository, "legacy-jti"
    )

    migrated = await service.authenticate_refresh(legacy_token)

    assert migrated is not None
    new_payload = decode_token(migrated["refresh_token"])
    assert new_payload["sid"]
    assert new_payload["jti"] != "legacy-jti"
    tx = token_repository.db.transaction.return_value
    old_update = tx.update.call_args_list[0]
    assert old_update.args[0] is old_ref
    assert old_update.args[1]["consumed_at"] is not None
    set_targets = [call.args[0] for call in tx.set.call_args_list]
    assert new_ref in set_targets
    assert session_ref in set_targets


@pytest.mark.asyncio
async def test_logout_revokes_token_and_session(monkeypatch) -> None:
    """ログアウトでトークンとセッションの両方を失効させること。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )
    tokens = await service.issue_tokens(_user(), "U123")
    payload = decode_token(tokens["refresh_token"])

    result = await service.logout(tokens["refresh_token"])

    assert result is True
    token_repository.revoke_token.assert_awaited_once_with(payload["jti"])
    session_repository.revoke.assert_awaited_once_with(payload["sid"])


@pytest.mark.asyncio
async def test_revoke_all_updates_generation_and_revokes_everything(
    monkeypatch,
) -> None:
    """全失効は認証世代更新とトークン・セッション失効を行うこと。"""
    user_repository, token_repository, session_repository = _repositories(monkeypatch)
    service = FirestoreAuthService(
        user_repository, token_repository, session_repository
    )

    revoked_count = await service.revoke_all_user_tokens("user-1")

    assert revoked_count == 2
    user_repository.increment_auth_version.assert_awaited_once_with("user-1")
    token_repository.revoke_all_user_tokens.assert_awaited_once_with("user-1")
    session_repository.revoke_all_for_user.assert_awaited_once_with("user-1")
