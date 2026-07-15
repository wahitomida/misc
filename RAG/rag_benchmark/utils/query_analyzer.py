"""クエリ意図分析: OK/NG フィルタの要否を LLM で判定.

R01/R04/R07/R09 の Vector 検索ステップで使用される.
"""
from __future__ import annotations

import json
import logging
from typing import Literal, TypedDict

from .llm_client import LLMClient

logger = logging.getLogger(__name__)


OkngFilter = Literal["OK", "NG", "BOTH", None]


class QueryIntent(TypedDict):
    okng_filter: OkngFilter
    reason: str


QUERY_ANALYSIS_SYSTEM = (
    "あなたはセンサ商談 RAG の検索戦略アドバイザーです. "
    "ユーザの質問を分析し、検索時に OK/NG フィルタが必要かを判定してください.\n"
    "ルール:\n"
    "  - 「OK 案件の〜」「成功パターン」「成約傾向」→ okng_filter: \"OK\"\n"
    "  - 「NG 案件の〜」「失注理由」「苦手な〜」→ okng_filter: \"NG\"\n"
    "  - 「OK と NG の違い」「境界条件」「OK/NG 傾向」→ okng_filter: \"BOTH\"\n"
    "  - それ以外 (個別事例の問い合わせ、条件確認、推奨等) → okng_filter: null\n\n"
    "JSON で返してください: {\"okng_filter\": \"OK\"|\"NG\"|\"BOTH\"|null, \"reason\": \"<短い理由>\"}"
)


def analyze_query_intent(llm: LLMClient, query: str) -> QueryIntent:
    """クエリの OK/NG フィルタ意図を分析.

    失敗時は ``{"okng_filter": None, "reason": "..."}`` を返す (安全側にフォールバック).
    """
    try:
        result = llm.chat(
            QUERY_ANALYSIS_SYSTEM,
            f"質問: {query}",
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(result.text)
        raw = parsed.get("okng_filter")
        if raw not in ("OK", "NG", "BOTH"):
            raw = None
        return {"okng_filter": raw, "reason": str(parsed.get("reason", ""))[:100]}
    except Exception as e:  # noqa: BLE001
        logger.warning("query intent 分析失敗: %s", e)
        return {"okng_filter": None, "reason": f"analysis_failed: {e}"}


def build_okng_where_clause(okng_filter: OkngFilter, var_name: str = "node") -> str:
    """OK/NG フィルタ用の Cypher WHERE 句を生成.

    BOTH や None の場合は空文字列 (フィルタ無し) を返す.
    """
    if okng_filter == "OK":
        return f"WHERE {var_name}.okng = 'OK'"
    if okng_filter == "NG":
        return f"WHERE {var_name}.okng = 'NG'"
    return ""
