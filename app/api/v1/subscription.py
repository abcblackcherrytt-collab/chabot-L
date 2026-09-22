"""
サブスクリプション管理エンドポイント

Stripe Checkoutとサブスクリプション管理のAPIエンドポイントを提供します。
"""

import logging
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.core.auth_cookies import (
    REFRESH_TOKEN_COOKIE_NAME,
    set_refresh_token_cookie,
)
from app.core.config import settings
from app.core.pricing import PLANS, get_plan_config, validate_plan_availability
from app.core.security import decode_token
from app.clients.stripe import StripeError
from app.services.firestore_auth_service import FirestoreAuthService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscription", tags=["subscription"])


# 選択画面に表示するプラン情報。金額はStripe側のPrice設定と合わせて運用する。
PLAN_SELECTION_CSS = """
  :root { color-scheme: light; font-family: -apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: #f5f7fb; color: #172033; }
  main { width: min(100% - 32px, 720px); margin: 0 auto; padding: 40px 0 32px; }
  .eyebrow { margin: 0 0 10px; color: #4967c5; font-size: .78rem; font-weight: 700; letter-spacing: .14em; }
  h1 { margin: 0; font-size: clamp(1.8rem, 7vw, 2.5rem); letter-spacing: -.04em; }
  .lead { margin: 14px 0 28px; color: #5d6880; line-height: 1.7; }
  .plans { display: grid; gap: 14px; }
  .plan { position: relative; display: block; padding: 22px; border: 1px solid #dce2ef; border-radius: 18px; background: #fff; color: inherit; text-decoration: none; box-shadow: 0 8px 24px rgba(32,48,88,.06); transition: transform .15s, box-shadow .15s; }
  .plan:hover { transform: translateY(-2px); box-shadow: 0 12px 30px rgba(32,48,88,.13); }
  .plan:focus-visible { outline: 3px solid #172033; outline-offset: 3px; box-shadow: 0 12px 30px rgba(32,48,88,.13); }
  .plan.pro { border: 2px solid #536bd0; padding: 21px; }
  .badge { position: absolute; top: -12px; right: 18px; padding: 5px 10px; border-radius: 99px; background: #536bd0; color: #fff; font-size: .72rem; font-weight: 700; }
  .plan-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  h2 { margin: 0; font-size: 1.2rem; }
  .price { margin: 14px 0 4px; font-size: 1.65rem; font-weight: 800; letter-spacing: -.04em; }
  .price small { color: #68738a; font-size: .78rem; font-weight: 500; letter-spacing: 0; }
  .limit { margin: 0; color: #536bd0; font-size: .9rem; font-weight: 700; }
  ul { display: grid; gap: 8px; margin: 18px 0 0; padding: 0; list-style: none; color: #59647b; font-size: .88rem; line-height: 1.45; }
  li::before { content: '✓'; margin-right: 8px; color: #536bd0; font-weight: 800; }
  .arrow { float: right; color: #536bd0; font-size: 1.4rem; }
  .note { margin: 24px 2px 0; color: #778197; font-size: .78rem; line-height: 1.7; }
  .note strong { color: #59647b; }
  @media (prefers-reduced-motion: reduce) { .plan { transition: none; } .plan:hover { transform: none; } }
  @media (min-width: 620px) { .plans { grid-template-columns: 1fr 1fr; } }
"""


PLAN_SELECTION_PAGE = """<!doctype html>
<html lang='ja'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>プランを選択 | Chabot</title>
<link rel='stylesheet' href='/api/v1/subscription/select.css'>
</head>
<body><main>
  <p class='eyebrow'>CHABOT SUBSCRIPTION</p>
  <h1>あなたに合うプランを選ぶ</h1>
  <p class='lead'>専門的な回答を、必要な量に合わせて。登録後はStripeの安全な決済ページへ進みます。</p>
  <section class='plans' aria-label='プラン一覧'>
    <a class='plan' href='/api/v1/subscription/checkout/basic'>
      <div class='plan-head'><h2>ベーシックプラン</h2><span class='arrow' aria-hidden='true'>→</span></div>
      <p class='price'>499円 <small>/ 月（税込）</small></p>
      <p class='limit'>1日 100問まで</p>
      <ul><li>有料コーパスによる詳しい回答</li><li>日々の学習・業務におすすめ</li></ul>
    </a>
    <a class='plan pro' href='/api/v1/subscription/checkout/pro'>
      <span class='badge'>たくさん使う方へ</span>
      <div class='plan-head'><h2>プロプラン</h2><span class='arrow' aria-hidden='true'>→</span></div>
      <p class='price'>999円 <small>/ 月（税込）</small></p>
      <p class='limit'>1日 500問まで</p>
      <ul><li>有料コーパスによる詳しい回答</li><li>質問数が多い方におすすめ</li></ul>
    </a>
  </section>
  <p class='note'><strong>お申し込みについて</strong><br>ボタンを押すとLINEログイン後、Stripeの決済ページへ移動します。プランの変更・解約はいつでも行えます。</p>
</main></body></html>"""


# ========== 依存性注入 ==========

def get_subscription_service() -> SubscriptionService:
    """サブスクリプションサービスの依存性"""
    return SubscriptionService()


# ========== Pydanticスキーマ ==========

class CheckoutRequest(BaseModel):
    """Checkoutセッション作成リクエスト"""

    plan: str = Field(..., description="プラン名（basic, pro）")


class CheckoutResponse(BaseModel):
    """Checkoutセッション作成レスポンス"""

    checkout_url: str = Field(..., description="Stripe Checkout URL")
    plan: str = Field(..., description="プラン名")


class SubscriptionStatusResponse(BaseModel):
    """サブスクリプションステータスレスポンス"""

    status: str = Field(..., description="サブスクリプションステータス")
    plan: str | None = Field(None, description="プラン名")
    subscription_id: str | None = Field(None, description="StripeサブスクリプションID")
    current_period_end: int | str | None = Field(None, description="現在の期間終了日")
    monthly_limit: int | None = Field(None, description="月次メッセージ制限")


class PlanInfoResponse(BaseModel):
    """プラン情報レスポンス"""

    plans: dict = Field(..., description="利用可能なプラン情報")


# ========== エンドポイント ==========


def _checkout_login_url(plan: str) -> str:
    """Checkoutへ戻る相対URLを付けたLINE Login URLを返す。"""
    return_to = f"/api/{settings.api_version}/subscription/checkout/{plan}"
    query = urllib.parse.urlencode({"return_to": return_to})
    return f"/api/{settings.api_version}/auth/line?{query}"


async def _authenticated_user(request: Request) -> tuple[str, str]:
    """Refresh Cookieをローテーションし、認証ユーザーIDと新Tokenを返す。"""
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LINE Login is required",
        )

    tokens = await FirestoreAuthService().refresh(refresh_token)
    access_payload = decode_token(tokens["access_token"]) if tokens else None
    user_id = access_payload.get("sub") if access_payload else None
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="LINE Login session is invalid or expired",
        )
    return user_id, tokens["refresh_token"]


def _validate_checkout_url(checkout_url: str) -> None:
    """Stripe公式Checkoutホスト以外へのリダイレクトを拒否する。"""
    parsed_checkout_url = urllib.parse.urlparse(checkout_url)
    if (
        parsed_checkout_url.scheme != "https"
        or parsed_checkout_url.hostname != "checkout.stripe.com"
    ):
        logger.error("Rejected unexpected Checkout URL host")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid checkout destination",
        )


@router.get("/checkout/{plan}", response_model=None)
async def redirect_to_checkout(
    plan: str,
    request: Request,
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> RedirectResponse | HTMLResponse:
    """LINEの登録リンクから認証済みStripe Checkoutへリダイレクトする。"""
    if plan not in {"basic", "pro"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown subscription plan",
        )

    plan_config = get_plan_config(plan)
    if not plan_config.get("price_id"):
        return HTMLResponse(
            content=(
                "<!doctype html><html lang='ja'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>決済準備中</title>"
                "<body style='font-family:sans-serif;max-width:36rem;margin:4rem auto;padding:1rem'>"
                "<h1>決済ページを準備中です</h1>"
                "<p>プラン登録の受付開始まで、もうしばらくお待ちください。</p>"
                "</body></html>"
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Cache-Control": "no-store"},
        )

    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        return RedirectResponse(url=_checkout_login_url(plan), status_code=303)

    tokens = await FirestoreAuthService().refresh(refresh_token)
    if not tokens:
        return RedirectResponse(url=_checkout_login_url(plan), status_code=303)

    access_payload = decode_token(tokens["access_token"])
    user_id = access_payload.get("sub") if access_payload else None
    if not user_id:
        return RedirectResponse(url=_checkout_login_url(plan), status_code=303)

    try:
        checkout_url = await subscription_service.create_checkout_session(
            user_id=user_id,
            plan=plan,
        )
    except (ValueError, StripeError) as exc:
        logger.warning(
            "Checkout could not start for plan=%s: error_type=%s",
            plan,
            type(exc).__name__,
        )
        return HTMLResponse(
            content="決済ページを準備中です。しばらくしてからもう一度お試しください。",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Cache-Control": "no-store"},
        )

    _validate_checkout_url(checkout_url)

    response = RedirectResponse(url=checkout_url, status_code=303)
    set_refresh_token_cookie(response, tokens["refresh_token"])
    return response


@router.get("/select", response_class=HTMLResponse)
async def select_plan() -> HTMLResponse:
    """リッチメニューから遷移する、basic/proのプラン選択画面を表示する。"""
    return HTMLResponse(
        content=PLAN_SELECTION_PAGE,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/select.css")
async def plan_selection_stylesheet() -> Response:
    """CSP準拠でプラン選択画面のスタイルを同一オリジン配信する。"""
    return Response(
        content=PLAN_SELECTION_CSS,
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/success", response_class=HTMLResponse)
async def checkout_success() -> HTMLResponse:
    """Stripe Checkout完了後の案内を表示する。"""
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>登録完了</title><body style='font-family:sans-serif;max-width:36rem;"
        "margin:4rem auto;padding:1rem'><h1>プラン登録を受け付けました</h1>"
        "<p>LINEに戻って、そのままChabotをご利用ください。</p></body></html>"
    )


@router.get("/cancel", response_class=HTMLResponse)
async def checkout_cancel() -> HTMLResponse:
    """Stripe Checkoutキャンセル後の案内を表示する。"""
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>登録キャンセル</title><body style='font-family:sans-serif;max-width:36rem;"
        "margin:4rem auto;padding:1rem'><h1>プラン登録をキャンセルしました</h1>"
        "<p>決済は行われていません。LINEへ戻ってください。</p></body></html>"
    )

@router.post("/checkout/create", response_model=CheckoutResponse)
async def create_checkout_session(
    payload: CheckoutRequest,
    request: Request,
    response: Response,
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> CheckoutResponse:
    """
    Stripe Checkoutセッションを作成

    認証済みユーザーが指定プランのサブスクリプション登録を行うための
    Checkout URLを生成します。

    Args:
        request: Checkoutリクエスト（プラン名）
        subscription_service: サブスクリプションサービス

    Returns:
        Checkoutレスポンス（Checkout URL）

    Raises:
        HTTPException: バリデーションエラー、Stripeエラーの場合
    """
    try:
        user_id, rotated_refresh_token = await _authenticated_user(request)
        plan = payload.plan

        # プランバリデーション
        if not validate_plan_availability(plan):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid or unavailable plan: {plan}"
            )

        # Checkoutセッション作成
        checkout_url = await subscription_service.create_checkout_session(
            user_id=user_id,
            plan=plan,
        )
        _validate_checkout_url(checkout_url)
        set_refresh_token_cookie(response, rotated_refresh_token)

        logger.info(f"Created checkout session for plan {plan}")

        return CheckoutResponse(
            checkout_url=checkout_url,
            plan=plan,
        )

    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid checkout request",
        )
    except Exception as exc:
        logger.error(
            "Error creating checkout session: error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Checkout session creation failed",
        )


@router.get("/plans", response_model=PlanInfoResponse)
async def get_available_plans() -> PlanInfoResponse:
    """
    利用可能なプラン情報を取得

    Returns:
        プラン情報レスポンス
    """
    try:
        plans_info = {}

        for plan_name in ["free", "basic", "pro"]:
            try:
                plan_config = get_plan_config(plan_name)
                plans_info[plan_name] = {
                    "name": plan_config["name"],
                    "monthly_limit": plan_config["monthly_limit"],
                    "available": validate_plan_availability(plan_name),
                }
            except ValueError:
                plans_info[plan_name] = {
                    "name": "Unknown",
                    "monthly_limit": 0,
                    "available": False,
                }

        return PlanInfoResponse(plans=plans_info)

    except Exception as exc:
        logger.error(
            "Error getting plan info: error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get plan information",
        )


@router.get("/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    request: Request,
    response: Response,
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> SubscriptionStatusResponse:
    """
    ユーザーのサブスクリプションステータスを取得

    Returns:
        サブスクリプションステータスレスポンス

    Raises:
        HTTPException: ステータス取得エラーの場合
    """
    try:
        user_id, rotated_refresh_token = await _authenticated_user(request)

        # サブスクリプションステータス取得
        status_data = await subscription_service.get_user_subscription_status(
            user_id
        )

        logger.info(f"Retrieved subscription status: {status_data.get('status')}")
        set_refresh_token_cookie(response, rotated_refresh_token)

        return SubscriptionStatusResponse(**status_data)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Error getting subscription status: error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get subscription status",
        )
