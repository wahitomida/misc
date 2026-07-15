"""``core.feedback.FeedbackManager`` のユニットテスト。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.exceptions import RoleNotFoundError
from core.feedback import (
    EXCEPTIONAL_HIGH_SCORE,
    EXCEPTIONAL_LOW_SCORE,
    TREND_DECLINING,
    TREND_IMPROVING,
    TREND_INSUFFICIENT,
    TREND_STABLE,
    FeedbackManager,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


REPO_ROLES_DIR = Path(__file__).resolve().parents[2] / "config" / "roles"


@pytest.fixture
def roles_copy_dir(tmp_path: Path) -> Path:
    """同梱のロール YAML を ``tmp_path/roles`` にクリーンコピーする。

    実運用で蓄積された ``feedback_history`` / ``feedback_stats`` /
    ``personality.observed_weaknesses`` はテストの初期状態を崩すので、
    コピー時に除去してクリーンな初期値に戻す。これにより各テストは
    「1 セッションを追加したら履歴は 1 件になる」前提を安全に使える。
    """
    dest = tmp_path / "roles"
    dest.mkdir()
    for src in REPO_ROLES_DIR.glob("*.yaml"):
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        data.pop("feedback_history", None)
        data.pop("feedback_stats", None)
        personality = data.get("personality")
        if isinstance(personality, dict):
            personality.pop("observed_weaknesses", None)
        (dest / src.name).write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return dest


def _read_role(roles_dir: Path, role_id: str) -> dict[str, Any]:
    return yaml.safe_load(
        (roles_dir / f"{role_id}.yaml").read_text(encoding="utf-8")
    )


def _entry(
    *,
    self_score: float,
    peer_score: float,
    session_id: str = "20260101_000000_idea",
    date: str = "2026-01-01",
    topic: str = "test topic",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "date": date,
        "topic": topic,
        "self_score_avg": self_score,
        "peer_score_avg": peer_score,
        "strengths_noted": strengths or [],
        "improvements_noted": improvements or [],
        "orchestrator_feedback": feedback,
    }


# ---------------------------------------------------------------------------
# update_role_feedback
# ---------------------------------------------------------------------------


class TestUpdateRoleFeedback:
    def test_appends_entry_to_history(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)

        fm.update_role_feedback(
            role_id="theorist",
            session_id="20260101_120000_idea",
            date="2026-01-01",
            topic="テスト",
            self_eval={"avg_score": 4.0},
            peer_avg=4.5,
            orchestrator_feedback={
                "strengths_noted": ["s1"],
                "improvements_noted": ["i1"],
                "orchestrator_feedback": "次回も期待",
            },
        )

        role = _read_role(roles_copy_dir, "theorist")
        history = role["feedback_history"]
        assert len(history) == 1
        entry = history[0]
        assert entry["session_id"] == "20260101_120000_idea"
        assert entry["self_score_avg"] == 4.0
        assert entry["peer_score_avg"] == 4.5
        assert entry["strengths_noted"] == ["s1"]
        assert entry["improvements_noted"] == ["i1"]
        assert entry["orchestrator_feedback"] == "次回も期待"

    def test_recalculates_stats_after_update(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)

        fm.update_role_feedback(
            role_id="theorist",
            session_id="s1",
            date="2026-01-01",
            topic="topic1",
            self_eval={"avg_score": 4.0},
            peer_avg=4.5,
            orchestrator_feedback={"strengths_noted": ["s1"]},
        )

        role = _read_role(roles_copy_dir, "theorist")
        stats = role["feedback_stats"]
        assert stats["total_sessions"] == 1
        assert stats["avg_self_score"] == 4.0
        assert stats["avg_peer_score"] == 4.5
        assert stats["trend"] == TREND_INSUFFICIENT
        assert stats["top_strength"] == "s1"
        assert "topic1" in stats["recent_topics"]

    def test_multiple_updates_accumulate(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)

        for i in range(3):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-0{i + 1}",
                topic=f"topic{i}",
                self_eval={"avg_score": 4.0 + i * 0.1},
                peer_avg=4.5,
                orchestrator_feedback={},
            )

        role = _read_role(roles_copy_dir, "theorist")
        assert len(role["feedback_history"]) == 3
        assert role["feedback_stats"]["total_sessions"] == 3

    def test_compresses_when_exceeding_max_history(
        self, roles_copy_dir: Path
    ) -> None:
        """max_history=3 で 5 件追加 → 圧縮されて 3 件以下に。"""
        fm = FeedbackManager(roles_copy_dir, max_history=3)

        for i in range(5):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-0{i + 1}",
                topic=f"topic{i}",
                self_eval={"avg_score": 3.0},
                peer_avg=3.0,
                orchestrator_feedback={},
            )

        role = _read_role(roles_copy_dir, "theorist")
        # 例外的スコアはないので、直近 3 件のみが残る
        assert len(role["feedback_history"]) == 3
        ids = [e["session_id"] for e in role["feedback_history"]]
        assert ids == ["s2", "s3", "s4"]

    def test_unknown_role_raises(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        with pytest.raises(RoleNotFoundError):
            fm.update_role_feedback(
                role_id="nonexistent",
                session_id="s1",
                date="2026-01-01",
                topic="t",
                self_eval={"avg_score": 4.0},
                peer_avg=4.0,
                orchestrator_feedback={},
            )

    def test_preserves_other_yaml_fields(self, roles_copy_dir: Path) -> None:
        """ロール YAML の他のフィールド (system_prompt 等) を保持する。"""
        fm = FeedbackManager(roles_copy_dir)
        before = _read_role(roles_copy_dir, "theorist")

        fm.update_role_feedback(
            role_id="theorist",
            session_id="s1",
            date="2026-01-01",
            topic="t",
            self_eval={"avg_score": 4.0},
            peer_avg=4.5,
            orchestrator_feedback={},
        )

        after = _read_role(roles_copy_dir, "theorist")
        assert before["role_id"] == after["role_id"]
        assert before["display_name"] == after["display_name"]
        assert before["system_prompt"] == after["system_prompt"]
        assert before["expertise"] == after["expertise"]


# ---------------------------------------------------------------------------
# _calculate_trend
# ---------------------------------------------------------------------------


class TestCalculateTrend:
    def test_insufficient_data_when_fewer_than_three(self) -> None:
        assert FeedbackManager._calculate_trend([4.0]) == TREND_INSUFFICIENT
        assert FeedbackManager._calculate_trend([4.0, 4.1]) == TREND_INSUFFICIENT

    def test_insufficient_data_when_only_recent_window(self) -> None:
        """直近 3 件しかない (earlier が空) なら insufficient。"""
        assert FeedbackManager._calculate_trend([4.0, 4.0, 4.0]) == TREND_INSUFFICIENT

    def test_improving_when_recent_significantly_higher(self) -> None:
        # earlier avg = 3.5, recent avg = 4.5 (diff = 1.0 > 0.3)
        scores = [3.0, 4.0, 4.5, 4.5, 4.5]
        assert FeedbackManager._calculate_trend(scores) == TREND_IMPROVING

    def test_declining_when_recent_significantly_lower(self) -> None:
        # earlier avg = 4.5, recent avg = 3.5 (diff = -1.0 < -0.3)
        scores = [5.0, 4.5, 4.0, 3.5, 3.0]
        assert FeedbackManager._calculate_trend(scores) == TREND_DECLINING

    def test_stable_when_within_threshold(self) -> None:
        # earlier avg ≈ recent avg, diff < 0.3
        scores = [4.0, 4.1, 4.0, 4.1, 4.2]
        assert FeedbackManager._calculate_trend(scores) == TREND_STABLE


# ---------------------------------------------------------------------------
# _compress_old_entries
# ---------------------------------------------------------------------------


class TestCompressOldEntries:
    def test_under_limit_returns_full_copy(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir, max_history=5)
        history = [_entry(self_score=3.0, peer_score=3.0) for _ in range(3)]

        result = fm._compress_old_entries(history)

        assert len(result) == 3
        assert result == history

    def test_compresses_to_max_history(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir, max_history=3)
        history = [
            _entry(session_id=f"s{i}", self_score=3.0, peer_score=3.0)
            for i in range(5)
        ]

        result = fm._compress_old_entries(history)

        # 例外的スコアなし → 直近 3 件のみ
        assert len(result) == 3
        assert [e["session_id"] for e in result] == ["s2", "s3", "s4"]

    def test_keeps_exceptional_high_scores(self, roles_copy_dir: Path) -> None:
        """``self_score_avg >= 4.8`` のエントリは保持される。"""
        fm = FeedbackManager(roles_copy_dir, max_history=3)
        history = [
            _entry(session_id="s_exceptional", self_score=EXCEPTIONAL_HIGH_SCORE, peer_score=4.0),
            _entry(session_id="s_normal", self_score=3.0, peer_score=3.0),
            _entry(session_id="s_recent_1", self_score=3.0, peer_score=3.0),
            _entry(session_id="s_recent_2", self_score=3.0, peer_score=3.0),
            _entry(session_id="s_recent_3", self_score=3.0, peer_score=3.0),
        ]

        result = fm._compress_old_entries(history)

        ids = [e["session_id"] for e in result]
        assert "s_exceptional" in ids
        assert ids[-3:] == ["s_recent_1", "s_recent_2", "s_recent_3"]

    def test_keeps_exceptional_low_scores(self, roles_copy_dir: Path) -> None:
        """``self_score_avg <= 1.5`` のエントリも保持される。"""
        fm = FeedbackManager(roles_copy_dir, max_history=3)
        history = [
            _entry(session_id="s_low", self_score=EXCEPTIONAL_LOW_SCORE, peer_score=2.0),
            _entry(session_id="s_recent_1", self_score=3.0, peer_score=3.0),
            _entry(session_id="s_recent_2", self_score=3.0, peer_score=3.0),
            _entry(session_id="s_recent_3", self_score=3.0, peer_score=3.0),
        ]

        result = fm._compress_old_entries(history)

        ids = [e["session_id"] for e in result]
        assert "s_low" in ids


# ---------------------------------------------------------------------------
# generate_feedback_context
# ---------------------------------------------------------------------------


class TestGenerateFeedbackContext:
    def test_empty_when_no_history(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        # 同梱の theorist.yaml は feedback_history が空
        assert fm.generate_feedback_context("theorist") == ""

    def test_empty_for_unknown_role(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        assert fm.generate_feedback_context("nonexistent_role") == ""

    def test_includes_improving_prefix(self, roles_copy_dir: Path) -> None:
        """improving トレンドのとき肯定的な前置きが入る。"""
        fm = FeedbackManager(roles_copy_dir)
        for i, score in enumerate([3.0, 3.5, 4.0, 4.5, 4.6, 4.7]):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-{i + 1:02d}",
                topic=f"topic{i}",
                self_eval={"avg_score": score},
                peer_avg=score,
                orchestrator_feedback={"orchestrator_feedback": "改善継続"},
            )

        ctx = fm.generate_feedback_context("theorist")

        assert "📈" in ctx
        assert "改善傾向" in ctx
        assert "改善継続" in ctx

    def test_includes_declining_prefix(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        for i, score in enumerate([4.7, 4.6, 4.5, 4.0, 3.5, 3.0]):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-{i + 1:02d}",
                topic=f"topic{i}",
                self_eval={"avg_score": score},
                peer_avg=score,
                orchestrator_feedback={
                    "improvements_noted": [f"改善点{i}"],
                },
            )

        ctx = fm.generate_feedback_context("theorist")

        assert "📉" in ctx
        assert "下降傾向" in ctx
        assert "改善点" in ctx

    def test_includes_improvements_and_feedback_sections(
        self, roles_copy_dir: Path
    ) -> None:
        fm = FeedbackManager(roles_copy_dir)
        for i in range(3):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-{i + 1:02d}",
                topic=f"topic{i}",
                self_eval={"avg_score": 4.0},
                peer_avg=4.0,
                orchestrator_feedback={
                    "strengths_noted": ["数学的厳密性"],
                    "improvements_noted": [f"改善点{i}"],
                    "orchestrator_feedback": f"期待{i}",
                },
            )

        ctx = fm.generate_feedback_context("theorist")

        assert "【過去に指摘された改善点】" in ctx
        assert "【指揮者からの継続的な期待】" in ctx
        assert "数学的厳密性" in ctx  # top_strength

    def test_aliased_method_returns_same_content(
        self, roles_copy_dir: Path
    ) -> None:
        """``generate_context_from_history`` は ``generate_feedback_context`` のエイリアス。"""
        fm = FeedbackManager(roles_copy_dir)
        fm.update_role_feedback(
            role_id="theorist",
            session_id="s1",
            date="2026-01-01",
            topic="t",
            self_eval={"avg_score": 4.0},
            peer_avg=4.0,
            orchestrator_feedback={"orchestrator_feedback": "期待"},
        )

        a = fm.generate_feedback_context("theorist")
        b = fm.generate_context_from_history("theorist")

        assert a == b


# ---------------------------------------------------------------------------
# should_reinforce_rules
# ---------------------------------------------------------------------------


class TestShouldReinforceRules:
    def test_false_for_unknown_role(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        assert fm.should_reinforce_rules("nonexistent") is False

    def test_false_for_empty_history(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        assert fm.should_reinforce_rules("theorist") is False

    def test_true_when_declining(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        for i, score in enumerate([4.7, 4.6, 4.5, 4.0, 3.5, 3.0]):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-{i + 1:02d}",
                topic=f"t{i}",
                self_eval={"avg_score": score},
                peer_avg=score,
                orchestrator_feedback={},
            )

        assert fm.should_reinforce_rules("theorist") is True

    def test_false_when_improving(self, roles_copy_dir: Path) -> None:
        fm = FeedbackManager(roles_copy_dir)
        for i, score in enumerate([3.0, 3.5, 4.0, 4.5, 4.6, 4.7]):
            fm.update_role_feedback(
                role_id="theorist",
                session_id=f"s{i}",
                date=f"2026-01-{i + 1:02d}",
                topic=f"t{i}",
                self_eval={"avg_score": score},
                peer_avg=score,
                orchestrator_feedback={},
            )

        assert fm.should_reinforce_rules("theorist") is False


# ---------------------------------------------------------------------------
# _most_common_theme
# ---------------------------------------------------------------------------


class TestMostCommonTheme:
    def test_empty_list_returns_empty_string(self) -> None:
        assert FeedbackManager._most_common_theme([]) == ""

    def test_returns_majority_when_repeated(self) -> None:
        items = ["A", "B", "A", "C", "A"]
        assert FeedbackManager._most_common_theme(items) == "A"

    def test_returns_last_when_all_unique(self) -> None:
        items = ["X", "Y", "Z"]
        assert FeedbackManager._most_common_theme(items) == "Z"
