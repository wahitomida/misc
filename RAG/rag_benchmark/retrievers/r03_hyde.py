"""R03: HyDE (Hypothetical Document Embeddings) - Gao et al. 2023.

クエリから仮想回答を LLM で生成し、その埋め込みで検索する.
クエリ (短文) と文書 (長文) の埋め込み空間ギャップを解消.
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


HYDE_SYSTEM = (
    "あなたはセンサ商談分析の専門家です. 与えられた質問に対する理想的な回答を"
    "商談分析レポートの形式で簡潔に書いてください. 具体的なセンサ名 (ZP-L 等)、"
    "工程名、機器名、ワーク種別、OK/NG 判定理由を含めてください. 150-250 字程度の簡潔な記述にとどめてください."
)


class HyDERetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R03"

    @property
    def method_name(self) -> str:
        return "HyDE"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        top_k = int(self.config.get("search_top_k", 10))
        max_tokens = int(self.config.get("hyde_max_tokens", 400))

        # Step 1: 仮想回答生成 (最大生成トークンを明示的に制限してレイテンシ削減)
        hypo = self.llm.chat(
            HYDE_SYSTEM,
            f"質問: {query}\n\n上記に対する理想的な商談分析レポート (最大 {max_tokens} 字、簡潔に):",
            temperature=0.3,
            max_tokens=max_tokens,
        )
        hypo_text = hypo.text.strip()

        # Step 2: 仮想回答を Embedding
        qvec = self.llm.embed(hypo_text)

        # Step 3: Vector 検索
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
            contexts_full.append(
                f"[Deal#{r['deal_id']} {r['okng']} sim={r['score']:.3f}]\n"
                f"理由: {r.get('reason') or ''}\n"
                f"内容: {r.get('content') or ''}"
            )

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deal_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "hypothetical_doc": hypo_text,
                "hypo_input_tokens": hypo.input_tokens,
                "hypo_output_tokens": hypo.output_tokens,
            },
        )
