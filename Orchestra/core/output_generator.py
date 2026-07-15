"""セッション出力ファイル一式 (7 種類) を生成する ``OutputGenerator``。

責務:
    - セッションディレクトリの作成
    - ``session_meta.json`` / ``discussion.json`` (構造化 JSON)
    - ``full_conversation.md`` / ``report.md`` / ``evaluation.md`` /
      ``summary.txt`` (Markdown / プレーンテキスト、内容は ``Synthesizer`` が生成済み)
    - ``vibe_coding_prompt.md`` (機能②のみ、``synthesis.vibe_coding_prompt_md`` が
      ``None`` の場合は出力しない)
    - セッション ID の自動生成 (``YYYYMMDD_HHMMSS_{type}``)

設計書: ``doc/14_output_format.md`` §14.1-14.8
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .data_models import (
        AgentEvaluations,
        DiscussionLog,
        OrchestraPlan,
        SynthesisResult,
    )
    from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# Constants
SESSION_ID_TIME_FORMAT = "%Y%m%d_%H%M%S"
SCHEMA_VERSION = "1.0.0"
GENERATED_BY = "ai-orchestra v1.0"

SESSION_TYPE_IDEA = "idea"
SESSION_TYPE_REVIEW = "review"


class OutputGenerator:
    """セッション出力ファイル群をディスクへ書き出す。

    Attributes:
        output_dir: 出力ベースディレクトリ。``output_dir/{session_id}/`` 以下に
            ファイル群が作成される。
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def generate(
        self,
        session_id: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
        memory: "ConversationMemory | None" = None,
    ) -> Path:
        """セッション出力ファイル一式を書き出し、セッションディレクトリを返す。

        Args:
            session_id: セッション ID (例: ``"20260620_143052_idea"``)。
            plan: ``Orchestrator`` 出力。
            discussion_log: ``Conductor`` 出力。
            synthesis: ``Synthesizer`` 出力 (各レポート文字列 + 評価データ)。
            memory: 共有メモリ (``discussion.json`` の追加情報源)。

        Returns:
            生成したセッションディレクトリの ``Path``。
        """
        session_dir = self._prepare_session_dir(session_id)

        self._write_session_meta(session_dir, session_id, plan, discussion_log, synthesis)
        self._write_discussion_json(
            session_dir, session_id, plan, discussion_log, synthesis, memory
        )
        self._write_full_conversation(session_dir, synthesis)
        self._write_report(session_dir, synthesis)
        self._write_evaluation(session_dir, synthesis)
        self._write_summary(session_dir, synthesis)
        self._write_vibe_prompt(session_dir, synthesis)

        return session_dir

    @staticmethod
    def generate_session_id(session_type: str = SESSION_TYPE_IDEA) -> str:
        """``YYYYMMDD_HHMMSS_{type}`` 形式のセッション ID を生成する。"""
        return datetime.now().strftime(SESSION_ID_TIME_FORMAT) + f"_{session_type}"

    # 互換エイリアス (実装ガイドの API 名)
    def _generate_session_id(self, session_type: str = SESSION_TYPE_IDEA) -> str:
        return self.generate_session_id(session_type)

    # ------------------------------------------------------------------
    # session ディレクトリ準備
    # ------------------------------------------------------------------

    def _prepare_session_dir(self, session_id: str) -> Path:
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        if any(session_dir.iterdir()):
            logger.warning(
                "Session directory %s already contains files; existing files may be overwritten.",
                session_dir,
            )
        return session_dir

    # ------------------------------------------------------------------
    # session_meta.json
    # ------------------------------------------------------------------

    def _write_session_meta(
        self,
        session_dir: Path,
        session_id: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
    ) -> None:
        meta = self._build_session_meta(session_id, plan, discussion_log, synthesis)
        path = session_dir / "session_meta.json"
        path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _build_session_meta(
        session_id: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
    ) -> dict[str, Any]:
        """``session_meta.json`` の中身を構築する (§14.2)。"""
        now = datetime.now().isoformat()
        session_type = OutputGenerator._derive_session_type(session_id)
        total_duration = sum(r.duration_sec for r in discussion_log.rounds)

        agents_used = [a.role_id for a in plan.selected_agents]
        models_used = sorted({a.model for a in plan.selected_agents})

        synth_meta = synthesis.session_meta or {}

        return {
            "_schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "type": (
                "idea_discussion" if session_type == SESSION_TYPE_IDEA else "code_review"
            ),
            "status": "completed",
            "created_at": synth_meta.get("started_at", now),
            "completed_at": synth_meta.get("ended_at", now),
            "duration_sec": total_duration,
            "user_prompt": plan.odsc.objective,
            "user_prompt_preview": plan.odsc.objective[:80],
            "expertise": synth_meta.get("expertise", "intermediate"),
            "models_used": models_used,
            "agents_used": agents_used,
            "total_rounds": len(discussion_log.rounds),
            "final_convergence": round(discussion_log.final_convergence_score, 3),
            "total_requests": int(
                synth_meta.get("statistics", {}).get("total_requests", 0)
            ),
            "follow_up": {
                "is_follow_up": False,
                "parent_session_id": None,
                "chain_depth": 0,
                "chain": [session_id],
            },
            "evaluation_summary": {
                "overall_quality": round(
                    synthesis.orchestrator_evaluation.overall_discussion_quality, 2
                ),
                "mvp": synthesis.orchestrator_evaluation.mvp_role_id,
                "avg_self_score": OutputGenerator._safe_avg(
                    [
                        ev.self_eval.avg_score
                        for ev in synthesis.agent_evaluations.values()
                    ]
                ),
                "avg_peer_score": OutputGenerator._compute_avg_peer_score(
                    synthesis.agent_evaluations
                ),
            },
            "output_files": {
                "discussion_json": "discussion.json",
                "full_conversation_md": "full_conversation.md",
                "report_md": "report.md",
                "evaluation_md": "evaluation.md",
                "summary_txt": "summary.txt",
                "vibe_coding_prompt_md": (
                    "vibe_coding_prompt.md"
                    if synthesis.vibe_coding_prompt_md is not None
                    else None
                ),
            },
        }

    # ------------------------------------------------------------------
    # discussion.json
    # ------------------------------------------------------------------

    def _write_discussion_json(
        self,
        session_dir: Path,
        session_id: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
        memory: "ConversationMemory | None",
    ) -> None:
        payload = self._build_discussion_payload(
            session_id, plan, discussion_log, synthesis, memory
        )
        path = session_dir / "discussion.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @classmethod
    def _build_discussion_payload(
        cls,
        session_id: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
        memory: "ConversationMemory | None",
    ) -> dict[str, Any]:
        """``discussion.json`` の中身を構築する (§14.3)。"""
        now = datetime.now().isoformat()
        rounds_payload = [
            cls._round_to_dict(r) for r in discussion_log.rounds
        ]

        return {
            "_schema_version": SCHEMA_VERSION,
            "_generated_by": GENERATED_BY,
            "_generated_at": now,
            "session": {
                "id": session_id,
                "started_at": synthesis.session_meta.get("started_at", now),
                "ended_at": synthesis.session_meta.get("ended_at", now),
                "duration_sec": sum(r.duration_sec for r in discussion_log.rounds),
            },
            "planning": {
                "odsc": cls._dataclass_to_dict(plan.odsc),
                "selected_agents": [
                    cls._dataclass_to_dict(a) for a in plan.selected_agents
                ],
                "discussion_plan": (
                    cls._dataclass_to_dict(plan.discussion_plan)
                    if plan.discussion_plan is not None
                    else None
                ),
                "private_instructions": {
                    role_id: cls._dataclass_to_dict(inst)
                    for role_id, inst in plan.private_instructions.items()
                },
            },
            "discussion": {
                "rounds": rounds_payload,
                "final_convergence_score": discussion_log.final_convergence_score,
                "early_termination": discussion_log.early_termination,
                "termination_detail": discussion_log.termination_detail,
                "score_history": list(discussion_log.score_history),
            },
            "evaluation": {
                role_id: {
                    "self_evaluation": cls._dataclass_to_dict(ev.self_eval),
                    "peer_evaluations": {
                        target: cls._dataclass_to_dict(pe)
                        for target, pe in ev.peer_evals.items()
                    },
                }
                for role_id, ev in synthesis.agent_evaluations.items()
            },
            "orchestrator_evaluation": cls._dataclass_to_dict(
                synthesis.orchestrator_evaluation
            ),
            "memory_summary": (
                memory.get_context_summary() if memory is not None else None
            ),
        }

    @classmethod
    def _round_to_dict(cls, round_log: Any) -> dict[str, Any]:
        return {
            "round": round_log.round,
            "phase_name": round_log.phase_name,
            "goal": round_log.goal,
            "duration_sec": round_log.duration_sec,
            "public_utterances": [
                cls._dataclass_to_dict(u) for u in round_log.public_utterances
            ],
            "convergence_check": (
                cls._dataclass_to_dict(round_log.convergence_check)
                if round_log.convergence_check is not None
                else None
            ),
        }

    @staticmethod
    def _dataclass_to_dict(obj: Any) -> Any:
        """dataclass を再帰的に dict 化する (None はそのまま返す)。"""
        if obj is None:
            return None
        if is_dataclass(obj):
            return asdict(obj)
        return obj

    # ------------------------------------------------------------------
    # Markdown / text 出力
    # ------------------------------------------------------------------

    def _write_full_conversation(
        self, session_dir: Path, synthesis: "SynthesisResult"
    ) -> None:
        (session_dir / "full_conversation.md").write_text(
            synthesis.full_conversation_md or "",
            encoding="utf-8",
        )

    def _write_report(
        self, session_dir: Path, synthesis: "SynthesisResult"
    ) -> None:
        (session_dir / "report.md").write_text(
            synthesis.report_md or "",
            encoding="utf-8",
        )

    def _write_evaluation(
        self, session_dir: Path, synthesis: "SynthesisResult"
    ) -> None:
        (session_dir / "evaluation.md").write_text(
            synthesis.evaluation_md or "",
            encoding="utf-8",
        )

    def _write_summary(
        self, session_dir: Path, synthesis: "SynthesisResult"
    ) -> None:
        (session_dir / "summary.txt").write_text(
            synthesis.summary_txt or "",
            encoding="utf-8",
        )

    def _write_vibe_prompt(
        self, session_dir: Path, synthesis: "SynthesisResult"
    ) -> None:
        """機能② のみ生成。``None`` ならファイルを作らない。"""
        if synthesis.vibe_coding_prompt_md is None:
            return
        (session_dir / "vibe_coding_prompt.md").write_text(
            synthesis.vibe_coding_prompt_md,
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # ユーティリティ
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_session_type(session_id: str) -> str:
        """``20260620_143052_idea`` → ``"idea"``。失敗時は ``"idea"``。"""
        parts = session_id.rsplit("_", 1)
        if len(parts) == 2 and parts[1] in (SESSION_TYPE_IDEA, SESSION_TYPE_REVIEW):
            return parts[1]
        return SESSION_TYPE_IDEA

    @staticmethod
    def _safe_avg(values: list[float]) -> float:
        """空リストでも例外を出さずに平均を計算する。"""
        non_zero = [float(v) for v in values if v]
        if not non_zero:
            return 0.0
        return round(sum(non_zero) / len(non_zero), 2)

    @staticmethod
    def _compute_avg_peer_score(
        evaluations: dict[str, "AgentEvaluations"],
    ) -> float:
        """全 peer スコアの平均を計算する。"""
        scores: list[int] = []
        for ev in evaluations.values():
            for pe in ev.peer_evals.values():
                scores.append(pe.score)
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 2)


__all__ = [
    "OutputGenerator",
    "SESSION_TYPE_IDEA",
    "SESSION_TYPE_REVIEW",
    "SESSION_ID_TIME_FORMAT",
]
