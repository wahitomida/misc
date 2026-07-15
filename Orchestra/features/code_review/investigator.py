"""Phase 2 個別調査の純粋ロジック。

``CodeReview`` から呼び出される、1 リーダー分の調査 (LLM 呼び出し + JSON
パース + ファイル結合) を提供する。

設計書: ``doc/12_code_review.md`` §12.3
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from core.data_models import PartLeaderConfig, ScanResult
from features.code_review.chunker import FileChunker
from features.code_review.prompts import INVESTIGATION_PROMPTS

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

INVESTIGATION_TEMPERATURE = 0.2
INVESTIGATION_MAX_TOKENS = 2_000
INVESTIGATION_MAX_FILE_CHARS = 60_000

# JSON 抽出 (``{ ... }`` ブロックを最初に見つけたものを採用)
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


# ----------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------


async def investigate_one_leader(
    api_client: "ResilientAPIClient",
    chunker: FileChunker,
    scan_result: ScanResult,
    leader: PartLeaderConfig,
) -> list[dict[str, Any]]:
    """1 パートリーダー分の調査を実行し findings を返す。

    LLM 呼び出し失敗、JSON 抽出失敗時は空リストを返す
    (上位の ``asyncio.gather`` を壊さない)。
    """
    prompt_template = INVESTIGATION_PROMPTS.get(leader.concern)
    if not prompt_template or not leader.assigned_files:
        return []

    file_content = concat_files(chunker, scan_result, leader.assigned_files)
    if not file_content.strip():
        return []

    prompt = prompt_template.format(file_content=file_content)
    try:
        response = await api_client.call(
            model=leader.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=INVESTIGATION_TEMPERATURE,
            max_tokens=INVESTIGATION_MAX_TOKENS,
        )
    except Exception as e:  # noqa: BLE001 - 1 リーダー失敗で全体止めない
        logger.warning(
            "LLM call failed for concern=%s: %s", leader.concern, e
        )
        return []

    return parse_findings(response.get("content") or "", leader.concern)


def concat_files(
    chunker: FileChunker,
    scan_result: ScanResult,
    assigned_files: list[str],
) -> str:
    """担当ファイルを結合して 1 つのプロンプト入力にする。

    ``INVESTIGATION_MAX_FILE_CHARS`` を超える場合は ``[... 残りは省略 ...]``
    を付けて切り詰める。
    """
    target_root = scan_result.target_path
    parts: list[str] = []
    used_chars = 0
    for rel_path in assigned_files:
        file_path = target_root / rel_path
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Skip file %s: %s", rel_path, e)
            continue
        chunks = chunker.chunk_file(content, rel_path)
        for chunk in chunks:
            snippet = (
                f"\n--- {chunk['file']} ({chunk['lines']}) ---\n"
                f"{chunk.get('content', '')}\n"
            )
            if used_chars + len(snippet) > INVESTIGATION_MAX_FILE_CHARS:
                parts.append("\n[... 残りは省略 ...]\n")
                return "".join(parts)
            parts.append(snippet)
            used_chars += len(snippet)
    return "".join(parts)


def parse_findings(
    content: str,
    concern: str,
) -> list[dict[str, Any]]:
    """LLM レスポンスから ``findings`` リストを抽出する。"""
    if not content:
        return []
    match = _JSON_BLOCK_RE.search(content)
    if not match:
        logger.debug("No JSON block found in %s response", concern)
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse JSON for %s: %s", concern, e)
        return []
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        return []
    return [f for f in findings if isinstance(f, dict)]


__all__ = [
    "investigate_one_leader",
    "concat_files",
    "parse_findings",
    "INVESTIGATION_TEMPERATURE",
    "INVESTIGATION_MAX_TOKENS",
    "INVESTIGATION_MAX_FILE_CHARS",
]
