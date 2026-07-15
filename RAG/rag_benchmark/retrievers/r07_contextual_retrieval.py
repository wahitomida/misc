"""R07: Contextual Retrieval - Anthropic 2024.

Vector + BM25(Fulltext) を Reciprocal Rank Fusion で統合.
さらに各 Deal にクラスタコンテキスト (objective/process/okng) を事前付加.
ENABLE_OKNG_FILTER=True なら Vector / Fulltext 双方で OK/NG フィルタを適用.
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.query_analyzer import analyze_query_intent
from ..utils.rrf import reciprocal_rank_fusion
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


class ContextualRetrievalRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R07"

    @property
    def method_name(self) -> str:
        return "Contextual Retrieval"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        vec_k = int(self.config.get("vector_top_k", 20))
        fts_k = int(self.config.get("fulltext_top_k", 20))
        rrf_k = int(self.config.get("rrf_k", 60))
        final_k = int(self.config.get("final_top_k", 10))

        # OK/NG フィルタ意図検出
        okng_filter: str | None = None
        intent_reason = ""
        if config.ENABLE_OKNG_FILTER:
            intent = analyze_query_intent(self.llm, query)
            if intent["okng_filter"] in ("OK", "NG"):
                okng_filter = intent["okng_filter"]
            intent_reason = intent["reason"]

        # Step 1: Vector 検索 Top-N (OK/NG フィルタ適用)
        qvec = self.llm.embed(query)
        if okng_filter:
            vec_rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score WHERE node.okng = $okng "
                "RETURN node.deal_id AS deal_id, score ORDER BY score DESC LIMIT $limit",
                k=vec_k * 3, q=qvec, okng=okng_filter, limit=vec_k,
            )
        else:
            vec_rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score "
                "RETURN node.deal_id AS deal_id, score ORDER BY score DESC",
                k=vec_k, q=qvec,
            )
        vec_ranking = [int(r["deal_id"]) for r in vec_rows]

        # Step 2: Fulltext (BM25) 検索 Top-N (OK/NG フィルタ適用)
        try:
            if okng_filter:
                fts_rows = self.neo4j.run_read(
                    "CALL db.index.fulltext.queryNodes('deal_content_fulltext', $kw) "
                    "YIELD node, score WHERE node.okng = $okng "
                    "RETURN node.deal_id AS deal_id, score ORDER BY score DESC LIMIT $k",
                    kw=self._sanitize_lucene(query), k=fts_k, okng=okng_filter,
                )
            else:
                fts_rows = self.neo4j.run_read(
                    "CALL db.index.fulltext.queryNodes('deal_content_fulltext', $kw) "
                    "YIELD node, score "
                    "RETURN node.deal_id AS deal_id, score ORDER BY score DESC LIMIT $k",
                    kw=self._sanitize_lucene(query), k=fts_k,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("fulltext クエリ失敗: %s", e)
            fts_rows = []
        fts_ranking = [int(r["deal_id"]) for r in fts_rows]

        # Step 3: RRF で統合
        rrf = reciprocal_rank_fusion([vec_ranking, fts_ranking], k=rrf_k)
        top_ids = [did for did, _ in rrf[:final_k]]

        if not top_ids:
            return RetrievalResult(
                [], [], (time.perf_counter() - t0) * 1000.0, 0,
                {"vector_hits": len(vec_ranking), "fulltext_hits": len(fts_ranking)},
            )

        # Step 4: 文脈付加 (Cluster.objective / process / Deal.okng を prepend)
        rows = self.neo4j.run_read(
            "MATCH (d:Deal) WHERE d.deal_id IN $ids "
            "MATCH (d)-[:BELONGS_TO_CLUSTER]->(c:Cluster) "
            "RETURN d.deal_id AS deal_id, d.content AS content, d.okng AS okng, "
            "       d.okng_reason AS reason, "
            "       c.objective AS objective, c.process AS process, c.cluster_id AS cluster_id",
            ids=top_ids,
        )
        row_by_id = {int(r["deal_id"]): r for r in rows}

        contexts_full: list[str] = []
        ordered_ids: list[int] = []
        for did, score in rrf[:final_k]:
            r = row_by_id.get(int(did))
            if not r:
                continue
            ordered_ids.append(int(did))
            prefix = (
                f"[Cluster: {r['cluster_id']} / objective: {(r.get('objective') or '')[:120]} / "
                f"process: {(r.get('process') or '')[:120]} / okng: {r['okng']}]"
            )
            contexts_full.append(
                f"[Deal#{did} RRF={score:.4f}]\n{prefix}\n"
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
                "vector_hits": len(vec_ranking),
                "fulltext_hits": len(fts_ranking),
                "rrf_top": [(d, round(s, 4)) for d, s in rrf[:final_k]],
                "okng_filter": okng_filter,
                "intent_reason": intent_reason,
            },
        )

    @staticmethod
    def _sanitize_lucene(text: str) -> str:
        """Lucene 構文の特殊文字をエスケープし、空白を OR で結合."""
        special = '+-&|!(){}[]^"~*?:\\/'
        cleaned = "".join(" " if c in special else c for c in text)
        terms = [t for t in cleaned.split() if t and len(t) > 1]
        return " ".join(terms) or text
