"""``core.turn_calculator`` のユニットテスト。"""

from __future__ import annotations

import time

import pytest

from core.config_loader import Settings
from core.data_models import DiscussionPlan, RoundConfig, RoundLog
from core.time_keeper import TimeKeeper
from core.turn_calculator import (
    CONDUCTOR_OVERHEAD_PER_ROUND,
    CONVERGENCE_CHECK_TIME,
    LEVEL_TIME_MAP,
    DynamicPlanAdjuster,
    TurnCalculator,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_round(
    *,
    round: int = 1,
    speakers: list[str] | None = None,
    pattern: str = "one_shot",
    level: str = "medium",
    time_budget_sec: float = 40.0,
    goal: str = "test goal",
    phase_name: str = "test phase",
) -> RoundConfig:
    return RoundConfig(
        round=round,
        phase_name=phase_name,
        speakers=speakers or ["a", "b", "c"],
        pattern=pattern,
        level=level,
        time_budget_sec=time_budget_sec,
        goal=goal,
    )


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


class TestConstants:
    """ガイドで明記された定数が定義されている。"""

    def test_level_time_map_matches_specification(self) -> None:
        assert LEVEL_TIME_MAP == {
            "minimal": 2.0,
            "low": 3.0,
            "medium": 5.0,
            "high": 10.0,
        }

    def test_overhead_constants(self) -> None:
        assert CONDUCTOR_OVERHEAD_PER_ROUND == 2.0
        assert CONVERGENCE_CHECK_TIME == 2.0


# ---------------------------------------------------------------------------
# calculate_round_time (パターン別)
# ---------------------------------------------------------------------------


class TestCalculateRoundTime:
    """``calculate_round_time`` がパターン別に正しい秒数を返す。"""

    def test_one_shot_uses_n_speakers(self) -> None:
        """one_shot: n_speakers * level + オーバーヘッド。"""
        calc = TurnCalculator()
        rc = _make_round(speakers=["a", "b", "c"], pattern="one_shot", level="medium")

        # 3 * 5 + 2 + 2 = 19
        assert calc.calculate_round_time(rc) == pytest.approx(19.0)

    def test_ping_pong_uses_min_cap(self) -> None:
        """ping_pong: min(n*2, 6) * level + オーバーヘッド。"""
        calc = TurnCalculator()
        # n=4 → 4*2=8、cap=6 → 6
        rc = _make_round(
            speakers=["a", "b", "c", "d"], pattern="ping_pong", level="low"
        )

        # 6 * 3 + 2 + 2 = 22
        assert calc.calculate_round_time(rc) == pytest.approx(22.0)

    def test_free_talk_uses_min_cap(self) -> None:
        """free_talk: min(n*3, 8) * level + オーバーヘッド。"""
        calc = TurnCalculator()
        # n=2 → 2*3=6, cap=8 → 6
        rc = _make_round(speakers=["a", "b"], pattern="free_talk", level="minimal")

        # 6 * 2 + 2 + 2 = 16
        assert calc.calculate_round_time(rc) == pytest.approx(16.0)

    def test_high_level_uses_20_seconds_per_utterance(self) -> None:
        """level=high なら 10 秒/発言 (Phase 3 で実測に合わせ短縮)。"""
        calc = TurnCalculator()
        rc = _make_round(speakers=["a"], pattern="one_shot", level="high")

        # 1 * 10 + 2 + 2 = 14
        assert calc.calculate_round_time(rc) == pytest.approx(14.0)

    def test_unknown_pattern_falls_back_to_one_shot(self) -> None:
        """未知パターンは one_shot 相当。"""
        calc = TurnCalculator()
        rc = _make_round(speakers=["a", "b"], pattern="unknown_xyz", level="medium")

        # 2 * 5 + 2 + 2 = 14 (one_shot と同じ)
        assert calc.calculate_round_time(rc) == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# calculate_total_time / fits_in_budget
# ---------------------------------------------------------------------------


class TestCalculateTotalAndFits:
    """``calculate_total_time`` / ``fits_in_budget`` の挙動。"""

    def test_total_is_sum_of_round_times(self) -> None:
        calc = TurnCalculator()
        plan = DiscussionPlan(
            estimated_rounds=2,
            round_config=[
                _make_round(round=1, speakers=["a", "b"], pattern="one_shot", level="low"),
                _make_round(round=2, speakers=["a"], pattern="one_shot", level="medium"),
            ],
        )

        # R1: 2*3+4 = 10, R2: 1*5+4 = 9 → total 19
        assert calc.calculate_total_time(plan) == pytest.approx(19.0)

    def test_fits_in_budget_true_when_under(self) -> None:
        calc = TurnCalculator()
        plan = DiscussionPlan(
            estimated_rounds=1,
            round_config=[_make_round(speakers=["a"], pattern="one_shot", level="low")],
        )
        # total = 1*3+4 = 7
        assert calc.fits_in_budget(plan, time_limit=20.0) is True

    def test_fits_in_budget_false_when_over(self) -> None:
        calc = TurnCalculator()
        plan = DiscussionPlan(
            estimated_rounds=1,
            round_config=[_make_round(speakers=["a", "b", "c"], pattern="one_shot", level="high")],
        )
        # total = 3*10+4 = 34
        assert calc.fits_in_budget(plan, time_limit=30.0) is False


# ---------------------------------------------------------------------------
# estimate_utterance_time (Settings 連携)
# ---------------------------------------------------------------------------


class TestEstimateUtteranceTime:
    """``estimate_utterance_time`` がモデル別補正係数を反映する。"""

    def test_without_settings_returns_base_only(self) -> None:
        calc = TurnCalculator(settings=None)
        assert calc.estimate_utterance_time("gpt-5.4", "high") == 10.0

    def test_with_settings_applies_multiplier(self) -> None:
        """設定の ``model_time_multiplier`` が掛かる。"""
        # 最小構成の Settings を直接生成
        settings = Settings(
            model_time_multiplier={"gpt-4.1": 0.5, "gpt-5.4": 1.0},
        )
        calc = TurnCalculator(settings=settings)

        # gpt-4.1 / medium → 5 * 0.5 = 2.5
        assert calc.estimate_utterance_time("gpt-4.1", "medium") == pytest.approx(2.5)
        # gpt-5.4 / high → 10 * 1.0 = 10.0
        assert calc.estimate_utterance_time("gpt-5.4", "high") == pytest.approx(10.0)

    def test_unknown_model_uses_multiplier_one(self) -> None:
        """設定にないモデルは補正係数 1.0。"""
        settings = Settings(model_time_multiplier={"gpt-4.1": 0.5})
        calc = TurnCalculator(settings=settings)

        assert calc.estimate_utterance_time("unknown-model", "low") == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# DynamicPlanAdjuster
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch):
    """``time.time`` をフリーズして TimeKeeper を制御可能にする。"""
    state = {"now": 2_000_000.0}

    def fake_time() -> float:
        return state["now"]

    def advance(dt: float) -> None:
        state["now"] += dt

    monkeypatch.setattr(time, "time", fake_time)
    return advance


class TestDowngradeLevel:
    """``_downgrade_level`` の段階下げ。"""

    def test_no_downgrade_when_overrun_small(self) -> None:
        assert DynamicPlanAdjuster._downgrade_level("high", overrun=5.0) == "high"

    def test_one_step_downgrade_for_significant_overrun(self) -> None:
        """15 < overrun <= 30 → 1 段階下げ。"""
        assert DynamicPlanAdjuster._downgrade_level("high", overrun=20.0) == "medium"
        assert DynamicPlanAdjuster._downgrade_level("medium", overrun=16.0) == "low"

    def test_two_step_downgrade_for_severe_overrun(self) -> None:
        """overrun > 30 → 2 段階下げ。"""
        assert DynamicPlanAdjuster._downgrade_level("high", overrun=40.0) == "low"
        assert DynamicPlanAdjuster._downgrade_level("medium", overrun=40.0) == "minimal"

    def test_minimal_stays_at_minimal(self) -> None:
        """最低 level からはそれ以上下がらない。"""
        assert DynamicPlanAdjuster._downgrade_level("minimal", overrun=100.0) == "minimal"


class TestAdjustForTimeOverrun:
    """``adjust_for_time_overrun`` の統合挙動。"""

    def test_returns_remaining_rounds_when_overrun_negligible(self, frozen_clock) -> None:
        """超過 <= 5 秒なら元の計画をそのまま返す。"""
        adjuster = DynamicPlanAdjuster()
        plan = DiscussionPlan(
            estimated_rounds=3,
            round_config=[
                _make_round(round=1, time_budget_sec=40.0),
                _make_round(round=2, time_budget_sec=40.0),
                _make_round(round=3, time_budget_sec=40.0),
            ],
        )
        keeper = TimeKeeper(time_limit_sec=300.0)
        # round 1 実績 42 秒 (超過 2 秒)
        completed = [RoundLog(round=1, duration_sec=42.0)]

        result = adjuster.adjust_for_time_overrun(plan, completed, keeper)

        # 残り 2 ラウンドを変更せず返す
        assert len(result) == 2
        assert result[0].level == "medium"
        assert result[1].level == "medium"
        assert result[0].time_budget_sec == 40.0

    def test_downgrades_level_for_significant_overrun(self, frozen_clock) -> None:
        """超過 20 秒 → 残ラウンドの level を 1 段階下げる。"""
        adjuster = DynamicPlanAdjuster()
        plan = DiscussionPlan(
            estimated_rounds=3,
            round_config=[
                _make_round(round=1, level="high", time_budget_sec=40.0),
                _make_round(round=2, level="high", time_budget_sec=40.0),
                _make_round(round=3, level="medium", time_budget_sec=40.0),
            ],
        )
        keeper = TimeKeeper(time_limit_sec=300.0)
        completed = [RoundLog(round=1, duration_sec=60.0)]  # 超過 20 秒

        result = adjuster.adjust_for_time_overrun(plan, completed, keeper)

        assert len(result) == 2
        assert result[0].level == "medium"  # high → medium
        assert result[1].level == "low"     # medium → low

    def test_recalculated_budgets_distribute_remaining_time_evenly(
        self, frozen_clock
    ) -> None:
        """新しい予算は残り時間 / 残ラウンド数。"""
        adjuster = DynamicPlanAdjuster()
        plan = DiscussionPlan(
            estimated_rounds=3,
            round_config=[
                _make_round(round=1, level="medium", time_budget_sec=40.0),
                _make_round(round=2, level="medium", time_budget_sec=40.0),
                _make_round(round=3, level="medium", time_budget_sec=40.0),
            ],
        )
        keeper = TimeKeeper(time_limit_sec=300.0, safety_margin=1.0, phase3_reserve_sec=0.0)
        # discussion_budget = 300, advance なし → remaining = 300
        completed = [RoundLog(round=1, duration_sec=80.0)]  # 超過 40 秒

        result = adjuster.adjust_for_time_overrun(plan, completed, keeper)

        # 残り 2 ラウンドに 300 を 2 等分 → 各 150
        assert len(result) == 2
        assert result[0].time_budget_sec == pytest.approx(150.0)
        assert result[1].time_budget_sec == pytest.approx(150.0)

    def test_returns_empty_when_no_remaining_rounds(self, frozen_clock) -> None:
        """全て完了済みなら空リスト。"""
        adjuster = DynamicPlanAdjuster()
        plan = DiscussionPlan(
            estimated_rounds=1,
            round_config=[_make_round(round=1, time_budget_sec=40.0)],
        )
        keeper = TimeKeeper(time_limit_sec=300.0)
        completed = [RoundLog(round=1, duration_sec=100.0)]

        result = adjuster.adjust_for_time_overrun(plan, completed, keeper)

        assert result == []

    def test_severe_overrun_triggers_two_step_downgrade(self, frozen_clock) -> None:
        """超過 40 秒で 2 段階下げ (high → low)。"""
        adjuster = DynamicPlanAdjuster()
        plan = DiscussionPlan(
            estimated_rounds=2,
            round_config=[
                _make_round(round=1, level="high", time_budget_sec=40.0),
                _make_round(round=2, level="high", time_budget_sec=40.0),
            ],
        )
        keeper = TimeKeeper(time_limit_sec=300.0)
        completed = [RoundLog(round=1, duration_sec=85.0)]  # 超過 45 秒

        result = adjuster.adjust_for_time_overrun(plan, completed, keeper)

        assert result[0].level == "low"
