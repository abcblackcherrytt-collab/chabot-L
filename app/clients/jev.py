"""TypeSafe Jev System One API client."""

import logging
from typing import Any, Dict

import httpx

from app.clients.base import BaseClientError

logger = logging.getLogger(__name__)


class JevClientError(BaseClientError):
    """Jev API 呼び出しに失敗した場合の例外。"""


class JevClient:
    """文章を生成せず、型付きの判定だけを返す Jev API クライアント。"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model_name: str,
        timeout: float = 5.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """APIキーが設定済みかを返す。"""
        return bool(self.api_key and not self.api_key.startswith("your-"))

    async def decide(
        self,
        state: str | Dict[str, Any],
        questions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """共有 state に対する複数の型付き判定を一度に実行する。"""
        if not self.is_configured:
            raise JevClientError("Jev API key is not configured")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.api_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model_name,
                        "state": state,
                        "questions": questions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Jev decision request failed: error_type=%s", type(exc).__name__
            )
            raise JevClientError("Jev decision request failed") from exc

        if not isinstance(payload, dict) or not isinstance(
            payload.get("answers"), dict
        ):
            raise JevClientError("Jev response did not contain answers")
        return payload
