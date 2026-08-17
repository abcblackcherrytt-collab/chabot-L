"""
プランと価格設定モジュール

サブスクリプションプランとStripe価格IDのマッピングを管理します。
"""

import os
from typing import Dict, Any

from app.core.config import settings


# 1日あたりのメッセージ上限。回数制御の唯一の基準値として使用します。
DAILY_MESSAGE_LIMITS: Dict[str, int] = {
    "free": 3,
    "basic": 100,
    "pro": 500,
}


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
        "monthly_limit": DAILY_MESSAGE_LIMITS["basic"],  # API互換用。実際の単位は1日
        "corpus_id": None,  # 設定から取得
        "stripe_plan_id": "basic",
    },
    "pro": {
        "name": "プロプラン",
        "price_id": os.getenv("STRIPE_PRO_PRICE_ID"),
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


def get_plan_from_price_id(price_id: str) -> str:
    """
    Stripe価格IDからプラン名を取得

    Args:
        price_id: Stripe価格ID

    Returns:
        プラン名（free, basic, pro）

    Raises:
        ValueError: 不正な価格IDの場合
    """
    for plan_name, plan_config in PLANS.items():
        if plan_config["price_id"] == price_id:
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
