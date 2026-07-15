# -*- coding: utf-8 -*-
"""分析API"""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models.schemas import AnalysisExecuteRequest
from app.services.analysis import execute_analysis

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request):
    return templates.TemplateResponse(request, "analysis.html")


@router.post("/api/analysis/execute")
async def api_analysis_execute(req: AnalysisExecuteRequest):
    """選択した分析を実行"""
    tasks = [execute_analysis(req.report_data, t) for t in req.analyses]
    results = await asyncio.gather(*tasks)
    return {"success": True, "analyses": results}
