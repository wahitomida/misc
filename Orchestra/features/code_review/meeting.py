"""Phase 4: コードレビュー全体会議。

各 concern のパートリーダーを ``Agent`` として参加させ、``Conductor.run_round``
で 1 ラウンドの全体会議を行う。会議の目的は findings の優先度付け・
修正順序の決定・副作用検討であり、対象テーマと findings の要約を
``odsc.objective`` および ``round_goal`` として注入する。

設計書: ``doc/12_code_review.md`` §12.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.agent import Agent
from core.conductor import Conductor
from core.data_models import (
    AgentConfig,
    DiscussionLog,
    DiscussionPlan,
    ODSC,
    OrchestraPlan,
    PrivateInstruction,
    RoundConfig,
    ScanResult,
)
from core.discussion_common import DEFAULT_EXPERTISE, apply_speaking_rules
from core.intervention import NoIntervention
from core.memory import ConversationMemory
from core.time_keeper import TimeKeeper

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings
    from core.role_manager import RoleManager

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# プロンプト定数と会議設定 (モジュール分離済み)
# 外部互換のため ``from features.code_review.meeting import ...`` は
# 引き続き参照可能 (下記 import で再エクスポート)。
# ----------------------------------------------------------------------
from .meeting_prompts import (  # noqa: E402
    DEFAULT_CONVERGENCE_THRESHOLD,
    MEETING_FINDINGS_PREVIEW,
    MEETING_GOAL_TEMPLATE,
    MEETING_LEVEL,
    MEETING_LEVEL_LOW,
    MEETING_OBJECTIVE_TEMPLATE,
    MEETING_PHASE_NAME,
    MEETING_TIME_BUDGET_SEC,
    MEETING_TIME_LIMIT_SEC,
    ROUND1_GOAL,
    ROUND1_PATTERN,
    ROUND1_PHASE_NAME,
    ROUND1_TIME_BUDGET_SEC,
    ROUND2_GOAL,
    ROUND2_MAX_UTTERANCES,
    ROUND2_PATTERN,
    ROUND2_PHASE_NAME,
    ROUND2_TIME_BUDGET_SEC,
    ROUND3_GOAL,
    ROUND3_PATTERN,
    ROUND3_PHASE_NAME,
    ROUND3_TIME_BUDGET_SEC,
)


@dataclass
class MeetingResult:
    """Phase 4 全体会議の結果。

    Attributes:
        discussion_log: 会議のログ。
        agents: 会議に参加したエージェント。
        plan: 会議用プラン。
    """

    discussion_log: DiscussionLog = field(default_factory=DiscussionLog)
    agents: dict[str, Agent] = field(default_factory=dict)
    plan: OrchestraPlan | None = None


# ----------------------------------------------------------------------
# Meeting
# ----------------------------------------------------------------------


async def run_meeting(
    api_client: "ResilientAPIClient",
    role_manager: "RoleManager",
    settings: "Settings",
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    conductor_model: str,
    expertise: str = DEFAULT_EXPERTISE,
    time_limit_sec: float = MEETING_TIME_LIMIT_SEC,
) -> MeetingResult:
    """Phase 4 の全体会議を 1 ラウンド実行する。

    Args:
        api_client: 共有 API クライアント。
        role_manager: ロール定義の取得元。
        settings: 全体設定。
        scan_result: Phase 1 のスキャン結果。
        findings: Phase 2-3 で集約された findings。
        focus: 解決済みの focus キー。
        conductor_model: 指揮者モデル。
        expertise: 発言の口調レベル (``beginner`` / ``intermediate`` /
            ``expert``)。Idea Discussion と共通の tone prefix を
            各 Agent に注入する。
        time_limit_sec: 会議全体の制限秒数。デフォルトは
            ``MEETING_TIME_LIMIT_SEC`` (240 秒)。

    Returns:
        ``MeetingResult`` (discussion_log + agents + plan)。
        ロール構築失敗時は空のデフォルトを返す。

    実装フロー:
        1. ``ReviewPlanner`` (LLM で動的計画) を試みる — Idea と同等の
           情報密度 (Objective / goal / private_instructions が LLM 生成)。
        2. LLM 失敗時は静的な ``_build_meeting_plan`` にフォールバック。
    """
    # まず findings ベースで参加リーダーを Python 側で確定 (LLM に任せない)
    static_plan = _build_meeting_plan(scan_result, findings, focus, role_manager)
    if not static_plan.selected_agents:
        logger.info("No leaders available for meeting; skipping Phase 4")
        return MeetingResult()

    # ReviewPlanner (LLM 動的計画) を試みる
    plan = await _build_meeting_plan_via_llm(
        api_client=api_client,
        scan_result=scan_result,
        findings=findings,
        focus=focus,
        static_plan=static_plan,
    )

    memory = ConversationMemory(api_client=api_client)
    agents = _build_agents(
        api_client, role_manager, settings, plan, memory, findings,
        expertise=expertise,
    )
    if not agents:
        logger.info("Failed to build any agents for meeting; skipping Phase 4")
        return MeetingResult()

    conductor = Conductor(
        api_client=api_client,
        agents=agents,
        memory=memory,
        time_keeper=TimeKeeper(time_limit_sec=time_limit_sec),
        settings=settings,
        intervention=NoIntervention(),
        model=conductor_model,
        enable_bonus_rounds=False,  # レビュー会議は 3 ラウンド固定 (Phase 4 仕様)
    )

    discussion_log = await conductor.run_discussion(plan)
    return MeetingResult(
        discussion_log=discussion_log,
        agents=agents,
        plan=plan,
    )


async def _build_meeting_plan_via_llm(
    api_client: "ResilientAPIClient",
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    static_plan: OrchestraPlan,
) -> OrchestraPlan:
    """``ReviewPlanner`` で LLM 動的計画を試み、失敗時は ``static_plan`` を返す。

    Idea Discussion の Orchestrator と同じ設計思想 (Objective / goal /
    private_instructions を LLM で動的生成) を Review でも適用する。
    ``selected_agents`` は ``static_plan`` の値を使う (findings ベースで
    Python 側で確定済み)。

    Args:
        api_client: LLM 呼び出し用クライアント。
        scan_result: フォルダスキャン結果。
        findings: concern → findings リストの辞書。
        focus: レビュー focus 設定。
        static_plan: findings ベースで確定済みの Python 版計画
            (LLM 失敗時のフォールバック)。

    Returns:
        LLM 成功時は LLM 生成の ``OrchestraPlan`` (selected_agents は
        ``static_plan`` の値を継承)、失敗時は ``static_plan``。
    """
    # 遅延 import で循環依存回避 (review_planner が meeting_prompts を参照)
    from features.code_review.review_planner import ReviewPlanner

    planner = ReviewPlanner(api_client=api_client)
    try:
        plan = await planner.plan(
            scan_result=scan_result,
            findings=findings,
            focus=focus,
            selected_agents=static_plan.selected_agents,
        )
        logger.info(
            "Review meeting plan generated via LLM Planner (rounds=%d, agents=%d)",
            plan.discussion_plan.estimated_rounds if plan.discussion_plan else 0,
            len(plan.selected_agents),
        )
        return plan
    except Exception as e:  # noqa: BLE001 - LLM 失敗時は静的計画にフォールバック
        logger.warning(
            "ReviewPlanner failed; falling back to static _build_meeting_plan: %s", e
        )
        return static_plan


# ----------------------------------------------------------------------
# Plan / Agent 構築
# ----------------------------------------------------------------------


def _build_meeting_plan(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    role_manager: "RoleManager | None" = None,
) -> OrchestraPlan:
    """会議用の最小 ``OrchestraPlan`` を組み立てる。

    ``CONCERN_TO_ROLE`` の 5 ロールを findings ベースでパートリーダーとして選び、
    ``role_manager`` を渡された場合は ``DEFAULT_ROLES`` 以外のカスタムロールを
    「一般参加者」としてすべて連なる。これにより Idea と同様に Review でも
    ユーザーが作成したカスタムロールが会議に参加できる。
    """
    from core.role_manager import DEFAULT_ROLES
    from features.code_review.constants import CONCERN_TO_MODEL, CONCERN_TO_ROLE

    total_findings = sum(len(items) for items in findings.values())
    objective = MEETING_OBJECTIVE_TEMPLATE.format(
        target_path=_safe_path(scan_result.target_path),
        focus=focus,
        total_findings=total_findings,
    )

    selected: list[AgentConfig] = []
    role_to_concerns_map: dict[str, list[tuple[str, int]]] = {}
    for concern, items in findings.items():
        if not items:
            continue
        role_id = CONCERN_TO_ROLE.get(concern)
        model = CONCERN_TO_MODEL.get(concern)
        if not role_id or not model:
            continue
        role_to_concerns_map.setdefault(role_id, []).append(
            (concern, len(items))
        )
        if any(a.role_id == role_id for a in selected):
            continue  # results と reproducibility が experimentalist で被るので重複排除
        selected.append(
            AgentConfig(
                role_id=role_id,
                model=model,
                level=MEETING_LEVEL,
                reason=f"{concern} 観点のパートリーダー",
                expected_contribution=(
                    f"{concern} 関連の findings ({len(items)} 件) を共有し"
                    "優先度判定に参加"
                ),
            )
        )

    # 重複排除後に expected_contribution を全 concern 反映で書き直す
    for cfg in selected:
        concerns = role_to_concerns_map.get(cfg.role_id, [])
        concern_summary = ", ".join(
            f"{c}({n}件)" for c, n in concerns
        )
        cfg.expected_contribution = (
            f"{concern_summary} の所見を共有し、3ラウンドで優先度・"
            "修正順序・副作用を合意する"
        )
    # デフォルトでないカスタムロールを一般参加者として合流させる。
    # Idea と同じくユーザー定義のロールも Review 全体会議に参加させることで
    # 「全ての AI が選べる」仕様を保つ。
    if role_manager is not None:
        try:
            all_summaries = role_manager.list_available_roles()
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to enumerate roles for meeting: %s", e)
            all_summaries = []
        existing_ids = {a.role_id for a in selected}
        for role in all_summaries:
            rid = role.get("role_id") or ""
            if not rid or rid in DEFAULT_ROLES or rid in existing_ids:
                continue
            description = (role.get("description") or "").strip()
            contribution = description or "カスタム視点で会議に参加する"
            selected.append(
                AgentConfig(
                    role_id=rid,
                    model=role.get("model") or "gpt-4.1",
                    level=MEETING_LEVEL,
                    reason="カスタムロールの一般参加者",
                    expected_contribution=contribution,
                )
            )
    speakers = [a.role_id for a in selected]
    round_configs = [
        RoundConfig(
            round=1,
            phase_name=ROUND1_PHASE_NAME,
            speakers=speakers,
            pattern=ROUND1_PATTERN,
            level=MEETING_LEVEL,
            time_budget_sec=ROUND1_TIME_BUDGET_SEC,
            goal=ROUND1_GOAL,
        ),
        RoundConfig(
            round=2,
            phase_name=ROUND2_PHASE_NAME,
            speakers=speakers,
            pattern=ROUND2_PATTERN,
            level=MEETING_LEVEL,
            time_budget_sec=ROUND2_TIME_BUDGET_SEC,
            goal=ROUND2_GOAL,
        ),
        RoundConfig(
            round=3,
            phase_name=ROUND3_PHASE_NAME,
            speakers=speakers,
            pattern=ROUND3_PATTERN,
            level=MEETING_LEVEL,
            time_budget_sec=ROUND3_TIME_BUDGET_SEC,
            goal=ROUND3_GOAL,
        ),
    ]
    total_time = sum(rc.time_budget_sec for rc in round_configs)
    discussion_plan = DiscussionPlan(
        estimated_rounds=len(round_configs),
        round_config=round_configs,
        total_estimated_time_sec=total_time,
        total_estimated_requests=len(speakers) * len(round_configs) + len(round_configs),
    )
    odsc = ODSC(
        objective=objective,
        deliverable="優先度確定・修正順序・副作用所見",
        success_criteria="全 concern が発言し、Phase A/B/C 分類が共有された",
        convergence_threshold=DEFAULT_CONVERGENCE_THRESHOLD,
    )

    # private_instructions: 各 AI への個別指示 (S1: PrivateInstruction 充実化)
    # Idea の Orchestrator と同じ 6 フィールド (expected_contribution / focus_points /
    # constraints / context_from_plan / feedback_reminder / speaking_rules) を埋めて、
    # Kickoff briefing で表示される情報密度を Idea と同等にする。
    private_instructions: dict[str, PrivateInstruction] = {}
    for cfg in selected:
        concerns = role_to_concerns_map.get(cfg.role_id, [])
        concern_labels = ", ".join(c for c, _ in concerns) if concerns else "全体"
        private_instructions[cfg.role_id] = PrivateInstruction(
            role_id=cfg.role_id,
            expected_contribution=cfg.expected_contribution,
            focus_points=[
                f"{concern_labels} 観点の findings を優先度・修正順序で共有する",
                "他リーダーの所見に対して具体的な反例・補足を 1 つ添える",
                "抽象的な指摘ではなく、ファイル名・行番号を必ず含める",
            ],
            constraints=[
                "抽象論だけの発言は禁止 (必ずファイル参照または具体的な数字を含める)",
                "他者と同じ具体例・言い回しを繰り返さない",
            ],
            context_from_plan=(
                f"Phase 4 全体会議 (3 ラウンド固定)。担当 concerns: {concern_labels}. "
                f"合計 findings {total_findings} 件を Phase A/B/C に分類する。"
            ),
        )

    return OrchestraPlan(
        odsc=odsc,
        selected_agents=selected,
        discussion_plan=discussion_plan,
        private_instructions=private_instructions,
    )


def _build_agents(
    api_client: "ResilientAPIClient",
    role_manager: "RoleManager",
    settings: "Settings",
    plan: OrchestraPlan,
    memory: ConversationMemory,
    findings: dict[str, list[dict[str, Any]]],
    expertise: str = DEFAULT_EXPERTISE,
) -> dict[str, Agent]:
    """会議参加 ``Agent`` を構築する。

    各エージェントの ``private_instruction`` に該当 concern の findings 要約を
    注入し、自分の調査結果を発言できるようにする。
    ``speaking_rules`` には Idea Discussion と完全に同じ tone prefix のみを
    注入し、Review 固有の発言ルールは使用しない (Idea と同じ土台)。
    """
    from features.code_review.constants import CONCERN_TO_ROLE

    role_to_concerns: dict[str, list[str]] = {}
    for concern, role_id in CONCERN_TO_ROLE.items():
        role_to_concerns.setdefault(role_id, []).append(concern)

    agents: dict[str, Agent] = {}
    for cfg in plan.selected_agents:
        try:
            role_definition = role_manager.load_role(cfg.role_id)
        except Exception as e:  # noqa: BLE001 - 1 体失敗で全体止めない
            logger.warning("Skip role %r (load failed): %s", cfg.role_id, e)
            continue

        agent = Agent(
            config=cfg,
            role_definition=role_definition,
            api_client=api_client,
            memory=memory,
            settings=settings,
        )
        agent.set_private_instruction(
            _format_finding_briefing(role_to_concerns.get(cfg.role_id, []), findings)
        )
        # Idea Discussion と完全に同じ共通仕組みを使う (Review 固有の
        # 発言ルールは廃止)。expertise 別 tone prefix のみ注入することで、
        # role_base_template.txt / DIVERSITY_RULE / 各ロール YAML の【発言の型】
        # という Idea と同じ土台で発言する。
        apply_speaking_rules(agent, expertise=expertise)
        agents[cfg.role_id] = agent
    return agents


def _format_finding_briefing(
    concerns: list[str],
    findings: dict[str, list[dict[str, Any]]],
) -> str:
    """会議用ブリーフィングを 1 つのテキストに整形する。

    発言ルールは Idea と共通の土台 (role_base_template.txt / DIVERSITY_RULE /
    各ロール YAML の【発言の型】) でカバーされるのでここには含めない。
    """
    if not concerns:
        return ""
    parts: list[str] = ["【全体会議ブリーフィング】"]
    for concern in concerns:
        items = findings.get(concern, [])
        parts.append(f"\n[{concern}] {len(items)} 件の所見")
        for item in items[:MEETING_FINDINGS_PREVIEW]:
            severity = item.get("severity", "?")
            file_ref = item.get("file", "?")
            line_ref = item.get("line", "?")
            title = item.get("title", "(無題)")
            parts.append(f"  - [{severity}] {file_ref} {line_ref}: {title}")
        if len(items) > MEETING_FINDINGS_PREVIEW:
            parts.append(f"  ... 他 {len(items) - MEETING_FINDINGS_PREVIEW} 件")
    parts.append(
        "\n会議では他リーダーの所見と関連付けて優先度・修正順序を主張すること。"
    )
    return "\n".join(parts)


def _safe_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


__all__ = [
    "run_meeting",
    "MeetingResult",
    "MEETING_OBJECTIVE_TEMPLATE",
    "MEETING_GOAL_TEMPLATE",
    "MEETING_TIME_BUDGET_SEC",
    "MEETING_TIME_LIMIT_SEC",
    "DEFAULT_CONVERGENCE_THRESHOLD",
]
