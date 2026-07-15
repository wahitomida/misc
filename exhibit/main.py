# -*- coding: utf-8 -*-
"""ExhibiReport - 展示会調査レポート自動生成Webアプリケーション"""

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routers import report, analysis, history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="ExhibiReport", version="1.0.0")

# 静的ファイル配信
app.mount("/static", StaticFiles(directory="static"), name="static")

# テンプレート
templates = Jinja2Templates(directory="templates")

# ルーター登録
app.include_router(report.router)
app.include_router(analysis.router)
app.include_router(history.router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
