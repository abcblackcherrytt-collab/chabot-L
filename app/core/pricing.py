"""
プランと価格設定モジュール

サブスクリプションプランとStripe価格IDのマッピングを管理します。
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings


# 1日あたりのメッセージ上限。回数制御の唯一の基準値として使用します。
DAILY_MESSAGE_LIMITS: Dict[str, int] = {
    "free": 3,
    "basic": 100,
    "pro": 500,
}


def _parse_price_ids(raw: Optional[str]) -> List[str]:
    """カンマ区切りのPrice ID環境変数をパースする。

    値上げ時に旧Priceで契約中の既存利用者（グランドファザーリング）の
    プラン判定のためだけに使われる。空・未設定なら空リスト。
    """
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# プラン定義
PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "name": "フリープラン",
        "price_id": None,  # freeプランは価格IDなし
        "monthly_limit": DAILY_MESSAGE_LIMITS["free"],  # API互換用。実際の単位は1日
        "corpus_id": None,  # 設定から取得
        "stripe_plan_id": None,
    },
    "basic": {
        "name": "ベーシックプラン",
        "price_id": os.getenv("STRIPE_BASIC_PRICE_ID"),
        "legacy_price_ids": _parse_price_ids(os.getenv("STRIPE_BASIC_LEGACY_PRICE_IDS")),
        "monthly_limit": DAILY_MESSAGE_LIMITS["basic"],  # API互換用。実際の単位は1日
        "corpus_id": None,  # 設定から取得
        "stripe_plan_id": "basic",
    },
    "pro": {
        "name": "プロプラン",
        "price_id": os.getenv("STRIPE_PRO_PRICE_ID"),
        "legacy_price_ids": _parse_price_ids(os.getenv("STRIPE_PRO_LEGACY_PRICE_IDS")),
        "monthly_limit": DAILY_MESSAGE_LIMITS["pro"],  # API互換用。実際の単位は1日
        "corpus_id": None,  # 設定から取得
        "stripe_plan_id": "pro",
    },
}


def get_daily_message_limit(plan: str) -> int:
    """プランの1日あたりのメッセージ上限を返します。"""
    if plan not in DAILY_MESSAGE_LIMITS:
        raise ValueError(
            f"Invalid plan: {plan}. Must be one of: {list(DAILY_MESSAGE_LIMITS.keys())}"
        )
    return DAILY_MESSAGE_LIMITS[plan]


def get_plan_config(plan: str) -> Dict[str, Any]:
    """
    プラン設定を取得

    Args:
        plan: プラン名（free, basic, pro）

    Returns:
        プラン設定辞書

    Raises:
        ValueError: 不正なプラン名の場合
    """
    if plan not in PLANS:
        raise ValueError(f"Invalid plan: {plan}. Must be one of: {list(PLANS.keys())}")

    plan_config = PLANS[plan].copy()

    # コーパスIDを設定から取得（既存設定活用）
    if plan == "free":
        plan_config["corpus_id"] = settings.google_corpus_id
    else:  # basic, pro
        plan_config["corpus_id"] = settings.google_corpus_id_plan1

    return plan_config


def resolve_effective_plan(user: Dict[str, Any]) -> str:
    """ユーザー文書から実効プランを解決する。

    優先度は 管理者指定のplan_override（source=admin）>
    Stripe契約（subscription_plan の basic/pro）> free。
    coupon / service_invite 由来のoverrideは従来どおり契約プランがfreeのときのみ
    適用し、有料契約を自動的にdowngradeしない。
    serviceはpro相当（同一コーパス・日次上限）として解決する。

    Args:
        user: ユーザードキュメントの辞書

    Returns:
        実効プラン名（free, basic, pro）
    """
    plan = user.get("subscription_plan") or "free"
    override = user.get("plan_override")
    if not isinstance(override, dict):
        return plan
    override_plan = override.get("plan")
    if override_plan not in ("basic", "pro", "service"):
        return plan
    expires_at = override.get("expires_at")
    if isinstance(expires_at, str):
        try:
            still_valid = datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
        except ValueError:
            still_valid = False
    else:
        still_valid = expires_at is None
    if not still_valid:
        return plan
    resolved = "pro" if override_plan == "service" else override_plan
    if override.get("source") == "admin":
        return resolved
    if plan not in ("basic", "pro"):
        return resolved
    return plan


def get_plan_from_price_id(price_id: str) -> str:
    """
    Stripe価格IDからプラン名を取得

    現行のPrice IDに加え、legacy_price_ids（値上げ前の旧Price）も判定対象に含む。
    Checkout新規作成は引き続き現行price_idのみを使用し、旧Priceでの新規契約は不可。

    Args:
        price_id: Stripe価格ID

    Returns:
        プラン名（free, basic, pro）

    Raises:
        ValueError: 不正な価格IDの場合
    """
    for plan_name, plan_config in PLANS.items():
        known_ids = [plan_config.get("price_id"), *(plan_config.get("legacy_price_ids") or [])]
        if price_id in known_ids:
            return plan_name

    # マッチしない場合はエラー
    raise ValueError(f"No plan found for price_id: {price_id}")


def validate_plan_availability(plan: str) -> bool:
    """
    プランが利用可能か検証

    Args:
        plan: プラン名

    Returns:
        利用可能ならTrue
    """
    if plan not in PLANS:
        return False

    # 有料プランは価格ID設定が必要
    if plan != "free" and not PLANS[plan]["price_id"]:
        return False

    return True


def get_checkout_urls() -> Dict[str, str]:
    """
    Checkout用URL設定を取得

    Returns:
        success_urlとcancel_urlの辞書
    """
    base_url = os.getenv(
        "STRIPE_CHECKOUT_BASE_URL",
        "https://your-app.com"
    )

    return {
        "success_url": os.getenv(
            "STRIPE_CHECKOUT_SUCCESS_URL",
            f"{base_url}/subscription/success"
        ),
        "cancel_url": os.getenv(
            "STRIPE_CHECKOUT_CANCEL_URL",
            f"{base_url}/subscription/cancel"
        ),
    }
