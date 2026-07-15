"""G-1: 計画 (``OrchestraPlan``) の Rich 表示。

責務:
    - Phase 1 終了直後にユーザーへ ODSC / 参加 AI / ラウンド計画 / 統計を提示
    - ``--no-confirm`` でないかぎり実行確認プロンプトを表示

設計書: ``doc/16_cli_interface.md`` §16.4.1, §16.4.2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from core.data_models import OrchestraPlan
    from core.rate_tracker import RateLimitTracker

logger = logging.getLogger(__name__)


CONFIRM_PROMPT = "\n▶ 実行しますか？ [Y/n]: "
_YES_RESPONSES = frozenset({"", "y", "yes"})


class PlanDisplay:
    """``OrchestraPlan`` を Rich で視覚的に表示する。

    Attributes:
        console: 表示先 ``rich.console.Console``。テスト時はファイル出力等に
            差し替えられる。
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def show(
        self,
        plan: "OrchestraPlan",
        rate_tracker: "RateLimitTracker",
    ) -> None:
        """ODSC + 参加 AI + ラウンドテーブル + 統計を表示する。"""
        self._show_odsc(plan)
        self._show_agents(plan)
        self._show_round_table(plan)
        self._show_statistics(plan, rate_tracker)

    def confirm_execution(self, no_confirm: bool = False) -> bool:
        """ユーザーに実行確認する。``no_confirm=True`` なら即 ``True``。"""
        if no_confirm:
            return True
        try:
            response = self.console.input(CONFIRM_PROMPT).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return response in _YES_RESPONSES

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _show_odsc(self, plan: "OrchestraPlan") -> None:
        odsc = plan.odsc
        self.console.print(
            Panel(
                f"[bold]Objective:[/bold] {odsc.objective}\n"
                f"[bold]Deliverable:[/bold] {odsc.deliverable}\n"
                f"[bold]Success Criteria:[/bold] {odsc.success_criteria}",
                title="🎯 ODSC",
                border_style="blue",
            )
        )

    def _show_agents(self, plan: "OrchestraPlan") -> None:
        if not plan.selected_agents:
            self.console.print("\n🤖 参加AI: (なし)")
            return
        agents_str = " / ".join(
            f"{a.role_id}({a.model})" for a in plan.selected_agents
        )
        self.console.print(f"\n🤖 参加AI: {agents_str}")

    def _show_round_table(self, plan: "OrchestraPlan") -> None:
        if plan.discussion_plan is None or not plan.discussion_plan.round_config:
            self.console.print("[dim](ラウンド計画なし)[/dim]")
            return

        table = Table(
            title="🎼 議論計画",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Round", style="cyan", width=6)
        table.add_column("Phase", style="magenta", width=20)
        table.add_column("参加者", style="green", width=20)
        table.add_column("Pattern", style="yellow", width=10)
        table.add_column("Level", style="red", width=8)
        table.add_column("時間", style="white", width=6)

        for rc in plan.discussion_plan.round_config:
            speakers = ", ".join(rc.speakers)
            table.add_row(
                str(rc.round),
                rc.phase_name,
                speakers,
                rc.pattern,
                rc.level,
                f"{rc.time_budget_sec:.0f}s",
            )
        self.console.print(table)

    def _show_statistics(
        self,
        plan: "OrchestraPlan",
        rate_tracker: "RateLimitTracker",
    ) -> None:
        dp = plan.discussion_plan
        if dp is not None:
            self.console.print(
                f"\n📊 予想リクエスト数: "
                f"[bold]{dp.total_estimated_requests}[/bold]"
            )
            self.console.print(
                f"⏱️  予想所要時間: "
                f"[bold]{dp.total_estimated_time_sec:.0f}秒[/bold]"
            )
        remaining = rate_tracker.remaining()
        self.console.print(
            f"🔑 日次残りリクエスト: [bold]{remaining}[/bold] / "
            f"{rate_tracker.daily_limit}"
        )


__all__ = ["PlanDisplay", "CONFIRM_PROMPT"]
