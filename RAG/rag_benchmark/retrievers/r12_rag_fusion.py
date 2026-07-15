"""R12: RAG-Fusion (Multi-Query + Reciprocal Rank Fusion).

Raudaschl (2024) "Forget RAG, the Future is RAG-Fusion"

クエリを 4 つに多角化 → 元 + 変形 5 クエリで各々 Vector 検索 → RRF で統合.
Global 質問で多角的な情報網羅を狙う.
ENABLE_OKNG_FILTER=True なら OK/NG フィルタも適用.
"""
from __future__ import annotations

import json
import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.query_analyzer import analyze_query_intent
from ..utils.rrf import reciprocal_rank_fusion
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


MULTI_QUERY_SYSTEM = (
    "あなたは検索クエリの多角化器です. ユーザの元クエリを 4 つの異なるバリエーションに言い換えてください.\n"
    "各バリエーションは:\n"
    "  - 元の意図を保持しつつ\n"
    "  - 異なる語彙・表現を使い\n"
    "  - 異なる側面 (具体例 / 抽象的傾向 / 条件 / 反対視点など) にフォーカス\n"
    "JSON で返してください: {\"queries\": [\"<q1>\", \"<q2>\", \"<q3>\", \"<q4>\"]}"
)


class RAGFusionRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R12"

    @property
    def method_name(self) -> str:
        return "RAG-Fusion"

    def _generate_query_variants(self, query: str, n: int) -> list[str]:
        try:
            result = self.llm.chat(
                MULTI_QUERY_SYSTEM,
                f"元クエリ: {query}\n\n{n} 個のバリエーションを生成してください.",
                temperature=0.5,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(result.text)
            variants = [str(q).strip() for q in parsed.get("queries", []) if q]
            return variants[:n]
        except Exception as e:  # noqa: BLE001
            logger.warning("R12 variant 生成失敗: %s", e)
            return []

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        num_variants = int(self.config.get("num_variants", 4))
        per_query_k = int(self.config.get("per_query_top_k", 10))
        rrf_k = int(self.config.get("rrf_k", 60))
        final_k = int(self.config.get("final_top_k", 15))

        # OK/NG フィルタ意図検出
        okng_filter: str | None = None
        intent_reason = ""
        if config.ENABLE_OKNG_FILTER:
            intent = analyze_query_intent(self.llm, query)
            if intent["okng_filter"] in ("OK", "NG"):
                okng_filter = intent["okng_filter"]
            intent_reason = intent["reason"]

        # Step 1: Multi-query 生成
        variants = self._generate_query_variants(query, num_variants)
        all_queries = [query] + variants  # 元 + バリエーション

        # Step 2: 各クエリで Vector 検索
        all_rankings: list[list[int]] = []
        per_query_hits: list[int] = []
        for q in all_queries:
            qvec = self.llm.embed(q)
            if okng_filter:
                rows = self.neo4j.run_read(
                    "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                    "YIELD node, score WHERE node.okng = $okng "
                    "RETURN node.deal_id AS deal_id ORDER BY score DESC LIMIT $limit",
                    k=per_query_k * 3, q=qvec, okng=okng_filter, limit=per_query_k,
                )
            else:
                rows = self.neo4j.run_read(
                    "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                    "YIELD node, score "
                    "RETURN node.deal_id AS deal_id ORDER BY score DESC",
                    k=per_query_k, q=qvec,
                )
            ranking = [int(r["deal_id"]) for r in rows]
            all_rankings.append(ranking)
            per_query_hits.append(len(ranking))

        # Step 3: RRF 統合
        fused = reciprocal_rank_fusion(all_rankings, k=rrf_k)
        top_ids = [int(did) for did, _ in fused[:final_k]]

        if not top_ids:
            return RetrievalResult(
                contexts=[], source_deal_ids=[],
                retrieval_time_ms=(time.perf_counter() - t0) * 1000.0,
                context_token_count=0,
                metadata={
                    "original_query": query,
                    "variant_queries": variants,
                    "per_query_hits": per_query_hits,
                    "okng_filter": okng_filter,
                    "intent_reason": intent_reason,
                },
            )

        # Step 4: Deal 詳細取得
        rows = self.neo4j.run_read(
            "MATCH (d:Deal) WHERE d.deal_id IN $ids "
            "RETURN d.deal_id AS deal_id, d.okng AS okng, "
            "       d.okng_reason AS reason, d.content AS content",
            ids=top_ids,
        )
        row_by_id = {int(r["deal_id"]): r for r in rows}

        contexts_full: list[str] = []
        ordered_ids: list[int] = []
        rrf_top_dict = dict(fused[:final_k])
        for did in top_ids:
            r = row_by_id.get(did)
            if not r:
                continue
            ordered_ids.append(did)
            score = rrf_top_dict.get(did, 0.0)
            contexts_full.append(
                f"[Deal#{did} {r['okng']} RRF={score:.4f}]\n"
                f"理由: {r.get('reason') or ''}\n"
                f"内容: {r.get('content') or ''}"
            )

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=ordered_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "original_query": query,
                "variant_queries": variants,
                "per_query_hits": per_query_hits,
                "total_candidates_dedup": len(fused),
                "rrf_top_scores": [(d, round(s, 4)) for d, s in fused[:5]],
                "okng_filter": okng_filter,
                "intent_reason": intent_reason,
            },
        )
