"""R04: GraphRAG Local Search - Microsoft Research 2024.

Vector seed → 2 ホップ サブグラフ展開 → Context Window Packing (優先度順).
ENABLE_OKNG_FILTER=True なら seed Deal 取得段階で OK/NG フィルタを適用.
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.query_analyzer import analyze_query_intent
from ..utils.token_counter import count_tokens, pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


_Q_EXPAND = """
MATCH (d:Deal {deal_id: $seed_id})-[:BELONGS_TO_CLUSTER]->(c:Cluster)
OPTIONAL MATCH (c)-[:IN_SEGMENT]->(s:Segment)
OPTIONAL MATCH (c)-[:CLUSTER_OK_TENDENCY]->(ok:OKTendency)
OPTIONAL MATCH (c)-[:CLUSTER_NG_TENDENCY]->(ng:NGTendency)
OPTIONAL MATCH (c)-[:CLUSTER_BOUNDARY]->(b:Boundary)
OPTIONAL MATCH (c)-[:HAS_PROCESS]->(p:Process)
OPTIONAL MATCH (c)-[:USES_EQUIPMENT]->(e:Equipment)
OPTIONAL MATCH (c)-[:TARGETS_WORKPIECE]->(w:Workpiece)
WITH d, c, s, ok, ng, b,
     collect(DISTINCT p.name)[0..5] AS processes,
     collect(DISTINCT e.name)[0..5] AS equipments,
     collect(DISTINCT w.name)[0..5] AS workpieces
OPTIONAL MATCH (c)<-[:BELONGS_TO_CLUSTER]-(sib:Deal)
WHERE sib.deal_id <> $seed_id
WITH d, c, s, ok, ng, b, processes, equipments, workpieces,
     collect(DISTINCT sib.content)[0..$sib_limit] AS sibling_contents
RETURN d.content AS deal_content,
       d.okng AS okng,
       d.okng_reason AS okng_reason,
       c.cluster_id AS cluster_id,
       c.objective AS cluster_objective,
       c.challenge AS cluster_challenge,
       s.name AS segment,
       ok.deal_level AS ok_tendency,
       ng.deal_level AS ng_tendency,
       b.okng_boundary AS boundary,
       processes, equipments, workpieces, sibling_contents
"""


class GraphRAGLocalRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R04"

    @property
    def method_name(self) -> str:
        return "GraphRAG Local"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        seed_k = int(self.config.get("seed_k", 5))
        min_score = float(self.config.get("min_score", 0.3))
        sib_limit = int(self.config.get("sibling_per_seed", 3))

        # OK/NG フィルタ意図検出
        okng_filter: str | None = None
        intent_reason = ""
        if config.ENABLE_OKNG_FILTER:
            intent = analyze_query_intent(self.llm, query)
            if intent["okng_filter"] in ("OK", "NG"):
                okng_filter = intent["okng_filter"]
            intent_reason = intent["reason"]

        # Step 1: Vector で seed Deal 取得
        qvec = self.llm.embed(query)
        if okng_filter:
            seeds = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score WHERE score > $min AND node.okng = $okng "
                "RETURN node.deal_id AS deal_id, score ORDER BY score DESC LIMIT $limit",
                k=seed_k * 3, q=qvec, min=min_score, okng=okng_filter, limit=seed_k,
            )
        else:
            seeds = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score WHERE score > $min "
                "RETURN node.deal_id AS deal_id, score ORDER BY score DESC",
                k=seed_k, q=qvec, min=min_score,
            )

        # 各 seed から 2 ホップ展開して 優先度別バケットに格納
        bucket_p1: list[tuple[int, str]] = []  # seed Deal + okng_reason
        bucket_p2: list[tuple[int, str]] = []  # Cluster objective + challenge
        bucket_p3: list[tuple[int, str]] = []  # OKTendency / NGTendency
        bucket_p4: list[tuple[int, str]] = []  # Boundary
        bucket_p5: list[tuple[int, str]] = []  # sibling Deal contents
        bucket_p6: list[tuple[int, str]] = []  # Equipment + Process
        seen_clusters: set[str] = set()

        subgraph_node_count = 0
        for seed in seeds:
            seed_id = int(seed["deal_id"])
            rows = self.neo4j.run_read(_Q_EXPAND, seed_id=seed_id, sib_limit=sib_limit)
            if not rows:
                continue
            r = rows[0]
            cid = r["cluster_id"]
            bucket_p1.append((seed_id, (
                f"[Seed Deal#{seed_id} {r['okng']} sim={seed['score']:.3f}]\n"
                f"理由: {r['okng_reason'] or ''}\n"
                f"内容: {(r['deal_content'] or '')[:1500]}"
            )))
            subgraph_node_count += 1
            # Cluster は同一 seed 群で重複しうるので 1 度だけ
            if cid not in seen_clusters:
                seen_clusters.add(cid)
                if r["cluster_objective"] or r["cluster_challenge"]:
                    bucket_p2.append((seed_id, (
                        f"[Cluster {cid} / Segment {r['segment'] or '?'}]\n"
                        f"目的: {r['cluster_objective'] or ''}\n"
                        f"課題: {r['cluster_challenge'] or ''}"
                    )))
                if r["ok_tendency"] or r["ng_tendency"]:
                    bucket_p3.append((seed_id, (
                        f"[OK/NG 傾向 in {cid}]\n"
                        f"OK 傾向: {r['ok_tendency'] or '-'}\n"
                        f"NG 傾向: {r['ng_tendency'] or '-'}"
                    )))
                if r["boundary"]:
                    bucket_p4.append((seed_id, f"[境界条件 in {cid}]\n{r['boundary']}"))
                if r["sibling_contents"]:
                    sibs = [s for s in (r["sibling_contents"] or []) if s]
                    if sibs:
                        bucket_p5.append((seed_id, (
                            f"[同クラスタ {cid} の類似商談 {len(sibs)} 件]\n" +
                            "\n  - ".join("" if i else "" for i in range(0)) +
                            "\n".join(f"  - {(s or '')[:400]}" for s in sibs)
                        )))
                if r["processes"] or r["equipments"] or r["workpieces"]:
                    bucket_p6.append((seed_id, (
                        f"[Cluster {cid} 横断軸]\n"
                        f"Process: {', '.join(r['processes'] or [])}\n"
                        f"Equipment: {', '.join(r['equipments'] or [])}\n"
                        f"Workpiece: {', '.join(r['workpieces'] or [])}"
                    )))

        # 優先度順で context を flatten
        ordered: list[str] = []
        deal_ids_order: list[int] = []
        for bucket in (bucket_p1, bucket_p2, bucket_p3, bucket_p4, bucket_p5, bucket_p6):
            for did, ctx in bucket:
                ordered.append(ctx)
                if did not in deal_ids_order:
                    deal_ids_order.append(did)

        contexts, tokens = pack_contexts_within_budget(ordered, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deal_ids_order,
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "seed_deals": [int(s["deal_id"]) for s in seeds],
                "subgraph_seed_count": subgraph_node_count,
                "clusters_visited": len(seen_clusters),
                "bucket_sizes": {
                    "p1_seed": len(bucket_p1),
                    "p2_cluster": len(bucket_p2),
                    "p3_tendency": len(bucket_p3),
                    "p4_boundary": len(bucket_p4),
                    "p5_sibling": len(bucket_p5),
                    "p6_horizontal": len(bucket_p6),
                },
                "okng_filter": okng_filter,
                "intent_reason": intent_reason,
            },
        )
