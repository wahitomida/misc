"""R06: LightRAG Hybrid - HKUDS 2024.

Dual-level (low-level 具体エンティティ + high-level 抽象テーマ) キーワード抽出 + Graph 探索.
Vector を使わず Fulltext と Graph のみで検索.
"""
from __future__ import annotations

import json
import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.lucene import sanitize_lucene
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


KEYWORD_EXTRACT_SYSTEM = (
    "あなたはセンサ商談検索のためのキーワード抽出器です. "
    "ユーザの質問から以下 2 種類のキーワードを抽出して JSON で返してください.\n"
    " - low_level_keywords: 具体名詞 (機器名・センサ名・ワーク名・工程名など). 例: 'ZP-L', 'レーザー変位センサ', 'ウェハ'.\n"
    " - high_level_keywords: 抽象テーマ (傾向・条件・課題). 例: 'OK傾向', '境界条件', '高温環境'.\n"
    "出力フォーマット: {\"low_level_keywords\": [...], \"high_level_keywords\": [...]}"
)


_Q_LOW_LEVEL = """
CALL db.index.fulltext.queryNodes($idx, $kw) YIELD node, score
WHERE score > $min_score
WITH node, score LIMIT $entity_limit
MATCH (node)<-[r]-(c:Cluster)
WHERE type(r) IN ['USES_EQUIPMENT', 'HAS_PROCESS', 'TARGETS_WORKPIECE']
MATCH (c)<-[:BELONGS_TO_CLUSTER]-(d:Deal)
WHERE coalesce(d.in_catchall_cluster, false) = false
WITH labels(node)[0] AS entity_type, node.name AS entity_name,
     d.deal_id AS deal_id, d.okng AS okng, d.okng_reason AS reason,
     d.content AS content, score
RETURN entity_type, entity_name, deal_id, okng, reason, content, score
ORDER BY score DESC LIMIT $deal_limit
"""


_Q_HIGH_LEVEL = """
CALL db.index.fulltext.queryNodes('cluster_objective_fulltext', $kw) YIELD node AS c, score
WHERE score > $min_score AND coalesce(c.is_catchall, false) = false
WITH c, score ORDER BY score DESC LIMIT $cluster_limit
OPTIONAL MATCH (c)-[:CLUSTER_OK_TENDENCY]->(ok:OKTendency)
OPTIONAL MATCH (c)-[:CLUSTER_NG_TENDENCY]->(ng:NGTendency)
OPTIONAL MATCH (c)-[:CLUSTER_BOUNDARY]->(b:Boundary)
OPTIONAL MATCH (c)<-[:BELONGS_TO_CLUSTER]-(d:Deal)
WITH c, ok, ng, b, score, collect(d)[0..$deal_limit] AS deals
UNWIND deals AS d
RETURN c.cluster_id AS cluster_id, c.objective AS objective,
       ok.segment_level AS ok_tendency, ng.segment_level AS ng_tendency,
       b.okng_boundary AS boundary,
       d.deal_id AS deal_id, d.okng AS okng, d.content AS content, score
"""


class LightRAGHybridRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R06"

    @property
    def method_name(self) -> str:
        return "LightRAG Hybrid"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        min_score = float(self.config.get("fulltext_min_score", 1.0))
        entity_limit = int(self.config.get("max_entities_per_keyword", 5))
        deal_limit = int(self.config.get("max_deals_per_entity", 3))

        # Step 1: Dual-level キーワード抽出
        try:
            kw_result = self.llm.chat(
                KEYWORD_EXTRACT_SYSTEM,
                f"質問: {query}\n\nキーワードを抽出してください.",
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(kw_result.text)
            low_keywords = [k for k in parsed.get("low_level_keywords", []) if k][:8]
            high_keywords = [k for k in parsed.get("high_level_keywords", []) if k][:8]
        except Exception as e:  # noqa: BLE001
            logger.warning("キーワード抽出失敗: %s", e)
            low_keywords, high_keywords = [], []

        # Step 2: Low-level Search (Equipment / Process / Workpiece fulltext → Deal)
        low_deal_score: dict[int, float] = {}
        low_contexts: list[tuple[int, str]] = []
        for kw in low_keywords:
            safe_kw = sanitize_lucene(kw)
            for idx in ("equipment_name_fulltext", "process_name_fulltext", "workpiece_name_fulltext"):
                try:
                    rows = self.neo4j.run_read(
                        _Q_LOW_LEVEL, idx=idx, kw=safe_kw,
                        min_score=min_score, entity_limit=entity_limit, deal_limit=deal_limit,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("low-level fulltext 失敗 kw=%s idx=%s: %s", kw, idx, e)
                    continue
                for r in rows:
                    did = int(r["deal_id"])
                    low_deal_score[did] = low_deal_score.get(did, 0.0) + float(r["score"])
                    if did not in {d for d, _ in low_contexts}:
                        low_contexts.append((did, (
                            f"[LowLevel: {r['entity_type']}='{r['entity_name']}' kw='{kw}' score={r['score']:.2f}]\n"
                            f"Deal#{did} {r['okng']}\n"
                            f"理由: {r.get('reason') or ''}\n"
                            f"内容: {(r.get('content') or '')[:600]}"
                        )))

        # Step 3: High-level Search (Cluster objective fulltext → Cluster + Deal)
        high_deal_score: dict[int, float] = {}
        high_contexts: list[tuple[int, str]] = []
        for kw in high_keywords:
            safe_kw = sanitize_lucene(kw)
            try:
                rows = self.neo4j.run_read(
                    _Q_HIGH_LEVEL, kw=safe_kw, min_score=min_score,
                    cluster_limit=entity_limit, deal_limit=deal_limit,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("high-level fulltext 失敗 kw=%s: %s", kw, e)
                continue
            for r in rows:
                did = int(r["deal_id"]) if r["deal_id"] is not None else None
                if did is None:
                    continue
                high_deal_score[did] = high_deal_score.get(did, 0.0) + float(r["score"])
                high_contexts.append((did, (
                    f"[HighLevel: Cluster {r['cluster_id']} kw='{kw}' score={r['score']:.2f}]\n"
                    f"目的: {(r.get('objective') or '')[:300]}\n"
                    f"OK 傾向: {(r.get('ok_tendency') or '')[:200]}\n"
                    f"NG 傾向: {(r.get('ng_tendency') or '')[:200]}\n"
                    f"境界: {(r.get('boundary') or '')[:200]}\n"
                    f"Deal#{did} {r['okng']}: {(r.get('content') or '')[:300]}"
                )))

        # Step 4: Merge & Dedup (両方ヒットでブースト)
        merged_score: dict[int, float] = {}
        for did, sc in low_deal_score.items():
            merged_score[did] = merged_score.get(did, 0.0) + sc
        for did, sc in high_deal_score.items():
            merged_score[did] = merged_score.get(did, 0.0) + sc * 1.5  # high をやや強め
        # 両方ヒットには追加ボーナス
        for did in set(low_deal_score) & set(high_deal_score):
            merged_score[did] += 2.0

        sorted_ids = sorted(merged_score.items(), key=lambda x: x[1], reverse=True)

        # 優先順に contexts を再構築 (重複除去)
        ctx_by_did: dict[int, list[str]] = {}
        for did, ctx in low_contexts + high_contexts:
            ctx_by_did.setdefault(did, []).append(ctx)

        ordered_contexts: list[str] = []
        ordered_deal_ids: list[int] = []
        for did, _sc in sorted_ids:
            for c in ctx_by_did.get(did, []):
                ordered_contexts.append(c)
            ordered_deal_ids.append(did)

        contexts, tokens = pack_contexts_within_budget(ordered_contexts, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=ordered_deal_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "low_keywords": low_keywords,
                "high_keywords": high_keywords,
                "low_hits": len(low_deal_score),
                "high_hits": len(high_deal_score),
                "overlap": len(set(low_deal_score) & set(high_deal_score)),
            },
        )
