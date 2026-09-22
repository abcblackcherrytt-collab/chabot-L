"""管理画面専用FastAPIアプリケーション。

公開Botの ``app.server`` とはASGI入口を分離し、管理ルートが公開Botへ
混入しない構造を保つ。IAP対応が完了するまでは既定で無効とする。
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.http_security import SecurityHeadersMiddleware


def create_admin_app(*, enabled: bool | None = None) -> FastAPI:
    """管理専用アプリを生成する。

    Args:
        enabled: ローカルテスト用の明示的な有効化。未指定時は設定値を使う。

    Returns:
        公開Botのルーターを含まない管理専用FastAPIアプリ。
    """
    admin_enabled = settings.admin_ui_enabled if enabled is None else enabled
    admin_app = FastAPI(
        title="Chabot Admin",
        description="Chabot management interface",
        version=settings.api_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    admin_app.add_middleware(
        SecurityHeadersMiddleware,
        referrer_policy="no-referrer",
        no_store=True,
    )

    @admin_app.get("/health", include_in_schema=False)
    async def health_check() -> dict[str, str]:
        """プロセス生存確認。個人情報や構成値は返さない。"""
        return {"status": "healthy"}

    @admin_app.get("/admin", response_class=HTMLResponse)
    async def admin_home() -> HTMLResponse:
        """認証実装前のローカル開発用プレースホルダーを返す。"""
        if not admin_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin UI is disabled",
            )
        return HTMLResponse(
            "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Chabot管理</title></head><body><main>"
            "<h1>Chabot管理</h1><p>管理機能は開発中です。</p>"
            "</main></body></html>"
        )

    return admin_app


app = create_admin_app()
