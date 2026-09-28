"""クーポンコードと引き換えサービスのテスト。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import firestore_usage_repository as usage_module
from app.services import coupon_service as service_module
from app.services.coupon_service import (
    CouponService,
    coupon_code_sha256,
    generate_coupon_code,
    has_valid_coupon_checksum,
    match_coupon_message,
    normalize_coupon_code,
)


class TestCouponCode:
    """コード形式のテスト。"""

    def test_generated_code_passes_checksum(self) -> None:
        """生成コードがチェックディジットを満たすこと。"""
        code = generate_coupon_code()

        assert len(code) == 10
        assert has_valid_coupon_checksum(code)

    def test_normalize_translates_ambiguous_chars(self) -> None:
        """O/I/LをCrockford表記へ正規化すること。"""
        assert normalize_coupon_code("oIL-1") == "0111"

    def test_checksum_detects_tampering(self) -> None:
        """改ざんコードを検出すること。"""
        code = generate_coupon_code()
        tampered = code[:-1] + ("0" if code[-1] != "0" else "1")

        assert not has_valid_coupon_checksum(tampered)

    def test_match_coupon_message(self) -> None:
        """「クーポン CODE」形式だけを対象にすること。"""
        assert match_coupon_message("クーポン ABC123XYZ0") == "ABC123XYZ0"
        assert match_coupon_message("クーポンについて教えて") is None
        assert match_coupon_message("ただの質問です") is None


class TestCouponRedeem:
    """引き換え処理のテスト。"""

    @pytest.fixture
    def coupon_service(self, monkeypatch) -> CouponService:
        """リポジトリをモックしたサービスを返す。"""
        repository = MagicMock()
        repository.redeem = AsyncMock(
            return_value={
                "status": "granted",
                "kind": "plan_grant",
                "plan": "basic",
                "duration_days": 14,
                "bonus_free_messages": None,
            }
        )
        usage_repo = MagicMock()
        usage_repo.count_coupon_attempt = AsyncMock(return_value=1)
        monkeypatch.setattr(
            usage_module,
            "FirestoreUsageRepository",
            lambda: usage_repo,
        )
        return CouponService(coupon_repository=repository)

    @pytest.mark.asyncio
    async def test_redeem_grants_plan(self, coupon_service) -> None:
        """有効コードの引き換えで付与結果を返すこと。"""
        code = generate_coupon_code()

        result = await coupon_service.redeem(raw_code=code, user_id="u1")

        assert result["status"] == "granted"
        assert "ベーシック" in result["message"]
        expected_hash = coupon_code_sha256(code)
        coupon_service.coupon_repository.redeem.assert_awaited_once_with(
            code_sha256=expected_hash,
            user_id="u1",
        )

    @pytest.mark.asyncio
    async def test_redeem_rejects_invalid_code_before_repo(self, coupon_service) -> None:
        """チェックディジット不正のコードをリポジトリ前に拒否すること。"""
        result = await coupon_service.redeem(raw_code="ABC", user_id="u1")

        assert result["status"] == "invalid_code"
        coupon_service.coupon_repository.redeem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redeem_applies_rate_limit(self, monkeypatch) -> None:
        """1日10回を超える試行を拒否すること。"""
        repository = MagicMock()
        repository.redeem = AsyncMock()
        usage_repo = MagicMock()
        usage_repo.count_coupon_attempt = AsyncMock(return_value=11)
        monkeypatch.setattr(
            usage_module,
            "FirestoreUsageRepository",
            lambda: usage_repo,
        )
        service = CouponService(coupon_repository=repository)

        result = await service.redeem(raw_code=generate_coupon_code(), user_id="u1")

        assert result["status"] == "rate_limited"
        repository.redeem.assert_not_awaited()


class TestCouponIssue:
    """発行バリデーションのテスト。"""

    @pytest.fixture
    def coupon_service(self) -> CouponService:
        """リポジトリをモックしたサービスを返す。"""
        repository = MagicMock()
        repository.create = AsyncMock(
            return_value={"id": "cpn-1", "kind": "plan_grant"}
        )
        return CouponService(coupon_repository=repository)

    @pytest.mark.asyncio
    async def test_issue_plan_grant(self, coupon_service) -> None:
        """プラン付与クーポンを発行できること。"""
        result = await coupon_service.issue(
            kind="plan_grant",
            plan="pro",
            duration_days=7,
            bonus_free_messages=None,
            max_redemptions=5,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            created_by="admin",
        )

        assert result["code"]
        assert has_valid_coupon_checksum(result["code"])
        stored = coupon_service.coupon_repository.create.await_args.kwargs
        assert stored["code_sha256"] == coupon_code_sha256(result["code"])
        assert stored["plan"] == "pro"

    @pytest.mark.asyncio
    async def test_issue_rejects_invalid_plan(self, coupon_service) -> None:
        """free指定のプラン付与を拒否すること。"""
        with pytest.raises(ValueError, match="invalid_plan"):
            await coupon_service.issue(
                kind="plan_grant",
                plan="free",
                duration_days=7,
                bonus_free_messages=None,
                max_redemptions=5,
                expires_at=None,
                created_by="admin",
            )
