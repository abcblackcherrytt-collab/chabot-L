"""
ベースクライアント
すべてのクライアントが継承するベースクラスを定義します。
テスト容易化のために、外部APIとの通信を抽象化します。
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel


logger = logging.getLogger(__name__)


class BaseClientError(Exception):
    """
    クライアントエラーベースクラス
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response = response

    def __str__(self) -> str:
        if self.status_code:
            return f"{self.status_code}: {self.message}"
        return self.message


class BaseClient:
    """
    ベースクライアント

    すべてのクライアントが継承するベースクラスです。
    共通のHTTPクライアント機能を提供します。
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        ベースクライアントを初期化します

        Args:
            base_url: APIのベースURL
            api_key: APIキー（オプション）
            timeout: リクエストタイムアウト（秒）
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._initialize_http_client()

    def _initialize_http_client(self):
        """
        HTTPクライアントを初期化します

        非同期HTTPクライアントを設定します。
        """
        import httpx

        self._http_client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self._get_default_headers(),
        )

    def _get_default_headers(self) -> Dict[str, str]:
        """
        デフォルトのHTTPヘッダーを取得します

        Returns:
            デフォルトのHTTPヘッダーの辞書
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"chabot/1.0.0",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    def _build_url(self, *path_parts: str) -> str:
        """
        完全なURLを構築します

        Args:
            *path_parts: URLのパス部分

        Returns:
            完全なURL
        """
        return "/".join([self.base_url, *path_parts])

    async def _handle_response(
        self,
        response: Any,
        error_class: type = BaseClientError,
    ) -> Any:
        """
        レスポンスを処理します

        Args:
            response: HTTPレスポンス
            error_class: エラークラス

        Returns:
            処理されたレスポンス

        Raises:
            BaseClientError: エラーが発生した場合
        """
        if isinstance(response, dict) and "error" in response:
            error_data = response["error"]
            message = error_data.get("message", "Unknown error")
            status_code = response.get("status")

            logger.error(f"API error: {message}")
            raise error_class(message, status_code, response)

        return response

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        GETリクエストを送信します

        Args:
            path: APIのパス
            params: クエリパラメータ
            headers: 追加のHTTPヘッダー

        Returns:
            APIレスポンス

        Raises:
            BaseClientError: APIエラーが発生した場合
        """
        url = self._build_url(path)
        merged_headers = {**self._get_default_headers()}
        if headers:
            merged_headers.update(headers)

        logger.debug(f"GET {url}")
        response = await self._http_client.get(
            url,
            params=params,
            headers=merged_headers,
        )

        return await self._handle_response(response.json())

    async def post(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        POSTリクエストを送信します

        Args:
            path: APIのパス
            data: フォームデータ
            json: JSONデータ
            headers: 追加のHTTPヘッダー

        Returns:
            APIレスポンス

        Raises:
            BaseClientError: APIエラーが発生した場合
        """
        url = self._build_url(path)
        merged_headers = {**self._get_default_headers()}
        if headers:
            merged_headers.update(headers)

        logger.debug(f"POST {url}")
        response = await self._http_client.post(
            url,
            data=data,
            json=json,
            headers=merged_headers,
        )

        return await self._handle_response(response.json())

    async def put(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        PUTリクエストを送信します

        Args:
            path: APIのパス
            data: フォームデータ
            json: JSONデータ
            headers: 追加のHTTPヘッダー

        Returns:
            APIレスポンス

        Raises:
            BaseClientError: APIエラーが発生した場合
        """
        url = self._build_url(path)
        merged_headers = {**self._get_default_headers()}
        if headers:
            merged_headers.update(headers)

        logger.debug(f"PUT {url}")
        response = await self._http_client.put(
            url,
            data=data,
            json=json,
            headers=merged_headers,
        )

        return await self._handle_response(response.json())

    async def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        DELETEリクエストを送信します

        Args:
            path: APIのパス
            headers: 追加のHTTPヘッダー

        Returns:
            APIレスポンス

        Raises:
            BaseClientError: APIエラーが発生した場合
        """
        url = self._build_url(path)
        merged_headers = {**self._get_default_headers()}
        if headers:
            merged_headers.update(headers)

        logger.debug(f"DELETE {url}")
        response = await self._http_client.delete(
            url,
            headers=merged_headers,
        )

        return await self._handle_response(response.json())

    async def close(self) -> None:
        """
        HTTPクライアントを閉じます

        非同期コンテキスト終了時に実行します。
        """
        await self._http_client.aclose()

    async def __aenter__(self):
        """非同期コンテキストマネージャーの開始"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャーの終了"""
        await self.close()
