"""G-4: セッション完了 / エラー時の表示。

設計書: ``doc/16_cli_interface.md`` §16.5
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


COMPLETION_DIVIDER = "━" * 50
ERROR_DIVIDER = "━" * 50

_OUTPUT_FILES: tuple[tuple[str, str, str, bool], ...] = (
    ("report.md", "📄 レポート:", "label", False),
    ("full_conversation.md", "🎭 会話ログ:", "label", False),
    ("evaluation.md", "📊 評価:   ", "label", False),
    ("summary.txt", "📋 要約:   ", "label", False),
    # vibe_coding_prompt.md は機能②のみ存在
    ("vibe_coding_prompt.md", "🤖 修正指示:", "label", True),
)


class CompletionDisplay:
    """セッション完了・エラー時のリッチ表示。"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def show_completion(
        self,
        output_path: Path,
        statistics: dict[str, Any],
    ) -> None:
        """セッション完了表示。

        Args:
            output_path: ``output_dir/{session_id}/`` の Path。
            statistics: ``total_requests`` / ``total_tokens`` /
                ``duration_sec`` / ``convergence`` を含む辞書。
                欠けたキーは 0 として表示する。
        """
        self.console.print()
        self.console.print(COMPLETION_DIVIDER)
        self.console.print("[bold green]✅ セッション完了！[/bold green]")
        self.console.print()
        self._show_output_files(Path(output_path))
        self.console.print()
        self._show_statistics(statistics)
        self.console.print(COMPLETION_DIVIDER)

    def show_error(
        self,
        error: BaseException | str,
        partial_output_path: Path | None = None,
    ) -> None:
        """エラー時の表示。

        Args:
            error: 例外オブジェクトまたはメッセージ。
            partial_output_path: 部分的に書き出された出力ディレクトリ
                (任意)。``None`` ならその行はスキップ。
        """
        self.console.print()
        self.console.print(ERROR_DIVIDER)
        self.console.print("[bold red]❌ エラーが発生しました[/bold red]")
        self.console.print()
        error_class = type(error).__name__ if isinstance(error, BaseException) else "Error"
        self.console.print(f"[red]{error_class}:[/red] {error}")
        if partial_output_path is not None:
            path = Path(partial_output_path)
            self.console.print(
                f"\n💾 部分出力: [link]{path}[/link]"
            )
        self.console.print(ERROR_DIVIDER)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _show_output_files(self, output_path: Path) -> None:
        for filename, label, _style, optional in _OUTPUT_FILES:
            file_path = output_path / filename
            if optional and not file_path.exists():
                continue
            self.console.print(f"{label} [link]{file_path}[/link]")

    def _show_statistics(self, statistics: dict[str, Any]) -> None:
        total_requests = int(statistics.get("total_requests", 0) or 0)
        total_tokens = int(statistics.get("total_tokens", 0) or 0)
        duration_sec = float(statistics.get("duration_sec", 0.0) or 0.0)
        convergence = float(statistics.get("convergence", 0.0) or 0.0)
        self.console.print(
            f"📈 統計: {total_requests} req | "
            f"{total_tokens:,} tokens | "
            f"{duration_sec:.0f}秒 | "
            f"収束 {convergence:.2f}"
        )


__all__ = ["CompletionDisplay", "COMPLETION_DIVIDER", "ERROR_DIVIDER"]
