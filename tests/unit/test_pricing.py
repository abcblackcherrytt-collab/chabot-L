"""pricingモジュールのPrice ID解決テスト。"""

import importlib
import os
from unittest.mock import patch

import pytest

from app.core import pricing


def _reload_with_env(**env):
    """環境変数を差し替えてpricingを再読み込みする。"""
    with patch.dict(os.environ, env, clear=False):
        return importlib.reload(pricing)


@pytest.fixture(autouse=True)
def restore_pricing():
    """テストごとにモジュール状態を元に戻す。"""
    yield
    importlib.reload(pricing)


def test_current_price_id_maps_to_plan():
    module = _reload_with_env(
        STRIPE_BASIC_PRICE_ID="price_new_basic",
        STRIPE_PRO_PRICE_ID="price_new_pro",
    )
    assert module.get_plan_from_price_id("price_new_basic") == "basic"
    assert module.get_plan_from_price_id("price_new_pro") == "pro"


def test_legacy_price_id_maps_to_plan():
    module = _reload_with_env(
        STRIPE_BASIC_PRICE_ID="price_new_basic",
        STRIPE_PRO_PRICE_ID="price_new_pro",
        STRIPE_BASIC_LEGACY_PRICE_IDS="price_old_basic, price_basic_v1",
        STRIPE_PRO_LEGACY_PRICE_IDS="price_old_pro",
    )
    assert module.get_plan_from_price_id("price_old_basic") == "basic"
    assert module.get_plan_from_price_id("price_basic_v1") == "basic"
    assert module.get_plan_from_price_id("price_old_pro") == "pro"


def test_unknown_price_id_raises():
    module = _reload_with_env(
        STRIPE_BASIC_PRICE_ID="price_new_basic",
        STRIPE_BASIC_LEGACY_PRICE_IDS="price_old_basic",
    )
    with pytest.raises(ValueError):
        module.get_plan_from_price_id("price_unknown")


def test_checkout_keeps_using_current_price_only():
    module = _reload_with_env(
        STRIPE_BASIC_PRICE_ID="price_new_basic",
        STRIPE_BASIC_LEGACY_PRICE_IDS="price_old_basic",
    )
    assert module.PLANS["basic"]["price_id"] == "price_new_basic"
