"""クーポン発行・引き換えサービス。

コードはCrockford Base32＋チェックディジットで発行し、平文は発行時のみ
管理UIへ1回返す。Bot側の引き換えは「クーポン CODE」形式のメッセージで受け付ける。
"""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.repositories.firestore_coupon_repository import (
    COUPON_KIND_BONUS_MESSAGES,
    COUPON_KIND_PLAN_GRANT,
    FirestoreCouponRepository,
)

logger = logging.getLogger(__name__)


CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
COUPON_CODE_LENGTH = 10
COUPON_MESSAGE_PATTERN = re.compile(r"^クーポン[ 　]+(?P<code>\S+)$")


def normalize_coupon_code(raw: str) -> str:
    """入力コードをCrockford Base32表記へ正規化する。"""
    normalized = raw.strip().upper().replace("-", "").replace(" ", "")
    normalized = normalized.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    return normalized


def coupon_code_sha256(code: str) -> str:
    """正規化済みコードのSHA-256ハッシュを返す。"""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def generate_coupon_code(length: int = COUPON_CODE_LENGTH) -> str:
    """チェックディジット付きのCrockford Base32コードを生成する。"""
    body = "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(length - 1))
    checksum = sum(CROCKFORD_ALPHABET.index(char) for char in body) % 32
    return body + CROCKFORD_ALPHABET[checksum]


def has_valid_coupon_checksum(code: str) -> bool:
    """コードのチェックディジットを検証する。"""
    if len(code) < 2 or any(char not in CROCKFORD_ALPHABET for char in code):
        return False
    body, check = code[:-1], code[-1]
    expected = sum(CROCKFORD_ALPHABET.index(char) for char in body) % 32
    return CROCKFORD_ALPHABET[expected] == check


def match_coupon_message(text: str) -> Optional[str]:
    """「クーポン CODE」形式のメッセージからコードを取り出す。"""
    matched = COUPON_MESSAGE_PATTERN.match(text or "")
    if not matched:
        return None
    return matched.group("code")


class CouponService:
    """クーポンの発行とBot側引き換えを担う。"""

    def __init__(self, coupon_repository: Optional[FirestoreCouponRepository] = None):
        """リポジトリを初期化する。"""
        self.coupon_repository = coupon_repository or FirestoreCouponRepository()

    async def issue(
        self,
        *,
        kind: str,
        plan: Optional[str],
        duration_days: Optional[int],
        bonus_free_messages: Optional[int],
        max_redemptions: int,
        expires_at: Optional[datetime],
        created_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """クーポンを発行し、平文コードを1回だけ返す。"""
        if kind == COUPON_KIND_PLAN_GRANT:
            if plan not in ("basic", "pro"):
                raise ValueError("invalid_plan")
            if not duration_days or int(duration_days) <= 0:
                raise ValueError("invalid_duration")
        elif kind == COUPON_KIND_BONUS_MESSAGES:
            if not bonus_free_messages or int(bonus_free_messages) <= 0:
                raise ValueError("invalid_bonus")
        else:
            raise ValueError("invalid_kind")
        if int(max_redemptions) <= 0:
            raise ValueError("invalid_max_redemptions")
        if expires_at and expires_at <= datetime.now(timezone.utc):
            raise ValueError("invalid_expires_at")

        code = generate_coupon_code()
        coupon = await self.coupon_repository.create(
            code_sha256=coupon_code_sha256(code),
            kind=kind,
            plan=plan,
            duration_days=int(duration_days) if duration_days else None,
            bonus_free_messages=int(bonus_free_messages) if bonus_free_messages else None,
            max_redemptions=int(max_redemptions),
            expires_at=expires_at,
            created_by=created_by,
            note=note,
        )
        return {"coupon": coupon, "code": code}

    async def redeem(self, *, raw_code: str, user_id: str) -> Dict[str, Any]:
        """Bot側の引き換えを処理し、LINE返信用の結果を返す。"""
        from app.repositories.firestore_usage_repository import FirestoreUsageRepository

        usage_repo = FirestoreUsageRepository()
        attempts = await usage_repo.count_coupon_attempt(user_id)
        if attempts > 10:
            return {
                "status": "rate_limited",
                "message": "本日はこれ以上クーポン引き換えを試行できません。明日またお試しください。",
            }

        code = normalize_coupon_code(raw_code)
        if not has_valid_coupon_checksum(code):
            return {
                "status": "invalid_code",
                "message": "クーポンコードが正しくありません。コードをご確認のうえ、再度送信してください。",
            }

        result = await self.coupon_repository.redeem(
            code_sha256=coupon_code_sha256(code),
            user_id=user_id,
        )
        status = result.get("status")
        if status == "granted":
            if result.get("kind") == COUPON_KIND_PLAN_GRANT:
                plan_label = {"basic": "ベーシック", "pro": "プロ"}.get(result.get("plan"), "")
                message = (
                    "クーポンを適用しました。\n"
                    + f"{plan_label}プラン（{result.get('duration_days')}日間）でご利用いただけます。"
                )
            else:
                message = (
                    "クーポンを適用しました。\n"
                    + f"本日は{result.get('bonus_free_messages')}回追加で質問できます。"
                )
            return {**result, "message": message}
        messages = {
            "not_found": "クーポンコードが正しくないか、存在しません。コードをご確認ください。",
            "expired": "このクーポンの有効期限が切れています。",
            "exhausted": "このクーポンの利用回数上限に達しています。",
            "already_redeemed": "このクーポンはすでにご利用済みです。",
            "revoked": "このクーポンは現在ご利用いただけません。",
        }
        return {
            **result,
            "message": messages.get(status, "クーポンを適用できませんでした。"),
        }
