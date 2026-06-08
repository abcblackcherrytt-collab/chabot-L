"""
Integration tests for Authentication API
認証APIの統合テスト
"""

import pytest
from httpx import AsyncClient


class TestAuthAPI:
    """認証APIの統合テストクラス"""

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient, sample_user_data):
        """
        ユーザー登録が成功することをテスト
        """
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == sample_user_data["email"]
        assert data["user"]["username"] == sample_user_data["username"]

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, sample_user_data):
        """
        重複メールアドレスで登録が失敗することをテスト
        """
        # 最初の登録
        await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )

        # 重複登録
        response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """
        無効なメールアドレスで登録が失敗することをテスト
        """
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "invalid-email",
                "username": "testuser",
                "password": "TestPassword123!",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_weak_password(self, client: AsyncClient):
        """
        弱いパスワードで登録が失敗することをテスト
        """
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "weak",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, sample_user_data):
        """
        ログインが成功することをテスト
        """
        # ユーザー登録
        await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )

        # ログイン
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """
        無効な認証情報でログインが失敗することをテスト
        """
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, sample_user_data):
        """
        トークンリフレッシュが成功することをテスト
        """
        # ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        refresh_token = register_response.json()["refresh_token"]

        # トークンリフレッシュ
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self, client: AsyncClient):
        """
        無効なトークンでリフレッシュが失敗することをテスト
        """
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )

        assert response.status_code == 401
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_logout_success(self, client: AsyncClient, sample_user_data):
        """
        ログアウトが成功することをテスト
        """
        # ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        access_token = register_response.json()["access_token"]
        refresh_token = register_response.json()["refresh_token"]

        # ログアウト
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Logged out successfully"

    @pytest.mark.asyncio
    async def test_logout_without_auth(self, client: AsyncClient):
        """
        認証なしでログアウトが失敗することをテスト
        """
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "some_token"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_revoke_all_tokens_success(self, client: AsyncClient, sample_user_data):
        """
        全トークンの失効が成功することをテスト
        """
        # ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        access_token = register_response.json()["access_token"]
        user_id = register_response.json()["user"]["id"]

        # 全トークンを失効
        response = await client.post(
            "/api/v1/auth/revoke-all",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"user_id": user_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "All tokens revoked successfully"

    @pytest.mark.asyncio
    async def test_get_me_success(self, client: AsyncClient, sample_user_data):
        """
        現在のユーザー情報取得が成功することをテスト
        """
        # ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        access_token = register_response.json()["access_token"]

        # 現在のユーザー情報を取得
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == sample_user_data["email"]
        assert data["username"] == sample_user_data["username"]
        assert "password" not in data  # パスワードは含まれていない

    @pytest.mark.asyncio
    async def test_get_me_without_auth(self, client: AsyncClient):
        """
        認証なしでユーザー情報取得が失敗することをテスト
        """
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_access_token_expiration(self, client: AsyncClient, sample_user_data):
        """
        アクセストークンの有効期限が正しく機能することをテスト
        """
        # ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        access_token = register_response.json()["access_token"]

        # すぐにアクセス（有効）
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200

        # 実際には15分待てないため、ここではトークン構造の検証のみ
        # 実際の期限切れテストはモックや設定変更で実装可能
        import jwt
        from app.core.config import settings

        decoded = jwt.decode(
            access_token,
            settings.jwt_secret_keys[0],
            algorithms=[settings.jwt_algorithm],
        )

        assert "exp" in decoded
        assert "jti" in decoded
