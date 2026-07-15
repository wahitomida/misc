"""R09: RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval).

Sarthi et al. ICLR 2024.

我々のグラフは既に3層構造をもつため、構築フェーズ不要:
  Level 0 (Leaf) : Deal.content        → Vector 検索 (filter なし or OK/NG フィルタ)
  Level 1 (Mid)  : Cluster.objective   → Fulltext 検索 (catchall 除外)
  Level 2 (Root) : Segment 集約テキスト → Fulltext 検索 (catchall 除外)

統合スコア = w0*norm(score_L0) + w1*norm(score_L1) + w2*norm(score_L2)
コンテキスト構造: root → mid → leaf (hierarchical)
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.query_analyzer import analyze_query_intent
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


def _normalize(scores: list[float]) -> list[float]:
    """min-max 正規化. 全部同値なら 1.0 を返す."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def _sanitize_lucene(text: str) -> str:
    special = '+-&|!(){}[]^"~*?:\\/'
    cleaned = "".join(" " if c in special else c for c in text)
    terms = [t for t in cleaned.split() if t and len(t) > 1]
    return " ".join(terms) or text


class RaptorRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R09"

    @property
    def method_name(self) -> str:
        return "RAPTOR"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        k0 = int(self.config.get("top_k_level0", 5))
        k1 = int(self.config.get("top_k_level1", 5))
        k2 = int(self.config.get("top_k_level2", 3))
        w0 = float(self.config.get("weight_level0", 0.5))
        w1 = float(self.config.get("weight_level1", 0.3))
        w2 = float(self.config.get("weight_level2", 0.2))

        # OK/NG フィルタ意図検出
        okng_filter: str | None = None
        intent_reason = ""
        if config.ENABLE_OKNG_FILTER:
            intent = analyze_query_intent(self.llm, query)
            if intent["okng_filter"] in ("OK", "NG"):
                okng_filter = intent["okng_filter"]
            intent_reason = intent["reason"]

        # ========== Level 0: Deal Vector 検索 (OK/NG フィルタ任意) ==========
        qvec = self.llm.embed(query)
        if okng_filter:
            l0_rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score WHERE node.okng = $okng "
                "RETURN node.deal_id AS id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC LIMIT $limit",
                k=k0 * 3, q=qvec, okng=okng_filter, limit=k0,
            )
        else:
            l0_rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score "
                "RETURN node.deal_id AS id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC",
                k=k0, q=qvec,
            )
        l0_norm = _normalize([float(r["score"]) for r in l0_rows])
        level0_items: list[dict] = [
            {
                "id": int(r["id"]),
                "level": 0,
                "raw_score": float(r["score"]),
                "weighted": ns * w0,
                "text": (
                    f"[L0 Deal#{int(r['id'])} {r['okng']} sim={r['score']:.3f} weight={ns * w0:.3f}]\n"
                    f"理由: {r.get('reason') or ''}\n"
                    f"内容: {(r.get('content') or '')[:800]}"
                ),
            }
            for r, ns in zip(l0_rows, l0_norm)
        ]

        # ========== Level 1: Cluster Fulltext 検索 (catchall 除外) ==========
        kw = _sanitize_lucene(query)
        try:
            l1_rows = self.neo4j.run_read(
                "CALL db.index.fulltext.queryNodes('cluster_objective_fulltext', $kw) "
                "YIELD node AS c, score "
                "WHERE coalesce(c.is_catchall, false) = false "
                "WITH DISTINCT c, score "
                "OPTIONAL MATCH (c)-[:CLUSTER_OK_TENDENCY]->(ok:OKTendency) "
                "OPTIONAL MATCH (c)-[:CLUSTER_NG_TENDENCY]->(ng:NGTendency) "
                "OPTIONAL MATCH (c)-[:CLUSTER_BOUNDARY]->(b:Boundary) "
                "RETURN c.cluster_id AS id, c.objective AS objective, "
                "       c.process AS process, c.challenge AS challenge, "
                "       c.dominant_okng AS okng, "
                "       max(ok.segment_level) AS ok_tendency, "
                "       max(ng.segment_level) AS ng_tendency, "
                "       max(b.okng_boundary) AS boundary, score "
                "ORDER BY score DESC LIMIT $k",
                kw=kw, k=k1,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("L1 fulltext クエリ失敗: %s", e)
            l1_rows = []
        l1_norm = _normalize([float(r["score"]) for r in l1_rows])
        level1_items: list[dict] = [
            {
                "id": str(r["id"]),
                "level": 1,
                "raw_score": float(r["score"]),
                "weighted": ns * w1,
                "text": (
                    f"[L1 Cluster {r['id']} ftsScore={r['score']:.2f} weight={ns * w1:.3f} okng={r['okng']}]\n"
                    f"目的: {(r.get('objective') or '')[:200]}\n"
                    f"工程: {(r.get('process') or '')[:200]}\n"
                    f"課題: {(r.get('challenge') or '')[:200]}\n"
                    f"OK 傾向: {(r.get('ok_tendency') or '')[:200]}\n"
                    f"NG 傾向: {(r.get('ng_tendency') or '')[:200]}\n"
                    f"境界: {(r.get('boundary') or '')[:200]}"
                ),
            }
            for r, ns in zip(l1_rows, l1_norm)
        ]

        # ========== Level 2: Segment 集約 → Fulltext 経由で集計 ==========
        # Segment 自体に fulltext index は無いので、Cluster fulltext のヒットを Segment 別に集計
        segments = self.neo4j.run_read(
            "MATCH (s:Segment)<-[:IN_SEGMENT]-(c:Cluster) "
            "WHERE coalesce(c.is_catchall, false) = false "
            "WITH s.name AS segment, "
            "     collect(c.objective)[0..5] AS objectives, "
            "     collect(DISTINCT c.dominant_okng) AS okngs, "
            "     count(c) AS cluster_count "
            "RETURN segment, objectives, okngs, cluster_count"
        )
        l2_scored: list[dict] = []
        for seg in segments:
            seg_name = seg["segment"]
            if not seg_name:
                continue
            try:
                rows = self.neo4j.run_read(
                    "CALL db.index.fulltext.queryNodes('cluster_objective_fulltext', $kw) "
                    "YIELD node AS c, score "
                    "MATCH (c)-[:IN_SEGMENT]->(s:Segment {name: $seg}) "
                    "WHERE coalesce(c.is_catchall, false) = false "
                    "RETURN sum(score) AS total_score, count(c) AS hit_count",
                    kw=kw, seg=seg_name,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("L2 fulltext クエリ失敗 seg=%s: %s", seg_name, e)
                continue
            if not rows or not rows[0]["total_score"]:
                continue
            l2_scored.append({
                "segment": seg_name,
                "total_score": float(rows[0]["total_score"]),
                "hit_count": int(rows[0]["hit_count"]),
                "objectives": seg["objectives"],
                "okngs": seg["okngs"],
                "cluster_count": seg["cluster_count"],
            })
        l2_scored.sort(key=lambda x: x["total_score"], reverse=True)
        l2_top = l2_scored[:k2]
        l2_norm = _normalize([s["total_score"] for s in l2_top])
        level2_items: list[dict] = [
            {
                "id": s["segment"],
                "level": 2,
                "raw_score": s["total_score"],
                "weighted": ns * w2,
                "text": (
                    f"[L2 Segment '{s['segment']}' fts_total={s['total_score']:.2f} "
                    f"hits={s['hit_count']} weight={ns * w2:.3f}]\n"
                    f"配下 Cluster 数: {s['cluster_count']} / 支配 OKNG: {','.join(s['okngs'])}\n"
                    f"代表目的: " + " / ".join([(o or '')[:80] for o in (s['objectives'] or [])])
                ),
            }
            for s, ns in zip(l2_top, l2_norm)
        ]

        # ========== コンテキスト構造: root → mid → leaf (hierarchical) ==========
        ordered = level2_items + level1_items + level0_items
        ordered_texts = [it["text"] for it in ordered]
        contexts, tokens = pack_contexts_within_budget(ordered_texts, config.CONTEXT_MAX_TOKENS)

        accepted_items = ordered[: len(contexts)]
        deal_ids = [it["id"] for it in accepted_items if it["level"] == 0]

        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deal_ids,
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "level0_hits": [it["id"] for it in level0_items],
                "level1_hits": [it["id"] for it in level1_items],
                "level2_hits": [it["id"] for it in level2_items],
                "level_weights": {"L0": w0, "L1": w1, "L2": w2},
                "accepted_per_level": {
                    "L0": sum(1 for it in accepted_items if it["level"] == 0),
                    "L1": sum(1 for it in accepted_items if it["level"] == 1),
                    "L2": sum(1 for it in accepted_items if it["level"] == 2),
                },
                "context_structure": "hierarchical",
                "okng_filter": okng_filter,
                "intent_reason": intent_reason,
            },
        )
