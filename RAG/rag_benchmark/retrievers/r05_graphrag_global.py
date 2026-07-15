"""R05: GraphRAG Global Search - Microsoft Research 2024 (軽量化版).

軽量化のポイント:
  1. Vector による事前フィルタで関連候補 Cluster のみ Map (全件評価は廃止)
  2. Bulk Map: 1 LLM call で複数 Community をまとめて評価 → API call 数を 1/N に削減
  3. catchall Cluster は除外

フロー:
  Step 1. catchall でない全 Cluster の objective+process+challenge を embedding 化 (1 batch call)
  Step 2. query との cosine 上位 N 件のみ抽出
  Step 3. Bulk Map: 候補を bulk_size ごとにまとめ、1 LLM call で複数 Community を評価
  Step 4. relevance ≥ threshold の summary を contexts に積む (Reduce)
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


BULK_MAP_SYSTEM = (
    "あなたは商談コミュニティの関連度評価器です. ユーザ質問に対し、与えられた複数の Community サマリそれぞれを"
    "  - relevance: 0-100 で評価\n"
    "  - summary: 関連する場合のみ 200 字以内で要約 (関連無しなら空文字列)\n"
    "の形式で評価してください.\n"
    "出力は厳密な JSON: {\"items\": [{\"community_id\": \"<id>\", \"relevance\": <int>, \"summary\": \"<text>\"}, ...]}"
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# =============================================================================
# Cluster Embedding キャッシュ (クラス変数 + ファイル永続化)
# =============================================================================
_CACHE_LOCK = threading.Lock()


def _load_cluster_cache(cache_path: Path) -> dict[str, list[float]] | None:
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("cluster cache 読み込み失敗: %s", e)
        return None


def _save_cluster_cache(cache_path: Path, cache: dict[str, list[float]]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        logger.info("cluster cache 保存: %s (%d entries)", cache_path, len(cache))
    except Exception as e:  # noqa: BLE001
        logger.warning("cluster cache 保存失敗: %s", e)


class GraphRAGGlobalRetriever(BaseRetriever):
    # クラス変数キャッシュ (プロセス内全インスタンスで共有)
    _cluster_embedding_cache: dict[str, list[float]] | None = None

    @property
    def method_id(self) -> str:
        return "R05"

    @property
    def method_name(self) -> str:
        return "GraphRAG Global"

    def _get_cluster_embeddings(self, rows: list[dict]) -> list[list[float]]:
        """rows の community_id 順に Embedding を返す.

        クラス変数キャッシュ → ファイル → 計算 + 保存 の順に解決.
        新規 Cluster (キャッシュにない) があれば差分のみ embed_batch.
        """
        cache_path = config.CLUSTER_EMBEDDING_CACHE_FILE

        # クラスキャッシュにロード
        if self.__class__._cluster_embedding_cache is None:
            with _CACHE_LOCK:
                if self.__class__._cluster_embedding_cache is None:
                    loaded = _load_cluster_cache(cache_path)
                    self.__class__._cluster_embedding_cache = loaded if loaded is not None else {}
                    logger.info(
                        "R05 cluster embedding cache 初期化: %d entries",
                        len(self.__class__._cluster_embedding_cache),
                    )

        cache = self.__class__._cluster_embedding_cache
        assert cache is not None

        # キャッシュにない Cluster を抽出
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        for i, r in enumerate(rows):
            cid = str(r["community_id"])
            if cid not in cache:
                text = (
                    f"{r.get('objective') or ''} | "
                    f"{r.get('process') or ''} | "
                    f"{r.get('challenge') or ''}"
                )
                missing_indices.append(i)
                missing_texts.append(text)

        # 差分のみ embed_batch
        if missing_texts:
            logger.info("R05 cluster embedding 差分計算: %d 件", len(missing_texts))
            new_embeddings: list[list[float]] = []
            BATCH = 100
            for j in range(0, len(missing_texts), BATCH):
                new_embeddings.extend(self.llm.embed_batch(missing_texts[j : j + BATCH]))
            with _CACHE_LOCK:
                for idx, emb in zip(missing_indices, new_embeddings):
                    cid = str(rows[idx]["community_id"])
                    cache[cid] = emb
                _save_cluster_cache(cache_path, cache)

        # rows 順に整列
        return [cache[str(r["community_id"])] for r in rows]

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        max_communities = int(self.config.get("max_communities", 60))
        bulk_size = int(self.config.get("bulk_map_size", 10))
        map_concurrency = int(self.config.get("map_concurrency", 2))
        threshold = float(self.config.get("relevance_threshold", 30))

        # ===== Step 1: 全 Cluster サマリ取得 (catchall 除外) =====
        rows = self.neo4j.run_read(
            "MATCH (c:Cluster) WHERE coalesce(c.is_catchall, false) = false "
            "OPTIONAL MATCH (c)-[:IN_SEGMENT]->(s:Segment) "
            "RETURN c.cluster_id AS community_id, c.objective AS objective, "
            "       c.process AS process, c.challenge AS challenge, "
            "       c.equipment AS equipment, c.dominant_okng AS okng, "
            "       s.name AS segment"
        )
        if not rows:
            return RetrievalResult([], [], (time.perf_counter() - t0) * 1000.0, 0,
                                   {"communities_total": 0})

        # ===== Step 2: Vector 事前フィルタで上位 max_communities のみ =====
        # ※ Cluster Embedding はキャッシュ化 (config.CLUSTER_EMBEDDING_CACHE_FILE)
        qvec = self.llm.embed(query)
        embeddings = self._get_cluster_embeddings(rows)
        scored: list[tuple[float, dict]] = []
        for emb, r in zip(embeddings, rows):
            scored.append((_cosine(qvec, emb), r))
        scored.sort(key=lambda x: x[0], reverse=True)
        candidates = [r for _, r in scored[:max_communities]]

        # ===== Step 3: Bulk Map (並列) =====
        def _bulk_map(chunk: list[dict]) -> list[dict]:
            block = "\n\n".join(
                f"[community_id={r['community_id']}]\n"
                f"Segment: {r.get('segment') or '?'} / OKNG: {r.get('okng') or '?'}\n"
                f"目的: {(r.get('objective') or '')[:160]}\n"
                f"工程: {(r.get('process') or '')[:120]}\n"
                f"機器: {(r.get('equipment') or '')[:80]}\n"
                f"課題: {(r.get('challenge') or '')[:120]}"
                for r in chunk
            )
            user_prompt = (
                f"質問: {query}\n\n以下 {len(chunk)} 件の Community について、関連度と要約を JSON で返してください.\n\n{block}"
            )
            try:
                result = self.llm.chat(
                    BULK_MAP_SYSTEM, user_prompt, temperature=0.0,
                    response_format={"type": "json_object"},
                )
                parsed = json.loads(result.text).get("items", [])
                return [
                    {
                        "community_id": str(e.get("community_id", "")),
                        "relevance": float(e.get("relevance", 0)),
                        "summary": str(e.get("summary", ""))[:300],
                        "tokens": result.input_tokens + result.output_tokens,
                    }
                    for e in parsed
                ]
            except Exception as ex:  # noqa: BLE001
                logger.warning("bulk_map 失敗 (%d 件): %s", len(chunk), ex)
                return [{"community_id": str(r["community_id"]), "relevance": 0.0, "summary": "", "tokens": 0}
                        for r in chunk]

        chunks = [candidates[i : i + bulk_size] for i in range(0, len(candidates), bulk_size)]
        relevance_map: dict[str, dict] = {}
        map_calls = 0
        map_total_tokens = 0
        with ThreadPoolExecutor(max_workers=map_concurrency) as ex:
            futures = [ex.submit(_bulk_map, c) for c in chunks]
            for fut in as_completed(futures):
                items = fut.result()
                map_calls += 1
                if items:
                    map_total_tokens += items[0]["tokens"]
                for item in items:
                    cid = item["community_id"]
                    if cid:
                        relevance_map[cid] = item

        # ===== Step 4: Reduce (関連度降順で contexts に詰める) =====
        relevant: list[tuple[dict, dict]] = []
        cand_map = {r["community_id"]: r for r in candidates}
        for cid, scored_item in relevance_map.items():
            if scored_item["relevance"] >= threshold and cid in cand_map:
                relevant.append((cand_map[cid], scored_item))
        relevant.sort(key=lambda x: x[1]["relevance"], reverse=True)

        contexts_full: list[str] = []
        for r, sc in relevant:
            contexts_full.append(
                f"[Community {r['community_id']} rel={sc['relevance']:.0f}]\n"
                f"Segment: {r.get('segment') or '?'} / OKNG: {r.get('okng') or '?'}\n"
                f"要約: {sc['summary']}\n"
                f"目的: {(r.get('objective') or '')[:200]}\n"
                f"工程: {(r.get('process') or '')[:200]}"
            )

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=[],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "communities_total": len(rows),
                "candidates_after_vector_filter": len(candidates),
                "relevant_communities": len(relevant),
                "bulk_size": bulk_size,
                "bulk_map_calls": map_calls,
                "map_total_tokens": map_total_tokens,
                "threshold": threshold,
            },
        )
