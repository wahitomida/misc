"""コードレビューのレポート関連の共通定数・ヘルパー。

設計書: ``doc/12_code_review.md`` §12.6, ``doc/14_output_format.md``
"""

from __future__ import annotations

from typing import Any


SEVERITY_ORDER: tuple[str, ...] = ("critical", "warning", "suggestion", "info")
CONCERN_DISPLAY: dict[str, str] = {
    "algorithm": "🧮 アルゴリズム",
    "reproducibility": "🔬 再現性",
    "performance": "🤖 性能",
    "structure": "📐 設計",
    "readability": "📝 可読性",
    "results": "📊 結果分析",
}
REPORT_TOP_FINDINGS = 20

_SEVERITY_BADGES: dict[str, str] = {
    "critical": "🔴 Critical",
    "warning": "🟡 Warning",
    "suggestion": "🔵 Suggestion",
    "info": "ℹ️ Info",
}


def count_by_severity(
    findings: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    """``findings`` を severity 単位で集計する。"""
    counts: dict[str, int] = {}
    for items in findings.values():
        for item in items:
            severity = str(item.get("severity", "info")).lower()
            counts[severity] = counts.get(severity, 0) + 1
    return counts


def sort_findings(
    findings: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """重大度の高い順に ``(concern, item)`` の並びを返す (info は除外)。"""
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for concern, items in findings.items():
        for item in items:
            severity = str(item.get("severity", "info")).lower()
            if severity == "info":
                continue
            try:
                rank = SEVERITY_ORDER.index(severity)
            except ValueError:
                rank = len(SEVERITY_ORDER)
            ranked.append((rank, concern, item))
    ranked.sort(key=lambda x: x[0])
    return [(concern, item) for _rank, concern, item in ranked]


def severity_badge(item: dict[str, Any]) -> str:
    severity = str(item.get("severity", "info")).lower()
    return _SEVERITY_BADGES.get(severity, severity)


__all__ = [
    "SEVERITY_ORDER",
    "CONCERN_DISPLAY",
    "REPORT_TOP_FINDINGS",
    "count_by_severity",
    "sort_findings",
    "severity_badge",
]
