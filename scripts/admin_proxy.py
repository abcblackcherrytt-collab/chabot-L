#!/usr/bin/env python3
"""Chabot管理コンソール（chabot-admin）用のローカル認証プロキシ。

Cloud RunのIAM保護を突破してブラウザから管理UIへアクセスするため、
localhostで受けたリクエストへIDトークンを付与してサービスへ中継する。

トークンはサービスアカウント（既定 chabot-sa）の権限借用（generateIdToken）で
発行し、audienceをサービスURLへ一致させる。allowlist（admin_admins）には
このサービスアカウントのメールを登録しておく。

環境変数:
  ADMIN_PROXY_PORT      待ち受けポート（既定 8080）
  CHABOT_ADMIN_URL      転送先サービスURL
  CHABOT_ADMIN_SA       権限借用するサービスアカウント
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import google.auth
import google.auth.transport.requests


SERVICE_URL = os.environ.get(
    "CHABOT_ADMIN_URL",
    "https://chabot-admin-742113528510.asia-northeast1.run.app",
).rstrip("/")
SA_EMAIL = os.environ.get(
    "CHABOT_ADMIN_SA",
    "chabot-sa@takahashi-451312.iam.gserviceaccount.com",
)
PORT = int(os.environ.get("ADMIN_PROXY_PORT", "8080"))
IAM_TOKEN_URL = (
    "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
    + SA_EMAIL
    + ":generateIdToken"
)

_cached_token: str = ""
_cached_exp: float = 0.0


def _user_access_token() -> str:
    """gcloudのユーザー認証情報からアクセストークンを取得する。"""
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def _mint_impersonated_id_token() -> str:
    """サービスアカウントになり代わり、audience一致のIDトークンを発行する。"""
    request = urllib.request.Request(
        IAM_TOKEN_URL,
        data=json.dumps(
            {"audience": SERVICE_URL, "includeEmail": True}
        ).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + _user_access_token(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())["token"]


def get_id_token() -> str:
    """期限切れ120秒前までキャッシュしたIDトークンを返す。"""
    global _cached_token, _cached_exp
    if _cached_token and time.time() < _cached_exp - 120:
        return _cached_token
    token = _mint_impersonated_id_token()
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    _cached_token = token
    _cached_exp = float(payload.get("exp", time.time() + 300))
    return token


HOP_BY_HOP = {
    "host",
    "authorization",
    "content-length",
    "connection",
    "accept-encoding",
    "transfer-encoding",
    "keep-alive",
}


class ProxyHandler(BaseHTTPRequestHandler):
    """localhostのリクエストへIDトークンを付けて転送する。"""

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP
        }
        # ブラウザのOrigin（localhost）を転送先オリジンへ書き換える。
        # アプリのOrigin検証は「リクエストHostと同一オリジンか」を見るため、
        # プロキシ経由でも同一オリジンとして成立させる。CSRFトークン検証は
        # 元のまま機能する（トークンはセッションCookieと紐づいている）。
        if "Origin" in headers:
            headers["Origin"] = SERVICE_URL
        try:
            headers["Authorization"] = "Bearer " + get_id_token()
        except Exception as exc:
            self.send_error(502, f"token mint failed: {type(exc).__name__}")
            return
        request = urllib.request.Request(
            SERVICE_URL + self.path,
            data=body,
            method=self.command,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                self._relay(response.status, response.headers, response.read())
        except urllib.error.HTTPError as exc:
            self._relay(exc.code, exc.headers, exc.read())
        except Exception as exc:
            self.send_error(502, f"proxy error: {type(exc).__name__}")

    def _relay(self, status: int, headers: Any, body: bytes) -> None:
        self.send_response(status)
        copied = {
            key: value
            for key, value in headers.items()
            if key.lower() not in HOP_BY_HOP
            and key.lower() != "set-cookie"
            and key.lower() != "content-length"
        }
        for key, value in copied.items():
            self.send_header(key, value)
        for value in headers.get_all("Set-Cookie") or []:
            self.send_header("Set-Cookie", value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_DELETE = _forward
    do_PATCH = _forward
    do_HEAD = _forward
    do_OPTIONS = _forward

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """最小限のアクセスログ（ヘッダやトークンは出さない）。"""
        sys.stderr.write("admin-proxy: %s %s\n" % (self.command, self.path))


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(
        f"admin-proxy: http://localhost:{PORT}/admin -> {SERVICE_URL}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
