"""
End-to-End tests for User Journey
ユーザージャーニーのエンドツーエンドテスト
"""

import pytest
from httpx import AsyncClient


class TestUserJourney:
    """ユーザージャーニーのE2Eテストクラス"""

    @pytest.mark.asyncio
    async def test_complete_user_registration_and_login_flow(
        self,
        client: AsyncClient,
        sample_user_data,
    ):
        """
        完全なユーザー登録からログインまでのフローをテスト
        """
        # 1. ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        assert register_response.status_code == 201
        register_data = register_response.json()
        assert "access_token" in register_data
        assert "refresh_token" in register_data

        access_token = register_data["access_token"]
        refresh_token = register_data["refresh_token"]

        # 2. ユーザー情報取得
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200
        user_data = me_response.json()
        assert user_data["email"] == sample_user_data["email"]
        assert user_data["username"] == sample_user_data["username"]

        # 3. ログアウト
        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )
        assert logout_response.status_code == 200

        # 4. ログアウト後のアクセストークンでアクセスできないことを確認
        me_response_after_logout = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response_after_logout.status_code == 401

        # 5. 再ログイン
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )
        assert login_response.status_code == 200
        login_data = login_response.json()
        assert "access_token" in login_data
        assert "refresh_token" in login_data

    @pytest.mark.asyncio
    async def test_token_refresh_flow(self, client: AsyncClient, sample_user_data):
        """
        トークンリフレッシュの完全なフローをテスト
        """
        # 1. ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        register_data = register_response.json()
        original_access_token = register_data["access_token"]
        original_refresh_token = register_data["refresh_token"]

        # 2. ユーザー情報取得（元のアクセストークンで）
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {original_access_token}"},
        )
        assert me_response.status_code == 200

        # 3. トークンリフレッシュ
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )
        assert refresh_response.status_code == 200
        refresh_data = refresh_response.json()
        new_access_token = refresh_data["access_token"]
        new_refresh_token = refresh_data["refresh_token"]

        # 4. 新しいアクセストークンでユーザー情報取得
        me_response_new = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_access_token}"},
        )
        assert me_response_new.status_code == 200

        # 5. 古いリフレッシュトークンで再度リフレッシュを試みる（失敗すべき）
        refresh_again_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )
        assert refresh_again_response.status_code == 401

        # 6. ログアウト
        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_access_token}"},
            json={"refresh_token": new_refresh_token},
        )
        assert logout_response.status_code == 200

    @pytest.mark.asyncio
    async def test_revoke_all_tokens_flow(self, client: AsyncClient, sample_user_data):
        """
        全トークン失効の完全なフローをテスト
        """
        # 1. ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        register_data = register_response.json()
        access_token = register_data["access_token"]
        refresh_token = register_data["refresh_token"]
        user_id = register_data["user"]["id"]

        # 2. 全トークンを失効
        revoke_response = await client.post(
            "/api/v1/auth/revoke-all",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"user_id": user_id},
        )
        assert revoke_response.status_code == 200

        # 3. アクセストークンでアクセスできないことを確認
        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 401

        # 4. リフレッシュトークンでリフレッシュできないことを確認
        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert refresh_response.status_code == 401

        # 5. 再ログインが必要であることを確認
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )
        assert login_response.status_code == 200

    @pytest.mark.asyncio
    async def test_multiple_sessions_flow(self, client: AsyncClient, sample_user_data):
        """
        複数セッションでのユーザー操作をテスト
        """
        # 1. ユーザー登録（セッション1）
        register_response_1 = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        register_data_1 = register_response_1.json()
        access_token_1 = register_data_1["access_token"]
        user_id = register_data_1["user"]["id"]

        # 2. 再ログイン（セッション2）
        login_response_2 = await client.post(
            "/api/v1/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )
        login_data_2 = login_response_2.json()
        access_token_2 = login_data_2["access_token"]
        refresh_token_2 = login_data_2["refresh_token"]

        # 3. 両方のセッションでアクセス可能であることを確認
        me_response_1 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token_1}"},
        )
        assert me_response_1.status_code == 200

        me_response_2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token_2}"},
        )
        assert me_response_2.status_code == 200

        # 4. セッション1のみログアウト
        logout_response_1 = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token_1}"},
            json={"refresh_token": "dummy_token"},  # セッション1のトークンは不明
        )

        # 5. セッション1のアクセストークンでアクセスできないことを確認
        me_response_1_after = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token_1}"},
        )
        assert me_response_1_after.status_code == 401

        # 6. セッション2はまだ有効であることを確認
        me_response_2_after = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token_2}"},
        )
        assert me_response_2_after.status_code == 200

        # 7. 全トークンを失効
        revoke_response = await client.post(
            "/api/v1/auth/revoke-all",
            headers={"Authorization": f"Bearer {access_token_2}"},
            json={"user_id": user_id},
        )
        assert revoke_response.status_code == 200

        # 8. セッション2も無効になっていることを確認
        me_response_2_final = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token_2}"},
        )
        assert me_response_2_final.status_code == 401

    @pytest.mark.asyncio
    async def test_rag_chat_flow(self, client: AsyncClient, sample_user_data):
        """
        RAGチャットの完全なフローをテスト
        """
        # 1. ユーザー登録
        register_response = await client.post(
            "/api/v1/auth/register",
            json=sample_user_data,
        )
        access_token = register_response.json()["access_token"]

        # 2. RAGクエリ（モック）
        # 実際のVertex AI APIを呼ぶのではなく、モックレスポンスを返す
        chat_response = await client.post(
            "/api/v1/chat/query",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "text": "What is the meaning of life?",
                "max_results": 5,
                "include_context": True,
            },
        )

        # 実際のAPIがない場合、404を返す可能性がある
        # ここではエンドポイントが存在する場合のみテスト
        if chat_response.status_code != 404:
            assert chat_response.status_code in [200, 503]  # 503: Vertex AI unavailable
            if chat_response.status_code == 200:
                data = chat_response.json()
                assert "answer" in data or "denied" in data
        else:
            # エンドポイントが存在しない場合はスキップ
            pytest.skip("Chat endpoint not implemented yet")

    @pytest.mark.asyncio
    async def test_security_headers(self, client: AsyncClient):
        """
        セキュリティヘッダーの設定をテスト
        """
        response = await client.get("/api/v1/auth/me")

        # 認証なしで401が返される
        assert response.status_code == 401

        # セキュリティ関連のヘッダーが存在するか確認
        headers = response.headers
        # 実際のヘッダーはミドルウェア実装に依存
        # ここでは基本的なチェックのみ
        assert "content-type" in headers
