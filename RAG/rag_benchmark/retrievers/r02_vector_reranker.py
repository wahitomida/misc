"""R02: Vector + LLM Reranker.

Vector で Top-50 を粗く取得 → LLM で関連度 0-10 にスコアリング → Top-5 を採用.
"""
from __future__ import annotations

import json
import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


RERANK_SYSTEM = (
    "あなたは検索リランカーです. ユーザの質問に対して、各候補文書の関連度を 0〜10 の整数で評価し、"
    "JSON 形式 {\"scores\": [{\"id\": <doc_id>, \"score\": <0-10>}, ...]} で返してください."
)


class VectorRerankerRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R02"

    @property
    def method_name(self) -> str:
        return "Vector + Reranker"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        initial_k = int(self.config.get("initial_top_k", 50))
        rerank_k = int(self.config.get("rerank_top_k", 5))
        batch = int(self.config.get("rerank_batch_size", 10))

        qvec = self.llm.embed(query)

        # Step 1: 粗く 50 件取得
        rows = self.neo4j.run_read(
            "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
            "YIELD node, score "
            "RETURN node.deal_id AS deal_id, node.okng AS okng, "
            "       node.okng_reason AS reason, node.content AS content, score",
            k=initial_k, q=qvec,
        )
        if not rows:
            return RetrievalResult([], [], (time.perf_counter() - t0) * 1000.0, 0, {"candidates": 0})

        # Step 2: バッチで Rerank
        rerank_scores: dict[int, float] = {}
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            docs_block = "\n\n".join(
                f"[doc_id={int(r['deal_id'])}] {(r.get('content') or '')[:500]}"
                for r in chunk
            )
            user_prompt = (
                f"質問: {query}\n\n候補文書:\n{docs_block}\n\n"
                f"各 doc_id について 0-10 の関連度スコアを JSON で返してください."
            )
            try:
                result = self.llm.chat(
                    RERANK_SYSTEM, user_prompt, temperature=0.0,
                    response_format={"type": "json_object"},
                )
                parsed = json.loads(result.text)
                for entry in parsed.get("scores", []):
                    did = int(entry["id"])
                    rerank_scores[did] = float(entry["score"])
            except Exception as e:  # noqa: BLE001
                logger.warning("rerank バッチ失敗: %s", e)

        # Step 3: rerank スコア上位 K を採用
        sorted_ids = sorted(rerank_scores.items(), key=lambda x: x[1], reverse=True)[:rerank_k]
        chosen_ids = [d for d, _ in sorted_ids]
        id_to_row = {int(r["deal_id"]): r for r in rows}

        contexts_full: list[str] = []
        for did in chosen_ids:
            r = id_to_row.get(did)
            if not r:
                continue
            score = rerank_scores.get(did, 0.0)
            contexts_full.append(
                f"[Deal#{did} {r['okng']} rerank={score:.1f}]\n"
                f"理由: {r.get('reason') or ''}\n"
                f"内容: {r.get('content') or ''}"
            )

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=chosen_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "initial_candidates": len(rows),
                "reranked": len(rerank_scores),
                "rerank_scores": sorted_ids,
            },
        )
