"""``main.py`` 用の共通ヘルパー群 (logging / settings 構築 / features 生成)。

責務:
    - 設定ファイル位置の定数
    - logging レベル切り替え
    - ``Settings.load`` ラッパー (CLI 用エラーハンドリング込み)
    - ``IdeaDiscussion`` / ``CodeReview`` の組み立て (API クライアント生成)
    - CLI トップでの統一エラー表示

これらをここに切り出すことで ``main.py`` を CLI 構造の宣言に集中させる。

設計書: ``doc/16_cli_interface.md`` §16.1, §16.3
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from core.config_loader import Settings

logger = logging.getLogger(__name__)
console = Console()


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_OUTPUT_DIR = Path("./output")
HISTORY_DEFAULT_LIMIT = 10
RATE_LIMIT_TRACKER_FILENAME = ".rate_tracker.json"
# ベースクライアントの安全マージン timeout (秒)。
# 実際の per-request timeout は ResilientAPIClient が
# settings.get_timeout(model) で解決する。ここはその上限の役割。
BASE_CLIENT_TIMEOUT_SEC = 180.0

REPLAY_SECTIONS: tuple[str, ...] = (
    "conversation",
    "report",
    "evaluation",
    "summary",
)
SECTION_TO_FILENAME: dict[str, str] = {
    "conversation": "full_conversation.md",
    "report": "report.md",
    "evaluation": "evaluation.md",
    "summary": "summary.txt",
}


# ----------------------------------------------------------------------
# logging
# ----------------------------------------------------------------------


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """CLI の ``-v`` / ``-q`` に応じて ``logging`` レベルを切り替える。"""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


# ----------------------------------------------------------------------
# settings
# ----------------------------------------------------------------------


def load_settings() -> "Settings":
    """``Settings.load`` を CLI 用のエラーハンドリング込みで呼ぶ。"""
    from core.config_loader import Settings
    from core.exceptions import ConfigLoadError

    config_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR
    try:
        return Settings.load(config_dir=config_dir)
    except ConfigLoadError as e:
        print_error_and_exit(e)
        raise  # never reached


# ----------------------------------------------------------------------
# features 構築
# ----------------------------------------------------------------------


def build_idea_discussion(
    settings: "Settings",
    no_confirm: bool = False,
):
    """``IdeaDiscussion`` を初期化する (API クライアント + マネージャ群を組み立て)。"""
    from features.idea_discussion import IdeaDiscussion

    api_client = _build_api_client(settings)
    role_manager, feedback_manager = _build_role_managers()

    confirm = (lambda _plan: True) if no_confirm else None
    if confirm is None:
        return IdeaDiscussion(
            api_client=api_client,
            role_manager=role_manager,
            feedback_manager=feedback_manager,
            settings=settings,
        )
    return IdeaDiscussion(
        api_client=api_client,
        role_manager=role_manager,
        feedback_manager=feedback_manager,
        settings=settings,
        confirm_callback=confirm,
    )


def build_code_review(settings: "Settings"):
    """``CodeReview`` を初期化する。"""
    from features.code_review import CodeReview

    api_client = _build_api_client(settings)
    role_manager, feedback_manager = _build_role_managers()
    return CodeReview(
        api_client=api_client,
        role_manager=role_manager,
        feedback_manager=feedback_manager,
        settings=settings,
    )


def _build_api_client(settings: "Settings"):
    """``ResilientAPIClient`` を組み立てる。

    API キーがない場合はその場で ``typer.Exit`` で終了する
    (``--help`` / ``list-roles`` パスはここを通らない設計)。
    """
    from core.api_client import ResilientAPIClient
    from core.openai_client import AsyncOpenAIClient
    from core.rate_tracker import RateLimitTracker

    if not settings.api_key:
        console.print(
            "[red]❌ API キーが設定されていません。"
            "[/red]"
        )
        console.print(
            "[dim]config/.env または環境変数 (KOTOBUDDY_API_KEY / "
            "AZURE_OPENAI_API_KEY) を設定してください。[/dim]"
        )
        raise typer.Exit(code=2)

    base_client = AsyncOpenAIClient(
        api_key=settings.api_key,
        endpoint=settings.endpoint,
        mode=settings.mode or "openai",
        api_version=settings.api_version,
        timeout_sec=BASE_CLIENT_TIMEOUT_SEC,
    )
    tracker = RateLimitTracker(
        persistence_path=SCRIPT_DIR / RATE_LIMIT_TRACKER_FILENAME,
    )
    return ResilientAPIClient(
        base_client=base_client,
        rate_tracker=tracker,
        mode=settings.mode,
        endpoint=settings.endpoint,
        settings=settings,
    )


def _build_role_managers():
    """``RoleManager`` と ``FeedbackManager`` を構築する。"""
    from core.feedback import FeedbackManager
    from core.role_manager import RoleManager

    roles_dir = SCRIPT_DIR / DEFAULT_CONFIG_DIR / "roles"
    role_manager = RoleManager(roles_dir=roles_dir)
    feedback_manager = FeedbackManager(roles_dir=roles_dir)
    return role_manager, feedback_manager


# ----------------------------------------------------------------------
# error 表示
# ----------------------------------------------------------------------


def print_error_and_exit(error: BaseException) -> None:
    """例外を Rich でフォーマットして CLI を終了する。"""
    error_class = type(error).__name__
    console.print(f"\n[red]❌ {error_class}:[/red] {error}")
    raise typer.Exit(code=1)


__all__ = [
    "SCRIPT_DIR",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_OUTPUT_DIR",
    "HISTORY_DEFAULT_LIMIT",
    "REPLAY_SECTIONS",
    "SECTION_TO_FILENAME",
    "RATE_LIMIT_TRACKER_FILENAME",
    "configure_logging",
    "load_settings",
    "build_idea_discussion",
    "build_code_review",
    "print_error_and_exit",
]
