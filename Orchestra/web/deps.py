"""FastAPI 依存注入。

責務:
    - ``Settings``、``RateLimitTracker``、``ResilientAPIClient``、
      ``RoleManager``、``FeedbackManager`` をシングルトンとして提供する。

設計書: doc/ui/01_ui_overview.md §3 (deps.py 仕様)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Depends

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings
    from core.feedback import FeedbackManager
    from core.rate_tracker import RateLimitTracker
    from core.role_manager import RoleManager


# プロジェクトルート (このファイルから 1 階層上)
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = Path("config")
RATE_LIMIT_TRACKER_FILENAME = ".rate_tracker.json"
BASE_CLIENT_TIMEOUT_SEC = 180.0


@lru_cache(maxsize=1)
def get_settings() -> "Settings":
    """``Settings`` をロードしてシングルトンとして返す。"""
    from core.config_loader import Settings

    config_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR
    return Settings.load(config_dir=config_dir)


@lru_cache(maxsize=1)
def get_rate_tracker() -> "RateLimitTracker":
    """``RateLimitTracker`` をシングルトンとして返す。"""
    from core.rate_tracker import RateLimitTracker

    return RateLimitTracker(
        persistence_path=SCRIPT_DIR / RATE_LIMIT_TRACKER_FILENAME,
    )


_api_client_cache: "ResilientAPIClient | None" = None


def get_api_client(
    settings: "Settings" = Depends(get_settings),
    tracker: "RateLimitTracker" = Depends(get_rate_tracker),
) -> "ResilientAPIClient":
    """``ResilientAPIClient`` をシングルトンとして返す。

    ``Settings`` は dataclass で hashable でないため ``lru_cache`` は使えない。
    モジュールレベル変数で 1 度だけ生成する。
    """
    global _api_client_cache
    if _api_client_cache is not None:
        return _api_client_cache

    from core.api_client import ResilientAPIClient
    from core.openai_client import AsyncOpenAIClient

    base_client = AsyncOpenAIClient(
        api_key=settings.api_key,
        endpoint=settings.endpoint,
        mode=settings.mode or "openai",
        api_version=settings.api_version,
        timeout_sec=BASE_CLIENT_TIMEOUT_SEC,
    )
    _api_client_cache = ResilientAPIClient(
        base_client=base_client,
        rate_tracker=tracker,
        mode=settings.mode,
        endpoint=settings.endpoint,
        settings=settings,
    )
    return _api_client_cache


@lru_cache(maxsize=1)
def get_role_manager() -> "RoleManager":
    """``RoleManager`` をシングルトンとして返す。"""
    from core.role_manager import RoleManager

    roles_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR / "roles"
    return RoleManager(roles_dir=roles_dir)


@lru_cache(maxsize=1)
def get_feedback_manager() -> "FeedbackManager":
    """``FeedbackManager`` をシングルトンとして返す。"""
    from core.feedback import FeedbackManager

    roles_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR / "roles"
    return FeedbackManager(roles_dir=roles_dir)


__all__ = [
    "get_settings",
    "get_rate_tracker",
    "get_api_client",
    "get_role_manager",
    "get_feedback_manager",
    "SCRIPT_DIR",
]
