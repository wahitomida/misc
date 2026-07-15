"""議論全体の時間管理を担う ``TimeKeeper``。

Phase 1 / Phase 2 / Phase 3 の予約時間を踏まえ、Phase 2 (議論本体) の残り時間と
時間圧力 (``TimePressure``) を提供する。指揮者はこれを見て次ラウンドを開始するか・
短縮するか・終了するかを判断する。

参照: ``doc/10_turn_management.md`` §10.2
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

# Constants
DEFAULT_TIME_LIMIT_SEC = 300.0
DEFAULT_PHASE3_RESERVE_SEC = 15.0
DEFAULT_SAFETY_MARGIN = 0.9
DEFAULT_ROUND_TIME_ESTIMATE_SEC = 30.0
NEXT_ROUND_MARGIN_FACTOR = 1.0  # バッファなしでギリギリまで実行 (以前 1.2)
MIN_ROUND_BUDGET_RATIO = 0.7    # 残時間が推定の 70% 以上なら短縮モードで開始可
FORCE_CONCLUDE_THRESHOLD_SEC = 5.0  # 残り 5 秒未満なら強制終了


class TimePressure(str, Enum):
    """残り時間に応じた圧力レベル。

    比率は ``remaining / discussion_budget`` で計算する。
    """

    RELAXED = "relaxed"      # 50% 超
    MODERATE = "moderate"    # 20-50%
    URGENT = "urgent"        # 5-20%
    CRITICAL = "critical"    # 5% 未満


@dataclass
class TimeKeeper:
    """セッション全体の時間管理。

    Attributes:
        time_limit_sec: 全体の制限時間 (秒)。
        phase1_actual_sec: Phase 1 の実測時間 (Phase 1 完了時にセットされる)。
        phase3_reserve_sec: Phase 3 用に確保する時間。
        safety_margin: ``time_limit_sec`` の何割を実効上限とするか。
        start_time: セッション開始時の monotonic 時刻 (``time.time()``)。
        round_times: 各ラウンドの実測秒数。
    """

    time_limit_sec: float = DEFAULT_TIME_LIMIT_SEC
    phase1_actual_sec: float = 0.0
    phase3_reserve_sec: float = DEFAULT_PHASE3_RESERVE_SEC
    safety_margin: float = DEFAULT_SAFETY_MARGIN
    # lambda 経由で参照することで、テスト時の ``monkeypatch.setattr(time, "time", ...)``
    # が反映されるようにする (関数オブジェクトをキャプチャしない)。
    start_time: float = field(default_factory=lambda: time.time())
    round_times: list[float] = field(default_factory=list)

    # ------------------------------------------------------------------
    # プロパティ (経過 / 予算 / 残り / 圧力)
    # ------------------------------------------------------------------

    @property
    def elapsed(self) -> float:
        """セッション開始からの経過秒数。"""
        return time.time() - self.start_time

    @property
    def discussion_budget(self) -> float:
        """Phase 2 で使える総時間 (秒)。負値にはなり得る。"""
        return (
            self.time_limit_sec * self.safety_margin
            - self.phase1_actual_sec
            - self.phase3_reserve_sec
        )

    @property
    def discussion_elapsed(self) -> float:
        """Phase 2 開始からの経過時間 (秒)。

        ``elapsed - phase1_actual_sec`` で計算する。Phase 1 が完了する前
        (``phase1_actual_sec == 0.0``) は ``elapsed`` と同じ。
        """
        return self.elapsed - self.phase1_actual_sec

    @property
    def remaining(self) -> float:
        """Phase 2 の残り時間。常に 0 以上にクリップする。"""
        return max(0.0, self.discussion_budget - self.discussion_elapsed)

    @property
    def pressure(self) -> TimePressure:
        """現在の時間圧力。"""
        budget = self.discussion_budget
        if budget <= 0:
            return TimePressure.CRITICAL

        ratio = self.remaining / budget
        if ratio > 0.5:
            return TimePressure.RELAXED
        if ratio > 0.2:
            return TimePressure.MODERATE
        if ratio > 0.05:
            return TimePressure.URGENT
        return TimePressure.CRITICAL

    # ------------------------------------------------------------------
    # ラウンド管理
    # ------------------------------------------------------------------

    def can_start_next_round(self, estimated_round_sec: float) -> bool:
        """次のラウンドを開始しても時間内に終わるか判定する。

        Args:
            estimated_round_sec: ラウンドの推定所要秒数。

        Returns:
            ``remaining > estimated_round_sec * 1.2`` を満たすなら ``True``。
        """
        return self.remaining > estimated_round_sec * NEXT_ROUND_MARGIN_FACTOR

    def record_round(self, duration_sec: float) -> None:
        """ラウンドの実績時間を記録する。

        Args:
            duration_sec: 経過秒数 (負値は 0 にクリップ)。
        """
        self.round_times.append(max(0.0, duration_sec))

    def get_moving_average(self, window: int = 3) -> float:
        """直近 ``window`` ラウンドの平均所要時間を返す。

        記録が無ければ ``DEFAULT_ROUND_TIME_ESTIMATE_SEC`` を返す。

        Args:
            window: 平均を取るラウンド数 (デフォルト 3)。

        Returns:
            平均秒数。
        """
        if not self.round_times:
            return DEFAULT_ROUND_TIME_ESTIMATE_SEC
        recent = self.round_times[-window:]
        return sum(recent) / len(recent)

    def force_conclude(self) -> bool:
        """強制終了すべきかを判定する。

        Returns:
            残り時間が ``FORCE_CONCLUDE_THRESHOLD_SEC`` 未満、または既に
            時間圧力が ``CRITICAL`` の場合 ``True``。
        """
        return (
            self.remaining < FORCE_CONCLUDE_THRESHOLD_SEC
            or self.pressure == TimePressure.CRITICAL
        )


__all__ = [
    "TimePressure",
    "TimeKeeper",
    "DEFAULT_TIME_LIMIT_SEC",
    "DEFAULT_PHASE3_RESERVE_SEC",
    "DEFAULT_SAFETY_MARGIN",
    "NEXT_ROUND_MARGIN_FACTOR",
    "MIN_ROUND_BUDGET_RATIO",
]
