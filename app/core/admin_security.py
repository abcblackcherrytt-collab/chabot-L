"""管理UI認証・セッション・CSRF基盤。

前段はCloud IAP（x-goog-iap-jwt-assertion）を想定し、検証後に管理者allowlist
（Firestore admin_admins/{email}）で認可する。書込みはCSRF tokenとOrigin検証で保護する。
ローカル開発用にdevモード（debug=True限定）を用意する。
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import Request

from app.core.config import settings
from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


ADMIN_SESSION_COOKIE = "chabot_admin_session"
ADMIN_CSRF_COOKIE = "chabot_admin_csrf"
ADMIN_ADMINS_COLLECTION = "admin_admins"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key-v1"
GOOGLE_OAUTH_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
IAP_ISSUERS = ("https://cloud.google.com/iap", "accounts.google.com")
GOOGLE_ID_TOKEN_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

_iap_certs_cache: Dict[str, Any] = {}
_iap_certs_cached_at: float = 0.0
_google_certs_cache: Dict[str, Any] = {}
_google_certs_cached_at: float = 0.0
_allowlist_cache: Dict[str, tuple[float, bool]] = {}
_ALLOWLIST_CACHE_TTL_SECONDS = 60.0
_IAP_CERTS_CACHE_TTL_SECONDS = 600.0


class AdminAuthError(Exception):
    """管理認証の失敗を表す。"""


def _sign(payload: bytes) -> str:
    """ペイロードへHMAC署名を付ける。"""
    key = settings.jwt_secret_keys_list[0].encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def create_admin_session_token(*, email: str, csrf_token: str) -> str:
    """短命管理セッショントークン（署名付き）を作成する。"""
    payload = json.dumps(
        {
            "sub": email,
            "csrf": csrf_token,
            "exp": int(time.time()) + settings.admin_session_ttl_seconds,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return f"{body}.{_sign(payload)}"


def verify_admin_session_token(token: str) -> Optional[Dict[str, Any]]:
    """管理セッショントークンを検証し、ペイロードを返す。"""
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
    return data


def issue_csrf_token() -> str:
    """CSRFトークンを生成する。"""
    return secrets.token_urlsafe(32)


async def _fetch_iap_certs(force: bool = False) -> Dict[str, str]:
    """Google IAP検証用公開鍵を取得し、キャッシュする。"""
    global _iap_certs_cache, _iap_certs_cached_at
    if (
        not force
        and _iap_certs_cache
        and time.monotonic() - _iap_certs_cached_at < _IAP_CERTS_CACHE_TTL_SECONDS
    ):
        return _iap_certs_cache
    async with httpx.AsyncClient() as client:
        response = await client.get(IAP_CERTS_URL)
        response.raise_for_status()
        data = response.json()
    certs = data.get("keys") if isinstance(data, dict) else data
    _iap_certs_cache = certs or {}
    _iap_certs_cached_at = time.monotonic()
    return _iap_certs_cache


async def _fetch_google_oauth_certs(force: bool = False) -> Dict[str, str]:
    """Google OAuth IDトークン検証用公開鍵（PEM形式）を取得し、キャッシュする。"""
    global _google_certs_cache, _google_certs_cached_at
    if (
        not force
        and _google_certs_cache
        and time.monotonic() - _google_certs_cached_at < _IAP_CERTS_CACHE_TTL_SECONDS
    ):
        return _google_certs_cache
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_OAUTH_CERTS_URL)
        response.raise_for_status()
        certs = response.json()
    _google_certs_cache = certs or {}
    _google_certs_cached_at = time.monotonic()
    return _google_certs_cache


def _decode_iap_assertion(assertion: str, certs: Dict[str, str]) -> Dict[str, Any]:
    """IAPアサーションJWTの署名・発行者・audience・有効期限を検証する。"""
    from google.auth import jwt as google_jwt

    if not settings.admin_iap_audience:
        raise AdminAuthError("iap_audience_not_configured")
    try:
        return google_jwt.decode(
            assertion,
            certs=certs,
            verify=True,
            audience=settings.admin_iap_audience,
        )
    except Exception as exc:
        raise AdminAuthError("invalid_iap_assertion") from exc


def _validate_iap_payload(payload: Dict[str, Any]) -> str:
    """検証済みペイロードから管理者メールアドレスを取り出す。"""
    issuer = payload.get("iss")
    if issuer not in IAP_ISSUERS:
        raise AdminAuthError("invalid_iap_issuer")
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise AdminAuthError("missing_iap_email")
    return email


async def extract_admin_identity(request: Request) -> str:
    """リクエストから管理者メールアドレスを確定する。

    - iapモード: x-goog-iap-jwt-assertion を検証する。
    - devモード: debug=True限定で X-Admin-Dev-Email を許可リストと照合する。
    - run_iamモード: Authorization Bearer のGoogle IDトークンを検証する
      （Cloud RunのIAM保護とcloud-run-proxy経由のブラウザ利用を想定）。
    """
    mode = settings.admin_auth_mode
    if mode == "run_iam":
        authorization = request.headers.get("Authorization", "")
        if not authorization.lower().startswith("bearer "):
            raise AdminAuthError("missing_bearer_token")
        return await verify_run_iam_identity(authorization[7:].strip())
    if mode == "dev":
        if not settings.debug:
            raise AdminAuthError("dev_mode_requires_debug")
        email = request.headers.get("X-Admin-Dev-Email", "")
        allowed = [
            item.strip()
            for item in settings.admin_dev_emails.split(",")
            if item.strip()
        ]
        if email not in allowed:
            raise AdminAuthError("dev_email_not_allowed")
        return email
    assertion = request.headers.get("X-Goog-Iap-Jwt-Assertion", "")
    if not assertion:
        raise AdminAuthError("missing_iap_assertion")
    certs = await _fetch_iap_certs()
    payload = _decode_iap_assertion(assertion, certs)
    return _validate_iap_payload(payload)


async def verify_run_iam_identity(token: str) -> str:
    """Cloud Run IAM呼び出し用のGoogle IDトークンを検証し、メールアドレスを返す。

    cloud-run-proxy および gcloud auth print-identity-token --audiences が
    サービスURLをaudienceとして発行したトークンを想定する。
    """
    from google.auth import jwt as google_jwt

    audiences = [
        item.strip()
        for item in settings.admin_run_iam_audiences.split(",")
        if item.strip()
    ]
    if not audiences:
        raise AdminAuthError("run_iam_audience_not_configured")
    certs = await _fetch_google_oauth_certs()
    payload: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    for audience in audiences:
        try:
            payload = google_jwt.decode(
                token,
                certs=certs,
                verify=True,
                audience=audience,
            )
            break
        except Exception as exc:
            last_error = exc
    if payload is None:
        raise AdminAuthError("invalid_bearer_token") from last_error
    if payload.get("iss") not in GOOGLE_ID_TOKEN_ISSUERS:
        raise AdminAuthError("invalid_id_token_issuer")
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        raise AdminAuthError("missing_id_token_email")
    if payload.get("email_verified") is False:
        raise AdminAuthError("email_not_verified")
    return email


async def is_admin_allowed(email: str) -> bool:
    """Firestore admin_admins/{email} で認可する（60秒キャッシュ）。"""
    cached = _allowlist_cache.get(email)
    now = time.monotonic()
    if cached and now - cached[0] < _ALLOWLIST_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        doc = await (
            get_firestore_client_sync()
            .collection(ADMIN_ADMINS_COLLECTION)
            .document(email)
            .get()
        )
        allowed = doc.exists and bool(doc.to_dict().get("enabled", True))
    except Exception as exc:
        logger.error(
            "Admin allowlist read failed: error_type=%s",
            type(exc).__name__,
        )
        return False
    _allowlist_cache[email] = (now, allowed)
    return allowed


def verify_csrf(request: Request, session_payload: Dict[str, Any]) -> None:
    """書込み要求のCSRFトークンとOriginを検証する。"""
    received = request.headers.get("X-CSRF-Token", "")
    expected = str(session_payload.get("csrf", ""))
    if not received or not hmac.compare_digest(received, expected):
        raise AdminAuthError("csrf_mismatch")
    origin = request.headers.get("Origin")
    if origin:
        base = str(request.base_url).rstrip("/")
        if origin != base:
            raise AdminAuthError("origin_mismatch")


def invalidate_allowlist_cache(email: Optional[str] = None) -> None:
    """allowlistキャッシュを破棄する（管理UIでの追加・削除反映用）。"""
    if email is None:
        _allowlist_cache.clear()
    else:
        _allowlist_cache.pop(email, None)
