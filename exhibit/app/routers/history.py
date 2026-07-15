# -*- coding: utf-8 -*-
"""履歴API"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    return templates.TemplateResponse(request, "history.html")


@router.get("/api/history")
async def api_history_list(user_id: str = "default"):
    """履歴一覧取得"""
    reports_dir = settings.USERS_DIR / user_id / "reports"
    if not reports_dir.exists():
        return {"success": True, "reports": []}

    reports = []
    for f in sorted(reports_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reports.append({
                "report_id": data.get("report_id", f.stem),
                "mode": data.get("mode", ""),
                "exhibition_name": data.get("exhibition", {}).get("name", ""),
                "company_count": len(data.get("companies", [])),
                "created_at": data.get("created_at", ""),
            })
        except Exception:
            continue
    return {"success": True, "reports": reports}


@router.get("/api/history/{report_id}")
async def api_history_detail(report_id: str, user_id: str = "default"):
    """履歴詳細取得"""
    reports_dir = settings.USERS_DIR / user_id / "reports"
    report_path = reports_dir / f"{report_id}.json"
    if not report_path.exists():
        return {"success": False, "error": "レポートが見つかりません"}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return {"success": True, "data": data}


@router.post("/api/history/save")
async def api_history_save(request: Request):
    """レポート保存"""
    body = await request.json()
    user_id = body.get("user_id", "default")
    reports_dir = settings.USERS_DIR / user_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_id = body.get("report_id") or str(uuid.uuid4())
    report_data = {
        "report_id": report_id,
        "mode": body.get("mode", "post_report"),
        "exhibition": body.get("exhibition", {}),
        "purpose": body.get("purpose", ""),
        "themes": body.get("themes", []),
        "companies": body.get("companies", []),
        "results": body.get("results", []),
        "created_at": body.get("created_at", datetime.now().isoformat()),
        "updated_at": datetime.now().isoformat(),
    }

    report_path = reports_dir / f"{report_id}.json"
    report_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"success": True, "report_id": report_id}


@router.delete("/api/history/{report_id}")
async def api_history_delete(report_id: str, user_id: str = "default"):
    """個別レポート削除"""
    reports_dir = settings.USERS_DIR / user_id / "reports"
    report_path = reports_dir / f"{report_id}.json"
    if not report_path.exists():
        return {"success": False, "error": "レポートが見つかりません"}
    try:
        report_path.unlink()
        return {"success": True, "report_id": report_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/history/clear")
async def api_history_clear(request: Request):
    """全履歴削除"""
    body = await request.json() if request.headers.get("content-length") else {}
    user_id = body.get("user_id", "default")
    reports_dir = settings.USERS_DIR / user_id / "reports"
    if not reports_dir.exists():
        return {"success": True, "deleted_count": 0}
    deleted = 0
    for f in reports_dir.glob("*.json"):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            continue
    return {"success": True, "deleted_count": deleted}
