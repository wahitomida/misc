"""``core.convergence`` のユニットテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.convergence import (
    AgreementDetector,
    ConvergenceChecker,
    RepetitionDetector,
)
from core.data_models import (
    ODSC,
    DiscussionPlan,
    OrchestraPlan,
    RoundLog,
    Utterance,
)
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _utterance(content: str, speaker: str = "theorist") -> Utterance:
    return Utterance(
        sequence=1,
        speaker=speaker,
        speaker_display=speaker,
        type="discussion",
        content=content,
        model="gpt-4.1",
        level="medium",
    )


def _plan() -> OrchestraPlan:
    return OrchestraPlan(
        odsc=ODSC(
            objective="テスト目的",
            deliverable="テスト成果物",
            success_criteria="テスト合格基準",
            convergence_threshold=0.8,
        ),
        discussion_plan=DiscussionPlan(estimated_rounds=1),
    )


def _make_client(
    tmp_path: Path, responses: list[dict[str, str]]
) -> tuple[ResilientAPIClient, MockAPIClient]:
    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    return client, mock


# ---------------------------------------------------------------------------
# ConvergenceChecker
# ---------------------------------------------------------------------------


class TestConvergenceCheckerCheck:
    """``ConvergenceChecker.check`` の正常系・異常系。"""

    @pytest.mark.asyncio
    async def test_check_parses_json_response(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "score": 0.75,
                "reasoning": "おおむね合意",
                "remaining_disagreements": ["k の選び方"],
                "recommendation": "continue",
            }
        )
        client, _ = _make_client(tmp_path, [{"content": body}])
        checker = ConvergenceChecker(client)
        round_log = RoundLog(
            round=1,
            duration_sec=10.0,
            phase_name="P1",
            goal="g1",
            public_utterances=[_utterance("hello")],
        )

        result = await checker.check(round_log, _plan())

        assert result.score == pytest.approx(0.75)
        assert result.recommendation == "continue"
        assert result.remaining_disagreements == ["k の選び方"]
        assert checker.score_history == [0.75]

    @pytest.mark.asyncio
    async def test_check_clamps_score_to_unit_range(self, tmp_path: Path) -> None:
        """範囲外スコアは [0,1] にクリップされる。"""
        body = json.dumps({"score": 1.5, "recommendation": "continue"})
        client, _ = _make_client(tmp_path, [{"content": body}])
        checker = ConvergenceChecker(client)
        round_log = RoundLog(round=1, duration_sec=10.0, public_utterances=[])

        result = await checker.check(round_log, _plan())

        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_check_unknown_recommendation_falls_back_to_continue(
        self, tmp_path: Path
    ) -> None:
        body = json.dumps({"score": 0.5, "recommendation": "weird_value"})
        client, _ = _make_client(tmp_path, [{"content": body}])
        checker = ConvergenceChecker(client)
        round_log = RoundLog(round=1, duration_sec=10.0, public_utterances=[])

        result = await checker.check(round_log, _plan())

        assert result.recommendation == "continue"

    @pytest.mark.asyncio
    async def test_check_handles_markdown_fence(self, tmp_path: Path) -> None:
        body = "```json\n" + json.dumps(
            {"score": 0.4, "recommendation": "continue"}
        ) + "\n```"
        client, _ = _make_client(tmp_path, [{"content": body}])
        checker = ConvergenceChecker(client)
        round_log = RoundLog(round=1, duration_sec=10.0, public_utterances=[])

        result = await checker.check(round_log, _plan())

        assert result.score == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_check_returns_fallback_on_unparseable_response(
        self, tmp_path: Path
    ) -> None:
        """JSON でない応答でも例外を出さず fallback 結果を返す。

        フォールバックは score=0.5 (中間値) で議論を継続させるポリシー。
        旧 (score=0.0) では早期終了を誘発したので中間値に変更済み。
        """
        client, _ = _make_client(tmp_path, [{"content": "全然JSONではない"}])
        checker = ConvergenceChecker(client)
        round_log = RoundLog(round=1, duration_sec=10.0, public_utterances=[])

        result = await checker.check(round_log, _plan())

        assert result.score == 0.5
        assert result.recommendation == "continue"


class TestShouldTerminate:
    @pytest.fixture
    def checker(self, tmp_path: Path) -> ConvergenceChecker:
        client, _ = _make_client(tmp_path, [{"content": "{}"}])
        return ConvergenceChecker(client)

    def test_terminates_when_score_above_threshold(
        self, checker: ConvergenceChecker
    ) -> None:
        from core.data_models import ConvergenceResult

        result = ConvergenceResult(score=0.85, recommendation="continue")
        assert checker.should_terminate(result, threshold=0.8) is True

    def test_terminates_when_recommendation_is_conclude(
        self, checker: ConvergenceChecker
    ) -> None:
        from core.data_models import ConvergenceResult

        result = ConvergenceResult(score=0.5, recommendation="conclude")
        assert checker.should_terminate(result, threshold=0.8) is True

    def test_does_not_terminate_when_below_threshold_and_continue(
        self, checker: ConvergenceChecker
    ) -> None:
        from core.data_models import ConvergenceResult

        result = ConvergenceResult(score=0.5, recommendation="continue")
        assert checker.should_terminate(result, threshold=0.8) is False


class TestIsStagnating:
    @pytest.fixture
    def checker(self, tmp_path: Path) -> ConvergenceChecker:
        client, _ = _make_client(tmp_path, [{"content": "{}"}])
        return ConvergenceChecker(client)

    def test_returns_false_when_history_too_short(
        self, checker: ConvergenceChecker
    ) -> None:
        checker.score_history = [0.5, 0.5]
        assert checker.is_stagnating(window=3) is False

    def test_returns_true_when_recent_scores_flat(
        self, checker: ConvergenceChecker
    ) -> None:
        checker.score_history = [0.50, 0.52, 0.51]
        assert checker.is_stagnating(window=3, tolerance=0.05) is True

    def test_returns_false_when_recent_scores_changing(
        self, checker: ConvergenceChecker
    ) -> None:
        checker.score_history = [0.30, 0.50, 0.80]
        assert checker.is_stagnating(window=3, tolerance=0.05) is False


# ---------------------------------------------------------------------------
# RepetitionDetector
# ---------------------------------------------------------------------------


class TestRepetitionDetector:
    @pytest.mark.asyncio
    async def test_returns_false_without_calling_api_when_too_few(
        self, tmp_path: Path
    ) -> None:
        """発言数が window 未満なら API を呼ばずに False。"""
        client, mock = _make_client(tmp_path, [])
        detector = RepetitionDetector(client)

        result = await detector.check_repetition(
            recent_utterances=[_utterance("a"), _utterance("b")],
            window=4,
        )

        assert result.is_repeating is False
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_parses_repeating_response(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "is_repeating": True,
                "repeated_topic": "k の選び方",
                "suggestion": "別の論点に移る",
            }
        )
        client, _ = _make_client(tmp_path, [{"content": body}])
        detector = RepetitionDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(4)]

        result = await detector.check_repetition(utterances, window=4)

        assert result.is_repeating is True
        assert result.repeated_topic == "k の選び方"
        assert result.suggestion == "別の論点に移る"

    @pytest.mark.asyncio
    async def test_parses_non_repeating_response(self, tmp_path: Path) -> None:
        body = json.dumps({"is_repeating": False})
        client, _ = _make_client(tmp_path, [{"content": body}])
        detector = RepetitionDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(4)]

        result = await detector.check_repetition(utterances)

        assert result.is_repeating is False

    @pytest.mark.asyncio
    async def test_unparseable_response_yields_safe_default(
        self, tmp_path: Path
    ) -> None:
        client, _ = _make_client(tmp_path, [{"content": "broken"}])
        detector = RepetitionDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(4)]

        result = await detector.check_repetition(utterances)

        assert result.is_repeating is False


# ---------------------------------------------------------------------------
# AgreementDetector
# ---------------------------------------------------------------------------


class TestAgreementDetector:
    @pytest.mark.asyncio
    async def test_returns_false_when_too_few_utterances(
        self, tmp_path: Path
    ) -> None:
        client, mock = _make_client(tmp_path, [])
        detector = AgreementDetector(client)

        result = await detector.check_excessive_agreement(
            recent_utterances=[_utterance("a"), _utterance("b")],
            window=3,
        )

        assert result is False
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_true_when_response_starts_with_true(self, tmp_path: Path) -> None:
        client, _ = _make_client(tmp_path, [{"content": "true"}])
        detector = AgreementDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(3)]

        result = await detector.check_excessive_agreement(utterances)

        assert result is True

    @pytest.mark.asyncio
    async def test_false_when_response_is_false(self, tmp_path: Path) -> None:
        client, _ = _make_client(tmp_path, [{"content": "false"}])
        detector = AgreementDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(3)]

        result = await detector.check_excessive_agreement(utterances)

        assert result is False

    @pytest.mark.asyncio
    async def test_case_insensitive_true(self, tmp_path: Path) -> None:
        client, _ = _make_client(tmp_path, [{"content": "TRUE\n"}])
        detector = AgreementDetector(client)
        utterances = [_utterance(f"a{i}") for i in range(3)]

        result = await detector.check_excessive_agreement(utterances)

        assert result is True
