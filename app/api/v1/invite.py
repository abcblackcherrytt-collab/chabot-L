"""無料登録URL（管理発行の1回限り招待）の引き換え導線。

トークンはURL fragment（#t=...）で受け渡し、landingページから同一originの
POSTへ移した直後に履歴から消去する。消費条件は「1回のLINE Login成功」で、
Firestore Transactionで unused -> consumed を確定する。
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.core.auth_cookies import (
    REFRESH_TOKEN_COOKIE_NAME,
    set_refresh_token_cookie,
)
from app.core.config import settings
from app.core.security import decode_token
from app.repositories.firestore_admin_invite_repository import (
    FirestoreAdminInviteRepository,
)
from app.services.firestore_auth_service import FirestoreAuthService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/invite", tags=["無料登録URL"])

CLAIM_COOKIE_NAME = "chabot_invite_claim"
CLAIM_TTL_SECONDS = 600


def _sign(payload: bytes) -> str:
    """ペイロードへHMAC署名を付ける。"""
    key = settings.jwt_secret_keys_list[0].encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _create_claim_token(invite_id: str) -> str:
    """招待ID入りの短命クレームトークンを作成する。"""
    payload = json.dumps(
        {"invite_id": invite_id, "exp": int(time.time()) + CLAIM_TTL_SECONDS},
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return f"{body}.{_sign(payload)}"


def _verify_claim_token(token: str) -> Optional[str]:
    """クレームトークンを検証し、招待IDを返す。"""
    try:
        body, signature = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    invite_id = data.get("invite_id")
    return invite_id if isinstance(invite_id, str) and invite_id else None


INVITE_LANDING_PAGE = """<!doctype html>
<html lang='ja'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Chabot 無料登録</title>
<style>
body{font-family:sans-serif;max-width:36rem;margin:4rem auto;padding:1rem;line-height:1.7}
</style>
</head>
<body>
<h1>Chabot 無料登録</h1>
<p id='message'>登録URLを確認しています…</p>
<script src='/api/v1/invite/claim.js'></script>
</body>
</html>"""


INVITE_CLAIM_JS = """(function () {
  'use strict';
  var message = document.getElementById('message');
  function show(text) { message.textContent = text; }
  var matched = window.location.hash.match(/^#t=([A-Za-z0-9_-]+)$/);
  if (!matched) {
    show('このURLは正しくありません。管理者へお問い合わせください。');
    return;
  }
  window.fetch('/api/v1/invite/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: matched[1] })
  })
    .then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function (result) {
      if (!result.ok) {
        show('この登録URLは利用できないか、有効期限が切れています。');
        return;
      }
      window.history.replaceState(null, '', window.location.pathname);
      window.location.href = result.data.login_url;
    })
    .catch(function () {
      show('通信エラーが発生しました。もう一度開き直してください。');
    });
})();"""


class InviteSessionRequest(BaseModel):
    """クレーム開始リクエスト。"""

    token: str = Field(min_length=10, max_length=128)


@router.get("", response_class=HTMLResponse)
async def invite_landing() -> HTMLResponse:
    """トークンfragmentを受け取るlandingページを返す。"""
    return HTMLResponse(
        content=INVITE_LANDING_PAGE,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/claim.js")
async def invite_claim_script() -> Response:
    """CSP準拠でクレーム用スクリプトを同一オリジン配信する。"""
    return Response(
        content=INVITE_CLAIM_JS,
        media_type="text/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/session")
async def invite_start_session(
    request: InviteSessionRequest,
    http_request: Request,
) -> JSONResponse:
    """トークンを検証し、短命クレームCookieを設定してLINE Loginへ案内する。"""
    import hashlib as _hashlib

    token_sha256 = _hashlib.sha256(request.token.encode("utf-8")).hexdigest()
    repository = FirestoreAdminInviteRepository()
    invite = await repository.find_active_by_token_hash(token_sha256)
    if invite is None:
        raise HTTPException(status_code=410, detail="Invite is unavailable")

    login_url = (
        f"/api/{settings.api_version}/auth/line"
        f"?return_to=/api/{settings.api_version}/invite/complete"
    )
    response = JSONResponse(content={"login_url": login_url})
    response.set_cookie(
        key=CLAIM_COOKIE_NAME,
        value=_create_claim_token(invite["id"]),
        max_age=CLAIM_TTL_SECONDS,
        path=f"/api/{settings.api_version}",
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _result_page(title: str, body: str) -> HTMLResponse:
    """結果表示ページを組み立てる。"""
    return HTMLResponse(
        "<!doctype html><html lang='ja'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><body style='font-family:sans-serif;max-width:36rem;"
        f"margin:4rem auto;padding:1rem'><h1>{title}</h1>{body}</body></html>",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/complete", response_class=HTMLResponse)
async def invite_complete(request: Request) -> Response:
    """LINE Login成功後に招待を消費して登録を確定する。"""
    claim_token = request.cookies.get(CLAIM_COOKIE_NAME)
    invite_id = _verify_claim_token(claim_token) if claim_token else None
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if not invite_id or not refresh_token:
        return _result_page(
            "登録を完了できませんでした",
            "<p>登録URLの有効期限が切れたか、ログインが完了していません。"
            "管理者へお問い合わせください。</p>",
        )

    try:
        tokens = await FirestoreAuthService().refresh(refresh_token)
        access_payload = decode_token(tokens["access_token"]) if tokens else None
        user_id = access_payload.get("sub") if access_payload else None
    except Exception:
        return _result_page(
            "登録を完了できませんでした",
            "<p>ログインセッションを確認できませんでした。再度ログインしてお試しください。</p>",
        )
    if not user_id:
        return _result_page(
            "登録を完了できませんでした",
            "<p>ユーザー情報を確認できませんでした。</p>",
        )

    repository = FirestoreAdminInviteRepository()
    consumed = await repository.consume(invite_id=invite_id, user_id=user_id)
    response: Response
    if consumed:
        try:
            await repository.mark_user_registration(
                invite_id=invite_id,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning(
                "Invite registration mark failed: error_type=%s",
                type(exc).__name__,
            )
        response = _result_page(
            "登録が完了しました",
            "<p>Chabotの無料アカウントとして登録されました。"
            "LINEに戻って、そのままご質問ください。</p>",
        )
    else:
        response = _result_page(
            "この登録URLは利用できません",
            "<p>このURLはすでに使用済みか、失効しています。</p>",
        )
    set_refresh_token_cookie(response, tokens["refresh_token"])
    response.delete_cookie(
        CLAIM_COOKIE_NAME,
        path=f"/api/{settings.api_version}",
    )
    return response
