"""機能①: 技術議論 (アイデアブラッシュアップ) の統合フロー。

責務:
    1. 入力バリデーション
    2. シナリオテンプレートの自動検出
    3. Phase 1: 計画立案 (``Orchestrator``)
    4. ユーザー確認
    5. Phase 2: 議論進行 (``Conductor``)
    6. Phase 3: 統合・評価 (``Synthesizer``)
    7. 出力ファイル群の生成 + フィードバック YAML 更新

設計書: ``doc/11_idea_discussion.md`` 全体
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from core.agent import Agent
from core.base_feature import (
    DiscussionFeatureBase,
    PhaseHandler,
    PhaseKey,
    PhaseKeyHandler,
)
from core.conductor import Conductor
from core.data_models import (
    AgentConfig,
    FollowUpContext,
    OrchestraPlan,
)
from core.discussion_common import DEFAULT_EXPERTISE, apply_speaking_rules
from core.exceptions import (
    InputTooLongError,
    InputTooShortError,
)
from core.intervention import InterventionHandler, NoIntervention
from core.memory import ConversationMemory
from core.orchestrator import Orchestrator
from core.output_generator import OutputGenerator, SESSION_TYPE_IDEA
from core.synthesizer import Synthesizer
from core.time_keeper import TimeKeeper

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings
    from core.feedback import FeedbackManager
    from core.role_manager import RoleManager

logger = logging.getLogger(__name__)

# Constants
MIN_INPUT_CHARS = 5
MAX_INPUT_CHARS = 5000
DEFAULT_TIME_LIMIT_SEC = 300.0
DEFAULT_MAX_AGENTS = 5
# expertise 別 tone prefix は core.discussion_common に集約。
# 変数名 DEFAULT_EXPERTISE は既存の外部参照を維持するため再エクスポート。

DEFAULT_PLANNER_MODEL = "gpt-5.4"
DEFAULT_PLANNER_LEVEL = "medium"
DEFAULT_CONDUCTOR_MODEL = "gpt-4.1"
DEFAULT_SYNTHESIZER_MODEL = "claude-sonnet-4-5"
DEFAULT_OUTPUT_DIR = Path("./output")
DEFAULT_SCENARIOS_SUBDIR = "scenarios"
MAX_ATTACHED_FILE_CHARS = 10000

# シナリオ検出キーワード (§11.3 シナリオの自動検出)
SCENARIO_KEYWORDS: dict[str, tuple[str, ...]] = {
    "algorithm_design": ("設計", "アルゴリズム", "手法", "アプローチ", "方式"),
    "experiment_planning": (
        "実験",
        "検証",
        "比較",
        "ベンチマーク",
        "評価",
    ),
    "paper_discussion": (
        "論文",
        "paper",
        "手法の理解",
        "読み会",
        "サーベイ",
    ),
}

ConfirmCallback = Callable[[OrchestraPlan], bool]
"""``plan`` を受け取り実行可否を返す確認コールバック。"""


def _default_confirm(plan: OrchestraPlan) -> bool:
    """デフォルトの確認 (常に True)。CLI 表示は G-1 で実装する。"""
    del plan
    return True


class IdeaDiscussion(DiscussionFeatureBase):
    """機能①: 技術議論の統合フロー。

    4 フェーズ構造 (入力 → 計画 → 議論 → 結果) に従う。

    Attributes:
        api_client: 共有 API クライアント。
        role_manager: ロール定義の取得元。
        feedback_manager: ロール YAML へのフィードバック蓄積。
        settings: 全体設定。
        confirm_callback: Phase 2 (計画) 完了後のユーザー確認関数。
            ``True`` を返せば Phase 3 (議論) に進む。テスト時は固定値
            callback を注入する。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        role_manager: "RoleManager",
        feedback_manager: "FeedbackManager | None",
        settings: "Settings",
        confirm_callback: ConfirmCallback = _default_confirm,
    ) -> None:
        super().__init__(
            api_client=api_client,
            role_manager=role_manager,
            feedback_manager=feedback_manager,
            settings=settings,
        )
        self.confirm_callback = confirm_callback

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        planner_model: str = DEFAULT_PLANNER_MODEL,
        conductor_model: str = DEFAULT_CONDUCTOR_MODEL,
        synth_model: str = DEFAULT_SYNTHESIZER_MODEL,
        time_limit: float = DEFAULT_TIME_LIMIT_SEC,
        max_agents: int = DEFAULT_MAX_AGENTS,
        expertise: str = DEFAULT_EXPERTISE,
        follow_up_id: str | None = None,
        attached_files: list[Path] | None = None,
        focus_hypotheses: list[str] | None = None,
        output_dir: Path | None = None,
        on_phase: PhaseHandler | None = None,
        on_phase_key: PhaseKeyHandler | None = None,
        intervention: InterventionHandler | None = None,
    ) -> Path | None:
        """機能①の完全フローを実行する (4 フェーズ)。

        Args:
            user_input: 議論テーマ。
            planner_model: Phase 2 (計画) 用モデル名。
            conductor_model: Phase 3 (議論) 進行用モデル名。
            synth_model: Phase 4 (結果) 統合用モデル名。
            time_limit: 議論全体の制限時間 (秒)。
            max_agents: 最大参加 AI 数。
            expertise: ``beginner`` / ``intermediate`` / ``expert``。
            follow_up_id: フォローアップ元セッション ID。
            attached_files: 添付ファイル (Path のリスト)。
            focus_hypotheses: 重点的に検証する仮説 ID のリスト。
            output_dir: 出力ディレクトリ。``None`` なら ``./output``。
            on_phase: 下位互換のフェーズ通知 (name のみ)。
            on_phase_key: 新形式のフェーズ通知 (PhaseKey + name)。

        Returns:
            生成されたセッションディレクトリの ``Path``。
            ユーザー確認で拒否された場合は ``None``。

        Raises:
            InputTooShortError: 入力が短すぎる。
            InputTooLongError: 入力が長すぎる。
        """
        # Phase 1: 入力 — バリデーション + follow-up 読み込み + シナリオ検出
        self.notify_phase(PhaseKey.INPUT, on_phase=on_phase, on_phase_key=on_phase_key)
        validated_input = self._validate_input(user_input)
        follow_up_context = self._load_follow_up(
            follow_up_id, attached_files, focus_hypotheses
        )
        scenario = self._detect_scenario(validated_input)

        # TimeKeeper は Phase 2 開始前に生成する。start_time = Phase 2 開始時刻とし、
        # Phase 2 (計画) 完了時に phase1_actual_sec (= 計画時間) を書き込む。
        # これで discussion_elapsed (= elapsed - phase1_actual_sec) が Phase 3
        # (議論) 開始時に 0 となる。
        time_keeper = TimeKeeper(time_limit_sec=time_limit)

        # Phase 2: 計画 — Orchestrator による ODSC/plan 生成
        self.notify_phase(PhaseKey.PLANNING, on_phase=on_phase, on_phase_key=on_phase_key)
        orchestrator = Orchestrator(
            api_client=self.api_client,
            role_manager=self.role_manager,
            feedback_manager=self.feedback_manager,
            settings=self.settings,
        )
        phase_planning_start = time.time()
        plan = await orchestrator.plan(
            user_input=validated_input,
            model=planner_model,
            level=DEFAULT_PLANNER_LEVEL,
            time_limit_sec=time_limit,
            max_agents=max_agents,
            expertise=expertise,
            follow_up_context=(
                self._follow_up_to_dict(follow_up_context)
                if follow_up_context
                else None
            ),
            scenario=scenario,
        )
        time_keeper.phase1_actual_sec = time.time() - phase_planning_start

        # 計画確認 (ユーザーが拒否したら中断)
        if not self._confirm_execution(plan):
            logger.info("User declined plan; aborting.")
            return None

        return await self._execute_discussion_and_synthesis(
            plan=plan,
            time_keeper=time_keeper,
            conductor_model=conductor_model,
            synth_model=synth_model,
            expertise=expertise,
            follow_up_context=follow_up_context,
            output_dir=output_dir,
            on_phase=on_phase,
            on_phase_key=on_phase_key,
            intervention=intervention,
        )

    async def run_from_plan(
        self,
        user_input: str,
        plan: OrchestraPlan,
        conductor_model: str = DEFAULT_CONDUCTOR_MODEL,
        synth_model: str = DEFAULT_SYNTHESIZER_MODEL,
        time_limit: float = DEFAULT_TIME_LIMIT_SEC,
        expertise: str = DEFAULT_EXPERTISE,
        output_dir: Path | None = None,
        on_phase: PhaseHandler | None = None,
        on_phase_key: PhaseKeyHandler | None = None,
        intervention: InterventionHandler | None = None,
    ) -> Path:
        """既存 ``OrchestraPlan`` から Phase 3 (議論) 以降だけを実行する。

        Web UI で Phase 2 (計画) を先に走らせた結果を再利用するための入口。
        Phase 1 再実行による待ち時間 (10-30s) を排除する。
        """
        del user_input  # 現状は未使用だが将来のフォローアップ用に受け取っておく
        time_keeper = TimeKeeper(time_limit_sec=time_limit, phase1_actual_sec=0.0)
        return await self._execute_discussion_and_synthesis(
            plan=plan,
            time_keeper=time_keeper,
            conductor_model=conductor_model,
            synth_model=synth_model,
            expertise=expertise,
            follow_up_context=None,
            output_dir=output_dir,
            on_phase=on_phase,
            on_phase_key=on_phase_key,
            intervention=intervention,
        )

    # ------------------------------------------------------------------
    # Phase 3 (議論) + Phase 4 (統合・評価) 共通処理
    # ------------------------------------------------------------------

    async def _execute_discussion_and_synthesis(
        self,
        *,
        plan: OrchestraPlan,
        time_keeper: TimeKeeper,
        conductor_model: str,
        synth_model: str,
        expertise: str,
        follow_up_context: FollowUpContext | None,
        output_dir: Path | None,
        on_phase: PhaseHandler | None,
        on_phase_key: PhaseKeyHandler | None,
        intervention: InterventionHandler | None,
    ) -> Path:
        """Phase 3 (議論) と Phase 4 (統合・評価・出力・feedback 更新) を実行する。

        ``run`` と ``run_from_plan`` の共通処理を集約する。呼び出し側は
        Phase 1 (validate) と Phase 2 (plan 生成 or 受領) だけを担当し、
        ここに Phase 3 以降を委譲する。

        Args:
            plan: 実行対象の ``OrchestraPlan``。
            time_keeper: 議論の残時間管理。``run`` では Phase 1 実測を差し引いた
                残時間、``run_from_plan`` では時間制限全体が渡される。
            conductor_model: 議論進行モデル。
            synth_model: 統合・評価モデル。
            expertise: 発言 tone 制御用の expertise レベル。
            follow_up_context: フォローアップ入力 (任意)。
            output_dir: 出力ディレクトリ (未指定なら ``DEFAULT_OUTPUT_DIR``)。
            on_phase / on_phase_key: フェーズ変化コールバック (任意)。
            intervention: SSE 介入ハンドラ (未指定なら ``NoIntervention``)。

        Returns:
            出力ファイルのパス。
        """
        # Phase 3: 議論 — Conductor.run_discussion
        self.notify_phase(PhaseKey.DISCUSSION, on_phase=on_phase, on_phase_key=on_phase_key)
        memory = ConversationMemory(api_client=self.api_client)
        agents = self._initialize_agents(plan, expertise=expertise)
        conductor = Conductor(
            api_client=self.api_client,
            agents=agents,
            memory=memory,
            time_keeper=time_keeper,
            settings=self.settings,
            intervention=intervention or NoIntervention(),
            model=conductor_model,
        )
        discussion_log = await conductor.run_discussion(plan)

        # Phase 4: 結果 — 統合・評価・出力ファイル生成・feedback 更新
        self.notify_phase(PhaseKey.RESULT, on_phase=on_phase, on_phase_key=on_phase_key)
        synthesizer = Synthesizer(
            api_client=self.api_client,
            feedback_manager=self.feedback_manager,
            settings=self.settings,
        )
        session_id = OutputGenerator.generate_session_id(SESSION_TYPE_IDEA)
        synthesis = await synthesizer.synthesize(
            plan=plan,
            discussion_log=discussion_log,
            memory=memory,
            agents=agents,
            model=synth_model,
            expertise=expertise,
            follow_up_context=(
                self._follow_up_to_dict(follow_up_context)
                if follow_up_context
                else None
            ),
            session_id=session_id,
        )
        output_path = self._write_output(
            session_id=session_id,
            plan=plan,
            discussion_log=discussion_log,
            synthesis=synthesis,
            memory=memory,
            output_dir=output_dir or DEFAULT_OUTPUT_DIR,
        )
        self._update_feedback(plan, synthesis, session_id)
        return output_path

    # ------------------------------------------------------------------
    # 入力バリデーション
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_input(user_input: str) -> str:
        """入力をトリムし、長さを検証する。

        Args:
            user_input: ユーザー入力テキスト。

        Returns:
            前後空白を除いた文字列。

        Raises:
            InputTooShortError: 5 文字未満。
            InputTooLongError: 5000 文字超。
        """
        if user_input is None:
            raise InputTooShortError("user_input must not be None")
        cleaned = user_input.strip()
        if len(cleaned) < MIN_INPUT_CHARS:
            raise InputTooShortError(
                f"入力が短すぎます ({len(cleaned)}文字)。"
                f"{MIN_INPUT_CHARS}文字以上で入力してください。"
            )
        if len(cleaned) > MAX_INPUT_CHARS:
            raise InputTooLongError(
                f"入力が長すぎます ({len(cleaned)}文字)。"
                f"{MAX_INPUT_CHARS}文字以内に収めてください。"
            )
        return cleaned

    # ------------------------------------------------------------------
    # follow-up
    # ------------------------------------------------------------------

    def _load_follow_up(
        self,
        session_id: str | None,
        attached_files: list[Path] | None,
        focus_hypotheses: list[str] | None,
    ) -> FollowUpContext | None:
        """フォローアップコンテキストを読み込む (Phase F-1 でフル実装)。

        本ステップでは:
            - ``session_id`` が ``None`` なら ``None`` を返す
            - 指定があれば最小限の ``FollowUpContext`` (添付・フォーカス
              のみ) を返す。過去セッション読み込み (``FollowUpManager``) は
              F-1 で実装する
        """
        if session_id is None:
            if attached_files or focus_hypotheses:
                logger.warning(
                    "attached_files / focus_hypotheses は follow_up_id 指定時のみ有効です。無視します。"
                )
            return None

        logger.info(
            "Loading follow-up context for session %s (FollowUpManager は Phase F-1 で実装)",
            session_id,
        )

        context = FollowUpContext(
            parent_session_id=session_id,
            chain=[session_id],
            chain_depth=1,
            focus_hypotheses=list(focus_hypotheses or []),
        )

        for path in attached_files or []:
            if not path.exists():
                raise FileNotFoundError(f"添付ファイルが見つかりません: {path}")
            content = path.read_text(encoding="utf-8")
            context.attached_files.append(
                {"name": path.name, "content": content[:MAX_ATTACHED_FILE_CHARS]}
            )

        return context

    @staticmethod
    def _follow_up_to_dict(
        context: FollowUpContext,
    ) -> dict[str, Any]:
        """``FollowUpContext`` を ``Orchestrator`` / ``Synthesizer`` 向け辞書に変換する。"""
        return {
            "previous_session_id": context.parent_session_id,
            "previous_conclusion": context.previous_conclusion,
            "previous_hypotheses": context.previous_hypotheses,
            "unresolved_issues": context.unresolved_issues,
            "new_input": context.new_input,
            "focus_hypotheses": context.focus_hypotheses,
            "attached_files": context.attached_files,
        }

    # ------------------------------------------------------------------
    # シナリオ検出
    # ------------------------------------------------------------------

    def _detect_scenario(self, user_input: str) -> dict[str, Any] | None:
        """テーマからシナリオを自動推定し、YAML を読み込む。

        マッチするシナリオファイルが ``config/scenarios/`` 配下に存在しない
        場合 (Phase F-3 未実装時) は ``None`` を返す。

        Args:
            user_input: バリデーション済みユーザー入力。

        Returns:
            シナリオ辞書 (YAML 由来) または ``None``。
        """
        scenarios_dir = self._scenarios_dir()
        input_lower = user_input.lower()

        best_match: str | None = None
        best_score = 0
        for scenario_name, keywords in SCENARIO_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in input_lower)
            if score > best_score:
                best_score = score
                best_match = scenario_name

        if not best_match or best_score < 1:
            return None

        scenario_path = scenarios_dir / f"{best_match}.yaml"
        if not scenario_path.exists():
            logger.info(
                "Scenario file %s not found (Phase F-3 でファイル追加予定); 続行",
                scenario_path,
            )
            return None

        try:
            return yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            logger.warning("Failed to parse scenario %s: %s", scenario_path, e)
            return None

    def _scenarios_dir(self) -> Path:
        """``config/scenarios/`` のパスを返す (settings に明示キーが無いため推定)。"""
        # settings に config_dir があれば優先、なければ既定パス
        config_dir = getattr(self.settings, "config_dir", None)
        if config_dir is None:
            config_dir = Path(__file__).resolve().parents[1] / "config"
        return Path(config_dir) / DEFAULT_SCENARIOS_SUBDIR

    # ------------------------------------------------------------------
    # 確認 / エージェント初期化 / 出力
    # ------------------------------------------------------------------

    def _confirm_execution(self, plan: OrchestraPlan) -> bool:
        """``confirm_callback`` を呼んで実行可否を取得する。

        Args:
            plan: Phase 1 で確定した計画。

        Returns:
            ``True`` なら続行、``False`` なら停止。
        """
        try:
            return bool(self.confirm_callback(plan))
        except Exception as e:  # noqa: BLE001 - コールバック失敗は安全側に倒す
            logger.warning("confirm_callback raised %s; aborting", e)
            return False

    def _initialize_agents(
        self, plan: OrchestraPlan, expertise: str = DEFAULT_EXPERTISE
    ) -> dict[str, Agent]:
        """``plan.selected_agents`` から ``Agent`` インスタンスを構築する。

        ロールが見つからない場合は警告ログを残してスキップ。
        各 Agent の ``speaking_rules`` に expertise 別 tone prefix を注入する。
        """
        agents: dict[str, Agent] = {}
        # plan ベースの一時メモリを使う (各 Agent が共有する想定だが、speak 時に
        # Conductor から context が注入されるため Agent 自体は memory を直接
        # 触らない)。空 memory を渡す。
        shared_memory = ConversationMemory(api_client=self.api_client)

        for cfg in plan.selected_agents:
            try:
                role_definition = self.role_manager.load_role(cfg.role_id)
            except Exception as e:  # noqa: BLE001 - 1 体失敗で全体止めない
                logger.warning(
                    "Skipping agent %r (role load failed): %s", cfg.role_id, e
                )
                continue

            agent_config = AgentConfig(
                role_id=cfg.role_id,
                model=cfg.model,
                level=cfg.level,
                reason=cfg.reason,
                expected_contribution=cfg.expected_contribution,
            )
            agent = Agent(
                config=agent_config,
                role_definition=role_definition,
                api_client=self.api_client,
                memory=shared_memory,
                settings=self.settings,
            )

            # expertise 別の tone prefix を speaking_rules として注入。
            # 議論の口調をレベルに合わせる (agent.py の
            # AGENT_RALLY_RULES / AGENT_CREATIVE_STANCE と上乗せ)。
            apply_speaking_rules(agent, expertise=expertise)

            # 個別指示・フィードバックの注入
            instruction = plan.private_instructions.get(cfg.role_id)
            if instruction is not None:
                agent.set_private_instruction(self._format_instruction(instruction))

            if self.feedback_manager is not None:
                feedback_text = self.feedback_manager.generate_feedback_context(
                    cfg.role_id
                )
                if feedback_text:
                    agent.set_feedback_context(feedback_text)

            agents[cfg.role_id] = agent
        return agents

    @staticmethod
    def _format_instruction(instruction: Any) -> str:
        """``PrivateInstruction`` を 1 つのテキストに整形する。"""
        parts: list[str] = []
        expected = getattr(instruction, "expected_contribution", "")
        if expected:
            parts.append(f"期待される貢献: {expected}")
        focus_points = getattr(instruction, "focus_points", []) or []
        if focus_points:
            parts.append("注目点:\n" + "\n".join(f"- {p}" for p in focus_points))
        constraints = getattr(instruction, "constraints", []) or []
        if constraints:
            parts.append("制約:\n" + "\n".join(f"- {c}" for c in constraints))
        context_from_plan = getattr(instruction, "context_from_plan", "")
        if context_from_plan:
            parts.append(f"位置づけ: {context_from_plan}")
        feedback_reminder = getattr(instruction, "feedback_reminder", "")
        if feedback_reminder:
            parts.append(f"フィードバック注意: {feedback_reminder}")
        return "\n\n".join(parts)

    def _write_output(
        self,
        session_id: str,
        plan: OrchestraPlan,
        discussion_log: Any,
        synthesis: Any,
        memory: ConversationMemory,
        output_dir: Path,
    ) -> Path:
        """``OutputGenerator`` で出力ファイル一式を書き出す。"""
        generator = OutputGenerator(output_dir=output_dir)
        return generator.generate(
            session_id=session_id,
            plan=plan,
            discussion_log=discussion_log,
            synthesis=synthesis,
            memory=memory,
        )

    def _update_feedback(
        self,
        plan: OrchestraPlan,
        synthesis: Any,
        session_id: str,
    ) -> None:
        """各エージェントのロール YAML に評価結果を蓄積する。"""
        if self.feedback_manager is None:
            return

        date_str = session_id.split("_")[0]
        try:
            formatted_date = (
                f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                if len(date_str) == 8
                else date_str
            )
        except Exception:  # noqa: BLE001
            formatted_date = date_str

        topic = plan.odsc.objective[:80]
        per_agent_feedback = synthesis.orchestrator_evaluation.per_agent_feedback
        mvp_role_id = getattr(
            synthesis.orchestrator_evaluation, "mvp_role_id", ""
        ) or ""

        for role_id, ev in synthesis.agent_evaluations.items():
            peer_avg = self._peer_avg_received(role_id, synthesis.agent_evaluations)
            fb_obj = per_agent_feedback.get(role_id)
            fb_dict = {
                "strengths_noted": list(getattr(fb_obj, "strengths_noted", []) or []),
                "improvements_noted": list(
                    getattr(fb_obj, "improvements_noted", []) or []
                ),
                "orchestrator_feedback": str(
                    getattr(fb_obj, "orchestrator_feedback", "")
                ),
            }
            try:
                self.feedback_manager.update_role_feedback(
                    role_id=role_id,
                    session_id=session_id,
                    date=formatted_date,
                    topic=topic,
                    self_eval={"avg_score": ev.self_eval.avg_score},
                    peer_avg=peer_avg,
                    orchestrator_feedback=fb_dict,
                    is_mvp=(role_id == mvp_role_id),
                )
            except Exception as e:  # noqa: BLE001 - 1 ロール失敗で全体止めない
                logger.warning(
                    "Failed to update feedback for %r: %s", role_id, e
                )

    @staticmethod
    def _peer_avg_received(
        role_id: str,
        evaluations: dict[str, Any],
    ) -> float:
        """ある ``role_id`` が他者から受けた peer スコアの平均を返す。"""
        scores: list[int] = []
        for evaluator_id, ev in evaluations.items():
            if evaluator_id == role_id:
                continue
            pe = ev.peer_evals.get(role_id)
            if pe is not None:
                scores.append(int(pe.score))
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 2)


__all__ = [
    "IdeaDiscussion",
    "ConfirmCallback",
    "MIN_INPUT_CHARS",
    "MAX_INPUT_CHARS",
    "SCENARIO_KEYWORDS",
]
