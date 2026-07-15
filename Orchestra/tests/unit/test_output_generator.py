"""``core.output_generator.OutputGenerator`` のユニットテスト。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from core.data_models import (
    ODSC,
    AgentConfig,
    AgentEvaluations,
    AgentFeedback,
    ConvergenceResult,
    DiscussionLog,
    DiscussionPlan,
    ODSCAchievement,
    OrchestraPlan,
    OrchestratorEvaluation,
    PeerEvaluation,
    PrivateInstruction,
    RoundConfig,
    RoundLog,
    SelfEvaluation,
    SynthesisResult,
    Utterance,
)
from core.output_generator import (
    SESSION_TYPE_IDEA,
    SESSION_TYPE_REVIEW,
    OutputGenerator,
)


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _utterance(speaker: str, content: str) -> Utterance:
    return Utterance(
        sequence=1,
        speaker=speaker,
        speaker_display=speaker,
        type="discussion",
        content=content,
        model="gpt-4.1",
        level="medium",
        tokens_used={"input": 100, "output": 30},
    )


def _plan() -> OrchestraPlan:
    return OrchestraPlan(
        odsc=ODSC(
            objective="テーマ: 点群GNN",
            deliverable="設計骨格",
            success_criteria="合意形成",
            convergence_threshold=0.8,
        ),
        selected_agents=[
            AgentConfig(role_id="theorist", model="gpt-5.4", level="high"),
            AgentConfig(role_id="devil", model="claude-sonnet-4-5", level="medium"),
        ],
        discussion_plan=DiscussionPlan(
            estimated_rounds=2,
            round_config=[
                RoundConfig(
                    round=1,
                    phase_name="P1",
                    speakers=["theorist", "devil"],
                    pattern="one_shot",
                    level="medium",
                    time_budget_sec=40,
                    goal="g1",
                ),
            ],
        ),
        private_instructions={
            "theorist": PrivateInstruction(
                role_id="theorist",
                expected_contribution="数式整理",
            ),
        },
    )


def _log() -> DiscussionLog:
    return DiscussionLog(
        rounds=[
            RoundLog(
                round=1,
                duration_sec=15.0,
                phase_name="P1",
                goal="g1",
                public_utterances=[
                    _utterance("theorist", "理論整理"),
                    _utterance("devil", "穴を指摘"),
                ],
                convergence_check=ConvergenceResult(
                    score=0.6,
                    reasoning="一部合意",
                    remaining_disagreements=["disagree1"],
                    recommendation="continue",
                ),
            ),
            RoundLog(
                round=2,
                duration_sec=20.0,
                phase_name="P2",
                goal="g2",
                public_utterances=[
                    _utterance("theorist", "修復案"),
                ],
                convergence_check=ConvergenceResult(
                    score=0.85,
                    reasoning="合意成立",
                    recommendation="conclude",
                ),
            ),
        ],
        final_convergence_score=0.85,
        score_history=[0.6, 0.85],
    )


def _synthesis(*, vibe: str | None = None) -> SynthesisResult:
    return SynthesisResult(
        report_md="# Report Header\n\n## 1. 問題設定\n",
        full_conversation_md="# 💬 議論完全台本\n",
        evaluation_md="# 📊 AI 評価レポート\n",
        summary_txt="━━ サマリ ━━",
        vibe_coding_prompt_md=vibe,
        agent_evaluations={
            "theorist": AgentEvaluations(
                self_eval=SelfEvaluation(
                    scores={"c1": 4, "c2": 5},
                    avg_score=4.5,
                    reasoning="ok",
                ),
                peer_evals={"devil": PeerEvaluation(score=4, comment="good")},
            ),
            "devil": AgentEvaluations(
                self_eval=SelfEvaluation(
                    scores={"d1": 3, "d2": 4},
                    avg_score=3.5,
                ),
                peer_evals={"theorist": PeerEvaluation(score=5, comment="great")},
            ),
        },
        orchestrator_evaluation=OrchestratorEvaluation(
            overall_discussion_quality=4.2,
            mvp_role_id="theorist",
            mvp_reason="議論を主導",
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
                    strengths_noted=["s1"],
                    improvements_noted=["i1"],
                    orchestrator_feedback="次回も期待",
                )
            },
        ),
        session_meta={
            "session_id": "20260620_143052_idea",
            "started_at": "2026-06-20T14:30:52+09:00",
            "ended_at": "2026-06-20T14:34:28+09:00",
            "expertise": "intermediate",
            "statistics": {
                "total_requests": 35,
                "total_utterances": 3,
            },
        },
    )


# ---------------------------------------------------------------------------
# generate_session_id
# ---------------------------------------------------------------------------


class TestGenerateSessionId:
    def test_format_idea(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        sid = gen.generate_session_id(SESSION_TYPE_IDEA)
        assert re.match(r"^\d{8}_\d{6}_idea$", sid)

    def test_format_review(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        sid = gen.generate_session_id(SESSION_TYPE_REVIEW)
        assert re.match(r"^\d{8}_\d{6}_review$", sid)

    def test_underscore_alias_method(self, tmp_path: Path) -> None:
        """``_generate_session_id`` (実装ガイドの命名) も動く。"""
        gen = OutputGenerator(tmp_path)
        assert gen._generate_session_id("idea").endswith("_idea")


# ---------------------------------------------------------------------------
# generate: 全体
# ---------------------------------------------------------------------------


class TestGenerateAllFiles:
    def test_generate_creates_session_dir(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)

        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )

        assert session_dir == tmp_path / "20260620_143052_idea"
        assert session_dir.exists()
        assert session_dir.is_dir()

    def test_generate_creates_six_required_files(self, tmp_path: Path) -> None:
        """vibe なしの場合は 6 ファイル (vibe_coding_prompt.md は作らない)。"""
        gen = OutputGenerator(tmp_path)

        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(vibe=None),
        )

        expected_files = {
            "session_meta.json",
            "discussion.json",
            "full_conversation.md",
            "report.md",
            "evaluation.md",
            "summary.txt",
        }
        actual_files = {p.name for p in session_dir.iterdir()}
        assert expected_files <= actual_files
        assert "vibe_coding_prompt.md" not in actual_files

    def test_generate_creates_vibe_prompt_when_present(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)

        session_dir = gen.generate(
            session_id="20260625_150000_review",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(vibe="# Vibe Prompt\n"),
        )

        vibe_path = session_dir / "vibe_coding_prompt.md"
        assert vibe_path.exists()
        assert vibe_path.read_text(encoding="utf-8") == "# Vibe Prompt\n"

    def test_generate_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        """output_dir が存在しなくても自動作成される。"""
        nested = tmp_path / "deep" / "nested" / "output"
        gen = OutputGenerator(nested)

        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )

        assert session_dir.exists()
        assert (session_dir / "session_meta.json").exists()

    def test_existing_session_dir_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """既存ディレクトリ + 既存ファイルがあっても警告のみで続行。"""
        sid = "20260620_143052_idea"
        existing = tmp_path / sid
        existing.mkdir()
        (existing / "legacy.txt").write_text("pre-existing")

        gen = OutputGenerator(tmp_path)

        with caplog.at_level("WARNING"):
            gen.generate(
                session_id=sid,
                plan=_plan(),
                discussion_log=_log(),
                synthesis=_synthesis(),
            )

        # 警告ログが出る
        assert any("already contains files" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# session_meta.json の中身
# ---------------------------------------------------------------------------


class TestSessionMeta:
    def test_session_meta_has_required_fields(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )

        meta = json.loads(
            (session_dir / "session_meta.json").read_text(encoding="utf-8")
        )

        for key in (
            "_schema_version",
            "session_id",
            "type",
            "status",
            "created_at",
            "completed_at",
            "duration_sec",
            "user_prompt",
            "expertise",
            "models_used",
            "agents_used",
            "total_rounds",
            "final_convergence",
            "evaluation_summary",
            "output_files",
            "follow_up",
        ):
            assert key in meta, f"missing key: {key}"

    def test_session_meta_reflects_plan_and_log(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )
        meta = json.loads(
            (session_dir / "session_meta.json").read_text(encoding="utf-8")
        )

        assert meta["session_id"] == "20260620_143052_idea"
        assert meta["type"] == "idea_discussion"
        assert meta["status"] == "completed"
        assert meta["user_prompt"] == "テーマ: 点群GNN"
        assert sorted(meta["agents_used"]) == ["devil", "theorist"]
        assert meta["total_rounds"] == 2
        assert meta["final_convergence"] == 0.85
        assert meta["evaluation_summary"]["mvp"] == "theorist"

    def test_session_type_review_reflected(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260625_150000_review",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(vibe="x"),
        )
        meta = json.loads(
            (session_dir / "session_meta.json").read_text(encoding="utf-8")
        )

        assert meta["type"] == "code_review"
        # vibe ありなのでファイル名が紐付く
        assert meta["output_files"]["vibe_coding_prompt_md"] == "vibe_coding_prompt.md"

    def test_session_meta_vibe_null_when_absent(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(vibe=None),
        )
        meta = json.loads(
            (session_dir / "session_meta.json").read_text(encoding="utf-8")
        )

        assert meta["output_files"]["vibe_coding_prompt_md"] is None


# ---------------------------------------------------------------------------
# discussion.json の中身
# ---------------------------------------------------------------------------


class TestDiscussionJson:
    def test_discussion_json_has_top_level_sections(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )

        data = json.loads(
            (session_dir / "discussion.json").read_text(encoding="utf-8")
        )

        for key in (
            "_schema_version",
            "_generated_by",
            "_generated_at",
            "session",
            "planning",
            "discussion",
            "evaluation",
            "orchestrator_evaluation",
        ):
            assert key in data

    def test_discussion_section_contains_rounds(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )
        data = json.loads(
            (session_dir / "discussion.json").read_text(encoding="utf-8")
        )

        rounds = data["discussion"]["rounds"]
        assert len(rounds) == 2
        assert rounds[0]["round"] == 1
        assert len(rounds[0]["public_utterances"]) == 2
        assert rounds[0]["convergence_check"]["score"] == 0.6
        assert rounds[1]["convergence_check"]["recommendation"] == "conclude"

    def test_planning_section_includes_odsc_and_agents(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )
        data = json.loads(
            (session_dir / "discussion.json").read_text(encoding="utf-8")
        )

        odsc = data["planning"]["odsc"]
        assert odsc["objective"] == "テーマ: 点群GNN"
        agents = data["planning"]["selected_agents"]
        assert {a["role_id"] for a in agents} == {"theorist", "devil"}
        # private_instructions
        assert "theorist" in data["planning"]["private_instructions"]

    def test_evaluation_section_has_each_agent(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=_synthesis(),
        )
        data = json.loads(
            (session_dir / "discussion.json").read_text(encoding="utf-8")
        )

        evaluation = data["evaluation"]
        assert set(evaluation.keys()) == {"theorist", "devil"}
        assert evaluation["theorist"]["self_evaluation"]["avg_score"] == 4.5
        assert evaluation["theorist"]["peer_evaluations"]["devil"]["score"] == 4


# ---------------------------------------------------------------------------
# Markdown / text ファイルの中身
# ---------------------------------------------------------------------------


class TestMarkdownAndTextWrites:
    def test_report_content_matches_synthesis(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        synth = _synthesis()
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=synth,
        )

        text = (session_dir / "report.md").read_text(encoding="utf-8")
        assert text == synth.report_md

    def test_full_conversation_content(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        synth = _synthesis()
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=synth,
        )
        text = (session_dir / "full_conversation.md").read_text(encoding="utf-8")
        assert text == synth.full_conversation_md

    def test_evaluation_md_content(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        synth = _synthesis()
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=synth,
        )
        text = (session_dir / "evaluation.md").read_text(encoding="utf-8")
        assert text == synth.evaluation_md

    def test_summary_txt_content(self, tmp_path: Path) -> None:
        gen = OutputGenerator(tmp_path)
        synth = _synthesis()
        session_dir = gen.generate(
            session_id="20260620_143052_idea",
            plan=_plan(),
            discussion_log=_log(),
            synthesis=synth,
        )
        text = (session_dir / "summary.txt").read_text(encoding="utf-8")
        assert text == synth.summary_txt
