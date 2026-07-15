"""G-2: 議論進行中のリアルタイム表示。

責務:
    - ラウンド開始ヘッダ
    - 1 発言ごとの絵文字付きパネル表示
    - 収束判定スコアの色付き表示
    - 指揮者の内心メモ (verbose 時のみ)

設計書: ``doc/16_cli_interface.md`` §16.4.3, §16.5
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

if TYPE_CHECKING:
    from core.data_models import ConvergenceResult, RoundConfig, Utterance
    from core.time_keeper import TimeKeeper

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------


CONVERGENCE_HIGH_THRESHOLD = 0.8
CONVERGENCE_MID_THRESHOLD = 0.5

PANEL_MAX_WIDTH = 80
PANEL_PADDING = 4

_MODEL_SHORT_NAMES: dict[str, str] = {
    "claude-sonnet-4-5": "claude-s4-5",
    "claude-sonnet-4": "claude-s4",
}


class DiscussionDisplay:
    """議論中の Rich 表示を司る。"""

    EMOJI_MAP: dict[str, str] = {
        "theorist": "🧮",
        "experimentalist": "🔬",
        "implementer": "🤖",
        "literature": "📚",
        "devil": "😈",
        "bird_eye": "🎯",
        "code_architect": "📐",
        "code_reviewer": "📝",
        "conductor": "🎵",
    }

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def show_round_start(
        self,
        round_config: "RoundConfig",
        time_keeper: "TimeKeeper",
    ) -> None:
        """ラウンド開始の区切り線を表示する。"""
        remaining = float(time_keeper.remaining)
        self.console.print(
            f"\n── [bold]Round {round_config.round}: "
            f"{round_config.phase_name}[/bold] "
            f"── ({round_config.pattern}, level={round_config.level}) "
            f"── 残り{remaining:.0f}秒 ──"
        )

    def show_utterance(self, utterance: "Utterance") -> None:
        """1 つの発言をパネル表示する。"""
        emoji = self.EMOJI_MAP.get(utterance.speaker, "🤖")
        model_short = _shorten_model_name(utterance.model)
        title = (
            f"{emoji} {utterance.speaker} "
            f"({model_short}, {utterance.duration_sec:.1f}s)"
        )
        border = "blue" if utterance.type == "discussion" else "dim"
        width = self._panel_width()
        self.console.print(
            Panel(
                utterance.content,
                title=title,
                border_style=border,
                width=width,
            )
        )

    def show_convergence(self, result: "ConvergenceResult") -> None:
        """収束判定結果を色付きで表示する。"""
        color = self._convergence_color(result.score)
        self.console.print(
            f"\n[{color}]📈 収束: {result.score:.2f}[/{color}] "
            f"— {result.reasoning}"
        )

    def show_orchestrator_memo(self, memo: str) -> None:
        """指揮者の内心メモを薄字で表示する (verbose 時のみ呼ぶ想定)。"""
        if not memo:
            return
        self.console.print(f"[dim]🎼 [内心] {memo}[/dim]")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convergence_color(score: float) -> str:
        if score >= CONVERGENCE_HIGH_THRESHOLD:
            return "green"
        if score >= CONVERGENCE_MID_THRESHOLD:
            return "yellow"
        return "red"

    def _panel_width(self) -> int:
        try:
            console_width = int(self.console.width)
        except (AttributeError, TypeError, ValueError):
            console_width = PANEL_MAX_WIDTH + PANEL_PADDING
        return min(PANEL_MAX_WIDTH, console_width - PANEL_PADDING)


def _shorten_model_name(model: str) -> str:
    return _MODEL_SHORT_NAMES.get(model, model)


__all__ = [
    "DiscussionDisplay",
    "CONVERGENCE_HIGH_THRESHOLD",
    "CONVERGENCE_MID_THRESHOLD",
]
