"""
LINE並列処理のユニットテスト
FirestoreアクセスとRAG処理の並列化を検証します。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.line_service import LineService


@pytest.fixture
def mock_line_client():
    """モック LINE クライアント"""
    client = MagicMock(spec=[])
    client.reply_message = AsyncMock(return_value={})
    client.push_message = AsyncMock(return_value={})
    client.get_profile = AsyncMock(return_value={
        "displayName": "テストユーザー",
        "userId": "U_test123",
    })
    client.health_check = AsyncMock(return_value={
        "status": "healthy",
        "service": "line",
    })
    return client


@pytest.fixture
def line_service(mock_line_client, monkeypatch):
    """テスト用 LINE サービス"""
    user_repo = MagicMock()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "email": None,
        "display_name": "テストユーザー",
        "role": "user",
        "is_active": True,
        "subscription_plan": "free",
    })
    user_repo.create_line_user = AsyncMock()
    user_repo.is_active = AsyncMock(return_value=True)
    user_repo.get_subscription_plan = AsyncMock(return_value="free")
    user_repo.deactivate_user = AsyncMock()

    rag_permission_repo = MagicMock()
    rag_permission_repo.get_by_plan = AsyncMock(return_value={
        "rag_corpus_id": "test-corpus",
        "model_name": "test-model",
    })

    usage_repo = MagicMock()
    usage_repo.increment_with_limit_check = AsyncMock(return_value={
        "success": True,
        "current_count": 1,
        "remaining": 2,
        "message": "ok",
    })

    service = LineService(line_client=mock_line_client)
    monkeypatch.setattr(service, "_get_user_repository", lambda db=None: user_repo)
    monkeypatch.setattr(
        service,
        "_get_rag_permission_repository",
        lambda: rag_permission_repo,
    )
    monkeypatch.setattr(
        "app.repositories.firestore_usage_repository.FirestoreUsageRepository",
        lambda: usage_repo,
    )
    service._test_usage_repo = usage_repo
    return service


class TestGetUserDataForParallel:
    """並列実行用ユーザーデータ取得テスト"""

    @pytest.mark.asyncio
    async def test_get_user_data_success(self, line_service):
        """ユーザーデータ取得が成功すること"""
        result = await line_service._get_user_data_for_parallel("U_test123")

        assert result["status"] == "success"
        assert result["user_id"] == "user-123"
        assert result["line_user_id"] == "U_test123"
        assert result["plan"] == "free"
        assert result["corpus_id"] == "test-corpus"
        assert result["model_name"] == "test-model"

    @pytest.mark.asyncio
    async def test_get_user_data_not_found(self, line_service, monkeypatch):
        """ユーザーが見つからない場合エラーが返ること"""
        user_repo = MagicMock()
        user_repo.find_by_line_user_id = AsyncMock(return_value=None)
        monkeypatch.setattr(line_service, "_get_user_repository", lambda db=None: user_repo)

        result = await line_service._get_user_data_for_parallel("U_unknown")

        assert result["status"] == "error"
        assert "見つかりません" in result["message"]

    @pytest.mark.asyncio
    async def test_get_user_data_inactive(self, line_service, monkeypatch):
        """非アクティブユーザーの場合エラーが返ること"""
        user_repo = MagicMock()
        user_repo.find_by_line_user_id = AsyncMock(return_value={
            "id": "user-123",
            "line_user_id": "U_test123",
        })
        user_repo.is_active = AsyncMock(return_value=False)
        monkeypatch.setattr(line_service, "_get_user_repository", lambda db=None: user_repo)

        result = await line_service._get_user_data_for_parallel("U_test123")

        assert result["status"] == "error"
        assert "無効です" in result["message"]


class TestCheckAndIncrementUsage:
    """回数制限チェックとインクリメントテスト"""

    @pytest.mark.asyncio
    async def test_check_usage_success(self, line_service):
        """回数制限チェックが成功すること"""
        result = await line_service._check_and_increment_usage("user-123", "free")

        assert result["success"] is True
        assert result["current_count"] == 1
        assert result["remaining"] == 2

    @pytest.mark.asyncio
    async def test_check_usage_limit_reached(self, line_service, monkeypatch):
        """回数制限に達した場合エラーが返ること"""
        usage_repo = MagicMock()
        usage_repo.increment_with_limit_check = AsyncMock(return_value={
            "success": False,
            "message": "本日の利用回数を超えました",
            "current_count": 3,
            "remaining": 0,
        })
        monkeypatch.setattr(
            "app.repositories.firestore_usage_repository.FirestoreUsageRepository",
            lambda: usage_repo,
        )

        result = await line_service._check_and_increment_usage("user-123", "free")

        assert result["success"] is False
        assert "超えました" in result["message"]
        assert result["current_count"] == 3
        assert result["remaining"] == 0


class TestParallelExecution:
    """並列実行テスト"""

    @pytest.mark.asyncio
    async def test_parallel_execution_timing(self, line_service):
        """並列実行時のタイミングを検証"""
        import time

        # 遅延をシミュレート
        async def slow_user_data(line_user_id):
            await asyncio.sleep(0.1)  # 100ms遅延
            return await line_service._get_user_data_for_parallel(line_user_id)

        async def slow_rag_query(text, **kwargs):
            await asyncio.sleep(0.2)  # 200ms遅延
            return {"answer": "テスト回答"}

        # 開始時刻
        start_time = time.time()

        # 並列実行
        user_data, rag_result = await asyncio.gather(
            slow_user_data("U_test123"),
            slow_rag_query("テスト質問"),
        )

        # 終了時刻
        elapsed_time = time.time() - start_time

        # 並列実行なので、200ms（遅い方）+ αで完了するはず
        # 逐次実行なら300ms以上かかる
        assert elapsed_time < 0.25, f"Parallel execution took {elapsed_time:.3f}s (expected <0.25s)"
        assert user_data["status"] == "success"
        assert rag_result["answer"] == "テスト回答"

    @pytest.mark.asyncio
    async def test_parallel_execution_with_exception(self, line_service):
        """並列実行時の例外処理を検証"""
        async def failing_user_data(line_user_id):
            raise Exception("User fetch failed")

        async def normal_rag_query(text, **kwargs):
            await asyncio.sleep(0.1)
            return {"answer": "テスト回答"}

        # 並列実行（片方が失敗）
        user_data, rag_result = await asyncio.gather(
            failing_user_data("U_test123"),
            normal_rag_query("テスト質問"),
            return_exceptions=True
        )

        # 例外がキャプチャされている
        assert isinstance(user_data, Exception)
        assert rag_result["answer"] == "テスト回答"

    @pytest.mark.asyncio
    async def test_parallel_execution_order_independence(self, line_service):
        """並列実行の順序独立性を検証"""
        # タスクの実行順序が結果に影響しないことを確認
        results = []

        async def create_tasks():
            tasks = [
                line_service._get_user_data_for_parallel("U_test123"),
                line_service._check_and_increment_usage("user-123", "free"),
            ]
            return await asyncio.gather(*tasks)

        # 複数回実行して一貫性を確認
        for _ in range(3):
            user_data, usage_result = await create_tasks()
            results.append((user_data, usage_result))

        # 全ての結果が一貫している
        for user_data, usage_result in results:
            assert user_data["status"] == "success"
            assert usage_result["success"] is True


class TestErrorHandling:
    """エラーハンドリングテスト"""

    @pytest.mark.asyncio
    async def test_get_user_data_exception_handling(self, line_service, monkeypatch):
        """ユーザーデータ取得時の例外ハンドリング"""
        user_repo = MagicMock()
        user_repo.find_by_line_user_id = AsyncMock(side_effect=Exception("DB error"))
        monkeypatch.setattr(line_service, "_get_user_repository", lambda db=None: user_repo)

        result = await line_service._get_user_data_for_parallel("U_test123")

        assert result["status"] == "error"
        assert "失敗しました" in result["message"]

    @pytest.mark.asyncio
    async def test_check_usage_exception_handling(self, line_service, monkeypatch):
        """回数制限チェック時の例外ハンドリング"""
        usage_repo = MagicMock()
        usage_repo.increment_with_limit_check = AsyncMock(side_effect=Exception("Firestore error"))
        monkeypatch.setattr(
            "app.repositories.firestore_usage_repository.FirestoreUsageRepository",
            lambda: usage_repo,
        )

        result = await line_service._check_and_increment_usage("user-123", "free")

        assert result["success"] is False
        assert "確認できません" in result["message"]


class TestIntegrationScenarios:
    """統合シナリオテスト"""

    @pytest.mark.asyncio
    async def test_full_parallel_flow_simulation(self, line_service):
        """完全な並列フローのシミュレーション"""
        # シミュレート: Firestore + RAG 並列実行
        tasks = [
            line_service._get_user_data_for_parallel("U_test123"),
            # RAGのモック
            asyncio.sleep(0.1, result={"answer": "RAG回答"}),
        ]

        user_data, rag_result = await asyncio.gather(*tasks)

        # ユーザーデータが正しく取得されている
        assert user_data["status"] == "success"
        assert user_data["plan"] == "free"

        # その後、回数制限チェック
        usage_result = await line_service._check_and_increment_usage(
            user_data["user_id"],
            user_data["plan"]
        )

        # 回数制限チェックが成功
        assert usage_result["success"] is True

        # フロー全体が成功
        assert "RAG回答" == rag_result
