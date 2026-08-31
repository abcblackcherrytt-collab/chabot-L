"""
セキュリティモジュール
JWTの生成・検証・失効管理、LINE署名検証を行います。
"""

import base64
import hmac
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt as pyjwt
import httpx
import bcrypt
from jwt import PyJWTError
from passlib.context import CryptContext

from .config import settings

logger = logging.getLogger(__name__)

# パスワードハッシュ化のコンテキスト
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
TOKEN_HASH_PREFIX = "sha256$"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    パスワードを検証します

    Args:
        plain_password: 平文パスワード
        hashed_password: ハッシュ化されたパスワード

    Returns:
        パスワードが一致すればTrue、それ以外はFalse
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    パスワードをハッシュ化します

    Args:
        password: 平文パスワード

    Returns:
        ハッシュ化されたパスワード
    """
    return pwd_context.hash(password)


def create_access_token(
    user_id: str,
    email: str,
    jti: str,
    additional_claims: Dict[str, Any] | None = None,
) -> Tuple[str, datetime]:
    """
    アクセストークンを作成します

    Args:
        user_id: ユーザーID
        email: ユーザーメールアドレス
        jti: JWT ID（一意識別子）
        additional_claims: 追加のクレーム

    Returns:
        (アクセストークン, 有効期限) のタプル
    """
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expires_at = datetime.now(timezone.utc) + expires_delta

    to_encode = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "exp": expires_at,
        "type": "access",
    }

    if additional_claims:
        to_encode.update(additional_claims)

    encoded_jwt = pyjwt.encode(
        to_encode,
        settings.jwt_secret_keys_list[0],  # 最新のシークレットキーを使用
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt, expires_at


def create_refresh_token(
    user_id: str,
    email: str,
    jti: str,
    additional_claims: Dict[str, Any] | None = None,
) -> Tuple[str, datetime]:
    """
    リフレッシュトークンを作成します

    Args:
        user_id: ユーザーID
        email: ユーザーメールアドレス
        jti: JWT ID（一意識別子）
        additional_claims: 追加のクレーム

    Returns:
        (リフレッシュトークン, 有効期限) のタプル
    """
    expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    expires_at = datetime.now(timezone.utc) + expires_delta

    to_encode = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "exp": expires_at,
        "type": "refresh",
    }

    if additional_claims:
        to_encode.update(additional_claims)

    encoded_jwt = pyjwt.encode(
        to_encode,
        settings.jwt_secret_keys_list[0],  # 最新のシークレットキーを使用
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt, expires_at


def decode_token(token: str) -> Dict[str, Any] | None:
    """
    トークンをデコードします

    複数のシークレットキーを順に試行し、有効なキーで検証します。
    これにより、鍵ローテーション中も旧キーで署名されたトークンを検証できます。

    Args:
        token: JWTトークン

    Returns:
        デコードされたペイロード、または失敗時はNone
    """
    # すべてのシークレットキーで検証を試行
    for secret_key in settings.jwt_secret_keys_list:
        try:
            payload = pyjwt.decode(
                token,
                secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            return payload
        except PyJWTError:
            continue

    return None


def verify_token_not_revoked(
    payload: Dict[str, Any],
    revoked_tokens: Dict[str, datetime],
) -> bool:
    """
    トークンが失効していないかを検証します

    Args:
        payload: デコードされたJWTペイロード
        revoked_tokens: 失効トークンの辞書 {jti: revoked_at}

    Returns:
        トークンが有効であればTrue、失効していればFalse
    """
    jti = payload.get("jti")
    if not jti:
        return False

    revoked_at = revoked_tokens.get(jti)
    if revoked_at is not None:
        return False

    return True


def hash_token(token: str) -> str:
    """
    トークンをハッシュ化してデータベースに保存します

    Args:
        token: 平文トークン

    Returns:
        ハッシュ化されたトークン
    """
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{TOKEN_HASH_PREFIX}{digest}"


def verify_token_hash(plain_token: str, hashed_token: str) -> bool:
    """
    トークンのハッシュを検証します

    高エントロピーのRefresh TokenはSHA-256ダイジェストを定時間比較します。
    既存のbcryptハッシュも移行期間中は検証できます。

    Args:
        plain_token: 平文トークン
        hashed_token: ハッシュ化されたトークン

    Returns:
        トークンが一致すればTrue、それ以外はFalse
    """
    if hashed_token.startswith(TOKEN_HASH_PREFIX):
        expected = hash_token(plain_token)
        return hmac.compare_digest(expected, hashed_token)

    # 旧bcryptトークンは72バイトで暗黙に切り詰められていたため、
    # passlibを経由せず同じ条件で検証する。新規保存には使用しない。
    try:
        candidate = plain_token.encode("utf-8")[:72]
        return bcrypt.checkpw(candidate, hashed_token.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Webhook署名を検証します

    HMAC-SHA256を使用して署名を検証します。

    Args:
        payload: リクエストボディ（バイト列）
        signature: X-Line-Signatureヘッダーの値（Base64エンコード）
        secret: Webhookシークレット（LINE Channel Secret）

    Returns:
        署名が有効であればTrue、それ以外はFalse
    """
    if not signature or not secret:
        return False

    # HMAC-SHA256で署名を計算
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()

    # Base64エンコードされた署名をデコード
    try:
        received_signature = base64.b64decode(signature)
    except Exception:
        return False

    # タイミング攻撃対策のため、定時間算法で比較
    return hmac.compare_digest(received_signature, expected_signature)


async def verify_line_id_token(
    id_token: str,
    channel_id: str,
    nonce: str = "",
) -> Optional[Dict[str, Any]]:
    """
    LINE Login の ID トークンを検証します

    LINE公式の検証APIで署名とOIDCクレームを検証します。

    Args:
        id_token: LINE Login から取得したID トークン
        channel_id: LINE Login チャネルID

    Returns:
        検証済みのペイロード、失敗時はNone
    """
    if not id_token or not channel_id:
        return None

    try:
        verify_data = {"id_token": id_token, "client_id": channel_id}
        if nonce:
            verify_data["nonce"] = nonce

        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                "https://api.line.me/oauth2/v2.1/verify",
                data=verify_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            logger.warning("LINE ID token verification rejected: %s", response.status_code)
            return None

        payload = response.json()
        if payload.get("iss") != "https://access.line.me":
            logger.warning("Invalid LINE ID token issuer")
            return None
        if payload.get("aud") != channel_id:
            logger.warning("LINE ID token audience mismatch")
            return None
        if nonce and payload.get("nonce") != nonce:
            logger.warning("LINE ID token nonce mismatch")
            return None
        if not payload.get("sub"):
            logger.warning("LINE ID token subject is missing")
            return None
        return payload

    except (httpx.HTTPError, ValueError) as e:
        logger.error(f"ID token verification failed: {e}")
        return None
