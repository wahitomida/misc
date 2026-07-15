"""R08: Agentic RAG (Multi-Step Retrieval) - OpenAI / LangGraph 推奨.

LLM が tool 群を自律的に呼び分け、必要なら追加検索を行うパターン.
"""
from __future__ import annotations

import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..tools.search_tools import SearchToolHandler, TOOL_DEFINITIONS
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


AGENT_SYSTEM = """
あなたはセンサ商談ナレッジグラフの検索エージェントです.
ユーザの質問に回答するため、以下の tool を順に呼び出して情報を収集してください.

利用可能な tool:
  - vector_search: クエリ意味的類似で Deal を取得
  - fulltext_search: キーワード全文検索 (deal/cluster/equipment/process/workpiece の各 fulltext index)
  - graph_traverse: 起点ノードから 1-2 ホップで関連ノードを取得
  - get_cluster_summary: Cluster の目的・工程・OK/NG 傾向を取得
  - finish: 最終回答を生成

戦略のヒント:
  1. まず vector_search または fulltext_search で関連 Deal/Cluster を粗く取得
  2. 結果から関連の高い Cluster を選び、get_cluster_summary で深掘り
  3. 不足があれば graph_traverse で隣接ノードを追加取得
  4. 十分集まったら finish を呼び、final_answer に回答を渡す

最大 7 回まで tool を呼べます. 質問に直結する情報を効率よく集めてください.
同じ deal_id を再取得しないよう、検索済みノードと未取得側を意識して呼び分けてください.
""".strip()


class AgenticRAGRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R08"

    @property
    def method_name(self) -> str:
        return "Agentic RAG"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        max_iter = int(self.config.get("max_tool_calls", 5))

        handler = SearchToolHandler(self.neo4j, self.llm)
        chat_result, tool_log = self.llm.chat_with_tools_loop(
            system_prompt=AGENT_SYSTEM,
            user_prompt=f"質問: {query}\n\n上記の質問に答えるために検索してください.",
            tools=TOOL_DEFINITIONS,
            tool_handler=handler,
            max_iterations=max_iter,
        )

        # Agent が finish を呼んだ場合、回答テキストは chat_result.text に入っている.
        # 本 Retriever はあくまで「コンテキスト + 参照 deal_ids」を返す位置付け.
        # Agent が組み立てたコンテキスト (collected_contexts) を deal_id ベースで dedup して contexts として返す.
        seen_did: set[int] = set()
        deduped_contexts: list[str] = []
        deduped_deal_ids: list[int] = []
        for ctx, did in zip(handler.collected_contexts, handler.collected_deal_ids):
            if did in seen_did:
                continue
            seen_did.add(did)
            deduped_contexts.append(ctx)
            deduped_deal_ids.append(did)
        # Deal 紐付けのない補助 context (Cluster サマリ等) も保持
        for ctx in handler.collected_contexts[len(handler.collected_deal_ids):]:
            deduped_contexts.append(ctx)
        contexts, tokens = pack_contexts_within_budget(
            deduped_contexts, config.CONTEXT_MAX_TOKENS,
        )
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deduped_deal_ids,
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "tool_calls": tool_log,
                "loop_count": len(tool_log),
                "agent_input_tokens": chat_result.input_tokens,
                "agent_output_tokens": chat_result.output_tokens,
                "agent_final_text_preview": (chat_result.text or "")[:500],
                "raw_collected_count": len(handler.collected_contexts),
                "unique_deal_count": len(deduped_deal_ids),
            },
        )
