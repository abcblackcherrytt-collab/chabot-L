"""
セキュリティモジュール
JWTの生成・検証・失効管理を行います。
"""

import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple
from jose import JWTError, jwt
from passlib.context import CryptContext
from .config import settings

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
        signature: X-Discode-Signatureヘッダーの値
        secret: Webhookシークレット

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
    ).hexdigest()

    # タイミング攻撃対策のため、定時間算法で比較
    return hmac.compare_digest(signature, expected_signature)


def verify_discord_signature(
    public_key: str,
    signature: str,
    timestamp: str,
    body: bytes,
) -> bool:
    """
    Discord Interactionsの署名を検証します

    Ed25519を使用してDiscordからのリクエストを検証します。
    Discord Developer PortalのGeneral Informationで取得した
    公開鍵を使用します。

    Args:
        public_key: Discord ApplicationのEd25519公開鍵（16進数文字列）
        signature: X-Signature-Ed25519ヘッダーの値（16進数文字列）
        timestamp: X-Signature-Timestampヘッダーの値
        body: リクエストボディ（バイト列）

    Returns:
        署名が有効であればTrue、それ以外はFalse
    """
    if not public_key or not signature or not timestamp:
        return False

    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except ImportError:
        return False

    try:
        verify_key = VerifyKey(bytes.fromhex(public_key))
        message = timestamp.encode() + body
        verify_key.verify(message, bytes.fromhex(signature))
        return True

    except (BadSignatureError, ValueError, Exception):
        return False
