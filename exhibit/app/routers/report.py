# -*- coding: utf-8 -*-
"""レポート作成API"""

from __future__ import annotations
import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.models.schemas import (
    ExhibitionFetchRequest,
    RecommendRequest,
    ResearchRequest,
    RegenerateRequest,
    CompanyInput,
    ExhibitionInfo,
    ExportMarkdownRequest,
    ExportTextRequest,
    ConfigSaveRequest,
)
from app.services.exhibition import fetch_exhibition_info
from app.services.company import investigate_company
from app.services.recommendation import recommend_companies
from app.utils.markdown_export import generate_markdown, generate_visit_list_text
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/pre-research", response_class=HTMLResponse)
async def pre_research(request: Request):
    return templates.TemplateResponse(request, "pre_research.html")


@router.get("/post-report", response_class=HTMLResponse)
async def post_report(request: Request):
    return templates.TemplateResponse(request, "post_report.html")


@router.post("/api/exhibition/fetch")
async def api_exhibition_fetch(req: ExhibitionFetchRequest):
    result = await fetch_exhibition_info(url=req.url, name=req.name)
    return {"success": True, "data": result}


@router.post("/api/recommend")
async def api_recommend(req: RecommendRequest):
    companies = await recommend_companies(
        exhibition=req.exhibition,
        purpose=req.purpose,
        themes=req.themes,
    )
    return {"success": True, "companies": companies}


@router.post("/api/research")
async def api_research(req: ResearchRequest):
    """企業調査実行（SSEストリーミング）"""
    async def event_generator():
        start_time = time.time()
        total = len(req.companies)
        completed = 0

        # 並列実行（セマフォで制御）
        semaphore = asyncio.Semaphore(settings.MAX_PARALLEL_SEARCHES)

        async def investigate_with_progress(company: CompanyInput, idx: int):
            nonlocal completed
            async with semaphore:
                # 開始通知
                yield_data = {
                    "type": "progress",
                    "index": idx,
                    "company": company.name,
                    "status": "searching",
                    "completed": completed,
                    "total": total,
                }
                return yield_data, await investigate_company(
                    company=company,
                    exhibition=req.exhibition,
                    purpose=req.purpose,
                    themes=req.themes,
                )

        # タスクを作成
        tasks = []
        for i, company in enumerate(req.companies):
            tasks.append(investigate_company(
                company=company,
                exhibition=req.exhibition,
                purpose=req.purpose,
                themes=req.themes,
            ))

        # 進捗状況を送信しながら実行
        pending = set()
        results_ordered = [None] * total

        for i, company in enumerate(req.companies):
            # 検索開始を通知
            event = {
                "type": "start",
                "index": i,
                "company": company.name,
                "completed": completed,
                "total": total,
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # セマフォで並列制御しながら実行
        async def run_one(idx: int, company: CompanyInput):
            async with semaphore:
                return idx, await investigate_company(
                    company=company,
                    exhibition=req.exhibition,
                    purpose=req.purpose,
                    themes=req.themes,
                )

        # 全タスクを非同期で並行実行
        pending_tasks = [
            asyncio.create_task(run_one(i, c))
            for i, c in enumerate(req.companies)
        ]

        for coro in asyncio.as_completed(pending_tasks):
            # 全体タイムアウトは設けない（最後まで待つ）
            try:
                idx, result = await coro
                completed += 1
                result_dict = result.model_dump() if hasattr(result, "model_dump") else result
                results_ordered[idx] = result_dict

                event = {
                    "type": "result",
                    "index": idx,
                    "company": req.companies[idx].name,
                    "status": result.status,
                    "completed": completed,
                    "total": total,
                    "data": result_dict,
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                pass
            except Exception as e:
                completed += 1
                event = {
                    "type": "error",
                    "index": idx if 'idx' in dir() else -1,
                    "error": str(e),
                    "completed": completed,
                    "total": total,
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 完了通知
        elapsed = time.time() - start_time
        event = {
            "type": "done",
            "completed": completed,
            "total": total,
            "elapsed_sec": round(elapsed, 1),
            "results": [r for r in results_ordered if r is not None],
        }
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/regenerate")
async def api_regenerate(req: RegenerateRequest):
    """1社の再生成"""
    result = await investigate_company(
        company=req.company,
        exhibition=req.exhibition,
        purpose=req.purpose,
        themes=req.themes,
    )
    return {"success": True, "data": result.model_dump()}


@router.post("/api/export/markdown")
async def api_export_markdown(req: ExportMarkdownRequest):
    md = generate_markdown(
        exhibition=req.exhibition,
        purpose=req.purpose,
        themes=req.themes,
        results=req.results,
    )
    return {"success": True, "markdown": md}


@router.post("/api/export/text")
async def api_export_text(req: ExportTextRequest):
    text = generate_visit_list_text(
        exhibition=req.exhibition,
        companies=[c.model_dump() for c in req.companies],
        purpose=req.purpose,
        themes=req.themes,
    )
    return {"success": True, "text": text}


@router.post("/api/config/save")
async def api_config_save(req: ConfigSaveRequest):
    """ユーザー設定保存"""
    import json as json_mod
    from datetime import datetime
    user_dir = settings.USERS_DIR / req.user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    config_path = user_dir / "config.json"

    config = {
        "user_id": req.user_id,
        "themes": req.themes,
        "purpose": req.purpose,
        "dark_mode": req.dark_mode,
        "updated_at": datetime.now().isoformat(),
    }
    if config_path.exists():
        existing = json_mod.loads(config_path.read_text(encoding="utf-8"))
        config["created_at"] = existing.get("created_at", config["updated_at"])
    else:
        config["created_at"] = config["updated_at"]

    config_path.write_text(json_mod.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"success": True}


@router.get("/api/config/load")
async def api_config_load(user_id: str = "default"):
    """ユーザー設定読み込み"""
    import json as json_mod
    config_path = settings.USERS_DIR / user_id / "config.json"
    if config_path.exists():
        config = json_mod.loads(config_path.read_text(encoding="utf-8"))
        return {"success": True, "data": config}
    return {"success": True, "data": None}
