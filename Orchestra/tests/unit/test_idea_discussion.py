"""``features.idea_discussion.IdeaDiscussion`` のユニットテスト。

実 API は使わず ``MockAPIClient`` で全フェーズを通す。レポート生成
(``Synthesizer`` 後半) は LLM 非経由なので 1 回の API 呼び出し
(orchestrator evaluation) だけ仕込めば動く。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.api_client import ResilientAPIClient, RetryConfig
from core.config_loader import Settings
from core.data_models import OrchestraPlan
from core.exceptions import InputTooLongError, InputTooShortError
from core.feedback import FeedbackManager
from core.rate_tracker import RateLimitTracker
from core.role_manager import RoleManager
from features.idea_discussion import (
    MAX_INPUT_CHARS,
    MIN_INPUT_CHARS,
    SCENARIO_KEYWORDS,
    IdeaDiscussion,
)
from tests.mocks.mock_api import MockAPIClient


REPO_ROLES_DIR = Path(__file__).resolve().parents[2] / "config" / "roles"
REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _planner_response_json(
    agents: list[dict[str, Any]] | None = None,
    rounds: list[dict[str, Any]] | None = None,
) -> str:
    """Orchestrator が要求する JSON 形式の最小レスポンス。"""
    agents = agents or [
        {
            "role_id": "theorist",
            "model": "gpt-5.4",
            "level": "medium",
            "reason": "テスト",
            "expected_contribution": "数式整理",
        }
    ]
    rounds = rounds or [
        {
            "round": 1,
            "phase_name": "問題定式化",
            "speakers": ["theorist"],
            "pattern": "one_shot",
            "level": "medium",
            "time_budget_sec": 20,
            "goal": "理論整理",
        }
    ]
    return json.dumps(
        {
            "odsc": {
                "objective": "テスト目的",
                "deliverable": "テスト成果物",
                "success_criteria": "テスト合格基準",
                "convergence_threshold": 0.8,
            },
            "selected_agents": agents,
            "discussion_plan": {
                "estimated_rounds": len(rounds),
                "round_config": rounds,
                "total_estimated_time_sec": sum(r["time_budget_sec"] for r in rounds),
                "total_estimated_requests": 5,
            },
            "private_instructions": {
                a["role_id"]: {
                    "expected_contribution": "x",
                    "focus_points": ["p1"],
                    "constraints": ["c1"],
                    "context_from_plan": "round 1",
                    "feedback_reminder": "",
                }
                for a in agents
            },
        }
    )


def _convergence_response_json(
    score: float = 0.85, recommendation: str = "conclude"
) -> str:
    return json.dumps(
        {
            "score": score,
            "reasoning": "テスト合意",
            "remaining_disagreements": [],
            "recommendation": recommendation,
        }
    )


def _orchestrator_eval_json(role_ids: list[str]) -> str:
    return json.dumps(
        {
            "overall_discussion_quality": 4.0,
            "mvp": {"role_id": role_ids[0], "reason": "テストMVP"},
            "odsc_achievement": {
                "achieved": True,
                "detail": "目標達成",
                "objective_met": True,
                "deliverable_met": True,
                "criteria_met": True,
            },
            "per_agent_feedback": {
                rid: {
                    "strengths_noted": ["s1", "s2"],
                    "improvements_noted": ["i1"],
                    "orchestrator_feedback": "次回も期待",
                }
                for rid in role_ids
            },
        }
    )


@pytest.fixture
def roles_copy_dir(tmp_path: Path) -> Path:
    """同梱のロール YAML を tmp_path にクリーンコピー (feedback 書き込み副作用を隔離)。

    実運用で蓄積された ``feedback_history`` / ``feedback_stats`` /
    ``personality.observed_weaknesses`` はテストの初期状態を崩すので除去する。
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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(
        config_dir=REPO_CONFIG_DIR,
        env_file=tmp_path / "missing.env",
    )


def _make_idea_discussion(
    *,
    tmp_path: Path,
    roles_dir: Path,
    settings: Settings,
    responses: list[dict[str, Any]] | None = None,
    confirm: bool = True,
    feedback_manager: FeedbackManager | None = None,
) -> tuple[IdeaDiscussion, MockAPIClient]:
    """テスト用 IdeaDiscussion を構築する。"""
    mock = MockAPIClient(responses=responses or [])
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    role_manager = RoleManager(roles_dir)
    fm = feedback_manager
    if fm is None and feedback_manager is not False:  # type: ignore[comparison-overlap]
        fm = FeedbackManager(roles_dir)

    feature = IdeaDiscussion(
        api_client=client,
        role_manager=role_manager,
        feedback_manager=fm,
        settings=settings,
        confirm_callback=lambda plan: confirm,
    )
    return feature, mock


# ---------------------------------------------------------------------------
# _validate_input
# ---------------------------------------------------------------------------


class TestValidateInput:
    def test_short_input_raises(self) -> None:
        with pytest.raises(InputTooShortError):
            IdeaDiscussion._validate_input("ab")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(InputTooShortError):
            IdeaDiscussion._validate_input("   \n  ")

    def test_long_input_raises(self) -> None:
        with pytest.raises(InputTooLongError):
            IdeaDiscussion._validate_input("a" * (MAX_INPUT_CHARS + 1))

    def test_valid_input_trimmed(self) -> None:
        assert IdeaDiscussion._validate_input("  hello world  ") == "hello world"

    def test_min_boundary_passes(self) -> None:
        assert (
            IdeaDiscussion._validate_input("a" * MIN_INPUT_CHARS) == "a" * MIN_INPUT_CHARS
        )


# ---------------------------------------------------------------------------
# _detect_scenario
# ---------------------------------------------------------------------------


class TestDetectScenario:
    def test_none_when_no_keyword_match(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        assert feature._detect_scenario("apple banana cherry") is None

    def test_none_when_scenario_file_missing(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """キーワードマッチしてもシナリオファイルが無ければ None。"""
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        # シナリオディレクトリを空ディレクトリに差し替え
        empty_dir = tmp_path / "scenarios_empty"
        empty_dir.mkdir()
        monkeypatch.setattr(feature, "_scenarios_dir", lambda: empty_dir)
        assert feature._detect_scenario("アルゴリズムの設計を議論") is None

    def test_loads_scenario_when_file_present(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings,
    ) -> None:
        """F-3 で配置された ``config/scenarios/*.yaml`` を読み込めること。"""
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        scenario = feature._detect_scenario("アルゴリズムの設計を議論")
        assert scenario is not None
        assert scenario["scenario_id"] == "algorithm_design"

    def test_keywords_are_defined_for_three_scenarios(self) -> None:
        assert set(SCENARIO_KEYWORDS.keys()) == {
            "algorithm_design",
            "experiment_planning",
            "paper_discussion",
        }

    def test_scenario_file_loaded_when_present(
        self,
        tmp_path: Path,
        roles_copy_dir: Path,
        settings: Settings,
    ) -> None:
        """シナリオファイルを一時 config_dir に置けば読み込まれる。"""
        custom_config_dir = tmp_path / "custom_config"
        (custom_config_dir / "scenarios").mkdir(parents=True)
        scenario_yaml = (
            "scenario_id: algorithm_design\n"
            'display_name: "テスト"\n'
            'description: "test"\n'
        )
        (custom_config_dir / "scenarios" / "algorithm_design.yaml").write_text(
            scenario_yaml, encoding="utf-8"
        )

        # settings.config_dir を差し替える
        custom_settings = Settings.load(
            config_dir=REPO_CONFIG_DIR, env_file=tmp_path / "missing.env"
        )
        custom_settings.config_dir = custom_config_dir  # type: ignore[attr-defined]

        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=custom_settings
        )
        result = feature._detect_scenario("アルゴリズム設計を議論したい")

        assert result is not None
        assert result["scenario_id"] == "algorithm_design"


# ---------------------------------------------------------------------------
# _load_follow_up
# ---------------------------------------------------------------------------


class TestLoadFollowUp:
    def test_returns_none_when_session_id_is_none(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        assert feature._load_follow_up(None, None, None) is None

    def test_returns_minimal_context_with_session_id(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        ctx = feature._load_follow_up("20260601_120000_idea", None, ["H1", "H2"])
        assert ctx is not None
        assert ctx.parent_session_id == "20260601_120000_idea"
        assert ctx.focus_hypotheses == ["H1", "H2"]
        assert ctx.chain == ["20260601_120000_idea"]
        assert ctx.chain_depth == 1

    def test_loads_attached_files(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        attach = tmp_path / "attach.md"
        attach.write_text("テスト添付内容", encoding="utf-8")

        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        ctx = feature._load_follow_up("20260601_120000_idea", [attach], None)

        assert ctx is not None
        assert len(ctx.attached_files) == 1
        assert ctx.attached_files[0]["name"] == "attach.md"
        assert "テスト添付内容" in ctx.attached_files[0]["content"]

    def test_missing_file_raises(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        with pytest.raises(FileNotFoundError):
            feature._load_follow_up(
                "20260601_120000_idea", [tmp_path / "nonexistent.md"], None
            )


# ---------------------------------------------------------------------------
# _confirm_execution
# ---------------------------------------------------------------------------


class TestConfirmExecution:
    def test_returns_true_when_callback_returns_true(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path,
            roles_dir=roles_copy_dir,
            settings=settings,
            confirm=True,
        )
        plan = OrchestraPlan(
            odsc=type(
                "ODSCStub",
                (),
                {
                    "objective": "x",
                    "deliverable": "x",
                    "success_criteria": "x",
                    "convergence_threshold": 0.8,
                },
            )()
        )
        assert feature._confirm_execution(plan) is True

    def test_returns_false_when_callback_returns_false(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path,
            roles_dir=roles_copy_dir,
            settings=settings,
            confirm=False,
        )
        plan = OrchestraPlan(
            odsc=type(
                "ODSCStub",
                (),
                {
                    "objective": "x",
                    "deliverable": "x",
                    "success_criteria": "x",
                    "convergence_threshold": 0.8,
                },
            )()
        )
        assert feature._confirm_execution(plan) is False

    def test_returns_false_when_callback_raises(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        from core.feedback import FeedbackManager

        mock = MockAPIClient(responses=[])
        tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
        client = ResilientAPIClient(
            base_client=mock,
            rate_tracker=tracker,
            retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
            mode="openai",
        )

        def boom(plan: Any) -> bool:
            raise RuntimeError("test failure")

        feature = IdeaDiscussion(
            api_client=client,
            role_manager=RoleManager(roles_copy_dir),
            feedback_manager=FeedbackManager(roles_copy_dir),
            settings=settings,
            confirm_callback=boom,
        )
        from core.data_models import ODSC

        plan = OrchestraPlan(
            odsc=ODSC(
                objective="x",
                deliverable="x",
                success_criteria="x",
                convergence_threshold=0.8,
            )
        )
        assert feature._confirm_execution(plan) is False


# ---------------------------------------------------------------------------
# _initialize_agents
# ---------------------------------------------------------------------------


class TestInitializeAgents:
    def test_creates_agent_per_selected(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        from core.data_models import (
            AgentConfig,
            ODSC,
            DiscussionPlan,
            PrivateInstruction,
        )

        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        plan = OrchestraPlan(
            odsc=ODSC(
                objective="x",
                deliverable="x",
                success_criteria="x",
                convergence_threshold=0.8,
            ),
            selected_agents=[
                AgentConfig(role_id="theorist", model="gpt-5.4", level="high"),
                AgentConfig(role_id="devil", model="claude-sonnet-4-5", level="medium"),
            ],
            discussion_plan=DiscussionPlan(estimated_rounds=1),
            private_instructions={
                "theorist": PrivateInstruction(
                    role_id="theorist",
                    expected_contribution="数式整理",
                    focus_points=["計算量"],
                    constraints=["実装の話はしない"],
                    context_from_plan="R1中心",
                ),
            },
        )

        agents = feature._initialize_agents(plan)

        assert set(agents.keys()) == {"theorist", "devil"}
        assert agents["theorist"].model == "gpt-5.4"
        assert agents["devil"].model == "claude-sonnet-4-5"
        # private instruction が反映されている
        assert "数式整理" in agents["theorist"].private_instruction
        assert "計算量" in agents["theorist"].private_instruction

    def test_skips_unknown_role(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        from core.data_models import AgentConfig, ODSC, DiscussionPlan

        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        plan = OrchestraPlan(
            odsc=ODSC(
                objective="x",
                deliverable="x",
                success_criteria="x",
                convergence_threshold=0.8,
            ),
            selected_agents=[
                AgentConfig(role_id="ghost", model="gpt-4.1", level="low"),
                AgentConfig(role_id="theorist", model="gpt-5.4", level="medium"),
            ],
            discussion_plan=DiscussionPlan(estimated_rounds=1),
        )

        agents = feature._initialize_agents(plan)

        assert set(agents.keys()) == {"theorist"}


# ---------------------------------------------------------------------------
# run (end-to-end with mocked LLM)
# ---------------------------------------------------------------------------


class TestRunEndToEnd:
    @pytest.mark.asyncio
    async def test_full_flow_produces_output_dir(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        """最小構成 (1 ラウンド × 1 agent) で全フローが完走する。"""
        # 必要な API レスポンス:
        # 1. Orchestrator.plan
        # 2. Conductor (Agent.speak × 1)
        # 3. ConvergenceChecker.check × 1
        # 4. Evaluator.request_combined_evaluation × 1 (agent ごと)
        # 5. Synthesizer._generate_orchestrator_evaluation × 1
        combined_eval_response = json.dumps(
            {
                "self_evaluation": {
                    "scores": {"c1": 4, "c2": 4, "c3": 4, "c4": 4},
                    "avg_score": 4.0,
                    "reasoning": "ok",
                    "key_contributions": ["k1"],
                    "missed_opportunities": ["m1"],
                },
                "peer_evaluations": {},
            }
        )
        responses = [
            {"content": _planner_response_json()},  # planner
            {"content": "**短い発言**"},  # agent speak
            {"content": _convergence_response_json()},  # convergence
            {"content": combined_eval_response},  # combined evaluation
            {"content": _orchestrator_eval_json(["theorist"])},  # orch eval
        ]
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path,
            roles_dir=roles_copy_dir,
            settings=settings,
            responses=responses,
            confirm=True,
        )

        output_dir = tmp_path / "out"
        result = await feature.run(
            user_input="テスト議論テーマ",
            planner_model="gpt-4.1",  # GPT-5 系の空応答リカバリ回避
            conductor_model="gpt-4.1",
            synth_model="gpt-4.1",
            time_limit=300,
            max_agents=2,
            output_dir=output_dir,
        )

        assert result is not None
        assert result.exists()
        # 6 ファイルが作成される (vibe なし)
        files = {p.name for p in result.iterdir()}
        for expected in (
            "session_meta.json",
            "discussion.json",
            "full_conversation.md",
            "report.md",
            "evaluation.md",
            "summary.txt",
        ):
            assert expected in files

    @pytest.mark.asyncio
    async def test_confirm_callback_false_returns_none(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        """ユーザーが拒否したら ``None`` を返し、Phase 2 以降は実行しない。"""
        responses = [{"content": _planner_response_json()}]  # planner だけ
        feature, mock = _make_idea_discussion(
            tmp_path=tmp_path,
            roles_dir=roles_copy_dir,
            settings=settings,
            responses=responses,
            confirm=False,
        )

        result = await feature.run(
            user_input="テスト議論",
            planner_model="gpt-4.1",
            time_limit=300,
        )

        assert result is None
        # 1 回 (planner) のみ呼ばれて Phase 2 以降は実行されない
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_full_flow_updates_feedback_yaml(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        """セッション完了後にロール YAML へ feedback_history が追記される。"""
        combined_eval_response = json.dumps(
            {
                "self_evaluation": {
                    "scores": {"c1": 4, "c2": 4, "c3": 4, "c4": 4},
                    "avg_score": 4.0,
                    "reasoning": "ok",
                    "key_contributions": ["k1"],
                    "missed_opportunities": ["m1"],
                },
                "peer_evaluations": {},
            }
        )
        responses = [
            {"content": _planner_response_json()},
            {"content": "短い発言"},
            {"content": "【結論】テストラウンドの結論"},
            # goal 達成度チェック (問題5対策で追加。achieved=true で追加発言不要)
            {"content": json.dumps({"achieved": True, "missing": ""})},
            {"content": _convergence_response_json()},
            {"content": combined_eval_response},
            {"content": _orchestrator_eval_json(["theorist"])},
        ]
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path,
            roles_dir=roles_copy_dir,
            settings=settings,
            responses=responses,
            confirm=True,
        )

        await feature.run(
            user_input="テスト議論",
            planner_model="gpt-4.1",
            conductor_model="gpt-4.1",
            synth_model="gpt-4.1",
            # BONUS_ROUND_MIN_REMAINING_SEC=30 未満で bonus round が発火しない。
            # 本テストは feedback_history 追記の検証のみで bonus round は範囲外。
            time_limit=25,
            max_agents=1,
            output_dir=tmp_path / "out",
        )

        import yaml as _yaml

        role = _yaml.safe_load(
            (roles_copy_dir / "theorist.yaml").read_text(encoding="utf-8")
        )
        history = role.get("feedback_history", [])
        assert len(history) == 1
        assert history[0]["topic"].startswith("テスト目的")
        assert history[0]["orchestrator_feedback"] == "次回も期待"

    @pytest.mark.asyncio
    async def test_run_input_validation_propagates(
        self, tmp_path: Path, roles_copy_dir: Path, settings: Settings
    ) -> None:
        feature, _ = _make_idea_discussion(
            tmp_path=tmp_path, roles_dir=roles_copy_dir, settings=settings
        )
        with pytest.raises(InputTooShortError):
            await feature.run(user_input="hi")
