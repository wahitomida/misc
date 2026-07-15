"""``--focus`` 自動推定: ``ScanResult`` の統計からコード状態を判定する。

LLM (planner_model) に ``CODE_STATE_DETECTION_PROMPT`` を投げて
プロジェクトの成熟度を判定し、``STATE_TO_DEFAULT_FOCUS`` で
``FOCUS_PRESETS`` のキーに変換する。

設計書: ``doc/12_code_review.md`` §12.7
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from core.data_models import ScanResult
from features.code_review.prompts import (
    CODE_STATE_DETECTION_PROMPT,
    STATE_TO_DEFAULT_FOCUS,
)

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

AUTO_FOCUS_TEMPERATURE = 0.0
AUTO_FOCUS_MAX_TOKENS = 50
DEFAULT_FALLBACK_FOCUS = "all"

_FOCUS_AUTO_MARKERS = frozenset({"auto", ""})

# テスト/docstring/型ヒント率の推定指標
_DOCSTRING_RE = re.compile(r'(?P<q>"""|\'\'\')')
_TYPE_HINT_RE = re.compile(
    r"def\s+\w+\s*\(.*->\s*[\w\[\]\.,\s\|]+\s*:", re.DOTALL
)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+", re.MULTILINE)


# ----------------------------------------------------------------------
# Public helpers
# ----------------------------------------------------------------------


def is_auto_focus(focus: str | None) -> bool:
    """``focus`` が明示指定でなく自動推定すべきかを返す。"""
    if focus is None:
        return True
    return focus in _FOCUS_AUTO_MARKERS


def compute_code_stats(scan_result: ScanResult) -> dict[str, Any]:
    """``CODE_STATE_DETECTION_PROMPT`` 用の統計を作る。

    Returns:
        ``total_files``, ``total_lines``, ``test_coverage``,
        ``docstring_ratio``, ``type_hint_ratio`` を含む辞書。
        ratio 系は ``"60%"`` のような文字列表現。
    """
    py_details = [
        f for f in scan_result.file_details
        if str(f.get("path", "")).endswith(".py")
    ]
    test_paths = [
        f for f in scan_result.file_tree
        if "test" in str(f.get("path", "")).lower()
    ]
    test_coverage = "有り" if test_paths else "無し"

    docstring_files = 0
    def_total = 0
    type_hinted_defs = 0
    for f in py_details:
        header = str(f.get("header", ""))
        if _DOCSTRING_RE.search(header):
            docstring_files += 1
        defs = _DEF_RE.findall(header)
        def_total += len(defs)
        type_hinted_defs += len(_TYPE_HINT_RE.findall(header))

    docstring_ratio = (
        f"{int(docstring_files / len(py_details) * 100)}%"
        if py_details else "0%"
    )
    type_hint_ratio = (
        f"{int(type_hinted_defs / def_total * 100)}%"
        if def_total else "0%"
    )

    return {
        "total_files": scan_result.total_files,
        "total_lines": scan_result.total_lines,
        "test_coverage": test_coverage,
        "docstring_ratio": docstring_ratio,
        "type_hint_ratio": type_hint_ratio,
    }


async def detect_focus(
    api_client: "ResilientAPIClient",
    scan_result: ScanResult,
    planner_model: str,
    valid_focuses: set[str],
) -> str:
    """``ScanResult`` から focus を推定する。

    LLM 呼び出し失敗、未知の状態名、未知の focus 名はすべて
    ``DEFAULT_FALLBACK_FOCUS`` ("all") にフォールバックする。

    Args:
        api_client: LLM 呼び出し用クライアント。
        scan_result: 推定の入力となるスキャン結果。
        planner_model: 判定に使うモデル名。
        valid_focuses: ``FOCUS_PRESETS`` のキー集合 (循環 import 回避のため
            外部から注入)。

    Returns:
        ``valid_focuses`` のいずれか。
    """
    stats = compute_code_stats(scan_result)
    prompt = CODE_STATE_DETECTION_PROMPT.format(**stats)
    try:
        response = await api_client.call(
            model=planner_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=AUTO_FOCUS_TEMPERATURE,
            max_tokens=AUTO_FOCUS_MAX_TOKENS,
        )
    except Exception as e:  # noqa: BLE001 - LLM 失敗時はフォールバック
        logger.warning(
            "Auto focus detection failed: %s; using %s",
            e,
            DEFAULT_FALLBACK_FOCUS,
        )
        return DEFAULT_FALLBACK_FOCUS

    tokens = (response.get("content") or "").strip().split()
    state_name = tokens[0].lower() if tokens else ""
    focus = STATE_TO_DEFAULT_FOCUS.get(state_name, DEFAULT_FALLBACK_FOCUS)
    if focus not in valid_focuses:
        return DEFAULT_FALLBACK_FOCUS
    return focus


__all__ = [
    "is_auto_focus",
    "compute_code_stats",
    "detect_focus",
    "AUTO_FOCUS_TEMPERATURE",
    "AUTO_FOCUS_MAX_TOKENS",
    "DEFAULT_FALLBACK_FOCUS",
]
