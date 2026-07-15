"""``core.synthesizer.Synthesizer`` のユニットテスト (D-4 前半)。

評価統合 + ``session_meta`` 生成のみを検証する。レポート生成スタブが空
文字列を返すことも確認する。
"""

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
    AgentEvaluations,
    DiscussionLog,
    DiscussionPlan,
    OrchestraPlan,
    PeerEvaluation,
    RoundLog,
    SelfEvaluation,
    SynthesisResult,
    Utterance,
)
from core.evaluator import Evaluator
from core.rate_tracker import RateLimitTracker
from core.synthesizer import (
    DEFAULT_SYNTHESIZER_MODEL,
    ORCHESTRATOR_EVALUATION_PROMPT,
    Synthesizer,
)
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class FakeAgent:
    """``Synthesizer`` / ``Evaluator`` から見える ``Agent`` の最小スタブ。"""

    def __init__(
        self,
        role_id: str,
        display_name: str | None = None,
    ) -> None:
        self.role_id = role_id
        self.display_name = display_name or role_id
        self.evaluation_criteria = [
            {"name": "c1", "description": "d1"},
            {"name": "c2", "description": "d2"},
            {"name": "c3", "description": "d3"},
        ]
        self.config = AgentConfig(
            role_id=role_id,
            model="gpt-4.1",
            level="medium",
            expected_contribution="テスト貢献",
        )


class StubEvaluator:
    """``Evaluator.request_combined_evaluation`` を制御するスタブ。"""

    def __init__(
        self,
        per_agent: dict[str, AgentEvaluations] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self.per_agent = per_agent or {}
        self.raise_for = raise_for or set()
        self.calls: list[str] = []

    async def request_combined_evaluation(
        self,
        agent: FakeAgent,
        other_agents: list[FakeAgent],
        discussion_log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> AgentEvaluations:
        del other_agents, discussion_log, plan
        self.calls.append(agent.role_id)
        if agent.role_id in self.raise_for:
            raise RuntimeError(f"stub failure for {agent.role_id}")
        if agent.role_id in self.per_agent:
            return self.per_agent[agent.role_id]
        # デフォルト: 全部 3 点の評価
        return AgentEvaluations(
            self_eval=SelfEvaluation(
                scores={"c1": 3, "c2": 3, "c3": 3},
                avg_score=3.0,
                reasoning=f"{agent.role_id} reasoning",
            ),
            peer_evals={},
        )


def _utterance(speaker: str, content: str) -> Utterance:
    return Utterance(
        sequence=1,
        speaker=speaker,
        speaker_display=speaker,
        type="discussion",
        content=content,
        model="gpt-4.1",
        level="medium",
    )


def _plan(role_ids: list[str] | None = None) -> OrchestraPlan:
    role_ids = role_ids or ["theorist", "devil"]
    return OrchestraPlan(
        odsc=ODSC(
            objective="テスト目的",
            deliverable="テスト成果物",
            success_criteria="テスト合格基準",
            convergence_threshold=0.8,
        ),
        selected_agents=[
            AgentConfig(role_id=rid, model="gpt-4.1", level="medium")
            for rid in role_ids
        ],
        discussion_plan=DiscussionPlan(estimated_rounds=2),
    )


def _log() -> DiscussionLog:
    return DiscussionLog(
        rounds=[
            RoundLog(
                round=1,
                duration_sec=10.0,
                phase_name="R1",
                goal="g1",
                public_utterances=[
                    _utterance("theorist", "理論整理"),
                    _utterance("devil", "穴指摘"),
                ],
            ),
            RoundLog(
                round=2,
                duration_sec=12.0,
                phase_name="R2",
                goal="g2",
                public_utterances=[
                    _utterance("theorist", "修復案"),
                ],
            ),
        ],
        final_convergence_score=0.85,
        score_history=[0.4, 0.85],
    )


def _make_synthesizer(
    tmp_path: Path,
    *,
    responses: list[dict[str, Any]] | None = None,
    evaluator: Any = None,
) -> tuple[Synthesizer, MockAPIClient]:
    mock = MockAPIClient(responses=responses or [])
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
    synth = Synthesizer(
        api_client=client,
        feedback_manager=None,
        settings=settings,
        evaluator=evaluator,
    )
    return synth, mock


def _orchestrator_eval_json() -> str:
    """有効な orchestrator evaluation 応答 JSON 文字列。"""
    return json.dumps(
        {
            "overall_discussion_quality": 4.2,
            "mvp": {"role_id": "theorist", "reason": "理論の核心を明確化"},
            "odsc_achievement": {
                "achieved": True,
                "detail": "目標達成",
                "objective_met": True,
                "deliverable_met": True,
                "criteria_met": True,
            },
            "per_agent_feedback": {
                "theorist": {
                    "strengths_noted": ["s1", "s2"],
                    "improvements_noted": ["i1"],
                    "orchestrator_feedback": "次回も期待",
                },
                "devil": {
                    "strengths_noted": ["s1"],
                    "improvements_noted": ["i1"],
                    "orchestrator_feedback": "批判力維持",
                },
            },
        }
    )


# ---------------------------------------------------------------------------
# 初期化
# ---------------------------------------------------------------------------


class TestSynthesizerInit:
    def test_default_model_from_settings(self, tmp_path: Path) -> None:
        """settings.models.synthesizer がデフォルトで使われる。"""
        synth, _ = _make_synthesizer(tmp_path)
        # settings.yaml の synthesizer = "gpt-5.4"
        assert synth.model == "gpt-5.4"

    def test_creates_default_evaluator_when_not_provided(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        assert isinstance(synth.evaluator, Evaluator)

    def test_uses_injected_evaluator(self, tmp_path: Path) -> None:
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(tmp_path, evaluator=stub)
        assert synth.evaluator is stub


# ---------------------------------------------------------------------------
# _run_evaluations
# ---------------------------------------------------------------------------


class TestRunEvaluations:
    @pytest.mark.asyncio
    async def test_evaluates_all_agents_in_parallel(self, tmp_path: Path) -> None:
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(tmp_path, evaluator=stub)
        agents = [FakeAgent("a"), FakeAgent("b"), FakeAgent("c")]

        result = await synth._run_evaluations(agents, _log(), _plan(["a", "b", "c"]))

        assert set(result.keys()) == {"a", "b", "c"}
        assert sorted(stub.calls) == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_empty_agents_returns_empty_dict(self, tmp_path: Path) -> None:
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(tmp_path, evaluator=stub)

        result = await synth._run_evaluations([], _log(), _plan())

        assert result == {}
        assert stub.calls == []

    @pytest.mark.asyncio
    async def test_failed_agent_is_excluded(self, tmp_path: Path) -> None:
        """1 agent が例外を投げても他の評価は完了する。"""
        stub = StubEvaluator(raise_for={"devil"})
        synth, _ = _make_synthesizer(tmp_path, evaluator=stub)
        agents = [FakeAgent("theorist"), FakeAgent("devil")]

        result = await synth._run_evaluations(agents, _log(), _plan())

        assert "theorist" in result
        assert "devil" not in result


# ---------------------------------------------------------------------------
# _generate_orchestrator_evaluation
# ---------------------------------------------------------------------------


class TestGenerateOrchestratorEvaluation:
    @pytest.mark.asyncio
    async def test_parses_valid_response(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(
            tmp_path, responses=[{"content": _orchestrator_eval_json()}]
        )
        evaluations = {
            "theorist": AgentEvaluations(self_eval=SelfEvaluation(avg_score=4.0)),
            "devil": AgentEvaluations(self_eval=SelfEvaluation(avg_score=3.5)),
        }

        result = await synth._generate_orchestrator_evaluation(
            evaluations, _plan(), _log()
        )

        assert result.overall_discussion_quality == pytest.approx(4.2)
        assert result.mvp_role_id == "theorist"
        assert "理論の核心" in result.mvp_reason
        assert result.odsc_achievement.achieved is True
        assert result.odsc_achievement.objective_met is True
        assert result.odsc_achievement.convergence_final == pytest.approx(0.85)
        assert "theorist" in result.per_agent_feedback
        assert result.per_agent_feedback["theorist"].strengths_noted == ["s1", "s2"]
        assert result.per_agent_feedback["devil"].orchestrator_feedback == "批判力維持"

    @pytest.mark.asyncio
    async def test_clips_overall_quality(self, tmp_path: Path) -> None:
        body = json.dumps(
            {
                "overall_discussion_quality": 99.0,  # 範囲外
                "mvp": {"role_id": "theorist", "reason": "x"},
                "odsc_achievement": {"achieved": True},
                "per_agent_feedback": {},
            }
        )
        synth, _ = _make_synthesizer(tmp_path, responses=[{"content": body}])

        result = await synth._generate_orchestrator_evaluation(
            {}, _plan(), _log()
        )

        assert result.overall_discussion_quality == 5.0

    @pytest.mark.asyncio
    async def test_handles_markdown_fence(self, tmp_path: Path) -> None:
        body = "```json\n" + _orchestrator_eval_json() + "\n```"
        synth, _ = _make_synthesizer(tmp_path, responses=[{"content": body}])

        result = await synth._generate_orchestrator_evaluation(
            {}, _plan(), _log()
        )

        assert result.mvp_role_id == "theorist"

    @pytest.mark.asyncio
    async def test_empty_response_returns_default_with_convergence(
        self, tmp_path: Path
    ) -> None:
        """空応答でも default + convergence_final は埋まる。"""
        synth, _ = _make_synthesizer(tmp_path, responses=[{"content": ""}])

        result = await synth._generate_orchestrator_evaluation(
            {}, _plan(), _log()
        )

        assert result.overall_discussion_quality == 0.0
        assert result.mvp_role_id == ""
        assert result.odsc_achievement.convergence_final == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_malformed_json_returns_default(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(
            tmp_path, responses=[{"content": "{ broken"}]
        )

        result = await synth._generate_orchestrator_evaluation(
            {}, _plan(), _log()
        )

        assert result.overall_discussion_quality == 0.0
        assert result.per_agent_feedback == {}


# ---------------------------------------------------------------------------
# プロンプト構築
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def test_prompt_includes_odsc_and_log(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {
            "theorist": AgentEvaluations(
                self_eval=SelfEvaluation(
                    scores={"c1": 4}, avg_score=4.0, reasoning="ok"
                ),
                peer_evals={"devil": PeerEvaluation(score=4, comment="good")},
            )
        }
        prompt = synth._build_orchestrator_eval_prompt(
            evaluations, _plan(), _log()
        )

        assert "テスト目的" in prompt
        assert "テスト合格基準" in prompt
        assert "Round 1" in prompt
        assert "theorist: 理論整理" in prompt

    def test_prompt_has_no_unresolved_placeholders(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {
            "theorist": AgentEvaluations(self_eval=SelfEvaluation())
        }
        prompt = synth._build_orchestrator_eval_prompt(
            evaluations, _plan(), _log()
        )

        for name in (
            "odsc",
            "full_discussion_log",
            "self_evaluations_formatted",
            "peer_evaluations_formatted",
            "per_agent_template",
        ):
            assert "{" + name + "}" not in prompt


class TestPromptConstants:
    def test_orchestrator_prompt_has_required_placeholders(self) -> None:
        for name in (
            "odsc",
            "full_discussion_log",
            "self_evaluations_formatted",
            "peer_evaluations_formatted",
            "per_agent_template",
        ):
            assert "{" + name + "}" in ORCHESTRATOR_EVALUATION_PROMPT


# ---------------------------------------------------------------------------
# _generate_session_meta
# ---------------------------------------------------------------------------


class TestGenerateSessionMeta:
    def test_session_meta_has_required_keys(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {"theorist": AgentEvaluations(self_eval=SelfEvaluation())}

        meta = synth._generate_session_meta(
            plan=_plan(),
            log=_log(),
            evaluations=evaluations,
            expertise="expert",
        )

        for key in (
            "session_id",
            "started_at",
            "ended_at",
            "duration_sec",
            "expertise",
            "plan_summary",
            "statistics",
        ):
            assert key in meta

    def test_statistics_summarize_log(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)

        meta = synth._generate_session_meta(
            plan=_plan(),
            log=_log(),
            evaluations={"theorist": AgentEvaluations(self_eval=SelfEvaluation())},
            expertise="intermediate",
        )

        stats = meta["statistics"]
        assert stats["total_rounds"] == 2
        assert stats["total_utterances"] == 3  # round 1: 2 + round 2: 1
        assert stats["final_convergence_score"] == pytest.approx(0.85)
        assert stats["score_history"] == [0.4, 0.85]
        assert stats["participating_agents"] == ["theorist"]

    def test_explicit_session_id_is_used(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)

        meta = synth._generate_session_meta(
            plan=_plan(),
            log=_log(),
            evaluations={},
            expertise="intermediate",
            session_id="20260601_120000_idea",
        )

        assert meta["session_id"] == "20260601_120000_idea"

    def test_auto_session_id_has_expected_format(self, tmp_path: Path) -> None:
        """自動生成された session_id は YYYYMMDD_HHMMSS_idea。"""
        synth, _ = _make_synthesizer(tmp_path)

        meta = synth._generate_session_meta(
            plan=_plan(),
            log=_log(),
            evaluations={},
            expertise="intermediate",
        )

        sid = meta["session_id"]
        # 例: "20260619_153022_idea"
        assert sid.endswith("_idea")
        assert len(sid.split("_")[0]) == 8  # YYYYMMDD


# ---------------------------------------------------------------------------
# synthesize: end-to-end
# ---------------------------------------------------------------------------


class TestSynthesizeEndToEnd:
    @pytest.mark.asyncio
    async def test_synthesize_returns_synthesis_result(self, tmp_path: Path) -> None:
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(
            tmp_path,
            responses=[{"content": _orchestrator_eval_json()}],
            evaluator=stub,
        )
        agents = {
            "theorist": FakeAgent("theorist"),
            "devil": FakeAgent("devil"),
        }

        result = await synth.synthesize(
            plan=_plan(["theorist", "devil"]),
            discussion_log=_log(),
            agents=agents,
            expertise="intermediate",
        )

        assert isinstance(result, SynthesisResult)
        # 評価が並列実行され、全 agent 分埋まる
        assert set(result.agent_evaluations.keys()) == {"theorist", "devil"}
        # 指揮者総合評価
        assert result.orchestrator_evaluation.mvp_role_id == "theorist"
        # session_meta
        assert "session_id" in result.session_meta

    @pytest.mark.asyncio
    async def test_report_fields_are_filled(self, tmp_path: Path) -> None:
        """D-4 後半: 4 種のレポートが非空文字列で埋まる。"""
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(
            tmp_path,
            responses=[{"content": _orchestrator_eval_json()}],
            evaluator=stub,
        )

        result = await synth.synthesize(
            plan=_plan(),
            discussion_log=_log(),
            agents={"theorist": FakeAgent("theorist"), "devil": FakeAgent("devil")},
        )

        assert result.report_md != ""
        assert result.full_conversation_md != ""
        assert result.evaluation_md != ""
        assert result.summary_txt != ""
        # コードレビュー専用は機能②で埋める
        assert result.vibe_coding_prompt_md is None
        assert result.feedback_updates == {}

    @pytest.mark.asyncio
    async def test_synthesize_with_missing_agent_skips_it(self, tmp_path: Path) -> None:
        """``plan.selected_agents`` に対応する Agent が無くてもエラーにしない。"""
        stub = StubEvaluator()
        synth, _ = _make_synthesizer(
            tmp_path,
            responses=[{"content": _orchestrator_eval_json()}],
            evaluator=stub,
        )

        result = await synth.synthesize(
            plan=_plan(["theorist", "devil"]),
            discussion_log=_log(),
            agents={"theorist": FakeAgent("theorist")},  # devil なし
        )

        # theorist のみが評価される
        assert set(result.agent_evaluations.keys()) == {"theorist"}


# ---------------------------------------------------------------------------
# レポート生成 (D-4 後半)
# ---------------------------------------------------------------------------


def _eval_with_scores(
    self_scores: dict[str, int],
    peer: dict[str, tuple[int, str]] | None = None,
) -> AgentEvaluations:
    """テスト用 AgentEvaluations ビルダー。"""
    avg = sum(self_scores.values()) / len(self_scores) if self_scores else 0.0
    peer_evals = {}
    for target, (score, comment) in (peer or {}).items():
        peer_evals[target] = PeerEvaluation(score=score, comment=comment)
    return AgentEvaluations(
        self_eval=SelfEvaluation(
            scores=self_scores,
            avg_score=round(avg, 2),
            reasoning="reasoning text",
            key_contributions=["contribution-1"],
            missed_opportunities=["missed-1"],
        ),
        peer_evals=peer_evals,
    )


def _full_orchestrator_eval() -> "OrchestratorEvaluation":
    from core.data_models import OrchestratorEvaluation as _OE

    from core.data_models import (
        AgentFeedback,
        ODSCAchievement,
    )

    return _OE(
        overall_discussion_quality=4.2,
        mvp_role_id="theorist",
        mvp_reason="理論面で議論を主導",
        odsc_achievement=ODSCAchievement(
            achieved=True,
            detail="目標達成",
            objective_met=True,
            deliverable_met=True,
            criteria_met=True,
            convergence_final=0.85,
        ),
        per_agent_feedback={
            "theorist": AgentFeedback(
                strengths_noted=["s1", "s2"],
                improvements_noted=["i1"],
                orchestrator_feedback="次回も期待",
            ),
            "devil": AgentFeedback(
                strengths_noted=["s1"],
                improvements_noted=["i1"],
                orchestrator_feedback="批判力維持",
            ),
        },
    )


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_report_includes_required_sections(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {
            "theorist": _eval_with_scores({"c1": 4, "c2": 5, "c3": 4}),
            "devil": _eval_with_scores({"c1": 4, "c2": 4, "c3": 4}),
        }

        report = await synth._generate_report(
            _plan(), _log(), evaluations, _full_orchestrator_eval(), "intermediate"
        )

        # ヘッダ
        assert "# 🔬 AI Orchestra 技術検討レポート" in report
        # ODSC.objective
        assert "テスト目的" in report
        # 主要セクション (§14.5.1)
        for section in (
            "## 1. 問題設定",
            "## 2. 技術的洞察",
            "## 3. 提案手法の骨格",
            "## 4. 仮説テーブル",
            "## 5. 実験計画",
            "## 6. 未解決問題",
            "## 7. 参考文献",
        ):
            assert section in report
        # ツール名フッタ
        assert "AI Orchestra v1.0" in report

    @pytest.mark.asyncio
    async def test_report_reflects_convergence_score(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        report = await synth._generate_report(
            _plan(), _log(), {}, _full_orchestrator_eval(), "intermediate"
        )
        assert "収束度**: 0.85" in report

    @pytest.mark.asyncio
    async def test_report_includes_hypotheses_when_extracted(
        self, tmp_path: Path
    ) -> None:
        """ログに H1/H2 が含まれていればテーブル形式で表示される。"""
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=10.0,
                    phase_name="R1",
                    goal="g1",
                    public_utterances=[
                        _utterance("theorist", "H1: multi-scale > single k"),
                        _utterance("devil", "H2 では密度不均一を検証"),
                    ],
                )
            ],
            final_convergence_score=0.6,
        )
        synth, _ = _make_synthesizer(tmp_path)
        report = await synth._generate_report(
            _plan(), log, {}, _full_orchestrator_eval(), "intermediate"
        )

        assert "| ID | 仮説 |" in report
        assert "H1" in report
        assert "H2" in report


class TestGenerateFullConversation:
    @pytest.mark.asyncio
    async def test_conversation_contains_all_rounds_and_utterances(
        self, tmp_path: Path
    ) -> None:
        synth, _ = _make_synthesizer(tmp_path)

        text = await synth._generate_full_conversation(_plan(), _log(), None)

        assert "## 🎼 舞台裏: 計画フェーズ" in text
        assert "## 💬 Round 1: R1" in text
        assert "## 💬 Round 2: R2" in text
        # 各発言が表示される
        for content in ("理論整理", "穴指摘", "修復案"):
            assert content in text

    @pytest.mark.asyncio
    async def test_conversation_includes_convergence_blocks(
        self, tmp_path: Path
    ) -> None:
        """ラウンドの convergence_check が表示される。"""
        from core.data_models import ConvergenceResult

        log = _log()
        log.rounds[0].convergence_check = ConvergenceResult(
            score=0.42,
            reasoning="まだ序盤",
            remaining_disagreements=["k の選び方"],
            recommendation="continue",
        )
        synth, _ = _make_synthesizer(tmp_path)

        text = await synth._generate_full_conversation(_plan(), log, None)

        assert "🎼 [収束: 0.42]" in text
        assert "まだ序盤" in text
        assert "k の選び方" in text
        assert "recommendation = continue" in text

    @pytest.mark.asyncio
    async def test_conversation_indicates_early_termination(
        self, tmp_path: Path
    ) -> None:
        log = _log()
        log.early_termination = "converged"
        log.termination_detail = "score 0.92 >= threshold 0.8"
        synth, _ = _make_synthesizer(tmp_path)

        text = await synth._generate_full_conversation(_plan(), log, None)

        assert "[早期終了] reason = converged" in text
        assert "score 0.92" in text


class TestGenerateEvaluationMd:
    @pytest.mark.asyncio
    async def test_includes_ranking_and_individual_details(
        self, tmp_path: Path
    ) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {
            "theorist": _eval_with_scores(
                {"定式化": 5, "深化": 4, "計算量": 4},
                peer={"devil": (4, "理論面で議論を導いた")},
            ),
            "devil": _eval_with_scores(
                {"穴の発見": 5, "反例の具体性": 4, "修復案": 4},
                peer={"theorist": (5, "理論を破ろうとした")},
            ),
        }

        md = await synth._generate_evaluation_md(
            evaluations, _full_orchestrator_eval()
        )

        assert "## 🏆 総合スコアランキング" in md
        # ランキング表のヘッダ
        assert "| 順位 | AI | 自己評価 | 他者評価 | 総合 |" in md
        # 個別評価セクション
        assert "### theorist" in md
        assert "### devil" in md
        # 自己振り返り
        assert "reasoning text" in md
        # 主な貢献 / やり残し
        assert "contribution-1" in md
        assert "missed-1" in md
        # 指揮者フィードバック
        assert "次回も期待" in md
        assert "批判力維持" in md
        # 議論品質指標
        assert "## 📈 議論品質の指標" in md
        assert "MVP" in md

    @pytest.mark.asyncio
    async def test_handles_no_evaluations(self, tmp_path: Path) -> None:
        """評価が空でも例外なくレポートを生成する。"""
        synth, _ = _make_synthesizer(tmp_path)
        from core.data_models import OrchestratorEvaluation

        md = await synth._generate_evaluation_md({}, OrchestratorEvaluation())

        assert "(評価データなし)" in md


class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_summary_is_plain_text_with_required_sections(
        self, tmp_path: Path
    ) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        evaluations = {
            "theorist": _eval_with_scores({"c1": 4}),
        }

        text = await synth._generate_summary(
            _plan(), _log(), evaluations, _full_orchestrator_eval()
        )

        # 罫線
        assert text.startswith("━")
        assert "AI Orchestra 結果サマリ" in text
        # セクション
        for section in ("━━ 結論 ━━", "━━ 主要洞察 ━━", "━━ 統計 ━━"):
            assert section in text
        # 統計値
        assert "収束: 0.85" in text
        assert "MVP: theorist" in text

    @pytest.mark.asyncio
    async def test_summary_includes_extracted_hypotheses(
        self, tmp_path: Path
    ) -> None:
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=10.0,
                    phase_name="R1",
                    goal="g1",
                    public_utterances=[
                        _utterance("theorist", "H1: multi-scale > single k"),
                        _utterance("devil", "H2 では密度不均一を検証"),
                    ],
                )
            ],
            final_convergence_score=0.6,
        )
        synth, _ = _make_synthesizer(tmp_path)
        from core.data_models import OrchestratorEvaluation

        text = await synth._generate_summary(
            _plan(), log, {}, OrchestratorEvaluation()
        )

        assert "━━ 仮説 (2個) ━━" in text
        assert "H1" in text
        assert "H2" in text


# ---------------------------------------------------------------------------
# _extract_hypotheses
# ---------------------------------------------------------------------------


class TestExtractHypotheses:
    @pytest.mark.asyncio
    async def test_extracts_id_pattern(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "H1: multi-scale が効く"),
                        _utterance("b", "H2 は実験で検証する"),
                        _utterance("c", "H3 は再現性を確認する"),
                    ],
                )
            ]
        )

        result = await synth._extract_hypotheses(log)

        ids = [h["id"] for h in result]
        assert ids == ["H1", "H2", "H3"]
        for h in result:
            assert h["status"] == "unverified"
            assert "verification" in h

    @pytest.mark.asyncio
    async def test_deduplicates_repeated_ids(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "H1 を提示"),
                        _utterance("b", "H1 を再度議論"),
                    ],
                )
            ]
        )

        result = await synth._extract_hypotheses(log)

        ids = [h["id"] for h in result]
        assert ids == ["H1"]

    @pytest.mark.asyncio
    async def test_falls_back_to_keyword_search(self, tmp_path: Path) -> None:
        """ID が無いが「仮説」を含む発言を補助的に拾う。"""
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "仮説: multi-scale が密度不均一に効く"),
                        _utterance("b", "別の hypothesis として、PE 不要説"),
                    ],
                )
            ]
        )

        result = await synth._extract_hypotheses(log)

        assert len(result) == 2
        # ID なしのキーワード検出は連番 (H1, H2) で振り直される
        assert [h["id"] for h in result] == ["H1", "H2"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_log(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)

        result = await synth._extract_hypotheses(DiscussionLog())

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_hypothesis_markers(
        self, tmp_path: Path
    ) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "ただの発言です"),
                        _utterance("b", "もうひとつの発言"),
                    ],
                )
            ]
        )

        result = await synth._extract_hypotheses(log)

        assert result == []


# ---------------------------------------------------------------------------
# 引用抽出 / duration フォーマッタ
# ---------------------------------------------------------------------------


class TestCitationExtraction:
    def test_extracts_author_year_pattern(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "PointNet (Qi+2017) は古典的だ"),
                        _utterance("b", "DGCNN (Wang+2019) を引用"),
                        _utterance("c", "(Smith+2023, arXiv) は preprint"),
                    ],
                )
            ]
        )
        citations = synth._extract_citations(log)
        assert "(Qi+2017)" in citations
        assert "(Wang+2019)" in citations
        assert "(Smith+2023, arXiv)" in citations

    def test_deduplicates_citations(self, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        log = DiscussionLog(
            rounds=[
                RoundLog(
                    round=1,
                    duration_sec=1.0,
                    public_utterances=[
                        _utterance("a", "(Qi+2017) を引用"),
                        _utterance("b", "また (Qi+2017) を引用"),
                    ],
                )
            ]
        )
        citations = synth._extract_citations(log)
        assert citations == ["(Qi+2017)"]


class TestDurationFormatter:
    @pytest.mark.parametrize(
        ("sec", "expected"),
        [
            (0.0, "0秒"),
            (45.7, "46秒"),
            (60.0, "1分00秒"),
            (216.0, "3分36秒"),
        ],
    )
    def test_format_duration(self, sec: float, expected: str, tmp_path: Path) -> None:
        synth, _ = _make_synthesizer(tmp_path)
        assert synth._format_duration(sec) == expected
