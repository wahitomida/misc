"""``core.time_keeper`` のユニットテスト。

``time.time()`` を直接モンキーパッチして経過時間を制御する。
"""

from __future__ import annotations

import time

import pytest

from core.time_keeper import (
    DEFAULT_PHASE3_RESERVE_SEC,
    TimeKeeper,
    TimePressure,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch):
    """``time.time`` を制御可能にするフィクスチャ。

    返り値は ``(set_time, advance)`` のタプル。
    """
    state = {"now": 1_000_000.0}

    def fake_time() -> float:
        return state["now"]

    monkeypatch.setattr(time, "time", fake_time)

    def set_time(t: float) -> None:
        state["now"] = t

    def advance(dt: float) -> None:
        state["now"] += dt

    return set_time, advance


def _make_keeper(
    set_time, advance,
    *,
    time_limit_sec: float = 300.0,
    phase1_actual_sec: float = 0.0,
    phase3_reserve_sec: float = DEFAULT_PHASE3_RESERVE_SEC,
    safety_margin: float = 0.9,
) -> TimeKeeper:
    """``start_time`` を現在時刻に固定した ``TimeKeeper`` を生成する。"""
    return TimeKeeper(
        time_limit_sec=time_limit_sec,
        phase1_actual_sec=phase1_actual_sec,
        phase3_reserve_sec=phase3_reserve_sec,
        safety_margin=safety_margin,
    )


# ---------------------------------------------------------------------------
# 基本プロパティ
# ---------------------------------------------------------------------------


class TestBasicProperties:
    """``elapsed`` / ``discussion_budget`` / ``remaining``。"""

    def test_elapsed_is_zero_at_start(self, frozen_clock) -> None:
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        assert keeper.elapsed == pytest.approx(0.0)

    def test_elapsed_advances_with_clock(self, frozen_clock) -> None:
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        advance(42.5)

        assert keeper.elapsed == pytest.approx(42.5)

    def test_discussion_budget_subtracts_phase_reserves(self, frozen_clock) -> None:
        """budget = limit * margin - phase1 - phase3_reserve。"""
        set_time, advance = frozen_clock
        # limit=300, margin=0.9 → 270
        # phase1=5 を引いて 265
        # phase3=25 を引いて 240
        keeper = _make_keeper(
            set_time,
            advance,
            time_limit_sec=300.0,
            phase1_actual_sec=5.0,
            phase3_reserve_sec=25.0,
            safety_margin=0.9,
        )

        assert keeper.discussion_budget == pytest.approx(240.0)

    def test_remaining_decreases_with_elapsed(self, frozen_clock) -> None:
        """100 秒経過したら残り 250-100=150 (デフォルト phase3_reserve=15)。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(
            set_time,
            advance,
            time_limit_sec=300.0,
            phase1_actual_sec=5.0,
        )
        # phase1 が 5 秒消化されているとみなす → discussion_elapsed = elapsed - 5
        advance(105.0)

        assert keeper.remaining == pytest.approx(150.0)

    def test_remaining_is_clamped_to_zero(self, frozen_clock) -> None:
        """予算超過しても 0 以上に維持。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=10.0)
        advance(100.0)

        assert keeper.remaining == 0.0


# ---------------------------------------------------------------------------
# pressure
# ---------------------------------------------------------------------------


class TestPressureLevels:
    """残り時間比率に対する ``TimePressure`` の遷移。"""

    def test_relaxed_above_50_percent(self, frozen_clock) -> None:
        """0 秒経過 → 100% 残 → RELAXED。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        assert keeper.pressure == TimePressure.RELAXED

    def test_moderate_between_20_and_50_percent(self, frozen_clock) -> None:
        """budget=270、150 秒経過 → 残り 120 → 約 44% → MODERATE。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)  # budget=270

        advance(150.0)

        assert keeper.pressure == TimePressure.MODERATE

    def test_urgent_between_5_and_20_percent(self, frozen_clock) -> None:
        """budget=270、220 秒経過 → 残り 50 → 約 18% → URGENT。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        advance(220.0)

        assert keeper.pressure == TimePressure.URGENT

    def test_critical_below_5_percent(self, frozen_clock) -> None:
        """budget=270、265 秒経過 → 残り 5 → 約 1.8% → CRITICAL。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        advance(265.0)

        assert keeper.pressure == TimePressure.CRITICAL

    def test_critical_when_budget_is_zero_or_negative(self, frozen_clock) -> None:
        """予算 0 / 負値の場合は常に CRITICAL。"""
        set_time, advance = frozen_clock
        # phase3 だけで予算消費 → 負値
        keeper = _make_keeper(
            set_time,
            advance,
            time_limit_sec=10.0,
            phase3_reserve_sec=100.0,
        )

        assert keeper.pressure == TimePressure.CRITICAL


# ---------------------------------------------------------------------------
# can_start_next_round
# ---------------------------------------------------------------------------


class TestCanStartNextRound:
    """``can_start_next_round`` は 20% マージンを要求する。"""

    def test_round_fits_with_margin(self, frozen_clock) -> None:
        """残り 100 秒、推定 50 秒なら 50*1.2=60 < 100 で OK。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=200.0)
        # budget = 200*0.9 - 0 - 25 = 155
        # 0 秒経過 → remaining = 155

        assert keeper.can_start_next_round(50.0) is True

    def test_round_too_long_for_remaining(self, frozen_clock) -> None:
        """残り 30 秒、推定 40 秒なら NG。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=100.0)
        # budget = 100*0.9 - 25 = 65, 35 秒経過 → 残り 30
        advance(35.0)

        assert keeper.can_start_next_round(40.0) is False

    def test_round_exactly_at_margin_boundary(self, frozen_clock) -> None:
        """残り == 推定*1.0 ちょうどなら strict > なので False (Phase 3 でマージン撤廃)。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=200.0)
        # budget = 200*0.9 - 15 = 165, 105 秒経過 → 残り 60
        advance(105.0)
        # 60.0 * 1.0 = 60.0、remaining=60.0 → strict > なので False
        assert keeper.can_start_next_round(60.0) is False


# ---------------------------------------------------------------------------
# record_round / get_moving_average
# ---------------------------------------------------------------------------


class TestRoundRecording:
    """``record_round`` と ``get_moving_average``。"""

    def test_get_moving_average_default_when_empty(self, frozen_clock) -> None:
        """履歴が空ならデフォルト推定値を返す。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        assert keeper.get_moving_average() == pytest.approx(30.0)

    def test_record_round_appends_history(self, frozen_clock) -> None:
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        keeper.record_round(10.0)
        keeper.record_round(20.0)

        assert keeper.round_times == [10.0, 20.0]

    def test_get_moving_average_uses_last_n_rounds(self, frozen_clock) -> None:
        """直近 ``window`` 件で平均を取る。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        for d in [5.0, 5.0, 5.0, 30.0, 60.0, 90.0]:
            keeper.record_round(d)

        # window=3 → (30 + 60 + 90) / 3 = 60
        assert keeper.get_moving_average(window=3) == pytest.approx(60.0)

    def test_negative_duration_is_clamped(self, frozen_clock) -> None:
        """負の値は 0 にクリップして記録する。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)

        keeper.record_round(-5.0)
        assert keeper.round_times == [0.0]


# ---------------------------------------------------------------------------
# force_conclude
# ---------------------------------------------------------------------------


class TestForceConclude:
    """``force_conclude`` は残り 5 秒未満 / CRITICAL で True。"""

    def test_not_forced_in_relaxed(self, frozen_clock) -> None:
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance)
        assert keeper.force_conclude() is False

    def test_forced_when_remaining_below_threshold(self, frozen_clock) -> None:
        """残り 5 秒未満で強制終了。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=100.0)
        # budget = 100*0.9 - 15 = 75, 73 秒経過 → 残り 2
        advance(73.0)

        assert keeper.force_conclude() is True

    def test_forced_when_pressure_is_critical(self, frozen_clock) -> None:
        """負予算 = CRITICAL で強制終了。"""
        set_time, advance = frozen_clock
        keeper = _make_keeper(set_time, advance, time_limit_sec=10.0, phase3_reserve_sec=100.0)

        assert keeper.force_conclude() is True
