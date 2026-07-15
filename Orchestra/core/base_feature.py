"""機能フローの共通基底クラス。

Idea Discussion / Code Review など、複数の機能で 4 フェーズ構造
(入力 → 計画 → 議論 → 結果) を統一するための抽象基底とヘルパー。

- ``PhaseKey``: 全機能で共通のフェーズキー。SSE 通知や UI 分岐に使う。
- ``PhaseHandler``: 従来の ``on_phase(name)`` シグネチャ (下位互換用)。
- ``PhaseKeyHandler``: 新形式 ``on_phase(key, description)`` シグネチャ。
- ``DiscussionFeatureBase``: 共通の初期化と通知ヘルパーを提供する抽象基底。

設計方針:
    各 feature の ``run()`` シグネチャは機能ごとに異なるため、``run()`` は
    抽象化しない。代わりに ``_notify_phase(key, description)`` で通知形式を
    統一し、``PhaseKey`` によってフェーズ判定ロジックを一元化する。

参照: ``doc/design/03_architecture.md``
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .api_client import ResilientAPIClient
    from .config_loader import Settings
    from .feedback import FeedbackManager
    from .role_manager import RoleManager

logger = logging.getLogger(__name__)


class PhaseKey(str, Enum):
    """全機能で共通のフェーズキー。

    - ``INPUT``:      Phase 1 - 入力受付・バリデーション (Idea: user_input,
                      Review: フォルダスキャン)。
    - ``PLANNING``:   Phase 2 - 計画立案・調査 (Idea: Orchestrator.plan,
                      Review: findings 収集 + 相互質問)。
    - ``DISCUSSION``: Phase 3 - 議論本体 (Conductor.run_discussion)。
    - ``RESULT``:     Phase 4 - 結果生成 (統合・評価・出力ファイル書き出し)。
    """

    INPUT = "input"
    PLANNING = "planning"
    DISCUSSION = "discussion"
    RESULT = "result"


# フェーズ表示名 (SSE の name 欄・ログに使う)
PHASE_DISPLAY: dict[PhaseKey, str] = {
    PhaseKey.INPUT: "Phase 1: 入力",
    PhaseKey.PLANNING: "Phase 2: 計画",
    PhaseKey.DISCUSSION: "Phase 3: 議論",
    PhaseKey.RESULT: "Phase 4: 結果",
}


PhaseHandler = Callable[[str], None]
"""下位互換: 従来の ``on_phase(name)`` シグネチャ。"""

PhaseKeyHandler = Callable[[PhaseKey, str], None]
"""新形式: ``on_phase_key(key, name)`` シグネチャ。"""


class DiscussionFeatureBase:
    """機能フローの共通基底クラス。

    Attributes:
        api_client: 共有 API クライアント。
        role_manager: ロール定義の取得元。
        feedback_manager: フィードバック蓄積 (None なら蓄積しない)。
        settings: 全体設定。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        role_manager: "RoleManager",
        feedback_manager: "FeedbackManager | None",
        settings: "Settings",
    ) -> None:
        self.api_client = api_client
        self.role_manager = role_manager
        self.feedback_manager = feedback_manager
        self.settings = settings

    def notify_phase(
        self,
        key: PhaseKey,
        description: str | None = None,
        on_phase: PhaseHandler | None = None,
        on_phase_key: PhaseKeyHandler | None = None,
    ) -> None:
        """フェーズ開始をハンドラに通知する。

        Args:
            key: フェーズキー。
            description: フェーズ表示名 (None なら ``PHASE_DISPLAY[key]``)。
            on_phase: 下位互換の ``on_phase(name)`` handler。
            on_phase_key: 新形式の ``on_phase_key(key, name)`` handler。

        Notes:
            両方の handler を同時に呼ぶ。UI / CLI どちらの呼び出しにも
            対応できるようにするため、片方だけ渡すことも可能。
        """
        name = description or PHASE_DISPLAY.get(key, key.value)
        logger.info("phase %s: %s", key.value, name)

        if on_phase is not None:
            try:
                on_phase(name)
            except Exception as e:  # noqa: BLE001 - 通知失敗で本体を止めない
                logger.warning("on_phase(%s) raised %s", name, e)

        if on_phase_key is not None:
            try:
                on_phase_key(key, name)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "on_phase_key(%s, %s) raised %s", key.value, name, e
                )


__all__ = [
    "PhaseKey",
    "PHASE_DISPLAY",
    "PhaseHandler",
    "PhaseKeyHandler",
    "DiscussionFeatureBase",
]
