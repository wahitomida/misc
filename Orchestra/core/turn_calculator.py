"""ラウンド所要時間の見積もりと動的計画調整。

設計書サンプル (10.1 / 10.3.1) のロジックに、``Settings`` から取り出した
モデル別補正係数とラウンド別オーバーヘッドを統合する。

参照: ``doc/10_turn_management.md`` §10.1, §10.3
"""

from __future__ import annotations

import logging
from typing import Iterable

from .config_loader import Settings
from .data_models import DiscussionPlan, RoundConfig, RoundLog
from .time_keeper import TimeKeeper

# Constants (実測ベースで取得した型: gpt-4.1 の 1 発言 2〜4 秒)
# 以前は minimal=3 / low=5 / medium=10 / high=20 だったが、実際の API レスポンスより
# 大きく見積もっており、ラウンド数が不当に少なくなる、時間作りの原因になっていた。
LEVEL_TIME_MAP: dict[str, float] = {
    "minimal": 2.0,
    "low": 3.0,
    "medium": 5.0,
    "high": 10.0,
}
CONDUCTOR_OVERHEAD_PER_ROUND: float = 2.0
CONVERGENCE_CHECK_TIME: float = 2.0

# 動的調整のしきい値
NEGLIGIBLE_OVERRUN_SEC: float = 5.0   # この秒数以下の超過は無視
SIGNIFICANT_OVERRUN_SEC: float = 15.0  # この秒数以上で 1 段階下げ
SEVERE_OVERRUN_SEC: float = 30.0       # この秒数以上で 2 段階下げ

# level の優先度 (上→下、強→弱)
LEVEL_ORDER: list[str] = ["high", "medium", "low", "minimal"]

# ping_pong パターンでの想定発言数の上限 (speakers*2 と min)
PING_PONG_UTTERANCE_CAP = 6
# free_talk パターンでの想定発言数の上限 (speakers*3 と min)
FREE_TALK_UTTERANCE_CAP = 8
FREE_TALK_UTTERANCES_PER_SPEAKER = 3

logger = logging.getLogger(__name__)


class TurnCalculator:
    """ラウンド単位・議論全体の所要時間を見積もる。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """Args: settings: ``Settings``。``None`` ならモデル補正係数なし。"""
        self.settings = settings

    # ------------------------------------------------------------------
    # 単一ラウンドの推定
    # ------------------------------------------------------------------

    def calculate_round_time(self, round_config: RoundConfig) -> float:
        """ラウンドの推定所要時間 (秒) を返す。

        ``pattern`` ごとに想定発言数を決め、``level`` 基準時間を掛けてから
        ``conductor`` のオーバーヘッドと収束判定時間を加える。

        Args:
            round_config: ラウンド設定。

        Returns:
            推定秒数。
        """
        n_speakers = len(round_config.speakers)
        level_time = LEVEL_TIME_MAP.get(round_config.level, LEVEL_TIME_MAP["medium"])

        utterances = self._estimate_utterance_count(round_config.pattern, n_speakers)
        return utterances * level_time + CONDUCTOR_OVERHEAD_PER_ROUND + CONVERGENCE_CHECK_TIME

    @staticmethod
    def _estimate_utterance_count(pattern: str, n_speakers: int) -> int:
        """パターン別の想定発言数を返す。"""
        if n_speakers <= 0:
            return 0
        if pattern == "one_shot":
            return n_speakers
        if pattern == "ping_pong":
            return min(n_speakers * 2, PING_PONG_UTTERANCE_CAP)
        if pattern == "free_talk":
            return min(n_speakers * FREE_TALK_UTTERANCES_PER_SPEAKER, FREE_TALK_UTTERANCE_CAP)
        # 未知パターンは one_shot 相当
        logger.warning("Unknown round pattern %r; falling back to one_shot.", pattern)
        return n_speakers

    # ------------------------------------------------------------------
    # 全体の推定
    # ------------------------------------------------------------------

    def calculate_total_time(self, plan: DiscussionPlan) -> float:
        """全ラウンド合計の推定所要時間を返す。"""
        return sum(self.calculate_round_time(rc) for rc in plan.round_config)

    def fits_in_budget(self, plan: DiscussionPlan, time_limit: float) -> bool:
        """計画が ``time_limit`` (秒) 内に収まるか判定する。"""
        return self.calculate_total_time(plan) <= time_limit

    # ------------------------------------------------------------------
    # 1 発言あたりの推定
    # ------------------------------------------------------------------

    def estimate_utterance_time(self, model: str, level: str) -> float:
        """モデル × level での 1 発言の推定時間。

        ``settings`` が与えられている場合は ``model_time_multiplier`` を反映する。

        Args:
            model: モデル名。
            level: 発言レベル。

        Returns:
            推定秒数。
        """
        base = LEVEL_TIME_MAP.get(level, LEVEL_TIME_MAP["medium"])
        if self.settings is None:
            return base
        multiplier = float(self.settings.model_time_multiplier.get(model, 1.0))
        return base * multiplier


class DynamicPlanAdjuster:
    """ラウンド実績が計画を超過した際に残ラウンドを再調整する。"""

    def __init__(self, calculator: TurnCalculator | None = None) -> None:
        """Args: calculator: 推定ロジック。未指定なら新規生成。"""
        self.calculator = calculator or TurnCalculator()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def adjust_for_time_overrun(
        self,
        plan: DiscussionPlan,
        completed_rounds: Iterable[RoundLog],
        time_keeper: TimeKeeper,
    ) -> list[RoundConfig]:
        """時間超過に応じて残ラウンドの ``level`` と予算を再計算する。

        Args:
            plan: 元の議論計画。
            completed_rounds: 既に完了したラウンドの実績ログ。
            time_keeper: 現在の時間状況。

        Returns:
            残ラウンド分の調整後 ``RoundConfig`` リスト。超過が無視できる
            場合は元の設定をそのまま返す (copy なし)。
        """
        completed_list = list(completed_rounds)
        n_done = len(completed_list)
        remaining_configs = plan.round_config[n_done:]

        total_overrun = self._calculate_total_overrun(plan, completed_list)

        if total_overrun <= NEGLIGIBLE_OVERRUN_SEC or not remaining_configs:
            return list(remaining_configs)

        remaining_time = time_keeper.remaining
        adjusted: list[RoundConfig] = []
        for rc in remaining_configs:
            new_level = self._downgrade_level(rc.level, total_overrun)
            new_budget = self._recalculate_budget(
                rc, new_level, remaining_time, len(remaining_configs)
            )
            adjusted.append(
                RoundConfig(
                    round=rc.round,
                    phase_name=rc.phase_name,
                    speakers=list(rc.speakers),
                    pattern=rc.pattern,
                    level=new_level,
                    time_budget_sec=new_budget,
                    goal=rc.goal,
                )
            )
        return adjusted

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_total_overrun(
        plan: DiscussionPlan,
        completed: list[RoundLog],
    ) -> float:
        """完了済みラウンドの累積超過時間を計算する。"""
        total = 0.0
        for i, log in enumerate(completed):
            if i >= len(plan.round_config):
                break
            planned = plan.round_config[i].time_budget_sec
            total += max(0.0, log.duration_sec - planned)
        return total

    @staticmethod
    def _downgrade_level(current_level: str, overrun: float) -> str:
        """超過量に応じて level を下げる。

        Args:
            current_level: 現行 level。
            overrun: 累積超過秒数。

        Returns:
            ``high`` → ``medium`` → ``low`` → ``minimal`` の順に下げる。
        """
        if current_level not in LEVEL_ORDER:
            return current_level
        idx = LEVEL_ORDER.index(current_level)
        if overrun > SEVERE_OVERRUN_SEC:
            return LEVEL_ORDER[min(idx + 2, len(LEVEL_ORDER) - 1)]
        if overrun > SIGNIFICANT_OVERRUN_SEC:
            return LEVEL_ORDER[min(idx + 1, len(LEVEL_ORDER) - 1)]
        return current_level

    @staticmethod
    def _recalculate_budget(
        rc: RoundConfig,
        new_level: str,
        remaining_time: float,
        remaining_rounds: int,
    ) -> float:
        """残り時間を残ラウンド数で均等配分する。

        ``rc`` / ``new_level`` は将来パターン別の補正に使う余地を残すため
        引数として受けるが、本実装では均等配分のみ。
        """
        del rc, new_level  # 現状は未使用 (将来拡張点)
        return remaining_time / max(remaining_rounds, 1)


__all__ = [
    "LEVEL_TIME_MAP",
    "CONDUCTOR_OVERHEAD_PER_ROUND",
    "CONVERGENCE_CHECK_TIME",
    "TurnCalculator",
    "DynamicPlanAdjuster",
]
