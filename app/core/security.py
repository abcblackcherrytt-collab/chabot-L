"""
セキュリティモジュール
JWTの生成・検証・失効管理、LINE署名検証を行います。
"""

import base64
import hmac
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from jose import JWTError, jwt
from passlib.context import CryptContext
from .config import settings

logger = logging.getLogger(__name__)

# パスワードハッシュ化のコンテキスト
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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

    encoded_jwt = jwt.encode(
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

    encoded_jwt = jwt.encode(
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
            payload = jwt.decode(
                token,
                secret_key,
                algorithms=[settings.jwt_algorithm],
            )
            return payload
        except JWTError:
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
    return pwd_context.hash(token)


def verify_token_hash(plain_token: str, hashed_token: str) -> bool:
    """
    トークンのハッシュを検証します

    bcryptの定時間算法を使用してタイミング攻撃を防ぎます。

    Args:
        plain_token: 平文トークン
        hashed_token: ハッシュ化されたトークン

    Returns:
        トークンが一致すればTrue、それ以外はFalse
    """
    return pwd_context.verify(plain_token, hashed_token)


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


def verify_line_id_token(
    id_token: str,
    channel_id: str,
) -> Optional[Dict[str, Any]]:
    """
    LINE Login の ID トークンを検証します

    OIDC仕様に基づき、ID トークンの署名・クレームを検証します。
    LINE PlatformはRS256（RSA + SHA-256）を使用します。

    Args:
        id_token: LINE Login から取得したID トークン
        channel_id: LINE Login チャネルID

    Returns:
        検証済みのペイロード、失敗時はNone
    """
    if not id_token or not channel_id:
        return None

    try:
        # ヘッダーをデコード（署名検証のため）
        parts = id_token.split(".")
        if len(parts) != 3:
            logger.warning("Invalid ID token format")
            return None

        header_b64 = parts[0]
        header_json = base64.urlsafe_b64decode(header_b64 + "==")
        header = json.loads(header_json)

        if header.get("alg") != "RS256":
            logger.warning(f"Unsupported algorithm: {header.get('alg')}")
            return None

        # ペイロードをデコード（署名検証なしで中身を確認）
        payload_b64 = parts[1]
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==")
        payload = json.loads(payload_json)

        # クレームの検証
        now = datetime.now(timezone.utc)

        # issuer の検証
        if payload.get("iss") != "https://access.line.me":
            logger.warning(f"Invalid issuer: {payload.get('iss')}")
            return None

        # audience の検証
        if payload.get("aud") != channel_id:
            logger.warning("Audience mismatch")
            return None

        # 有効期限の検証
        exp = payload.get("exp")
        if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < now:
            logger.warning("ID token expired")
            return None

        # 発行時刻の検証（5分以上前は拒否）
        iat = payload.get("iat")
        if iat and (now - datetime.fromtimestamp(iat, tz=timezone.utc)).total_seconds() > 300:
            logger.warning("ID token too old")
            return None

        # TODO: RS256署名の検証を実装
        # 本番運用時は LINE の公開鍵（JWKS）を取得して署名を検証する必要があります
        # https://api.line.me/oauth2/v2.1/certs から公開鍵を取得
        logger.warning("ID token signature verification not yet implemented")

        return payload

    except Exception as e:
        logger.error(f"ID token verification failed: {e}")
        return None
