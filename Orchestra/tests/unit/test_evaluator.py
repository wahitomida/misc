"""``core.evaluator.Evaluator`` のユニットテスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.config_loader import Settings
from core.data_models import (
    ODSC,
    AgentConfig,
    DiscussionLog,
    DiscussionPlan,
    OrchestraPlan,
    RoundLog,
    Utterance,
)
from core.evaluator import (
    COMBINED_EVALUATION_PROMPT,
    DEFAULT_EVALUATOR_MODEL,
    PEER_EVALUATION_PROMPT,
    SELF_EVALUATION_PROMPT,
    Evaluator,
)
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class FakeAgent:
    """``Evaluator`` から見える ``Agent`` の最小スタブ。"""

    def __init__(
        self,
        role_id: str,
        display_name: str | None = None,
        criteria: list[dict[str, str]] | None = None,
        expected: str = "テストの貢献",
    ) -> None:
        self.role_id = role_id
        self.display_name = display_name or role_id
        self.evaluation_criteria = criteria or [
            {"name": "c1", "description": "d1"},
            {"name": "c2", "description": "d2"},
            {"name": "c3", "description": "d3"},
        ]
        self.config = AgentConfig(
            role_id=role_id,
            model="gpt-4.1",
            level="medium",
            expected_contribution=expected,
        )


def _utterance(speaker: str, content: str, display: str | None = None) -> Utterance:
    return Utterance(
        sequence=1,
        speaker=speaker,
        speaker_display=display or speaker,
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


def _log() -> DiscussionLog:
    """2 ラウンド × 各 2 発言の簡易ログ。"""
    return DiscussionLog(
        rounds=[
            RoundLog(
                round=1,
                duration_sec=10.0,
                phase_name="R1",
                goal="goal-1",
                public_utterances=[
                    _utterance("theorist", "理論の整理"),
                    _utterance("devil", "穴を指摘"),
                ],
            ),
            RoundLog(
                round=2,
                duration_sec=12.0,
                phase_name="R2",
                goal="goal-2",
                public_utterances=[
                    _utterance("theorist", "修復案を提示"),
                    _utterance("devil", "更なる懸念"),
                ],
            ),
        ]
    )


def _make_evaluator(
    tmp_path: Path,
    responses: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> tuple[Evaluator, MockAPIClient]:
    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    settings = Settings.load(
        config_dir=Path(__file__).resolve().parents[2] / "config",
        env_file=tmp_path / "missing.env",
    )
    evaluator = Evaluator(api_client=client, settings=settings, model=model)
    return evaluator, mock


# ---------------------------------------------------------------------------
# 初期化
# ---------------------------------------------------------------------------


class TestEvaluatorInit:
    def test_default_model_falls_back_to_gpt41(self, tmp_path: Path) -> None:
        """settings.models に "evaluator" が無ければ ``gpt-4.1``。"""
        evaluator, _ = _make_evaluator(tmp_path, responses=[])
        assert evaluator.model == DEFAULT_EVALUATOR_MODEL

    def test_explicit_model_override(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, responses=[], model="gpt-5-mini")
        assert evaluator.model == "gpt-5-mini"


# ---------------------------------------------------------------------------
# self evaluation: 正常系
# ---------------------------------------------------------------------------


class TestRequestSelfEvaluation:
    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "scores": {"c1": 5, "c2": 4, "c3": 3},
                "avg_score": 4.0,
                "reasoning": "おおむね良好",
                "key_contributions": ["観点A", "観点B"],
                "missed_opportunities": ["観点C"],
            }
        )
        evaluator, mock = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.scores == {"c1": 5, "c2": 4, "c3": 3}
        assert result.avg_score == pytest.approx(4.0)
        assert "おおむね良好" in result.reasoning
        assert result.key_contributions == ["観点A", "観点B"]
        assert result.missed_opportunities == ["観点C"]
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_scores_are_clipped_to_1_5(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "scores": {"c1": 10, "c2": 0, "c3": -3},
                "reasoning": "テスト",
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        # 10 → 5、0 / -3 → 1 にクリップ
        assert result.scores == {"c1": 5, "c2": 1, "c3": 1}

    @pytest.mark.asyncio
    async def test_avg_score_recomputed_when_missing(self, tmp_path: Path) -> None:
        body = json.dumps({"scores": {"c1": 4, "c2": 4, "c3": 5}})
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.avg_score == pytest.approx((4 + 4 + 5) / 3, rel=1e-3)

    @pytest.mark.asyncio
    async def test_handles_markdown_fence(self, tmp_path: Path) -> None:
        body = "```json\n" + json.dumps({"scores": {"c1": 3}}) + "\n```"
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.scores == {"c1": 3}

    @pytest.mark.asyncio
    async def test_empty_response_returns_default(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [{"content": ""}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.scores == {}
        assert result.avg_score == 0.0

    @pytest.mark.asyncio
    async def test_malformed_json_returns_default(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [{"content": "{ broken json"}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.scores == {}

    @pytest.mark.asyncio
    async def test_non_numeric_score_is_skipped(self, tmp_path: Path) -> None:
        body = json.dumps(
            {"scores": {"c1": 4, "c2": "high", "c3": 3}}
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("theorist")

        result = await evaluator.request_self_evaluation(agent, _log(), _plan())

        assert result.scores == {"c1": 4, "c3": 3}  # c2 はスキップ


# ---------------------------------------------------------------------------
# peer evaluation
# ---------------------------------------------------------------------------


class TestRequestPeerEvaluation:
    @pytest.mark.asyncio
    async def test_parses_valid_peer_response(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "theorist": {"score": 5, "comment": "MVP級"},
                "devil": {"score": 4, "comment": "穴探しが鋭い"},
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist"), FakeAgent("devil")]

        result = await evaluator.request_peer_evaluation(agent, others, _log())

        assert set(result.keys()) == {"theorist", "devil"}
        assert result["theorist"].score == 5
        assert result["theorist"].comment == "MVP級"
        assert result["devil"].score == 4

    @pytest.mark.asyncio
    async def test_excludes_self_from_evaluation(self, tmp_path: Path) -> None:
        """``other_agents`` に自分自身が含まれていても評価しない。"""
        body = json.dumps(
            {
                "theorist": {"score": 4, "comment": "ok"},
                "experimentalist": {"score": 5, "comment": "自己評価!?"},
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [
            FakeAgent("theorist"),
            FakeAgent("experimentalist"),  # 自分自身 → 除外される
        ]

        result = await evaluator.request_peer_evaluation(agent, others, _log())

        assert "experimentalist" not in result
        assert "theorist" in result

    @pytest.mark.asyncio
    async def test_unknown_role_id_in_response_is_dropped(
        self, tmp_path: Path
    ) -> None:
        body = json.dumps(
            {
                "theorist": {"score": 4, "comment": "ok"},
                "ghost_role": {"score": 5, "comment": "誰？"},
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist")]

        result = await evaluator.request_peer_evaluation(agent, others, _log())

        assert "ghost_role" not in result
        assert "theorist" in result

    @pytest.mark.asyncio
    async def test_empty_others_does_not_call_api(self, tmp_path: Path) -> None:
        """評価対象が空 (自分しかいない) なら API を呼ばずに空辞書を返す。"""
        evaluator, mock = _make_evaluator(tmp_path, [])
        agent = FakeAgent("theorist")

        result = await evaluator.request_peer_evaluation(
            agent, [FakeAgent("theorist")], _log()
        )

        assert result == {}
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_score_clipped_to_1_5(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "theorist": {"score": 99, "comment": "too high"},
                "devil": {"score": "bad", "comment": "non-numeric"},
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist"), FakeAgent("devil")]

        result = await evaluator.request_peer_evaluation(agent, others, _log())

        assert result["theorist"].score == 5  # 99 → 5
        assert result["devil"].score == 0  # 数値変換不能なら 0


# ---------------------------------------------------------------------------
# combined evaluation
# ---------------------------------------------------------------------------


class TestRequestCombinedEvaluation:
    @pytest.mark.asyncio
    async def test_parses_self_and_peer_together(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "self_evaluation": {
                    "scores": {"c1": 4, "c2": 5, "c3": 3},
                    "avg_score": 4.0,
                    "reasoning": "test",
                    "key_contributions": ["x"],
                    "missed_opportunities": ["y"],
                },
                "peer_evaluations": {
                    "theorist": {"score": 5, "comment": "great"},
                    "devil": {"score": 3, "comment": "ok"},
                },
            }
        )
        evaluator, mock = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist"), FakeAgent("devil")]

        result = await evaluator.request_combined_evaluation(
            agent, others, _log(), _plan()
        )

        assert result.self_eval.scores == {"c1": 4, "c2": 5, "c3": 3}
        assert result.self_eval.avg_score == pytest.approx(4.0)
        assert set(result.peer_evals.keys()) == {"theorist", "devil"}
        assert result.peer_evals["theorist"].score == 5
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_combined_excludes_self_in_peer(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "self_evaluation": {"scores": {"c1": 4}},
                "peer_evaluations": {
                    "theorist": {"score": 4, "comment": "ok"},
                    "experimentalist": {"score": 5, "comment": "self!"},
                },
            }
        )
        evaluator, _ = _make_evaluator(tmp_path, [{"content": body}])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist")]

        result = await evaluator.request_combined_evaluation(
            agent, others, _log(), _plan()
        )

        assert "experimentalist" not in result.peer_evals
        assert "theorist" in result.peer_evals


# ---------------------------------------------------------------------------
# プロンプト構築
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def test_self_prompt_includes_role_and_criteria(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [])
        agent = FakeAgent(
            "theorist",
            display_name="🧮 理論屋",
            criteria=[
                {"name": "定式化", "description": "数学的な整理"},
                {"name": "理論根拠", "description": "定理引用"},
                {"name": "計算量", "description": "オーダー表記"},
            ],
        )
        prompt = evaluator._build_self_eval_prompt(agent, _log(), _plan())

        assert "🧮 理論屋" in prompt
        assert "theorist" in prompt
        assert "定式化" in prompt
        assert "理論根拠" in prompt
        # 期待される貢献
        assert "テストの貢献" in prompt
        # ODSC
        assert "テスト目的" in prompt
        assert "テスト合格基準" in prompt

    def test_self_prompt_highlights_own_utterances(self, tmp_path: Path) -> None:
        """当該 agent の発言が ``**`` で囲まれる。"""
        evaluator, _ = _make_evaluator(tmp_path, [])
        agent = FakeAgent("theorist")
        prompt = evaluator._build_self_eval_prompt(agent, _log(), _plan())

        # theorist の発言はハイライト、他は通常
        assert "**theorist: 理論の整理**" in prompt
        assert "**theorist: 修復案を提示**" in prompt
        assert "devil: 穴を指摘" in prompt
        assert "**devil: 穴を指摘**" not in prompt

    def test_peer_prompt_lists_other_agents(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [])
        agent = FakeAgent("experimentalist")
        others = [
            FakeAgent("theorist", display_name="🧮 理論屋"),
            FakeAgent("devil", display_name="😈 穴探し"),
        ]
        prompt = evaluator._build_peer_eval_prompt(agent, others, _log())

        assert "🧮 理論屋" in prompt
        assert "(theorist)" in prompt
        assert "😈 穴探し" in prompt
        # 自分自身は評価対象に含めない
        assert "experimentalist" not in prompt.replace("【あなた】", "").split(
            "【評価対象】"
        )[1].split("【議論ログ】")[0]

    def test_combined_prompt_has_both_sections(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [])
        agent = FakeAgent("experimentalist")
        others = [FakeAgent("theorist"), FakeAgent("devil")]
        prompt = evaluator._build_combined_eval_prompt(
            agent, others, _log(), _plan()
        )

        # self_evaluation と peer_evaluations の両方が含まれる
        assert "self_evaluation" in prompt
        assert "peer_evaluations" in prompt
        # 評価基準とテンプレート両方
        assert "<1-5の整数>" in prompt
        assert "<1-5>" in prompt

    def test_prompt_has_no_unresolved_placeholders(self, tmp_path: Path) -> None:
        evaluator, _ = _make_evaluator(tmp_path, [])
        agent = FakeAgent("theorist")
        others = [FakeAgent("devil"), FakeAgent("experimentalist")]

        for prompt in (
            evaluator._build_self_eval_prompt(agent, _log(), _plan()),
            evaluator._build_peer_eval_prompt(agent, others, _log()),
            evaluator._build_combined_eval_prompt(agent, others, _log(), _plan()),
        ):
            for name in (
                "role_display_name",
                "role_id",
                "expected_contribution",
                "evaluation_criteria_formatted",
                "discussion_log_with_highlights",
                "other_agents_list",
            ):
                assert "{" + name + "}" not in prompt


# ---------------------------------------------------------------------------
# プロンプト定数
# ---------------------------------------------------------------------------


class TestPromptConstants:
    def test_self_evaluation_prompt_has_required_placeholders(self) -> None:
        for name in (
            "role_display_name",
            "role_id",
            "expected_contribution",
            "evaluation_criteria_formatted",
            "objective",
            "success_criteria",
            "discussion_log_with_highlights",
            "scores_template",
        ):
            assert "{" + name + "}" in SELF_EVALUATION_PROMPT

    def test_peer_evaluation_prompt_has_required_placeholders(self) -> None:
        for name in (
            "self_role_display_name",
            "self_role_id",
            "other_agents_list",
            "discussion_log",
            "peer_template",
        ):
            assert "{" + name + "}" in PEER_EVALUATION_PROMPT

    def test_combined_prompt_has_both_sections(self) -> None:
        assert "self_evaluation" in COMBINED_EVALUATION_PROMPT
        assert "peer_evaluations" in COMBINED_EVALUATION_PROMPT
