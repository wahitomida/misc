"""G-3: 経過時間 / 残り時間の進捗バー表示 (``rich.progress``)。

設計書: ``doc/16_cli_interface.md`` §16.4.4
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

logger = logging.getLogger(__name__)


DEFAULT_TASK_DESCRIPTION = "議論進行中"
BAR_WIDTH = 30


class TimeDisplay:
    """``rich.progress.Progress`` でラップした時間表示。

    Attributes:
        time_limit: 進捗バーの total となる秒数。
        progress: ``rich.progress.Progress`` インスタンス。
        task_id: ``add_task`` で得たタスク ID (未開始は ``None``)。
    """

    def __init__(
        self,
        time_limit: float,
        console: Console | None = None,
        description: str = DEFAULT_TASK_DESCRIPTION,
    ) -> None:
        self.time_limit = float(time_limit)
        self.description = description
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=BAR_WIDTH),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TextColumn("残り [bold]{task.fields[remaining]}[/bold]s"),
            console=console,
        )
        self.task_id: TaskID | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """進捗バーを開始しタスクを 1 つ追加する。"""
        self.progress.start()
        self.task_id = self.progress.add_task(
            self.description,
            total=self.time_limit,
            remaining=f"{self.time_limit:.0f}",
        )

    def update(self, elapsed: float, remaining: float) -> None:
        """``elapsed`` / ``remaining`` の値で進捗を更新する。

        ``start()`` 未呼び出しなら無視する。
        """
        if self.task_id is None:
            return
        self.progress.update(
            self.task_id,
            completed=max(0.0, float(elapsed)),
            remaining=f"{max(0.0, float(remaining)):.0f}",
        )

    def stop(self) -> None:
        """進捗バーを停止する。複数回呼んでも安全。"""
        try:
            self.progress.stop()
        except Exception as e:  # noqa: BLE001 - 二重 stop は警告のみ
            logger.debug("TimeDisplay.stop ignored: %s", e)

    # ------------------------------------------------------------------
    # context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "TimeDisplay":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.stop()


# ======================================================================
# PhaseProgress: フェーズベース進捗バー
# ======================================================================

PHASE_BAR_WIDTH = 40


class PhaseProgress:
    """フェーズ単位で進捗を表示するシンプルなバー。

    Attributes:
        total_phases: フェーズ総数。
        progress: Rich Progress インスタンス。
    """

    def __init__(
        self,
        total_phases: int,
        console: Console | None = None,
    ) -> None:
        self.total_phases = total_phases
        self._console = console
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=PHASE_BAR_WIDTH),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed:.0f}/{task.total:.0f})"),
            console=console,
            transient=False,
        )
        self.task_id: TaskID | None = None

    def start(self) -> None:
        """進捗バーを開始する。"""
        self.progress.start()
        self.task_id = self.progress.add_task(
            "準備中...",
            total=self.total_phases,
        )

    def advance(self, description: str) -> None:
        """次フェーズに進む。

        Args:
            description: 現在フェーズの説明テキスト。
        """
        if self.task_id is None:
            return
        self.progress.update(
            self.task_id,
            advance=1,
            description=description,
        )

    def complete(self) -> None:
        """全フェーズ完了として 100% にする。"""
        if self.task_id is None:
            return
        self.progress.update(
            self.task_id,
            completed=self.total_phases,
            description="✅ 完了",
        )

    def stop(self) -> None:
        """進捗バーを停止する。"""
        try:
            self.progress.stop()
        except Exception as e:  # noqa: BLE001
            logger.debug("PhaseProgress.stop ignored: %s", e)

    def __enter__(self) -> "PhaseProgress":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.stop()


__all__ = ["TimeDisplay", "PhaseProgress", "DEFAULT_TASK_DESCRIPTION"]
