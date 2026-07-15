"""Phase 5: ``SynthesisResult`` 組み立てと ``OutputGenerator`` 連携。

各サブビルダー (``report_writer`` / ``vibe_prompt``) を統合して
``OutputGenerator.generate`` 互換の最小 ``OrchestraPlan`` と
``SynthesisResult`` を作る。

設計書: ``doc/12_code_review.md`` §12.6, ``doc/14_output_format.md``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.data_models import (
    AgentConfig,
    AgentEvaluations,
    DiscussionLog,
    DiscussionPlan,
    ODSC,
    OrchestraPlan,
    OrchestratorEvaluation,
    ScanResult,
    SynthesisResult,
)
from core.output_generator import OutputGenerator, SESSION_TYPE_REVIEW
from features.code_review.report_common import count_by_severity
from features.code_review.report_writer import (
    build_evaluation_md,
    build_full_conversation_md,
    build_report_md,
    build_summary_txt,
)
from features.code_review.vibe_prompt import build_vibe_prompt_md

logger = logging.getLogger(__name__)


DEFAULT_REVIEW_CONVERGENCE_THRESHOLD = 0.7
DEFAULT_REVIEW_LEVEL = "medium"


def build_synthesis_result(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    discussion_log: DiscussionLog,
    focus: str,
    session_id: str,
    evaluations: dict[str, AgentEvaluations] | None = None,
    orchestrator_eval: OrchestratorEvaluation | None = None,
    meeting_plan: OrchestraPlan | None = None,
) -> SynthesisResult:
    """``findings`` から ``SynthesisResult`` を組み立てる (LLM 非経由)。"""
    evaluations = evaluations or {}
    orchestrator_eval = orchestrator_eval or OrchestratorEvaluation()

    return SynthesisResult(
        report_md=build_report_md(
            scan_result, findings, focus, discussion_log
        ),
        full_conversation_md=build_full_conversation_md(
            discussion_log,
            scan_result=scan_result,
            findings=findings,
            evaluations=evaluations,
            plan=meeting_plan,
        ),
        evaluation_md=build_evaluation_md(
            findings, evaluations=evaluations, orchestrator_eval=orchestrator_eval
        ),
        summary_txt=build_summary_txt(
            scan_result, findings, focus, discussion_log
        ),
        vibe_coding_prompt_md=build_vibe_prompt_md(
            scan_result, findings, focus
        ),
        agent_evaluations=evaluations,
        orchestrator_evaluation=orchestrator_eval,
        session_meta=_build_session_meta(
            session_id=session_id,
            scan_result=scan_result,
            findings=findings,
            focus=focus,
            discussion_log=discussion_log,
            evaluations=evaluations,
            orchestrator_eval=orchestrator_eval,
        ),
    )


def build_review_plan(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
) -> OrchestraPlan:
    """``OutputGenerator`` 互換の最小 ``OrchestraPlan`` を作る。

    ``session_meta.json`` 生成時に ``plan.odsc.objective`` と
    ``plan.selected_agents`` が参照される。
    """
    from features.code_review.constants import CONCERN_TO_MODEL, CONCERN_TO_ROLE

    selected: list[AgentConfig] = []
    seen: set[str] = set()
    for concern in findings.keys():
        role_id = CONCERN_TO_ROLE.get(concern, concern)
        if role_id in seen:
            continue
        seen.add(role_id)
        selected.append(
            AgentConfig(
                role_id=role_id,
                model=CONCERN_TO_MODEL.get(concern, ""),
                level=DEFAULT_REVIEW_LEVEL,
                reason=f"{concern} 観点",
                expected_contribution=concern,
            )
        )

    total_findings = sum(len(v) for v in findings.values())
    odsc = ODSC(
        objective=(
            f"コードレビュー: {scan_result.target_path} (focus={focus}, "
            f"findings={total_findings})"
        ),
        deliverable="report.md / vibe_coding_prompt.md",
        success_criteria="優先度別の課題一覧と修正順序が提示されること",
        convergence_threshold=DEFAULT_REVIEW_CONVERGENCE_THRESHOLD,
    )
    return OrchestraPlan(
        odsc=odsc,
        selected_agents=selected,
        discussion_plan=DiscussionPlan(estimated_rounds=1, round_config=[]),
    )


def write_outputs(
    output_dir: Path,
    session_id: str,
    plan: OrchestraPlan,
    discussion_log: DiscussionLog,
    synthesis: SynthesisResult,
) -> Path:
    """``OutputGenerator`` でセッションディレクトリを生成する。"""
    generator = OutputGenerator(output_dir=Path(output_dir))
    return generator.generate(
        session_id=session_id,
        plan=plan,
        discussion_log=discussion_log,
        synthesis=synthesis,
        memory=None,
    )


def make_review_session_id() -> str:
    """``YYYYMMDD_HHMMSS_review`` 形式のセッション ID を返す。"""
    return OutputGenerator.generate_session_id(SESSION_TYPE_REVIEW)


def _build_session_meta(
    session_id: str,
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    discussion_log: DiscussionLog,
    evaluations: dict[str, AgentEvaluations] | None = None,
    orchestrator_eval: OrchestratorEvaluation | None = None,
) -> dict[str, Any]:
    from datetime import datetime

    evaluations = evaluations or {}
    orchestrator_eval = orchestrator_eval or OrchestratorEvaluation()

    now = datetime.now()
    total_duration = sum(r.duration_sec for r in discussion_log.rounds)
    created_at = datetime.fromtimestamp(
        now.timestamp() - total_duration
    ).isoformat()

    counts = count_by_severity(findings)
    has_evaluation = bool(evaluations)

    meta: dict[str, Any] = {
        "session_type": "code_review",
        "scan": {
            "target_path": str(scan_result.target_path),
            "total_files": scan_result.total_files,
            "total_lines": scan_result.total_lines,
        },
        "focus": focus,
        "findings_summary": {
            "total": sum(counts.values()),
            "by_severity": dict(counts),
            "by_concern": {c: len(items) for c, items in findings.items()},
        },
        "meeting_rounds": len(discussion_log.rounds),
        "expertise": "intermediate",
        "started_at": created_at,
        "ended_at": now.isoformat(),
        "evaluation_skipped": not has_evaluation,
        "statistics": {
            "total_requests": discussion_log.total_requests,
        },
        "_session_id_hint": session_id,
    }

    if has_evaluation:
        avg_self = _safe_avg(
            [ev.self_eval.avg_score for ev in evaluations.values()]
        )
        meta["evaluation_summary"] = {
            "overall_quality": round(
                orchestrator_eval.overall_discussion_quality, 2
            ),
            "mvp": orchestrator_eval.mvp_role_id,
            "avg_self_score": avg_self,
        }

    return meta


def _safe_avg(values: list[float]) -> float:
    """NaN / None を除外して平均を返す。空なら 0.0。"""
    valid = [v for v in values if v and v > 0]
    return round(sum(valid) / len(valid), 2) if valid else 0.0


__all__ = [
    "build_synthesis_result",
    "build_review_plan",
    "write_outputs",
    "make_review_session_id",
]
