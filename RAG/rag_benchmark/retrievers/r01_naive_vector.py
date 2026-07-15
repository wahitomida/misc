"""R01: Naive Vector RAG.

最も基本的なベースライン. クエリを Embedding 化し Neo4j Vector Index で Top-K 取得.
ENABLE_OKNG_FILTER=True なら、クエリ分析結果に基づき OK/NG フィルタを追加適用.
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.query_analyzer import analyze_query_intent
from ..utils.token_counter import count_tokens, pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


class NaiveVectorRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R01"

    @property
    def method_name(self) -> str:
        return "Naive Vector RAG"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        top_k = int(self.config.get("top_k", 10))

        # OK/NG フィルタ意図検出
        okng_filter: str | None = None
        intent_reason = ""
        if config.ENABLE_OKNG_FILTER:
            intent = analyze_query_intent(self.llm, query)
            if intent["okng_filter"] in ("OK", "NG"):
                okng_filter = intent["okng_filter"]
            intent_reason = intent["reason"]

        qvec = self.llm.embed(query)

        # Cypher 構築 (フィルタ有無で分岐)
        if okng_filter:
            # Vector Index は WHERE を直接受けないので oversample → filter
            cypher = (
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score "
                "WHERE node.okng = $okng "
                "RETURN node.deal_id AS deal_id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC LIMIT $limit"
            )
            rows = self.neo4j.run_read(
                cypher, k=top_k * 3, q=qvec, okng=okng_filter, limit=top_k,
            )
        else:
            rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score "
                "RETURN node.deal_id AS deal_id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC",
                k=top_k, q=qvec,
            )

        contexts_full: list[str] = []
        deal_ids: list[int] = []
        for r in rows:
            deal_ids.append(int(r["deal_id"]))
            ctx = (
                f"[Deal#{r['deal_id']} {r['okng']} sim={r['score']:.3f}]\n"
                f"理由: {r.get('reason') or ''}\n"
                f"内容: {r.get('content') or ''}"
            )
            contexts_full.append(ctx)

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deal_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "top_k": top_k,
                "candidates": len(rows),
                "okng_filter": okng_filter,
                "intent_reason": intent_reason,
            },
        )
