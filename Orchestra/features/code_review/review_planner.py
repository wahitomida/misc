"""Review 全体会議用の動的 Planner。

Idea の ``Orchestrator`` は「アイデアの深化」目的で ``PLANNING_PROMPT`` が
特化されているため、Review の「findings の優先度・修正順序・副作用の議論」に
そのまま流用できない。本モジュールは Idea と同じ設計思想 (4 段階議論構造 +
動的 goal 生成 + private_instructions LLM 生成) を Review 用に特化した
Planner を提供する。

**役割分担**:
    - Objective / discussion_plan / private_instructions: LLM で動的生成
    - selected_agents: findings ベースで Python 側で確定 (LLM に任せない)
    - 出力形式は Idea の ``OrchestraPlan`` と完全互換

**Idea の Orchestrator との違い**:
    - 参加者は findings に紐付いた concern 担当者に固定
    - Objective は「レビュー対象のコード改善」目的
    - Round 数は 3 固定 (Review Phase 4 仕様)
    - 発散フェーズは「各リーダーが担当 concern の最重要課題を報告」

**フォールバック**:
    LLM 呼び出しや JSON パースに失敗した場合、呼び出し側で
    ``features.code_review.meeting._build_meeting_plan`` (静的 Python 版) に
    フォールバックする想定。

設計書: (Review Phase 4 動的計画立案の仕様)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.data_models import (
    AgentConfig,
    DiscussionPlan,
    ODSC,
    OrchestraPlan,
    PrivateInstruction,
    RoundConfig,
    ScanResult,
)
from core.orchestrator import Orchestrator
from features.code_review.meeting_prompts import (
    DEFAULT_CONVERGENCE_THRESHOLD,
    MEETING_FINDINGS_PREVIEW,
    MEETING_LEVEL,
    ROUND1_PATTERN,
    ROUND1_PHASE_NAME,
    ROUND1_TIME_BUDGET_SEC,
    ROUND2_PATTERN,
    ROUND2_PHASE_NAME,
    ROUND2_TIME_BUDGET_SEC,
    ROUND3_PATTERN,
    ROUND3_PHASE_NAME,
    ROUND3_TIME_BUDGET_SEC,
)

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient

logger = logging.getLogger(__name__)

# Constants
DEFAULT_REVIEW_PLANNER_MODEL = "gpt-5.4"
DEFAULT_REVIEW_PLANNER_LEVEL = "medium"


# ----------------------------------------------------------------------
# Review 用 Planner プロンプト
# ----------------------------------------------------------------------

REVIEW_PLANNING_PROMPT = """\
あなたは AI Orchestra のコードレビュー全体会議の指揮者です。
Phase 2 で完了した個別調査の findings をもとに、Phase 4 全体会議 (3 ラウンド固定)
の計画を立ててください。

【会議の目的】
複数のパートリーダー AI が findings を持ち寄り、以下を合意する:
- 各 findings の優先度 (Phase A: 即修正 / Phase B: 段階的 / Phase C: 保留)
- 修正順序 (依存関係を含む)
- 修正による副作用の想定

目的は「アイデアの深化」ではなく「既に発見された問題の優先度・修正順序の
合意形成」であることに注意してください。

【★ 議論フェーズ構造 (絶対遵守、3 ラウンド固定) ★】
Round 1 (課題報告): pattern="one_shot"、全 speakers 参加。
  goal 例「各リーダーが担当 concern の最重要 findings を 1 件報告し、
         ファイル名・行番号・影響範囲を明示する」
  各リーダーは自分の担当 concern の findings から最も致命的な 1 件を報告する。

Round 2 (比較評価と深掘り): pattern="free_talk"。
  goal 例「他リーダーの所見に反例・補足を 1 つ添え、Phase A/B/C の候補を並行検討する」
  【重要】1 案に絞り込まず、全 concerns を並行して比較する。

Round 3 (合意形成): pattern="one_shot"。
  goal 例「Phase A/B/C の分類を確定し、修正順序と副作用を各 1 文で明示する」
  最終的な優先度と修正順序を合意する。

【★ goal の書き方 (絶対遵守) ★】
「動詞 + 具体成果物 + 数字」の形。数字必須。
良い例: 「Phase A 候補を 3 件確定する」「副作用を各 1 文で明示する」。
悪い例: 「議論する」「検討する」(数字なし)。

【会議の自然さ (数値過剰の抑制)】
- 疑似変数 (τ=0.8、ε=0.1、δ、σ 等) や単位の羅列 (bps、+3pt、≤10ms 等) は禁止
- 数字は代表となる 1〜2 個に絞る
- ファイル名・行番号・件数などレビューで自然な数値のみ使う

【レビュー対象】
- 対象パス: {target_path}
- Focus: {focus}
- 合計 findings 件数: {total_findings}
- 観点別内訳: {concern_summary}

【参加リーダー (Python 側で確定済み、順序は変えない)】
{leaders_section}

【findings プレビュー (各 concern の上位 3 件)】
{findings_preview}

【★ 出力形式 (JSON のみ、前後に説明文を付けない) ★】
{{
  "odsc": {{
    "objective": "レビュー対象・findings 件数・目的を 100〜200 字で自然に述べる",
    "deliverable": "優先度確定・修正順序・副作用の合意 (Phase A/B/C 分類)",
    "success_criteria": "全 concern が発言し、Phase A/B/C の全 findings が分類済み",
    "convergence_threshold": 0.75
  }},
  "discussion_plan": {{
    "estimated_rounds": 3,
    "round_config": [
      {{"round": 1, "phase_name": "課題報告と問題提起", "speakers": [...],
        "pattern": "one_shot", "level": "medium",
        "time_budget_sec": 60, "goal": "..."}},
      {{"round": 2, "phase_name": "深掘りと反論", "speakers": [...],
        "pattern": "free_talk", "level": "medium",
        "time_budget_sec": 120, "goal": "..."}},
      {{"round": 3, "phase_name": "合意形成", "speakers": [...],
        "pattern": "one_shot", "level": "medium",
        "time_budget_sec": 60, "goal": "..."}}
    ],
    "total_estimated_time_sec": 240,
    "total_estimated_requests": 30
  }},
  "private_instructions": {{
    "<role_id>": {{
      "expected_contribution": "このリーダーが会議で貢献する具体的な内容 (1〜2 文)",
      "focus_points": [
        "担当 concern の findings をどう共有するか",
        "他リーダーの所見にどう反応するか",
        "ファイル名・行番号を含めることの徹底"
      ],
      "constraints": [
        "抽象論だけの発言は禁止",
        "他者と同じ具体例・言い回しを繰り返さない"
      ],
      "context_from_plan": "3 ラウンドの中でこのリーダーが果たす役割の位置付け"
    }}
  }}
}}

【制約】
- 各ラウンドの speakers は上記【参加リーダー】の全 role_id を含めること (順序は同じ)
- private_instructions は 【参加リーダー】に列挙された全 role_id を含めること
- round_config は必ず 3 件 (Round 1/2/3、pattern と phase_name はテンプレ通り)
- 各ラウンドの level は "medium" 統一
- JSON 以外の文字 (説明文・コードフェンス) は一切出さない
"""


# ----------------------------------------------------------------------
# ReviewPlanner クラス
# ----------------------------------------------------------------------


class ReviewPlanner:
    """Review 全体会議用の動的 Planner。

    Idea の ``Orchestrator`` と同じ設計思想 (LLM で計画を動的生成) を
    Review 特化で提供する。selected_agents は Python 側で findings ベースに
    確定するため、LLM 出力の該当セクションは無視する。

    Attributes:
        api_client: LLM 呼び出し用クライアント。
        model: Planner LLM モデル。
        level: Planner LLM level。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        model: str = DEFAULT_REVIEW_PLANNER_MODEL,
        level: str = DEFAULT_REVIEW_PLANNER_LEVEL,
    ) -> None:
        self.api_client = api_client
        self.model = model
        self.level = level

    async def plan(
        self,
        scan_result: ScanResult,
        findings: dict[str, list[dict[str, Any]]],
        focus: str,
        selected_agents: list[AgentConfig],
    ) -> OrchestraPlan:
        """LLM で動的に計画を立てる。

        Args:
            scan_result: フォルダスキャン結果。
            findings: concern → findings リストの辞書。
            focus: レビュー focus 設定 (``all`` / ``performance`` など)。
            selected_agents: findings ベースで Python 側で確定した参加リーダー。
                Planner LLM が上書きしないよう明示的に受け取り、返却時に埋め戻す。

        Returns:
            ``OrchestraPlan``。LLM 失敗時は ``PlanValidationError`` が伝播する
            (呼び出し側でキャッチして静的な ``_build_meeting_plan`` に
            フォールバックする想定)。
        """
        prompt = self._build_prompt(
            scan_result=scan_result,
            findings=findings,
            focus=focus,
            selected_agents=selected_agents,
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたはコードレビュー全体会議の指揮者です。"
                        " 必ず有効な JSON オブジェクトを返してください。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            level=self.level,
        )
        content = str(response.get("content") or "")

        # Idea の Orchestrator の parse ロジックを再利用 (JSON 抽出 + 型変換)
        json_text = Orchestrator._extract_json(content)
        data = json.loads(json_text)
        if not isinstance(data, dict):
            raise ValueError(
                f"Planner response must be a JSON object, got {type(data).__name__}"
            )

        odsc = self._parse_odsc(data.get("odsc") or {})
        discussion_plan = self._parse_discussion_plan(
            data.get("discussion_plan") or {},
            speakers=[a.role_id for a in selected_agents],
        )
        private_instructions = self._parse_private_instructions(
            data.get("private_instructions") or {},
            selected_agents=selected_agents,
        )

        return OrchestraPlan(
            odsc=odsc,
            selected_agents=selected_agents,
            discussion_plan=discussion_plan,
            private_instructions=private_instructions,
        )

    # ------------------------------------------------------------------
    # プロンプト組み立て
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        scan_result: ScanResult,
        findings: dict[str, list[dict[str, Any]]],
        focus: str,
        selected_agents: list[AgentConfig],
    ) -> str:
        """Review 用 PLANNING_PROMPT を組み立てる。"""
        total_findings = sum(len(items) for items in findings.values())
        concern_summary = ", ".join(
            f"{c}({len(items)}件)" for c, items in findings.items() if items
        ) or "(なし)"

        leaders_section = "\n".join(
            f"- role_id: {a.role_id} | 期待: {a.expected_contribution}"
            for a in selected_agents
        ) or "(なし)"

        findings_preview = _format_findings_preview(findings)

        return REVIEW_PLANNING_PROMPT.format(
            target_path=_safe_path(scan_result.target_path),
            focus=focus,
            total_findings=total_findings,
            concern_summary=concern_summary,
            leaders_section=leaders_section,
            findings_preview=findings_preview,
        )

    # ------------------------------------------------------------------
    # LLM 応答パース
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_odsc(raw: dict[str, Any]) -> ODSC:
        """LLM 応答から ODSC を組み立てる (フィールド欠落に耐性あり)。"""
        threshold_raw = raw.get("convergence_threshold", DEFAULT_CONVERGENCE_THRESHOLD)
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            threshold = DEFAULT_CONVERGENCE_THRESHOLD
        threshold = max(0.5, min(0.95, threshold))
        return ODSC(
            objective=str(raw.get("objective") or "コードレビュー全体会議"),
            deliverable=str(raw.get("deliverable") or "優先度確定・修正順序・副作用所見"),
            success_criteria=str(raw.get("success_criteria") or "全 concern が発言し Phase A/B/C 分類済み"),
            convergence_threshold=threshold,
        )

    @staticmethod
    def _parse_discussion_plan(
        raw: dict[str, Any],
        speakers: list[str],
    ) -> DiscussionPlan:
        """LLM 応答から DiscussionPlan を組み立てる。speakers は Python 側の
        値で強制上書きする (LLM が変更した場合の防衛)。"""
        raw_configs = raw.get("round_config") or []
        round_configs: list[RoundConfig] = []
        defaults = [
            (ROUND1_PHASE_NAME, ROUND1_PATTERN, ROUND1_TIME_BUDGET_SEC),
            (ROUND2_PHASE_NAME, ROUND2_PATTERN, ROUND2_TIME_BUDGET_SEC),
            (ROUND3_PHASE_NAME, ROUND3_PATTERN, ROUND3_TIME_BUDGET_SEC),
        ]
        # 3 ラウンド固定を保証: LLM 出力が不足したらデフォルトで補完
        for i, (default_phase, default_pattern, default_time) in enumerate(defaults):
            rc = raw_configs[i] if i < len(raw_configs) and isinstance(raw_configs[i], dict) else {}
            round_configs.append(
                RoundConfig(
                    round=int(rc.get("round", i + 1)),
                    phase_name=str(rc.get("phase_name") or default_phase),
                    speakers=list(speakers),  # Python 側の値で強制上書き
                    pattern=str(rc.get("pattern") or default_pattern),
                    level=str(rc.get("level") or MEETING_LEVEL),
                    time_budget_sec=float(rc.get("time_budget_sec") or default_time),
                    goal=str(rc.get("goal") or "(未設定)"),
                )
            )
        total_time = sum(rc.time_budget_sec for rc in round_configs)
        try:
            total_requests = int(raw.get("total_estimated_requests") or 0)
        except (TypeError, ValueError):
            total_requests = 0
        if total_requests <= 0:
            total_requests = len(speakers) * 3 + 3

        return DiscussionPlan(
            estimated_rounds=len(round_configs),
            round_config=round_configs,
            total_estimated_time_sec=total_time,
            total_estimated_requests=total_requests,
        )

    @staticmethod
    def _parse_private_instructions(
        raw: dict[str, Any],
        selected_agents: list[AgentConfig],
    ) -> dict[str, PrivateInstruction]:
        """LLM 応答から PrivateInstruction を組み立てる。

        LLM 応答に含まれない role_id は空 (デフォルト値) の PrivateInstruction
        を割り当てる (Agent 生成時に role の default プロンプトで補完される)。
        """
        result: dict[str, PrivateInstruction] = {}
        for cfg in selected_agents:
            rid = cfg.role_id
            entry = raw.get(rid) if isinstance(raw, dict) else None
            if not isinstance(entry, dict):
                entry = {}
            result[rid] = PrivateInstruction(
                role_id=rid,
                expected_contribution=str(
                    entry.get("expected_contribution")
                    or cfg.expected_contribution
                    or ""
                ),
                focus_points=_str_list(entry.get("focus_points")),
                constraints=_str_list(entry.get("constraints")),
                context_from_plan=str(entry.get("context_from_plan") or ""),
                feedback_reminder=str(entry.get("feedback_reminder") or ""),
                speaking_rules=str(entry.get("speaking_rules") or ""),
            )
        return result


# ----------------------------------------------------------------------
# ヘルパー
# ----------------------------------------------------------------------


def _str_list(raw: Any) -> list[str]:
    """LLM 応答の list フィールドを ``list[str]`` に正規化する。"""
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()]


def _safe_path(target_path: Path | str) -> str:
    """``target_path`` を UI 表示用の文字列に変換する。"""
    try:
        return str(target_path)
    except Exception:  # noqa: BLE001
        return "(不明)"


def _format_findings_preview(
    findings: dict[str, list[dict[str, Any]]],
    per_concern: int = MEETING_FINDINGS_PREVIEW,
) -> str:
    """各 concern の上位 N 件を LLM プロンプト用に整形する。"""
    parts: list[str] = []
    for concern, items in findings.items():
        if not items:
            continue
        parts.append(f"[{concern}] {len(items)} 件")
        for item in items[:per_concern]:
            severity = item.get("severity", "?")
            file_ref = item.get("file") or item.get("file_path") or "?"
            line_ref = item.get("line") or item.get("line_range") or "?"
            title = item.get("title", "(無題)")
            parts.append(f"  - [{severity}] {file_ref} L{line_ref}: {title}")
    return "\n".join(parts) if parts else "(findings なし)"


__all__ = [
    "ReviewPlanner",
    "REVIEW_PLANNING_PROMPT",
    "DEFAULT_REVIEW_PLANNER_MODEL",
    "DEFAULT_REVIEW_PLANNER_LEVEL",
]
