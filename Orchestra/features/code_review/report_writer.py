"""コードレビューレポート本文 (Markdown / テキスト) ビルダー。

``SynthesisResult`` に詰めるための各レポート文字列を構築する。

設計書: ``doc/12_code_review.md`` §12.6, ``doc/14_output_format.md``
"""

from __future__ import annotations

import re
from typing import Any

from core.data_models import (
    AgentEvaluations,
    DiscussionLog,
    OrchestraPlan,
    OrchestratorEvaluation,
    PeerEvaluation,
    ScanResult,
)
from features.code_review.report_common import (
    CONCERN_DISPLAY,
    REPORT_TOP_FINDINGS,
    count_by_severity,
    severity_badge,
    sort_findings,
)


SUMMARY_DIVIDER = "━" * 40


# ----------------------------------------------------------------------
# report.md
# ----------------------------------------------------------------------


def build_report_md(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    discussion_log: DiscussionLog,
) -> str:
    counts = count_by_severity(findings)
    total = sum(counts.values())
    lines: list[str] = [
        "# 🔬 コードレビュー レポート",
        "",
        f"> **対象**: {scan_result.target_path}",
        f"> **Focus**: {focus}",
        f"> **総ファイル数**: {scan_result.total_files} / "
        f"**総行数**: {scan_result.total_lines}",
        "",
        "---",
        "",
        "## 概要",
        "",
        "| 観点 | 課題数 | Critical | Warning | Suggestion |",
        "|---|---|---|---|---|",
    ]
    for concern, items in findings.items():
        c_counts = count_by_severity({concern: items})
        lines.append(
            f"| {CONCERN_DISPLAY.get(concern, concern)} | {len(items)} | "
            f"{c_counts.get('critical', 0)} | {c_counts.get('warning', 0)} | "
            f"{c_counts.get('suggestion', 0)} |"
        )
    lines.extend(
        [
            f"| **合計** | **{total}** | **{counts.get('critical', 0)}** | "
            f"**{counts.get('warning', 0)}** | "
            f"**{counts.get('suggestion', 0)}** |",
            "",
            "---",
            "",
            "## 主要課題 (重大度順)",
            "",
        ]
    )

    sorted_items = sort_findings(findings)
    if not sorted_items:
        lines.append("(検出された課題はありません)")
    else:
        for i, (concern, item) in enumerate(sorted_items[:REPORT_TOP_FINDINGS], 1):
            lines.extend(_format_report_finding(i, concern, item))

    if discussion_log.rounds:
        lines.extend(["---", "", "## 全体会議の要旨", ""])
        for round_log in discussion_log.rounds:
            for u in round_log.public_utterances:
                lines.append(
                    f"- **{u.speaker_display}**: {u.content[:200]}"
                )
        lines.append("")

    return "\n".join(lines)


def _format_report_finding(
    index: int,
    concern: str,
    item: dict[str, Any],
) -> list[str]:
    lines = [
        (
            f"### [{index}] {severity_badge(item)} "
            f"{CONCERN_DISPLAY.get(concern, concern)} - "
            f"{item.get('title', '(無題)')}"
        ),
        "",
        f"**ファイル**: {item.get('file', '?')} {item.get('line', '')}",
    ]
    problem = item.get("problem") or item.get("answer", "")
    if problem:
        lines.append(f"**問題**: {problem}")
    fix = item.get("fix_suggestion", "")
    if fix:
        lines.append(f"**修正方針**: {fix}")
    impact = item.get("impact", "")
    if impact:
        lines.append(f"**影響**: {impact}")
    lines.append("")
    return lines


# ----------------------------------------------------------------------
# evaluation.md / summary.txt / full_conversation.md
# ----------------------------------------------------------------------


def build_full_conversation_md(
    discussion_log: DiscussionLog,
    scan_result: ScanResult | None = None,
    findings: dict[str, list[dict[str, Any]]] | None = None,
    evaluations: dict[str, AgentEvaluations] | None = None,
    plan: OrchestraPlan | None = None,
) -> str:
    """§14.4 準拠の全体会議ログを生成する。

    セクション構成:
        1. ヘッダ (テーマ / 参加者 / ラウンド数 / 収束スコア)
        2. 舞台裏 (指揮者の内心 + 各 AI への期待)
        3. 各ラウンドの発言と収束チェック
        4. 評価タイム
    """
    if not discussion_log.rounds:
        return "# \U0001f3ad AI Orchestra \u2014 全体会議ログ\n\n(議論ログなし)\n"

    evaluations = evaluations or {}
    parts: list[str] = []
    parts.extend(_render_conversation_header(discussion_log, scan_result, plan))
    parts.extend(_render_backstage_and_expectations(findings, plan))
    parts.extend(_render_conversation_rounds(discussion_log))
    parts.extend(_render_evaluations_section(evaluations, plan))
    return "\n".join(parts)


def _render_conversation_header(
    discussion_log: DiscussionLog,
    scan_result: ScanResult | None,
    plan: OrchestraPlan | None,
) -> list[str]:
    """会話ログ冒頭のヘッダ (テーマ・参加者・ラウンド数・収束スコア)。"""
    convergence = discussion_log.final_convergence_score
    target = str(scan_result.target_path) if scan_result else "(不明)"
    participants = _build_participants_display(discussion_log, plan)
    return [
        "# \U0001f3ad AI Orchestra \u2014 全体会議ログ",
        "",
        f"> テーマ: コードレビュー {target}",
        f"> 参加: {participants}",
        f"> ラウンド数: {len(discussion_log.rounds)} | 収束: {convergence:.2f}",
        "",
        "---",
        "",
    ]


def _render_backstage_and_expectations(
    findings: dict[str, list[dict[str, Any]]] | None,
    plan: OrchestraPlan | None,
) -> list[str]:
    """指揮者の舞台裏 (内心セクション + 各 AI への期待)。"""
    lines: list[str] = [
        "## \U0001f3bc 舞台裏: 計画フェーズ",
        "",
        "```",
    ]
    if findings:
        counts = count_by_severity(findings)
        total = sum(counts.values())
        lines.append(
            f"\U0001f3bc [内心] 課題 {total} 件を抱えている "
            f"(C:{counts.get('critical', 0)} / W:{counts.get('warning', 0)} / "
            f"S:{counts.get('suggestion', 0)})"
        )
        top_concern = _find_top_concern(findings)
        if top_concern:
            lines.append(
                f"\U0001f3bc [内心] 最優先は {top_concern} 系。"
                "ここを Phase A に置きたい"
            )
        lines.append(
            "\U0001f3bc [内心] 3ラウンド構成 — "
            "Round1で論点出し、Round2で反論、Round3で合意"
        )
    else:
        lines.append("\U0001f3bc [内心] 全体会議で課題の優先度を確定する")
    lines.append("```")
    lines.append("")

    if plan and plan.private_instructions:
        for role_id, pi in plan.private_instructions.items():
            emoji = _extract_emoji_for_role(role_id, plan)
            instruction = pi.expected_contribution or "(指示なし)"
            lines.append(f"**\U0001f3bc\u2192{emoji}** {instruction}")
        lines.append("")
    return lines


def _render_conversation_rounds(discussion_log: DiscussionLog) -> list[str]:
    """全ラウンドの発言と収束チェックを描画する。"""
    lines: list[str] = []
    for round_log in discussion_log.rounds:
        lines.append("---")
        lines.append("")
        goal_summary = _summarize_goal(round_log.goal)
        header = (
            f"## \U0001f4ac Round {round_log.round}: "
            f"{round_log.phase_name or '全体会議'}"
        )
        if goal_summary:
            header += f" — {goal_summary}"
        lines.append(header)
        lines.append("")
        for u in round_log.public_utterances:
            emoji = _extract_emoji(u.speaker_display)
            content = _strip_conclusion_tags(u.content)
            if u.type == "conclusion":
                lines.append(f"> **🎯 {emoji} 結論** {content}")
            else:
                lines.append(f"**{emoji}** {content}")
            lines.append("")
        check = round_log.convergence_check
        if check is None:
            continue
        lines.append("```")
        lines.append(
            f"\U0001f3bc [収束: {check.score:.2f}] "
            f"{check.reasoning or '(理由なし)'}"
        )
        if check.remaining_disagreements:
            lines.append(
                f"\U0001f3bc [未解決] "
                f"{', '.join(check.remaining_disagreements)}"
            )
        lines.append("```")
        lines.append("")
    return lines


def _render_evaluations_section(
    evaluations: dict[str, AgentEvaluations],
    plan: OrchestraPlan | None,
) -> list[str]:
    """会話ログ末尾の評価タイムセクション。"""
    lines: list[str] = [
        "---",
        "",
        "## \U0001f4ca 評価タイム",
        "",
    ]
    if not evaluations:
        lines.append("評価: 未実施")
        lines.append("")
        return lines
    for role_id, ev in evaluations.items():
        emoji = _extract_emoji_for_role(role_id, plan)
        avg = ev.self_eval.avg_score
        reasoning = (ev.self_eval.reasoning or "")[:80]
        lines.append(f"{emoji}→自分 {avg:.1f}/5。{reasoning}")
        for target_id, pe in ev.peer_evals.items():
            target_emoji = _extract_emoji_for_role(target_id, plan)
            lines.append(
                f"{emoji}→{target_emoji} {pe.score}/5。{pe.comment}"
            )
    lines.append("")
    return lines


# role_id → 絵文字の既知マッピング (display_name が取れない時のフォールバック)
_ROLE_EMOJI_MAP: dict[str, str] = {
    "theorist": "🧮",
    "experimentalist": "🔬",
    "implementer": "🤖",
    "literature": "📚",
    "devil": "😈",
    "code_architect": "📐",
    "code_reviewer": "📝",
    "bird_eye": "🎯",
    "son_masayoshi": "🐑",
    "matushita_kounosuke": "🍿",
}


def _extract_emoji_for_role(role_id: str, plan: OrchestraPlan | None) -> str:
    """role_id から絵文字を解決する (plan の selected_agents → 既知マップ)。

    未知の role_id は ``🎭`` (汎用マスク) を返す。
    """
    del plan  # selected_agents には display_name がないので既知マップを使う
    return _ROLE_EMOJI_MAP.get(role_id, "🎭")


def _build_participants_display(
    log: DiscussionLog, plan: OrchestraPlan | None
) -> str:
    """『🔬 実験屋(experimentalist) / 📐 設計リーダー(code_architect)』形式。"""
    seen: dict[str, str] = {}
    for r in log.rounds:
        for u in r.public_utterances:
            if u.speaker not in seen:
                seen[u.speaker] = u.speaker_display
    if not seen:
        return "(なし)"
    return " / ".join(f"{disp}({rid})" for rid, disp in seen.items())


def _find_top_concern(findings: dict[str, list[dict[str, Any]]]) -> str:
    """件数最多の concern キーを返す。"""
    if not findings:
        return ""
    return max(findings.items(), key=lambda kv: len(kv[1]))[0]


def _summarize_goal(goal: str) -> str:
    """ラウンド goal を 1 行に圧縮 (1 行目のみを取る)。"""
    if not goal:
        return ""
    first_line = goal.strip().split("\n", 1)[0]
    return first_line[:60]


def _extract_emoji(speaker_display: str) -> str:
    """speaker_display の先頭絵文字を取り出す。"""
    if speaker_display and ord(speaker_display[0]) > 0x2600:
        return speaker_display[0]
    return speaker_display


def _strip_conclusion_tags(content: str) -> str:
    """結論発言から旧フォーマットタグを除去する (P1: フォーマットタグ廃止)。

    Idea 側と同じ処理。ROUND_CONCLUSION_INSTRUCTION 書き換え後も LLM が
    慣性で「【結論】〜【合意点】〜【相違点】〜【次論点】」を出す場合に
    出力段で機械的に除去する。
    """
    if not content:
        return content
    cleaned = content
    for tag in ("【最終結論】", "【結論】", "【合意点】", "【相違点】", "【次論点】"):
        cleaned = cleaned.replace(tag, "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", " ", cleaned)
    return cleaned.strip()


def build_evaluation_md(
    findings: dict[str, list[dict[str, Any]]],
    evaluations: dict[str, AgentEvaluations] | None = None,
    orchestrator_eval: OrchestratorEvaluation | None = None,
) -> str:
    """§14.6 準拠の評価レポートを生成する。

    セクション構成:
        1. ヘッダ
        2. 総合スコアランキング (evaluations あり時)
        3. 個別評価詳細 (evaluations あり時)
        4. 議論品質 (orchestrator_eval に品質スコアあり時)
        5. 課題サマリ (常に)
        6. 観点別内訳 (常に)
    """
    evaluations = evaluations or {}
    orchestrator_eval = orchestrator_eval or OrchestratorEvaluation()
    counts = count_by_severity(findings)
    total = sum(counts.values())

    parts: list[str] = ["# コードレビュー評価", ""]
    if evaluations:
        parts.extend(_render_score_ranking_section(evaluations))
        parts.extend(_render_individual_evaluations(evaluations, orchestrator_eval))
        parts.extend(_render_discussion_quality(orchestrator_eval))
    else:
        parts.append("評価の生成に失敗しました。")
        parts.append("")
    parts.extend(_render_findings_summary(findings, counts, total))
    return "\n".join(parts)


def _render_score_ranking_section(
    evaluations: dict[str, AgentEvaluations],
) -> list[str]:
    """総合スコアランキングの表を描画する。"""
    lines: list[str] = ["## 🏆 総合スコアランキング", ""]
    ranking = _build_score_ranking(evaluations)
    if not ranking:
        lines.append("(ランキングを算出できませんでした)")
        lines.extend(["", "---", ""])
        return lines
    lines.append("| 順位 | AI | 自己評価 | 他者評価 | 総合 |")
    lines.append("|---|---|---|---|---|")
    medals = ["🥇", "🥈", "🥉"]
    for i, (role_id, self_avg, peer_avg, combined) in enumerate(ranking):
        medal = medals[i] if i < len(medals) else f"{i + 1}"
        lines.append(
            f"| {medal} | {role_id} | {self_avg:.2f} | "
            f"{peer_avg:.2f} | **{combined:.2f}** |"
        )
    lines.extend(["", "---", ""])
    return lines


def _render_individual_evaluations(
    evaluations: dict[str, AgentEvaluations],
    orchestrator_eval: OrchestratorEvaluation,
) -> list[str]:
    """個別 AI の詳細評価 (自己評価表 + 他者評価表 + 指揮者フィードバック)。"""
    lines: list[str] = ["## 📝 個別評価詳細", ""]
    for role_id, ev in evaluations.items():
        lines.append(f"### {role_id}")
        lines.append("")
        lines.extend(_render_self_evaluation_table(ev))
        lines.extend(_render_peer_received_table(role_id, evaluations))
        lines.extend(_render_orchestrator_feedback(role_id, orchestrator_eval))
        lines.append("---")
        lines.append("")
    return lines


def _render_self_evaluation_table(ev: AgentEvaluations) -> list[str]:
    """自己評価スコア表 (基準ごとの ⭐ 表示) と 3-5 文の reasoning を返す。"""
    lines: list[str] = []
    self_eval = ev.self_eval
    if self_eval.scores:
        lines.append("| 基準 | スコア |")
        lines.append("|---|---|")
        for name, score in self_eval.scores.items():
            stars = "⭐" * score + "☆" * (5 - score)
            lines.append(f"| {name} | {stars} ({score}/5) |")
        lines.append(f"| **平均** | **{self_eval.avg_score:.2f}** |")
    lines.append("")
    if self_eval.reasoning:
        lines.append(f"> {self_eval.reasoning}")
        lines.append("")
    return lines


def _render_peer_received_table(
    role_id: str,
    evaluations: dict[str, AgentEvaluations],
) -> list[str]:
    """他者から受けた評価の表を返す。誰からも受けていなければ空。"""
    received = _collect_peer_received(role_id, evaluations)
    if not received:
        return []
    lines = ["**他者からの評価:**", "", "| 評価者 | スコア | コメント |", "|---|---|---|"]
    for evaluator_id, pe in received.items():
        lines.append(f"| {evaluator_id} | {pe.score}/5 | {pe.comment} |")
    lines.append("")
    return lines


def _render_orchestrator_feedback(
    role_id: str,
    orchestrator_eval: OrchestratorEvaluation,
) -> list[str]:
    """指揮者から特定ロールへのフィードバック (strengths / improvements)。"""
    fb = orchestrator_eval.per_agent_feedback.get(role_id)
    if not fb:
        return []
    lines = ["**🎵 指揮者フィードバック:**", ""]
    for s in fb.strengths_noted or []:
        lines.append(f"- 👍 {s}")
    for s in fb.improvements_noted or []:
        lines.append(f"- 📌 {s}")
    lines.append("")
    return lines


def _render_discussion_quality(orchestrator_eval: OrchestratorEvaluation) -> list[str]:
    """議論品質スコアと MVP の一言。品質が 0 なら空。"""
    if orchestrator_eval.overall_discussion_quality <= 0:
        return []
    lines = [
        "## 📈 議論品質",
        "",
        f"- 品質: {orchestrator_eval.overall_discussion_quality:.1f}/5",
    ]
    if orchestrator_eval.mvp_role_id:
        lines.append(
            f"- MVP: {orchestrator_eval.mvp_role_id}"
            f" ({orchestrator_eval.mvp_reason})"
        )
    lines.append("")
    return lines


def _render_findings_summary(
    findings: dict[str, list[dict[str, Any]]],
    counts: dict[str, int],
    total: int,
) -> list[str]:
    """課題サマリ + 観点別内訳 (常に末尾で描画)。"""
    lines = [
        "---",
        "",
        "## 課題サマリ",
        "",
        f"- **総課題数**: {total}",
        f"- Critical: {counts.get('critical', 0)}",
        f"- Warning: {counts.get('warning', 0)}",
        f"- Suggestion: {counts.get('suggestion', 0)}",
        f"- Info: {counts.get('info', 0)}",
        "",
        "## 観点別内訳",
        "",
    ]
    for concern, items in findings.items():
        lines.append(
            f"- {CONCERN_DISPLAY.get(concern, concern)}: {len(items)} 件"
        )
    return lines


def _build_score_ranking(
    evaluations: dict[str, AgentEvaluations],
) -> list[tuple[str, float, float, float]]:
    """(role_id, self_avg, peer_avg, total) のリストを総合降順で返す。"""
    received: dict[str, list[int]] = {}
    for _evaluator_id, ev in evaluations.items():
        for target_id, pe in ev.peer_evals.items():
            received.setdefault(target_id, []).append(pe.score)

    ranking: list[tuple[str, float, float, float]] = []
    for role_id, ev in evaluations.items():
        self_avg = float(ev.self_eval.avg_score or 0.0)
        peer_scores = received.get(role_id, [])
        peer_avg = (
            sum(peer_scores) / len(peer_scores) if peer_scores else 0.0
        )
        combined = (self_avg + peer_avg) / 2 if (self_avg or peer_avg) else 0.0
        ranking.append((role_id, self_avg, peer_avg, combined))
    ranking.sort(key=lambda x: x[3], reverse=True)
    return ranking


def _collect_peer_received(
    role_id: str,
    evaluations: dict[str, AgentEvaluations],
) -> dict[str, PeerEvaluation]:
    """ある role_id が他者から受けた評価を集める。"""
    received: dict[str, PeerEvaluation] = {}
    for evaluator_id, ev in evaluations.items():
        if evaluator_id == role_id:
            continue
        pe = ev.peer_evals.get(role_id)
        if pe is not None:
            received[evaluator_id] = pe
    return received


def build_summary_txt(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
    discussion_log: DiscussionLog,
) -> str:
    counts = count_by_severity(findings)
    total = sum(counts.values())
    return "\n".join(
        [
            SUMMARY_DIVIDER,
            "コードレビュー サマリ",
            SUMMARY_DIVIDER,
            f"対象: {scan_result.target_path}",
            f"focus: {focus} | ファイル数: {scan_result.total_files}",
            (
                f"課題: {total} (C:{counts.get('critical', 0)} / "
                f"W:{counts.get('warning', 0)} / "
                f"S:{counts.get('suggestion', 0)})"
            ),
            f"全体会議: {len(discussion_log.rounds)} ラウンド",
            SUMMARY_DIVIDER,
        ]
    )


__all__ = [
    "build_report_md",
    "build_full_conversation_md",
    "build_evaluation_md",
    "build_summary_txt",
    "SUMMARY_DIVIDER",
]
