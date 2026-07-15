"""``core.rate_tracker.RateLimitTracker`` のユニットテスト。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.rate_tracker import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_SAFETY_MARGIN,
    RateLimitTracker,
)


@pytest.fixture
def tracker_path(tmp_path: Path) -> Path:
    """テスト用の永続化パス (毎回フレッシュ)。"""
    return tmp_path / "rate.json"


def _make_tracker(path: Path, **kwargs) -> RateLimitTracker:
    """テスト用ヘルパー: ``persistence_path`` を必ず差し替える。"""
    return RateLimitTracker(persistence_path=path, **kwargs)


# ---------------------------------------------------------------------------
# 初期状態 / インクリメント
# ---------------------------------------------------------------------------


class TestInitialState:
    """新規 ``RateLimitTracker`` の状態。"""

    def test_defaults_match_specification(self, tracker_path: Path) -> None:
        """daily_limit=10000, safety_margin=0.9 がデフォルト。"""
        tracker = _make_tracker(tracker_path)
        assert tracker.daily_limit == DEFAULT_DAILY_LIMIT
        assert tracker.safety_margin == DEFAULT_SAFETY_MARGIN
        assert tracker.request_count == 0
        assert tracker.last_reset == date.today()

    def test_remaining_equals_daily_limit_initially(self, tracker_path: Path) -> None:
        """初期状態の残量は daily_limit と同じ。"""
        tracker = _make_tracker(tracker_path)
        assert tracker.remaining() == DEFAULT_DAILY_LIMIT

    def test_utilization_zero_initially(self, tracker_path: Path) -> None:
        """初期使用率は 0.0。"""
        tracker = _make_tracker(tracker_path)
        assert tracker.utilization() == 0.0


class TestIncrement:
    """``increment`` の挙動。"""

    def test_increment_default_step_is_one(self, tracker_path: Path) -> None:
        """引数なし呼び出しで +1。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment()
        assert tracker.request_count == 1
        assert tracker.remaining() == DEFAULT_DAILY_LIMIT - 1

    def test_increment_with_explicit_step(self, tracker_path: Path) -> None:
        """``n`` 指定で任意増分。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment(5)
        tracker.increment(3)
        assert tracker.request_count == 8


# ---------------------------------------------------------------------------
# can_proceed / utilization
# ---------------------------------------------------------------------------


class TestCanProceed:
    """``can_proceed`` は safety_margin × daily_limit を閾値とする。"""

    def test_returns_true_below_safety_margin(self, tracker_path: Path) -> None:
        """初期状態では小さな推定値は通る。"""
        tracker = _make_tracker(tracker_path)
        assert tracker.can_proceed(100) is True

    def test_returns_false_when_estimate_would_cross_threshold(
        self, tracker_path: Path
    ) -> None:
        """90% を超える推定値は通らない。"""
        tracker = _make_tracker(tracker_path)
        # daily=10000, margin=0.9 → 9000 が閾値。9001 を消費しようとしたら NG。
        assert tracker.can_proceed(9001) is False

    def test_returns_false_when_current_already_at_threshold(
        self, tracker_path: Path
    ) -> None:
        """既に閾値ぎりぎりの場合は 0 個でも NG。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment(9000)
        # 9000 + 0 = 9000、threshold=9000 を満たさない (strict <)
        assert tracker.can_proceed(0) is False

    def test_returns_true_at_threshold_minus_one(self, tracker_path: Path) -> None:
        """8999 + 0 = 8999 < 9000 で OK。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment(8999)
        assert tracker.can_proceed(0) is True


class TestUtilization:
    """``utilization`` の挙動。"""

    def test_utilization_reports_consumed_fraction(self, tracker_path: Path) -> None:
        """消費量 / daily_limit を返す。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment(2500)
        assert tracker.utilization() == pytest.approx(0.25)

    def test_utilization_can_exceed_one_when_over_limit(self, tracker_path: Path) -> None:
        """上限超過時は 1.0 超を返す (上限自体は強制しない)。"""
        tracker = _make_tracker(tracker_path, daily_limit=100)
        tracker.increment(150)
        assert tracker.utilization() == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# 日付リセット
# ---------------------------------------------------------------------------


class TestDateReset:
    """日付が変わったら自動リセットされる。"""

    def test_check_reset_zeroes_count_on_new_day(
        self, tracker_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``date.today()`` が進めばカウンターがリセットされる。"""
        import core.rate_tracker as rt

        tracker = _make_tracker(tracker_path)
        tracker.increment(500)
        assert tracker.request_count == 500

        # 翌日に進める
        next_day = date.today() + timedelta(days=1)

        class _FakeDate(date):
            @classmethod
            def today(cls):  # type: ignore[override]
                return next_day

        monkeypatch.setattr(rt, "date", _FakeDate)

        # remaining() 呼び出しで _check_reset が走る
        assert tracker.remaining() == DEFAULT_DAILY_LIMIT
        assert tracker.request_count == 0
        assert tracker.last_reset == next_day

    def test_increment_triggers_reset_on_new_day(
        self, tracker_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``increment`` 経由でもリセットが走る。"""
        import core.rate_tracker as rt

        tracker = _make_tracker(tracker_path)
        tracker.increment(500)

        next_day = date.today() + timedelta(days=1)

        class _FakeDate(date):
            @classmethod
            def today(cls):  # type: ignore[override]
                return next_day

        monkeypatch.setattr(rt, "date", _FakeDate)

        tracker.increment(1)
        # リセット後に +1 された状態
        assert tracker.request_count == 1
        assert tracker.last_reset == next_day


# ---------------------------------------------------------------------------
# 永続化 (_save / _load)
# ---------------------------------------------------------------------------


class TestPersistence:
    """JSON 永続化と復元。"""

    def test_state_is_persisted_to_disk(self, tracker_path: Path) -> None:
        """increment 後にファイルへ書き出される。"""
        tracker = _make_tracker(tracker_path)
        tracker.increment(42)

        assert tracker_path.exists()
        data = json.loads(tracker_path.read_text(encoding="utf-8"))
        assert data["request_count"] == 42
        assert data["last_reset"] == date.today().isoformat()

    def test_state_is_restored_across_instances(self, tracker_path: Path) -> None:
        """新しいインスタンスを作っても今日のカウンタが復元される。"""
        first = _make_tracker(tracker_path)
        first.increment(123)

        second = _make_tracker(tracker_path)
        assert second.request_count == 123
        assert second.last_reset == date.today()

    def test_state_from_previous_day_is_reset_on_load(self, tracker_path: Path) -> None:
        """昨日以前のファイルは復元せず 0 から始める。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tracker_path.write_text(
            json.dumps({"request_count": 999, "last_reset": yesterday}),
            encoding="utf-8",
        )

        tracker = _make_tracker(tracker_path)
        assert tracker.request_count == 0
        assert tracker.last_reset == date.today()

    def test_broken_persistence_file_is_ignored(self, tracker_path: Path) -> None:
        """壊れたファイルでも例外を伝播せず初期値で続行する。"""
        tracker_path.write_text("not a json {", encoding="utf-8")

        tracker = _make_tracker(tracker_path)
        assert tracker.request_count == 0
        assert tracker.last_reset == date.today()

    def test_missing_keys_in_persistence_file_are_ignored(self, tracker_path: Path) -> None:
        """キー欠落でも例外を出さず初期値で続行する。"""
        tracker_path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

        tracker = _make_tracker(tracker_path)
        assert tracker.request_count == 0
