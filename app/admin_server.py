"""管理画面専用FastAPIアプリケーション。

公開Botの app.server とはASGI入口を分離し、管理ルートが公開Botへ
混入しない構造を保つ。IAP対応が完了するまでは既定で無効とする。
"""

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

from app.admin_api import router as admin_api_router
from app.core.config import settings
from app.core.http_security import SecurityHeadersMiddleware


_STATIC_DIR = Path(__file__).resolve().parent / "static" / "admin"


ADMIN_PAGE_HTML = """<!doctype html>
<html lang='ja'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Chabot 管理</title>
<link rel='stylesheet' href='/admin.css'>
</head>
<body>
<a class='skip-link' href='#main-content'>本文へスキップ</a>
<div class='app-shell'>
  <header class='app-header'>
    <div class='brand'>
      <span class='brand-mark' aria-hidden='true'>C</span>
      <div>
        <h1>Chabot 管理</h1>
        <p class='brand-sub'>Chabot 管理コンソール</p>
      </div>
    </div>
    <p class='env-badge' id='env-badge'><span aria-hidden='true'>●</span> <span id='env-badge-text'>接続確認中…</span></p>
  </header>
  <div class='app-body'>
    <nav class='section-nav' aria-label='管理メニュー'>
      <ul>
        <li><button type='button' data-section='overview'>集計</button></li>
        <li><button type='button' data-section='users'>ユーザー</button></li>
        <li><button type='button' data-section='settings'>回数上限設定</button></li>
        <li><button type='button' data-section='coupons'>クーポン</button></li>
        <li><button type='button' data-section='invites'>無料登録URL</button></li>
        <li><button type='button' data-section='conversations'>会話保管</button></li>
        <li><button type='button' data-section='feedback'>要望</button></li>
        <li><button type='button' data-section='audit'>監査ログ</button></li>
      </ul>
    </nav>
    <main id='main-content' class='section-main' tabindex='-1'>
      <noscript><p class='noscript-note'>この画面を操作するにはJavaScriptを有効にしてください。</p></noscript>
      <div id='section-host'></div>
    </main>
  </div>
</div>
<script src='/admin.js' defer></script>
</body>
</html>"""


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

    def _ensure_enabled() -> None:
        if not admin_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin UI is disabled",
            )

    async def _ensure_enabled_dependency() -> None:
        """管理APIルーター全体への有効化ゲート。"""
        _ensure_enabled()

    admin_app.include_router(
        admin_api_router,
        dependencies=[Depends(_ensure_enabled_dependency)],
    )

    @admin_app.get("/health", include_in_schema=False)
    async def health_check() -> dict[str, str]:
        """プロセス生存確認。個人情報や構成値は返さない。"""
        return {"status": "healthy"}

    @admin_app.get("/admin", response_class=HTMLResponse)
    async def admin_home() -> HTMLResponse:
        """ローカル開発用の管理コンソールHTMLを返す。"""
        _ensure_enabled()
        return HTMLResponse(ADMIN_PAGE_HTML)

    @admin_app.get("/admin.css")
    async def admin_stylesheet() -> FileResponse:
        """CSP準拠で管理画面のスタイルを同一オリジン配信する。"""
        _ensure_enabled()
        return FileResponse(_STATIC_DIR / "admin.css", media_type="text/css")

    @admin_app.get("/admin.js")
    async def admin_script() -> FileResponse:
        """CSP準拠で管理画面のスクリプトを同一オリジン配信する。"""
        _ensure_enabled()
        return FileResponse(_STATIC_DIR / "admin.js", media_type="text/javascript")

    return admin_app


app = create_admin_app()
