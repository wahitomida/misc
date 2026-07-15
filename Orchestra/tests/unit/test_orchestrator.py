"""``core.orchestrator.Orchestrator`` のユニットテスト。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.config_loader import Settings
from core.data_models import OrchestraPlan
from core.exceptions import (
    InputTooLongError,
    InputTooShortError,
    PlanValidationError,
)
from core.orchestrator import (
    MAX_INPUT_CHARS,
    Orchestrator,
    PLANNING_PROMPT,
)
from core.rate_tracker import RateLimitTracker
from core.role_manager import RoleManager
from tests.mocks.mock_api import MockAPIClient


REPO_ROLES_DIR = Path(__file__).resolve().parents[2] / "config" / "roles"


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _valid_plan_json(
    selected_agents: list[dict[str, Any]] | None = None,
    rounds: list[dict[str, Any]] | None = None,
    instructions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """設計書 §4.6 のスキーマに準拠した最小プラン辞書。"""
    if selected_agents is None:
        selected_agents = [
            {
                "role_id": "theorist",
                "model": "gpt-5.4",
                "level": "high",
                "reason": "数式的定式化",
                "expected_contribution": "理論基盤の確立",
            },
            {
                "role_id": "devil",
                "model": "claude-sonnet-4-5",
                "level": "medium",
                "reason": "穴探し",
                "expected_contribution": "前提検証",
            },
        ]
    if rounds is None:
        rounds = [
            {
                "round": 1,
                "phase_name": "問題定式化",
                "speakers": ["theorist"],
                "pattern": "one_shot",
                "level": "medium",
                "time_budget_sec": 40,
                "goal": "数学的整理",
            },
            {
                "round": 2,
                "phase_name": "穴探し",
                "speakers": ["devil"],
                "pattern": "one_shot",
                "level": "medium",
                "time_budget_sec": 40,
                "goal": "反例検証",
            },
        ]
    if instructions is None:
        instructions = {
            "theorist": {
                "expected_contribution": "定式化",
                "focus_points": ["計算量"],
                "constraints": ["実装の話はしない"],
                "context_from_plan": "R1中心",
                "feedback_reminder": "",
            },
            "devil": {
                "expected_contribution": "反例提示",
                "focus_points": ["密度不均一"],
                "constraints": ["修復案も添える"],
                "context_from_plan": "R2中心",
                "feedback_reminder": "",
            },
        }
    return {
        "odsc": {
            "objective": "テーマを多角的に評価する",
            "deliverable": "提案手法の骨格 + 実験計画",
            "success_criteria": "アルゴリズム骨格の合意",
            "convergence_threshold": 0.8,
        },
        "selected_agents": selected_agents,
        "discussion_plan": {
            "estimated_rounds": len(rounds),
            "round_config": rounds,
            "total_estimated_time_sec": sum(r["time_budget_sec"] for r in rounds),
            "total_estimated_requests": 20,
        },
        "private_instructions": instructions,
    }


def _make_orchestrator(
    tmp_path: Path,
    *,
    responses: list[dict[str, Any]] | None = None,
    feedback_manager: Any = None,
) -> tuple[Orchestrator, MockAPIClient, Settings]:
    """テスト用の Orchestrator + MockAPIClient + Settings。"""
    if responses is None:
        responses = [{"content": json.dumps(_valid_plan_json())}]
    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    api_client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    role_manager = RoleManager(REPO_ROLES_DIR)
    settings = Settings.load(
        config_dir=Path(__file__).resolve().parents[2] / "config",
        env_file=tmp_path / "missing.env",
    )
    orch = Orchestrator(
        api_client=api_client,
        role_manager=role_manager,
        feedback_manager=feedback_manager,
        settings=settings,
    )
    return orch, mock, settings


# ---------------------------------------------------------------------------
# 入力検証
# ---------------------------------------------------------------------------


class TestInputValidation:
    """``_validate_input`` の境界条件。"""

    @pytest.mark.asyncio
    async def test_empty_input_raises_too_short(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        with pytest.raises(InputTooShortError):
            await orch.plan(user_input="")

    @pytest.mark.asyncio
    async def test_whitespace_only_input_raises_too_short(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        with pytest.raises(InputTooShortError):
            await orch.plan(user_input="   \n   ")

    @pytest.mark.asyncio
    async def test_too_long_input_raises_too_long(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        with pytest.raises(InputTooLongError):
            await orch.plan(user_input="a" * (MAX_INPUT_CHARS + 1))


# ---------------------------------------------------------------------------
# ハッピーパス
# ---------------------------------------------------------------------------


class TestPlanHappyPath:
    """正常系: モック応答を受け取って ``OrchestraPlan`` を組み立てる。"""

    @pytest.mark.asyncio
    async def test_plan_returns_orchestra_plan(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)

        plan = await orch.plan(user_input="点群GNNでの特徴抽出設計指針")

        assert isinstance(plan, OrchestraPlan)
        assert plan.odsc.objective.startswith("テーマを")
        assert plan.odsc.convergence_threshold == pytest.approx(0.8)
        assert {a.role_id for a in plan.selected_agents} == {"theorist", "devil"}
        assert plan.discussion_plan is not None
        assert len(plan.discussion_plan.round_config) == 2
        assert "theorist" in plan.private_instructions

    @pytest.mark.asyncio
    async def test_plan_uses_planner_model_from_settings(self, tmp_path: Path) -> None:
        """settings.models.planner がデフォルトで使われる。"""
        orch, mock, settings = _make_orchestrator(tmp_path)

        await orch.plan(user_input="テストテーマです")

        mock.assert_call_count(1)
        called_model = mock.call_log[0]["model"]
        assert called_model == settings.models["planner"]

    @pytest.mark.asyncio
    async def test_plan_uses_cli_model_override(self, tmp_path: Path) -> None:
        """``model`` 引数で settings を上書きできる。"""
        orch, mock, _ = _make_orchestrator(tmp_path)

        await orch.plan(user_input="テストテーマです", model="gpt-4.1")

        assert mock.call_log[0]["model"] == "gpt-4.1"


# ---------------------------------------------------------------------------
# _extract_json / Markdown フェンス対応
# ---------------------------------------------------------------------------


class TestJsonExtraction:
    """``_extract_json`` が複数の応答形式を扱える。"""

    @pytest.mark.asyncio
    async def test_plain_json_response(self, tmp_path: Path) -> None:
        body = json.dumps(_valid_plan_json())
        orch, _, _ = _make_orchestrator(tmp_path, responses=[{"content": body}])
        plan = await orch.plan(user_input="テストテーマです")
        assert plan.odsc.deliverable.startswith("提案手法")

    @pytest.mark.asyncio
    async def test_json_inside_markdown_fence(self, tmp_path: Path) -> None:
        body = "```json\n" + json.dumps(_valid_plan_json()) + "\n```"
        orch, _, _ = _make_orchestrator(tmp_path, responses=[{"content": body}])
        plan = await orch.plan(user_input="テストテーマです")
        assert plan.odsc.objective

    @pytest.mark.asyncio
    async def test_json_inside_anonymous_fence(self, tmp_path: Path) -> None:
        body = "```\n" + json.dumps(_valid_plan_json()) + "\n```"
        orch, _, _ = _make_orchestrator(tmp_path, responses=[{"content": body}])
        plan = await orch.plan(user_input="テストテーマです")
        assert plan.odsc.objective

    @pytest.mark.asyncio
    async def test_json_with_surrounding_explanation(self, tmp_path: Path) -> None:
        """JSON の前後に説明文があっても抽出できる。"""
        body = (
            "了解しました。以下が計画です:\n\n"
            + json.dumps(_valid_plan_json())
            + "\n\nご確認ください。"
        )
        orch, _, _ = _make_orchestrator(tmp_path, responses=[{"content": body}])
        plan = await orch.plan(user_input="テストテーマです")
        assert plan.odsc.objective


# ---------------------------------------------------------------------------
# パースエラー
# ---------------------------------------------------------------------------


class TestParseErrors:
    """``_parse_plan_response`` が不正入力を検出する。"""

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, tmp_path: Path) -> None:
        """空応答は ``PlanValidationError("empty")`` で弾く。

        GPT-5 系では空応答リカバリが走るため、ここでは標準モデル
        (``gpt-4.1``) を明示指定してリカバリを回避する。
        """
        orch, _, _ = _make_orchestrator(tmp_path, responses=[{"content": ""}])
        with pytest.raises(PlanValidationError, match="empty"):
            await orch.plan(user_input="テストテーマです", model="gpt-4.1")

    @pytest.mark.asyncio
    async def test_non_json_response_raises(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": "これは JSON ではありません"}]
        )
        with pytest.raises(PlanValidationError, match="No JSON object found"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_malformed_json_raises(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": "{ broken json"}]
        )
        with pytest.raises(PlanValidationError, match="not valid JSON"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_missing_top_level_key_raises(self, tmp_path: Path) -> None:
        data = _valid_plan_json()
        del data["selected_agents"]
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="selected_agents"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_missing_odsc_key_raises(self, tmp_path: Path) -> None:
        data = _valid_plan_json()
        del data["odsc"]["success_criteria"]
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="success_criteria"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_missing_round_key_raises(self, tmp_path: Path) -> None:
        data = _valid_plan_json()
        del data["discussion_plan"]["round_config"][0]["pattern"]
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="pattern"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_empty_selected_agents_raises(self, tmp_path: Path) -> None:
        data = _valid_plan_json(selected_agents=[])
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="non-empty"):
            await orch.plan(user_input="テストテーマです")


# ---------------------------------------------------------------------------
# _validate_plan: 構造整合
# ---------------------------------------------------------------------------


class TestPlanValidation:
    """``_validate_plan`` の整合性検証。"""

    @pytest.mark.asyncio
    async def test_unknown_role_id_raises(self, tmp_path: Path) -> None:
        """``config/roles/`` に存在しない role_id は弾く。"""
        data = _valid_plan_json(
            selected_agents=[
                {
                    "role_id": "nonexistent_role",
                    "model": "gpt-4.1",
                    "level": "medium",
                }
            ]
        )
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="unknown role_ids"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_speaker_not_in_selected_agents_raises(self, tmp_path: Path) -> None:
        """ラウンドの speakers が selected_agents に含まれない場合は弾く。"""
        data = _valid_plan_json(
            selected_agents=[
                {"role_id": "theorist", "model": "gpt-5.4", "level": "medium"},
            ],
            rounds=[
                {
                    "round": 1,
                    "phase_name": "r1",
                    "speakers": ["theorist", "devil"],  # devil は未選定
                    "pattern": "one_shot",
                    "level": "medium",
                    "time_budget_sec": 30,
                    "goal": "g",
                }
            ],
            instructions={"theorist": {"expected_contribution": "x"}},
        )
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )
        with pytest.raises(PlanValidationError, match="not in selected_agents"):
            await orch.plan(user_input="テストテーマです")

    @pytest.mark.asyncio
    async def test_overrunning_plan_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """合計推定時間が制限時間の 90% を超えると警告ログ。"""
        # 非常に重い計画 (各ラウンド high, 多人数) を作る
        agents = [
            {"role_id": rid, "model": "gpt-5.4", "level": "high"}
            for rid in ["theorist", "experimentalist", "implementer",
                        "literature", "devil"]
        ]
        rounds = [
            {
                "round": i + 1,
                "phase_name": f"phase{i+1}",
                "speakers": [a["role_id"] for a in agents],
                "pattern": "one_shot",
                "level": "high",
                "time_budget_sec": 100.0,
                "goal": "g",
            }
            for i in range(5)
        ]
        instructions = {
            a["role_id"]: {"expected_contribution": "x"} for a in agents
        }
        data = _valid_plan_json(
            selected_agents=agents, rounds=rounds, instructions=instructions
        )
        orch, _, _ = _make_orchestrator(
            tmp_path, responses=[{"content": json.dumps(data)}]
        )

        with caplog.at_level(logging.WARNING, logger="core.orchestrator"):
            # 60 秒制限に対し各ラウンド 5*20+5=105 秒 * 5 ラウンド = 525 秒で大幅超過
            await orch.plan(
                user_input="超過テスト",
                time_limit_sec=60.0,
            )

        warnings = [r for r in caplog.records if "exceeds discussion budget" in r.message]
        assert warnings, "Expected an overrun warning"


# ---------------------------------------------------------------------------
# プロンプト構築
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    """``_build_planning_prompt`` の構築結果。"""

    def test_prompt_includes_user_input_and_constraints(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)

        prompt = orch._build_planning_prompt(
            user_input="テストテーマXYZ",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario=None,
        )

        assert "テストテーマXYZ" in prompt
        # 圧縮版 planning_prompt.txt は「制限時間 {N} 秒で」形式
        assert "制限時間 300 秒で" in prompt
        assert "最大 5 体" in prompt
        assert "expertise レベル: intermediate" in prompt

    def test_prompt_lists_all_available_roles(self, tmp_path: Path) -> None:
        """8 ロール全てがプロンプトに列挙される。"""
        orch, _, _ = _make_orchestrator(tmp_path)
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario=None,
        )
        for role_id in [
            "theorist", "experimentalist", "implementer",
            "literature", "devil", "bird_eye",
            "code_architect", "code_reviewer",
        ]:
            assert role_id in prompt

    def test_prompt_follow_up_section_when_provided(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up={
                "previous_session_id": "20260601_120000_idea",
                "previous_conclusion": "前回はXに合意",
                "new_input": "今回は実装段階",
            },
            scenario=None,
        )
        assert "【follow-up情報】" in prompt
        assert "20260601_120000_idea" in prompt
        assert "前回はXに合意" in prompt

    def test_prompt_follow_up_section_absent_when_not_provided(
        self, tmp_path: Path
    ) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario=None,
        )
        assert "【follow-up情報】" not in prompt

    def test_prompt_scenario_section_when_provided(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario={"focus": "performance", "code_state": "prototype"},
        )
        assert "【シナリオ設定】" in prompt
        assert "focus: performance" in prompt
        assert "code_state: prototype" in prompt

    def test_prompt_has_no_unresolved_placeholders(self, tmp_path: Path) -> None:
        orch, _, _ = _make_orchestrator(tmp_path)
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario=None,
        )
        # ``{user_input}`` 等の単純プレースホルダが残っていない
        for name in ("user_input", "time_limit_sec", "max_agents", "expertise"):
            assert "{" + name + "}" not in prompt


class TestFeedbackInjection:
    """``feedback_manager`` が与えられた場合のプロンプト挿入。"""

    def test_feedback_context_included(self, tmp_path: Path) -> None:
        class StubFB:
            def generate_context_from_history(self, role_id: str) -> str:
                if role_id == "theorist":
                    return "- 過去の改善点: 代替案の具体性\n- 期待: 改善継続"
                return ""

        orch, _, _ = _make_orchestrator(tmp_path, feedback_manager=StubFB())
        prompt = orch._build_planning_prompt(
            user_input="x",
            roles=orch.role_manager.list_available_roles(),
            time_limit_sec=300.0,
            max_agents=5,
            expertise="intermediate",
            follow_up=None,
            scenario=None,
        )
        assert "代替案の具体性" in prompt
        assert "改善継続" in prompt


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------


class TestConstants:
    def test_planning_prompt_is_a_string_template(self) -> None:
        assert "{user_input}" in PLANNING_PROMPT
        assert "{roles_section}" in PLANNING_PROMPT
        assert "{time_limit_sec" in PLANNING_PROMPT  # フォーマット指定子もあるので前方一致
