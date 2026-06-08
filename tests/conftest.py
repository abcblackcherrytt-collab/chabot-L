"""
Test configuration and fixtures
テスト用のフィクスチャと設定を管理します。
"""

import asyncio
import os
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.server import app


# テスト用データベースURL
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:"
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    イベントループフィクスチャ
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    テスト用データベースエンジンフィクスチャ
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=pool.StaticPool,
        connect_args={"check_same_thread": False} if "sqlite" in TEST_DATABASE_URL else {},
        echo=False,
    )

    # テーブルを作成
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # テーブルを削除
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    test_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    テスト用データベースセッションフィクスチャ
    """
    async_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session

        # テスト後にロールバック
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    テスト用HTTPクライアントフィクスチャ
    """
    from httpx import ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_user_data():
    """
    サンプルユーザーデータフィクスチャ
    """
    return {
        "email": "test@example.com",
        "username": "testuser",
        "password": "TestPassword123!",
    }


@pytest.fixture
def sample_login_data():
    """
    サンプルログインデータフィクスチャ
    """
    return {
        "email": "test@example.com",
        "password": "TestPassword123!",
    }


@pytest.fixture
def mock_vertex_ai_response():
    """
    Vertex AI RAGレスポンスのモックフィクスチャ
    """
    return {
        "answer": "This is a test answer from RAG.",
        "contexts": [
            {"content": "This is test context 1.", "source": "doc1.pdf"},
            {"content": "This is test context 2.", "source": "doc2.pdf"},
        ],
        "confidence": 0.85,
        "denied": False,
    }


@pytest.fixture
def mock_vertex_ai_denied_response():
    """
    Vertex AI拒否レスポンスのモックフィクスチャ
    """
    return {
        "denied": True,
        "reason": "The request contains sensitive information.",
        "message": "I'm sorry, I cannot answer this request.",
    }


@pytest.fixture
def mock_stripe_customer():
    """
    Stripe顧客のモックフィクスチャ
    """
    class MockCustomer:
        id = "cus_test123"
        email = "test@example.com"
        name = "Test User"
        created = 1234567890

    return MockCustomer()


@pytest.fixture
def mock_stripe_subscription():
    """
    Stripeサブスクリプションのモックフィクスチャ
    """
    class MockPaymentIntent:
        id = "pi_test123"

    class MockInvoice:
        id = "in_test123"
        amount = 1000
        currency = "jpy"
        status = "paid"
        payment_intent = MockPaymentIntent()

    class MockPrice:
        id = "price_test123"

    class MockSubscriptionItem:
        price = MockPrice()

    class MockSubscription:
        id = "sub_test123"
        customer = "cus_test123"
        status = "active"
        items = type('obj', (object,), {'data': [MockSubscriptionItem()]})()
        current_period_start = 1234567890
        current_period_end = 1234567890 + 2592000  # 30日後
        cancel_at_period_end = False
        created = 1234567890
        updated_at = 1234567890
        latest_invoice = MockInvoice()

    return MockSubscription()


@pytest.fixture
def mock_discode_channel():
    """
    Discodeチャンネルのモックフィクスチャ
    """
    return {
        "id": "ch_test123",
        "name": "test-channel",
        "description": "Test channel description",
        "owner_id": "user123",
        "created_at": 1234567890,
    }


@pytest.fixture
def mock_discode_message():
    """
    Discodeメッセージのモックフィクスチャ
    """
    return {
        "id": "msg_test123",
        "channel_id": "ch_test123",
        "user_id": "user123",
        "text": "This is a test message.",
        "created_at": 1234567890,
    }
