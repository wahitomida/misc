"""人間介入インターフェース。

責務:
    - ``Conductor`` が各ラウンド間 / 進捗イベントで人間からの介入を確認する
      標準インターフェースを定義する。
    - v1.0 では ``NoIntervention`` (常に介入なし) のみ提供。CLI 経由の対話
      介入 (``CLIIntervention``) や WebSocket 経由 (``WebIntervention``) は
      将来フェーズで追加する。
    - Web UI 用 SSE 配信のため ``SSEInterventionHandler`` を提供。

設計書: ``doc/05_conductor.md`` §5.7, ``doc/ui/08_sse_realtime.md`` §6.3
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any


logger = logging.getLogger(__name__)


class InterventionHandler(ABC):
    """人間介入の抽象インターフェース。

    実装側は ``check_intervention`` と ``notify_progress`` を実装する。
    """

    @abstractmethod
    def check_intervention(
        self,
        round_num: int,
        context: dict[str, Any],
    ) -> str | None:
        """各ラウンド間で人間からの介入を確認する。

        Args:
            round_num: 現在のラウンド番号 (1-indexed)。
            context: 議論の現在状態 (``convergence`` / ``summary`` /
                ``remaining_time`` / ``completed_rounds`` などを含む辞書)。

        Returns:
            ``None`` なら介入なし (自動続行)。文字列なら人間からの指示。
        """

    @abstractmethod
    def notify_progress(self, event: str, data: dict[str, Any]) -> None:
        """進捗イベントを通知する (UI 更新用)。

        実装側は副作用のみで戻り値なし。例外を投げないこと。

        Args:
            event: イベント名 (例: ``"round_complete"``)。
            data: 任意のペイロード。
        """


class NoIntervention(InterventionHandler):
    """初期版: 介入なし。全て自動進行する。"""

    def check_intervention(
        self,
        round_num: int,
        context: dict[str, Any],
    ) -> str | None:
        """常に ``None`` を返す。"""
        del round_num, context
        return None

    def notify_progress(self, event: str, data: dict[str, Any]) -> None:
        """何もしない (no-op)。"""
        del event, data


class SSEInterventionHandler(InterventionHandler):
    """Web UI 向け SSE 配信用 ``InterventionHandler``。

    コアエンジンの進捗イベントを ``asyncio.Queue`` に投入し、
    SSE エンドポイントがキューから取り出してストリームに流す。

    ``notify_progress`` は同期メソッドだが、内部で event loop に
    キュー投入をスケジュールするため、Conductor が ``await`` 無しで
    呼び出しても安全。``await`` で呼びたい場合は
    ``notify_progress_async`` を使う。

    設計書: ``doc/ui/08_sse_realtime.md`` §6.3

    Attributes:
        queue: イベント送出先キュー (``{"type": event, ...}`` を put する)。
    """

    def __init__(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        self._queue = queue
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def check_intervention(
        self,
        round_num: int,
        context: dict[str, Any],
    ) -> str | None:
        """常に ``None`` を返す (将来 WebSocket 経由で介入を追加可能)。"""
        del round_num, context
        return None

    def notify_progress(self, event: str, data: dict[str, Any]) -> None:
        """進捗イベントを (非同期で) キューに送信する。

        例外は内部で吸収し、ログに警告を残すのみ。
        """
        payload: dict[str, Any] = {"type": event, **data}
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full; dropping event: %s", event
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("SSE notify_progress failed: %s", e)

    async def notify_progress_async(
        self, event: str, data: dict[str, Any]
    ) -> None:
        """進捗イベントを await でキューに送信する。

        キューが満杯ならバックプレッシャーとして待機する。
        """
        await self._queue.put({"type": event, **data})


__all__ = [
    "InterventionHandler",
    "NoIntervention",
    "SSEInterventionHandler",
]
