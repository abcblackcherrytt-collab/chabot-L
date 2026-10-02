"""管理コンソールAPIルーター（/api/v1/admin/*）。

このルーターは管理専用アプリ（app.admin_server）にだけ登録する。
公開Bot（app.server）へ混入しないことをroute分離テストで固定する。
書込みは管理者セッション・CSRFトークン・Origin検証で保護する。
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_security import (
    ADMIN_CSRF_COOKIE,
    ADMIN_SESSION_COOKIE,
    AdminAuthError,
    create_admin_session_token,
    extract_admin_identity,
    is_admin_allowed,
    issue_csrf_token,
    verify_admin_session_token,
    verify_csrf,
)
from app.core.config import settings
from app.services.admin_service import AdminService

logger = logging.getLogger(__name__)


router = APIRouter(prefix=f"/api/{settings.api_version}/admin", tags=["管理API"])


class AdminSessionResponse(BaseModel):
    """管理セッション確立レスポンス。"""

    email: str
    csrf_token: str


class DevLoginRequest(BaseModel):
    """ローカル開発用ログインリクエスト。"""

    email: str = Field(min_length=3, max_length=254)


class PlanDraftRequest(BaseModel):
    """プラン下書き保存リクエスト。"""

    daily_message_limit: int = Field(ge=1, le=999)
    base_revision: int = Field(ge=0)


class PlanPublishRequest(BaseModel):
    """プラン反映リクエスト。"""

    revision: int = Field(ge=0)


class CouponIssueRequest(BaseModel):
    """クーポン発行リクエスト。"""

    kind: str
    plan: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=1, le=365)
    bonus_free_messages: Optional[int] = Field(default=None, ge=1, le=100)
    max_redemptions: int = Field(default=1, ge=1, le=10000)
    expires_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=200)


class InviteIssueRequest(BaseModel):
    """登録URL発行リクエスト。"""

    ttl_hours: Optional[int] = Field(default=None, ge=1, le=720)
    invite_type: str = Field(default="free", pattern="^(free|service)$")


class UserPlanRequest(BaseModel):
    """プラン変更リクエスト。"""

    plan: str = Field(pattern="^(free|basic|pro|service)$")


class UserDeactivateRequest(BaseModel):
    """ユーザー無効化リクエスト。"""

    reason: str = Field(min_length=1, max_length=200)


class FreeUserRequest(BaseModel):
    """LINE user ID直指定のfree作成リクエスト。"""

    line_user_id: str = Field(min_length=10, max_length=64)


class FeedbackStatusRequest(BaseModel):
    """要望ステータス更新リクエスト。"""

    status: str
    admin_note: Optional[str] = Field(default=None, max_length=500)


class RepresentativeAnswerRequest(BaseModel):
    """代表回答保存リクエスト。"""

    representative_answer: str = Field(min_length=1, max_length=4000)


def _admin_service() -> AdminService:
    """管理サービスを生成する。"""
    return AdminService()


async def _require_admin_session(request: Request) -> Dict[str, Any]:
    """管理セッションCookieを検証し、allowlistを再確認する。"""
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    payload = verify_admin_session_token(token) if token else None
    if payload is None:
        raise HTTPException(status_code=401, detail="Admin session required")
    email = str(payload.get("sub", ""))
    if not await is_admin_allowed(email):
        raise HTTPException(status_code=403, detail="Admin not allowed")
    return payload


async def _require_admin_write(request: Request) -> Dict[str, Any]:
    """書込み要求にセッション・CSRF・Origin検証を課す。"""
    payload = await _require_admin_session(request)
    try:
        verify_csrf(request, payload)
    except AdminAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return payload


def _set_session_cookies(response: Response, *, email: str, csrf_token: str) -> None:
    """管理セッションCookieとCSRF Cookieを設定する。"""
    # run_iamモードはlocalhostの管理プロキシ経由を想定するためSecure属性を付けない。
    # それ以外の本番モード（IAP）はSecureを付ける。
    cookie_secure = not settings.debug and settings.admin_auth_mode != "run_iam"
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_admin_session_token(email=email, csrf_token=csrf_token),
        max_age=settings.admin_session_ttl_seconds,
        path="/",
        httponly=True,
        secure=cookie_secure,
        samesite="strict",
    )
    response.set_cookie(
        key=ADMIN_CSRF_COOKIE,
        value=csrf_token,
        max_age=settings.admin_session_ttl_seconds,
        path="/",
        httponly=False,
        secure=cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/session", response_model=AdminSessionResponse)
async def establish_session(request: Request) -> JSONResponse:
    """IAP等で認証済みの管理者にセッションを発行する。"""
    try:
        email = await extract_admin_identity(request)
    except AdminAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"reason": str(exc), "mode": settings.admin_auth_mode},
        ) from exc
    if not await is_admin_allowed(email):
        raise HTTPException(status_code=403, detail="Admin not allowed")
    csrf_token = issue_csrf_token()
    response = JSONResponse(
        content=AdminSessionResponse(email=email, csrf_token=csrf_token).model_dump()
    )
    _set_session_cookies(response, email=email, csrf_token=csrf_token)
    return response


@router.post("/dev-login", response_model=AdminSessionResponse)
async def dev_login(request_data: DevLoginRequest, request: Request) -> JSONResponse:
    """devモード（debug=True限定）で開発用ログインを確立する。"""
    if settings.admin_auth_mode != "dev" or not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    allowed = [item.strip() for item in settings.admin_dev_emails.split(",") if item.strip()]
    if request_data.email not in allowed:
        raise HTTPException(status_code=403, detail="Dev email not allowed")
    if not await is_admin_allowed(request_data.email):
        raise HTTPException(status_code=403, detail="Admin not allowed")
    csrf_token = issue_csrf_token()
    response = JSONResponse(
        content=AdminSessionResponse(
            email=request_data.email, csrf_token=csrf_token
        ).model_dump()
    )
    _set_session_cookies(response, email=request_data.email, csrf_token=csrf_token)
    return response


@router.get("/users")
async def list_users(
    q: Optional[str] = None,
    plan: Optional[str] = None,
    status_filter: Optional[str] = None,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """ユーザー一覧（非PII要約）を返す。"""
    return await _admin_service().list_users(q=q, plan=plan, status=status_filter)


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """ユーザー詳細（PII含む・監査記録付き）を返す。"""
    detail = await _admin_service().get_user_detail(
        user_id=user_id,
        actor=session["sub"],
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    return detail


@router.post("/users/{user_id}/plan", status_code=204)
async def change_user_plan(
    user_id: str,
    request_data: UserPlanRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Response:
    """プラン変更（plan_override）を行う。"""
    await _run_service(
        _admin_service().change_user_plan,
        user_id=user_id,
        plan=request_data.plan,
        actor=session["sub"],
    )
    return Response(status_code=204)


@router.post("/users/{user_id}/deactivate", status_code=204)
async def deactivate_user(
    user_id: str,
    request_data: UserDeactivateRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Response:
    """ユーザーを無効化する。"""
    await _run_service(
        _admin_service().deactivate_user,
        user_id=user_id,
        reason=request_data.reason,
        actor=session["sub"],
    )
    return Response(status_code=204)


@router.post("/users/free")
async def create_free_user(
    request_data: FreeUserRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """LINE user ID直指定でfreeユーザーを作成する。"""
    return await _run_service(
        _admin_service().create_free_user,
        line_user_id=request_data.line_user_id,
        actor=session["sub"],
    )


@router.get("/plan-settings")
async def get_plan_settings(
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """プラン別上限設定を返す。"""
    return {"items": await _admin_service().get_plan_settings()}


@router.put("/plan-settings/{plan}")
async def save_plan_draft(
    plan: str,
    request_data: PlanDraftRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """プラン下書きを保存する。"""
    return await _run_service(
        _admin_service().save_plan_draft,
        plan=plan,
        daily_message_limit=request_data.daily_message_limit,
        base_revision=request_data.base_revision,
        actor=session["sub"],
    )


@router.post("/plan-settings/{plan}/publish")
async def publish_plan(
    plan: str,
    request_data: PlanPublishRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """プラン下書きを反映する。"""
    return await _run_service(
        _admin_service().publish_plan,
        plan=plan,
        revision=request_data.revision,
        actor=session["sub"],
    )


@router.post("/plan-settings/{plan}/rollback")
async def rollback_plan(
    plan: str,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """プランを直前revisionへ戻す。"""
    return await _run_service(
        _admin_service().rollback_plan,
        plan=plan,
        actor=session["sub"],
    )


@router.post("/coupons")
async def issue_coupon(
    request_data: CouponIssueRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """クーポンを発行する。平文コードはこの応答にのみ載る。"""
    return await _run_service(
        _admin_service().issue_coupon,
        actor=session["sub"],
        kind=request_data.kind,
        plan=request_data.plan,
        duration_days=request_data.duration_days,
        bonus_free_messages=request_data.bonus_free_messages,
        max_redemptions=request_data.max_redemptions,
        expires_at=request_data.expires_at,
        note=request_data.note,
    )


@router.get("/coupons")
async def list_coupons(
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """クーポン一覧を返す。"""
    return {"items": await _admin_service().list_coupons()}


@router.post("/coupons/{coupon_id}/revoke", status_code=204)
async def revoke_coupon(
    coupon_id: str,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Response:
    """クーポンを失効する。"""
    result = await _run_service(
        _admin_service().revoke_coupon,
        coupon_id=coupon_id,
        actor=session["sub"],
    )
    if not result:
        raise HTTPException(status_code=404, detail="Coupon not revocable")
    return Response(status_code=204)


@router.post("/invites")
async def issue_invite(
    request_data: InviteIssueRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """無料登録URLを発行する。平文URLはこの応答にのみ載る。"""
    return await _run_service(
        _admin_service().issue_invite,
        actor=session["sub"],
        ttl_hours=request_data.ttl_hours,
        invite_type=request_data.invite_type,
    )


@router.get("/invites")
async def list_invites(
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """無料登録URL一覧を返す。"""
    return {"items": await _admin_service().list_invites()}


@router.post("/invites/{invite_id}/revoke", status_code=204)
async def revoke_invite(
    invite_id: str,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Response:
    """未使用の無料登録URLを失効する。"""
    result = await _run_service(
        _admin_service().revoke_invite,
        invite_id=invite_id,
        actor=session["sub"],
    )
    if not result:
        raise HTTPException(status_code=404, detail="Invite not revocable")
    return Response(status_code=204)


@router.get("/conversations")
async def list_conversations(
    limit: int = 100,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """会話メタデータ（本文なし）を返す。"""
    return await _admin_service().list_conversations(limit=min(limit, 500))


@router.get("/conversations/{conversation_id}/question")
async def get_conversation_question(
    conversation_id: str,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """会話から質問本文だけを抽出して返す（回答本文は返さない）。"""
    return await _run_service(
        _admin_service().get_conversation_question,
        conversation_id=conversation_id,
    )


@router.post("/conversations/{conversation_id}/representative-answer")
async def save_representative_answer(
    conversation_id: str,
    request_data: RepresentativeAnswerRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Dict[str, Any]:
    """会話の質問へ管理者の代表回答を保存する。"""
    return await _run_service(
        _admin_service().save_representative_answer,
        conversation_id=conversation_id,
        representative_answer=request_data.representative_answer,
        actor=session["sub"],
    )


@router.get("/representative-answers")
async def list_representative_answers(
    limit: int = 100,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """保存済み代表回答の一覧を返す。"""
    return await _run_service(
        _admin_service().list_representative_answers,
        limit=min(limit, 500),
    )


@router.get("/corpora")
async def list_corpora(
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """プラン別コーパス設定と実体メタデータを返す。"""
    return await _admin_service().list_corpora()


@router.get("/feedback")
async def list_feedback(
    status_filter: Optional[str] = None,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """要望一覧を返す。"""
    return {"items": await _admin_service().list_feedback(status=status_filter)}


@router.post("/feedback/{feedback_id}/status", status_code=204)
async def update_feedback_status(
    feedback_id: str,
    request_data: FeedbackStatusRequest,
    request: Request,
    session: Dict[str, Any] = Depends(_require_admin_write),
) -> Response:
    """要望の対応ステータスを更新する。"""
    result = await _run_service(
        _admin_service().update_feedback_status,
        feedback_id=feedback_id,
        status=request_data.status,
        admin_note=request_data.admin_note,
        actor=session["sub"],
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return Response(status_code=204)


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 100,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """監査ログ一覧を返す。"""
    return {"items": await _admin_service().list_audit_logs(limit=min(limit, 500))}


@router.get("/stats")
async def get_stats(
    days: int = 30,
    session: Dict[str, Any] = Depends(_require_admin_session),
) -> Dict[str, Any]:
    """日次統計の範囲集計を返す。"""
    return await _run_service(_admin_service().get_stats, days=days)


async def _run_service(coro_fn, *args: Any, **kwargs: Any) -> Any:
    """サービス例外をHTTPエラーへ変換して実行する。"""
    try:
        return await coro_fn(*args, **kwargs)
    except ValueError as exc:
        message = str(exc)
        if "revision" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
