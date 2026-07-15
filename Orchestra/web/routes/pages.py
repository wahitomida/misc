"""HTML ページルーティング。

設計書: doc/ui/02_page_structure.md §1.3
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def _templates():
    """循環 import を避けるため遅延 import で取得する。"""
    from web.app import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Hero ランディングページ。"""
    return _templates().TemplateResponse(
        request,
        "pages/home.html",
        {},
    )


@router.get("/idea", response_class=HTMLResponse)
async def idea(request: Request, follow_up: str | None = None) -> HTMLResponse:
    """Idea 議論ページ。``follow_up`` でフォローアップモード。"""
    return _templates().TemplateResponse(
        request,
        "pages/idea.html",
        {"follow_up_id": follow_up},
    )


@router.get("/review", response_class=HTMLResponse)
async def review(request: Request) -> HTMLResponse:
    """Code Review ページ。"""
    return _templates().TemplateResponse(
        request,
        "pages/review.html",
        {},
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request) -> HTMLResponse:
    """セッション履歴ページ。"""
    return _templates().TemplateResponse(
        request,
        "pages/history.html",
        {},
    )


@router.get("/replay/{session_id}", response_class=HTMLResponse)
async def replay(request: Request, session_id: str) -> HTMLResponse:
    """セッション再表示ページ。"""
    return _templates().TemplateResponse(
        request,
        "pages/replay.html",
        {"session_id": session_id},
    )


@router.get("/roles", response_class=HTMLResponse)
async def roles(request: Request) -> HTMLResponse:
    """ロール管理ページ。"""
    return _templates().TemplateResponse(
        request,
        "pages/roles.html",
        {},
    )
