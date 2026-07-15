"""``vibe_coding_prompt.md`` の組み立て。

AI コーディングアシスタントに渡す修正指示書を、調査済みの ``findings`` から
決定的に生成する (LLM 非経由)。

設計書: ``doc/12_code_review.md`` §12.6.2
"""

from __future__ import annotations

from typing import Any

from core.data_models import ScanResult
from features.code_review.report_common import (
    CONCERN_DISPLAY,
    severity_badge,
    sort_findings,
)


GLOBAL_CONSTRAINTS: tuple[str, ...] = (
    "既存テストを壊さない",
    "型ヒント・docstring を維持・追加する",
    "マジックナンバーは定数化する",
    "関数 50 行以下、ファイル 300 行以下を目標",
)


def build_vibe_prompt_md(
    scan_result: ScanResult,
    findings: dict[str, list[dict[str, Any]]],
    focus: str,
) -> str:
    """``vibe_coding_prompt.md`` を組み立てる。"""
    lines: list[str] = [
        "# 🤖 コード修正指示書 (AI向け)",
        "",
        "## プロジェクトコンテキスト",
        "",
        f"- 対象: {scan_result.target_path}",
        f"- focus: {focus}",
        f"- ファイル数: {scan_result.total_files}",
        "",
        "## 修正タスク一覧 (優先度順)",
        "",
    ]
    sorted_items = sort_findings(findings)
    if not sorted_items:
        lines.append("(修正タスクはありません)")
    else:
        for i, (concern, item) in enumerate(sorted_items, 1):
            lines.extend(_format_task(i, concern, item))

    lines.extend(["## グローバル制約", ""])
    for i, constraint in enumerate(GLOBAL_CONSTRAINTS, 1):
        lines.append(f"{i}. {constraint}")
    lines.append("")
    return "\n".join(lines)


def _format_task(
    index: int,
    concern: str,
    item: dict[str, Any],
) -> list[str]:
    badge = severity_badge(item)
    lines = [
        (
            f"### {badge} Task {index}: "
            f"{CONCERN_DISPLAY.get(concern, concern)} - "
            f"{item.get('title', '(無題)')}"
        ),
        "",
        f"**対象**: {item.get('file', '?')} {item.get('line', '')}",
    ]
    current = item.get("current_code", "")
    if current:
        lines.extend(["**現状のコード:**", "```", current, "```"])
    problem = item.get("problem") or item.get("answer", "")
    if problem:
        lines.append(f"**問題点**: {problem}")
    fix = item.get("fix_suggestion", "")
    if fix:
        lines.append(f"**修正方針**: {fix}")
    impact = item.get("impact", "")
    if impact:
        lines.append(f"**影響範囲**: {impact}")
    lines.append("")
    return lines


__all__ = ["build_vibe_prompt_md", "GLOBAL_CONSTRAINTS"]
