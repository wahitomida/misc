"""日次 API リクエスト数を追跡し、ファイルへ永続化する。

KotoBuddy API の日次 10,000 リクエスト上限を超過しないため、起動・終了を
またいでカウンターを維持する。日付が変わるとカウンターはリセットされる。

参照: ``doc/15_error_handling.md`` §15.4
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# Constants
DEFAULT_DAILY_LIMIT = 10000
DEFAULT_SAFETY_MARGIN = 0.9
DEFAULT_PERSISTENCE_PATH = Path(".orchestra_rate_limit.json")

logger = logging.getLogger(__name__)


@dataclass
class RateLimitTracker:
    """日次リクエスト数の追跡とディスク永続化を行う。

    Attributes:
        daily_limit: 日次上限 (デフォルト 10,000)。
        safety_margin: ``can_proceed`` 判定に使う安全マージン (0〜1.0)。
        request_count: 当日のリクエスト消費数。
        last_reset: 最後にリセットした日付 (``date``)。
        persistence_path: カウンターを永続化する JSON ファイルのパス。
    """

    daily_limit: int = DEFAULT_DAILY_LIMIT
    safety_margin: float = DEFAULT_SAFETY_MARGIN
    request_count: int = 0
    last_reset: date = field(default_factory=date.today)
    persistence_path: Path = field(default_factory=lambda: DEFAULT_PERSISTENCE_PATH)

    def __post_init__(self) -> None:
        """ファイルから過去状態を復元する。"""
        # Path 以外で渡された場合は変換しておく (テスト互換)
        self.persistence_path = Path(self.persistence_path)
        self._load()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def increment(self, n: int = 1) -> None:
        """リクエスト数を ``n`` だけ増やしてファイルに保存する。

        Args:
            n: 増分。デフォルト 1。
        """
        self._check_reset()
        self.request_count += n
        self._save()

    def remaining(self) -> int:
        """当日の残りリクエスト数を返す。"""
        self._check_reset()
        return self.daily_limit - self.request_count

    def can_proceed(self, estimated_requests: int) -> bool:
        """``estimated_requests`` を追加消費しても安全マージン内に収まるか判定する。

        Args:
            estimated_requests: これから消費する予定のリクエスト数。

        Returns:
            ``(request_count + estimated_requests) < daily_limit * safety_margin``
            を満たすなら ``True``。
        """
        self._check_reset()
        threshold = self.daily_limit * self.safety_margin
        return (self.request_count + estimated_requests) < threshold

    def utilization(self) -> float:
        """使用率 (0.0〜) を返す。日次上限を超えた場合は 1.0 を超え得る。"""
        self._check_reset()
        if self.daily_limit <= 0:
            return 0.0
        return self.request_count / self.daily_limit

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _check_reset(self) -> None:
        """日付が変わっていれば ``request_count`` をリセットする。"""
        today = date.today()
        if today != self.last_reset:
            logger.info(
                "Daily rate counter reset: %s -> %s (was %d requests)",
                self.last_reset,
                today,
                self.request_count,
            )
            self.request_count = 0
            self.last_reset = today
            self._save()

    def _save(self) -> None:
        """現在の状態を JSON ファイルに書き出す。書込失敗は警告のみ。"""
        data = {
            "request_count": self.request_count,
            "last_reset": self.last_reset.isoformat(),
        }
        try:
            self.persistence_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to persist rate tracker state to %s: %s", self.persistence_path, e)

    def _load(self) -> None:
        """ファイルから状態を復元する。失敗時は初期値のまま続行。"""
        if not self.persistence_path.exists():
            return
        try:
            text = self.persistence_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(text)
            saved_date = date.fromisoformat(data["last_reset"])
            saved_count = int(data["request_count"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("Rate tracker state file is broken (%s); starting fresh.", e)
            return

        if saved_date == date.today():
            self.request_count = saved_count
            self.last_reset = saved_date
        else:
            # 日付が変わっていれば 0 にリセット
            self.request_count = 0
            self.last_reset = date.today()
            self._save()


__all__ = ["RateLimitTracker", "DEFAULT_DAILY_LIMIT", "DEFAULT_SAFETY_MARGIN"]
