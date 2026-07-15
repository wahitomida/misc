"""Phase 3-5 の関数ラッパー: ``CodeReview`` クラスから委譲される薄い関数群。

各関数は失敗時に上位フローを止めない (空結果を返す) ことで、
``CodeReview.run`` の堅牢性を保つ。

設計書: ``doc/12_code_review.md`` §12.4, §12.5, §12.6
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.data_models import (
    AgentEvaluations,
    DiscussionLog,
    OrchestratorEvaluation,
    ScanResult,
)
from core.discussion_common import DEFAULT_EXPERTISE
from features.code_review.cross_question import CrossQuestioner
from features.code_review.meeting import MeetingResult, run_meeting
from features.code_review.report_builder import (
    build_review_plan,
    build_synthesis_result,
    make_review_session_id,
    write_outputs,
)

if TYPE_CHECKING:
    from core.agent import Agent
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings
    from core.feedback import FeedbackManager
    from core.role_manager import RoleManager

logger = logging.getLogger(__name__)


async def run_phase3_cross_question(
    cross_questioner: CrossQuestioner,
    findings: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Phase 3 を実行する。

    ``CrossQuestioner.run`` 内部で LLM 呼び出し失敗は握りつぶされるが、
    その他予期せぬ例外は元の ``findings`` をそのまま返す。
    """
    if not findings:
        return findings
    try:
        return await cross_questioner.run(findings, leaders=[])
    except Exception as e:  # noqa: BLE001 - Phase 3 失敗で全体止めない
        logger.warning("Phase 3 cross-question failed: %s", e)
        return findings


async def run_phase4_meeting(
    api_client: "ResilientAPIClient",
    role_manager: "RoleManager",
    settings: "Settings",
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    conductor_model: str,
    expertise: str = DEFAULT_EXPERTISE,
    time_limit_sec: float | None = None,
) -> MeetingResult:
    """Phase 4 全体会議を実行する (``meeting.run_meeting`` に委譲)。

    findings が空、またはロール読み込みに失敗した場合は空の
    ``MeetingResult`` を返す。``time_limit_sec`` は ``None`` なら
    ``meeting.MEETING_TIME_LIMIT_SEC`` のデフォルトを使う。
    """
    if not any(findings.values()):
        return MeetingResult()
    kwargs: dict[str, Any] = {
        "api_client": api_client,
        "role_manager": role_manager,
        "settings": settings,
        "scan_result": scan_result,
        "findings": findings,
        "focus": focus,
        "conductor_model": conductor_model,
        "expertise": expertise,
    }
    if time_limit_sec is not None:
        kwargs["time_limit_sec"] = time_limit_sec
    try:
        return await run_meeting(**kwargs)
    except Exception as e:  # noqa: BLE001 - Phase 4 失敗で全体止めない
        logger.warning("Phase 4 meeting failed: %s", e)
        return MeetingResult()


async def run_phase5_report(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    discussion_log: DiscussionLog,
    focus: str,
    output_dir: Path,
    api_client: "ResilientAPIClient | None" = None,
    settings: "Settings | None" = None,
    agents: dict[str, "Agent"] | None = None,
    meeting_plan: Any | None = None,
    feedback_manager: "FeedbackManager | None" = None,
) -> Path:
    """Phase 5 レポート一式を ``output_dir`` 配下に書き出す。

    評価が可能な場合 (agents + api_client + settings あり) は
    自己/他者/指揮者評価を実施してからレポートに反映する。
    ``feedback_manager`` を渡すと評価結果をロール YAML の
    ``feedback_history`` にも追記する (idea と一致した集計を可能にする)。

    Returns:
        作成されたセッションディレクトリの ``Path``。
    """
    session_id, evaluations, orchestrator_eval = await _prepare_review_session(
        api_client=api_client,
        settings=settings,
        agents=agents,
        discussion_log=discussion_log,
        meeting_plan=meeting_plan,
        feedback_manager=feedback_manager,
    )
    return await _build_and_write_outputs(
        scan_result=scan_result,
        findings=findings,
        discussion_log=discussion_log,
        focus=focus,
        output_dir=output_dir,
        session_id=session_id,
        evaluations=evaluations,
        orchestrator_eval=orchestrator_eval,
        meeting_plan=meeting_plan,
    )


async def _prepare_review_session(
    *,
    api_client: "ResilientAPIClient | None",
    settings: "Settings | None",
    agents: dict[str, "Agent"] | None,
    discussion_log: DiscussionLog,
    meeting_plan: Any | None,
    feedback_manager: "FeedbackManager | None",
) -> tuple[str, dict[str, AgentEvaluations], OrchestratorEvaluation]:
    """評価実行 + セッション ID 生成 + feedback 永続化を行う。

    Returns:
        ``(session_id, evaluations, orchestrator_eval)``。評価不能な場合は
        ``evaluations`` は空辞書、``orchestrator_eval`` はデフォルトを返す。
        いずれの失敗も上位フローは止めない。
    """
    evaluations: dict[str, AgentEvaluations] = {}
    orchestrator_eval = OrchestratorEvaluation()

    if agents and api_client and settings and meeting_plan:
        evaluations, orchestrator_eval = await _run_review_evaluations(
            api_client=api_client,
            settings=settings,
            agents=agents,
            discussion_log=discussion_log,
            plan=meeting_plan,
        )

    session_id = make_review_session_id()

    if feedback_manager is not None and evaluations:
        _persist_review_feedback(
            feedback_manager=feedback_manager,
            session_id=session_id,
            plan=meeting_plan,
            evaluations=evaluations,
            orchestrator_eval=orchestrator_eval,
        )
    return session_id, evaluations, orchestrator_eval


async def _build_and_write_outputs(
    *,
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    discussion_log: DiscussionLog,
    focus: str,
    output_dir: Path,
    session_id: str,
    evaluations: dict[str, AgentEvaluations],
    orchestrator_eval: OrchestratorEvaluation,
    meeting_plan: Any | None,
) -> Path:
    """レビュー plan / synthesis を組み立て、レポート一式を書き出す。

    IO (書き出し) は別スレッドに逃がしてイベントループを塞がない。
    """
    plan = build_review_plan(scan_result, findings, focus)
    synthesis = build_synthesis_result(
        scan_result=scan_result,
        findings=findings,
        discussion_log=discussion_log,
        focus=focus,
        session_id=session_id,
        evaluations=evaluations,
        orchestrator_eval=orchestrator_eval,
        meeting_plan=meeting_plan,
    )
    return await asyncio.to_thread(
        write_outputs,
        output_dir,
        session_id,
        plan,
        discussion_log,
        synthesis,
    )


async def _run_review_evaluations(
    api_client: "ResilientAPIClient",
    settings: "Settings",
    agents: dict[str, "Agent"],
    discussion_log: DiscussionLog,
    plan: Any,
) -> tuple[dict[str, AgentEvaluations], OrchestratorEvaluation]:
    """コードレビュー用の評価を実行する。

    Returns:
        (agent_evaluations, orchestrator_evaluation) のタプル。
        失敗時は空のデフォルトを返す。
    """
    from core.evaluator import Evaluator
    from core.synthesizer import Synthesizer

    evaluations: dict[str, AgentEvaluations] = {}
    orchestrator_eval = OrchestratorEvaluation()

    try:
        evaluator = Evaluator(api_client=api_client, settings=settings)
        agent_list = list(agents.values())

        async def _eval_one(
            agent: "Agent",
        ) -> tuple[str, AgentEvaluations | None]:
            try:
                result = await evaluator.request_combined_evaluation(
                    agent=agent,
                    other_agents=agent_list,
                    discussion_log=discussion_log,
                    plan=plan,
                )
                return agent.role_id, result
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Review evaluation failed for %r: %s", agent.role_id, e
                )
                return agent.role_id, None

        results = await asyncio.gather(*(_eval_one(a) for a in agent_list))
        evaluations = {
            role_id: ev for role_id, ev in results if ev is not None
        }

        # 指揮者総合評価
        if evaluations:
            synthesizer = Synthesizer(
                api_client=api_client,
                feedback_manager=None,
                settings=settings,
            )
            orchestrator_eval = (
                await synthesizer._generate_orchestrator_evaluation(
                    evaluations, plan, discussion_log
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Review evaluation phase failed: %s", e)

    return evaluations, orchestrator_eval


def _persist_review_feedback(
    feedback_manager: "FeedbackManager",
    session_id: str,
    plan: Any,
    evaluations: dict[str, AgentEvaluations],
    orchestrator_eval: OrchestratorEvaluation,
) -> None:
    """レビュー評価結果を各ロール YAML の feedback_history に追記する。

    idea_discussion 側と同じ書式で保存し、ロール横断のダッシュボードで
    idea + review を合算して集計できるようにする。
    """
    date_str = session_id.split("_")[0]
    try:
        formatted_date = (
            f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            if len(date_str) == 8
            else date_str
        )
    except Exception:  # noqa: BLE001
        formatted_date = date_str

    objective = getattr(getattr(plan, "odsc", None), "objective", "") or ""
    topic = str(objective)[:80]
    per_agent_feedback = getattr(orchestrator_eval, "per_agent_feedback", {}) or {}
    mvp_role_id = getattr(orchestrator_eval, "mvp_role_id", "") or ""

    for role_id, ev in evaluations.items():
        peer_avg = _peer_avg_received(role_id, evaluations)
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
            feedback_manager.update_role_feedback(
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
                "Failed to update review feedback for %r: %s", role_id, e
            )


def _peer_avg_received(
    role_id: str,
    evaluations: dict[str, AgentEvaluations],
) -> float:
    """ある ``role_id`` が他者から受けた peer スコアの平均。"""
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
    "run_phase3_cross_question",
    "run_phase4_meeting",
    "run_phase5_report",
]
