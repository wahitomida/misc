# -*- coding: utf-8 -*-
"""アプリケーション設定"""

import os
from pathlib import Path
from dotenv import load_dotenv
import vertexai

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
    GCP_LOCATION: str = os.getenv("GCP_LOCATION", "us-central1")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gemini-2.5-flash")
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    MAX_PARALLEL_SEARCHES: int = int(os.getenv("MAX_PARALLEL_SEARCHES", "5"))
    SEARCH_TIMEOUT_SEC: int = int(os.getenv("SEARCH_TIMEOUT_SEC", "30"))  # （未使用）
    OVERALL_TIMEOUT_SEC: int = 180  # （未使用）
    DATA_DIR: Path = BASE_DIR / "data"
    USERS_DIR: Path = DATA_DIR / "users"
    EXPORTS_DIR: Path = DATA_DIR / "exports"

    def __init__(self):
        if not self.GCP_PROJECT_ID:
            raise RuntimeError(".env の GCP_PROJECT_ID が設定されていません。")
        self.USERS_DIR.mkdir(parents=True, exist_ok=True)
        self.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        vertexai.init(project=self.GCP_PROJECT_ID, location=self.GCP_LOCATION)


settings = Settings()
