"""AI Orchestra Web UI — FastAPI アプリケーション定義。

責務:
    - FastAPI インスタンス生成
    - Jinja2Templates 設定
    - 静的ファイルマウント (/static)
    - CORS ミドルウェア (開発時のみ)
    - 404 / 500 エラーハンドラ (API: JSON / Page: HTML)
    - ルーター登録

デバッグモード:
    環境変数 ``ORCHESTRA_DEBUG=1`` をセットすると、
    CORS と Swagger UI (``/api/docs``) が有効化される。
    ``serve.py --debug`` はこの変数を自動でセットする。

設計書: doc/ui/01_ui_overview.md, doc/ui/02_page_structure.md
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from web.routes import api_idea, api_review, api_roles, api_sessions, pages

logger = logging.getLogger(__name__)

# Constants
WEB_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# 開発モードの判定 (環境変数を serve.py からセット)
DEBUG_MODE = os.getenv("ORCHESTRA_DEBUG", "").lower() in ("1", "true", "yes")

# 開発用 CORS 許可オリジン
def _dev_cors_origins() -> list[str]:
    """開発時に許可するオリジン一覧を返す。"""
    return [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

# Jinja2 テンプレート (他モジュールから import 可能)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _is_api_request(request: Request) -> bool:
    """リクエストが API 系か (JSON を期待しているか) を判定する。"""
    if request.url.path.startswith("/api/"):
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def create_app() -> FastAPI:
    """FastAPI アプリケーションを生成する。

    デバッグモード (``ORCHESTRA_DEBUG=1``) では Swagger UI と
    localhost CORS を有効化する。本番モードではどちらも無効。
    """
    docs_url = "/api/docs" if DEBUG_MODE else None

    app = FastAPI(
        title="AI Orchestra",
        description="複数のAI専門家が議論・レビューを行うマルチエージェントシステム",
        version="1.0.0",
        docs_url=docs_url,
        redoc_url=None,
    )

    # CORS (開発時のみ)
    if DEBUG_MODE:
        logger.info("Debug mode: CORS enabled for %s", _dev_cors_origins())
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_dev_cors_origins(),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 静的ファイル
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ルーター登録
    app.include_router(pages.router)
    app.include_router(api_sessions.router)
    app.include_router(api_idea.router)
    app.include_router(api_review.router)
    app.include_router(api_roles.router)

    # 404 ハンドラ
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> HTMLResponse | JSONResponse:
        if exc.status_code == 404:
            if _is_api_request(request):
                return JSONResponse(
                    status_code=404,
                    content={"error": "not_found", "detail": str(exc.detail)},
                )
            return templates.TemplateResponse(
                request,
                "errors/404.html",
                {},
                status_code=404,
            )
        # その他の HTTPException は標準処理に委譲
        if _is_api_request(request):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": "http_error", "detail": str(exc.detail)},
            )
        return HTMLResponse(
            content=f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>",
            status_code=exc.status_code,
        )

    # 500 ハンドラ (予期しない例外)
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> HTMLResponse | JSONResponse:
        logger.exception("Unhandled exception in %s", request.url.path)
        if _is_api_request(request):
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "detail": str(exc),
                },
            )
        return templates.TemplateResponse(
            request,
            "errors/500.html",
            {"error_detail": str(exc)},
            status_code=500,
        )

    @app.get("/api/health")
    async def health() -> JSONResponse:
        """ヘルスチェック。

        設定・APIコントローラ・SSEセマフォの状態を返す。
        詳細は doc/ui/10_web_api.md §7.1。
        """
        from web.deps import get_rate_tracker, get_settings
        from web.routes.api_idea import MAX_CONCURRENT_SESSIONS, _sse_semaphore

        version = "1.0.0"

        try:
            settings = get_settings()
            tracker = get_rate_tracker()
            remaining = tracker.remaining()
            daily = int(tracker.daily_limit)
            mode = settings.mode or "openai"
            model_available = bool(settings.api_key)
        except Exception as e:  # noqa: BLE001
            logger.warning("health check degraded: %s", e)
            return JSONResponse({
                "status": "degraded",
                "mode": None,
                "model_available": False,
                "error": str(e),
                "rate_limit_remaining": None,
                "rate_limit_daily": None,
                "active_sessions": 0,
                "max_sessions": MAX_CONCURRENT_SESSIONS,
                "version": version,
            })

        # セマフォの現在値からアクティブセッション数を推定
        try:
            available = int(_sse_semaphore._value)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            available = MAX_CONCURRENT_SESSIONS
        active = MAX_CONCURRENT_SESSIONS - available

        return JSONResponse({
            "status": "ok" if model_available else "degraded",
            "mode": mode,
            "model_available": model_available,
            "rate_limit_remaining": remaining,
            "rate_limit_daily": daily,
            "active_sessions": active,
            "max_sessions": MAX_CONCURRENT_SESSIONS,
            "version": version,
        })

    return app


app = create_app()
