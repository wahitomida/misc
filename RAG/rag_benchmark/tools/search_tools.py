"""R08 Agentic RAG 用ツール定義 + ハンドラ."""
from __future__ import annotations

import json
import logging
from typing import Any

from ..utils.llm_client import LLMClient
from ..utils.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "vector_search",
            "description": (
                "クエリテキストに意味的に類似した商談事例を Vector 検索で取得する. "
                "具体的な条件や事例を探す場合に有効."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string", "description": "検索クエリ (日本語)"},
                    "top_k": {"type": "integer", "description": "取得件数", "default": 10},
                },
                "required": ["query_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fulltext_search",
            "description": (
                "キーワードで全文検索する. 特定の製品名・工程名・機器名を含む事例を探す場合に有効."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "検索キーワード"},
                    "index_name": {
                        "type": "string",
                        "enum": [
                            "deal_content_fulltext",
                            "cluster_objective_fulltext",
                            "equipment_name_fulltext",
                            "process_name_fulltext",
                            "workpiece_name_fulltext",
                        ],
                    },
                },
                "required": ["keyword", "index_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graph_traverse",
            "description": (
                "特定ノードから 1〜2 ホップでグラフを辿って関連情報を取得する."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node_label": {
                        "type": "string",
                        "enum": ["Deal", "Cluster", "Equipment", "Process", "Workpiece", "Segment"],
                    },
                    "start_node_key_field": {
                        "type": "string",
                        "description": "起点ノードの一意キー名 (Deal=deal_id, Cluster=cluster_id, それ以外=name)",
                    },
                    "start_node_key_value": {
                        "type": "string",
                        "description": "起点ノードの一意キー値 (Deal は整数文字列, 他は文字列)",
                    },
                    "max_hops": {"type": "integer", "default": 2, "minimum": 1, "maximum": 3},
                },
                "required": ["start_node_label", "start_node_key_field", "start_node_key_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cluster_summary",
            "description": "指定クラスタの目的・工程・機器・課題・OK/NG 傾向のサマリを取得する.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster_id": {"type": "string", "description": "クラスタ ID"},
                },
                "required": ["cluster_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "十分な情報が集まったので最終回答を生成する.",
            "parameters": {
                "type": "object",
                "properties": {
                    "final_answer": {"type": "string", "description": "最終回答テキスト"},
                },
                "required": ["final_answer"],
            },
        },
    },
]


class SearchToolHandler:
    """tool_calls の実行ハンドラ. retrieve した Deal id を蓄積する."""

    def __init__(self, neo4j: Neo4jClient, llm: LLMClient):
        self.neo4j = neo4j
        self.llm = llm
        self.collected_deal_ids: list[int] = []
        self.collected_contexts: list[str] = []

    def __call__(self, name: str, args: dict[str, Any]) -> str:
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
            return handler(args)
        except Exception as e:  # noqa: BLE001
            logger.exception("tool %s failed", name)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ---------------- tools ----------------
    def _tool_vector_search(self, args: dict) -> str:
        query_text = args.get("query_text", "")
        top_k = int(args.get("top_k", 10))
        qvec = self.llm.embed(query_text)
        rows = self.neo4j.run_read(
            "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
            "YIELD node, score "
            "RETURN node.deal_id AS deal_id, node.okng AS okng, "
            "       substring(node.content, 0, 300) AS preview, score",
            k=top_k, q=qvec,
        )
        for r in rows:
            self.collected_deal_ids.append(int(r["deal_id"]))
            self.collected_contexts.append(
                f"[Deal#{r['deal_id']} {r['okng']} sim={r['score']:.3f}]\n{r['preview']}"
            )
        return json.dumps(
            [{"deal_id": int(r["deal_id"]), "okng": r["okng"], "score": round(r["score"], 3),
              "preview": r["preview"]} for r in rows],
            ensure_ascii=False,
        )

    def _tool_fulltext_search(self, args: dict) -> str:
        keyword = args.get("keyword", "")
        index_name = args.get("index_name", "deal_content_fulltext")
        rows = self.neo4j.run_read(
            "CALL db.index.fulltext.queryNodes($idx, $kw) YIELD node, score "
            "RETURN labels(node)[0] AS label, "
            "       coalesce(node.deal_id, node.cluster_id, node.name) AS key, "
            "       coalesce(substring(node.content, 0, 300), node.objective, node.description, '') AS preview, "
            "       score "
            "ORDER BY score DESC LIMIT 10",
            idx=index_name, kw=keyword,
        )
        # Deal を含む結果は collected に追加
        for r in rows:
            if r["label"] == "Deal":
                try:
                    self.collected_deal_ids.append(int(r["key"]))
                    self.collected_contexts.append(
                        f"[Deal#{r['key']} fulltext={r['score']:.2f}]\n{r['preview']}"
                    )
                except (ValueError, TypeError):
                    pass
        return json.dumps(
            [{"label": r["label"], "key": str(r["key"]),
              "preview": r["preview"], "score": round(r["score"], 2)} for r in rows],
            ensure_ascii=False,
        )

    def _tool_graph_traverse(self, args: dict) -> str:
        label = args.get("start_node_label", "Deal")
        key_field = args.get("start_node_key_field", "deal_id")
        key_value = args.get("start_node_key_value", "")
        max_hops = int(args.get("max_hops", 2))

        # Deal の key は数値
        if key_field == "deal_id":
            try:
                key_value = int(key_value)
            except (ValueError, TypeError):
                return json.dumps({"error": "deal_id は整数文字列を渡してください"}, ensure_ascii=False)

        cypher = (
            f"MATCH (n:{label}) WHERE n.{key_field} = $kv "
            f"MATCH path = (n)-[*1..{max_hops}]-(m) "
            "WITH n, m, length(path) AS hop, labels(m)[0] AS m_label "
            "RETURN m_label AS label, hop, "
            "       coalesce(m.deal_id, m.cluster_id, m.name) AS key, "
            "       coalesce(substring(m.content, 0, 200), m.objective, m.description, '') AS preview "
            "LIMIT 30"
        )
        rows = self.neo4j.run_read(cypher, kv=key_value)
        # Deal を含む結果は collected に追加
        for r in rows:
            if r["label"] == "Deal" and r["key"] is not None:
                try:
                    self.collected_deal_ids.append(int(r["key"]))
                    self.collected_contexts.append(f"[Deal#{r['key']} hop={r['hop']}]\n{r['preview']}")
                except (ValueError, TypeError):
                    pass
        return json.dumps(
            [{"label": r["label"], "key": str(r["key"]) if r["key"] is not None else "",
              "hop": r["hop"], "preview": r["preview"]} for r in rows],
            ensure_ascii=False,
        )

    def _tool_get_cluster_summary(self, args: dict) -> str:
        cluster_id = args.get("cluster_id", "")
        rows = self.neo4j.run_read(
            "MATCH (c:Cluster {cluster_id: $cid}) "
            "OPTIONAL MATCH (c)-[:IN_SEGMENT]->(s:Segment) "
            "OPTIONAL MATCH (c)-[:CLUSTER_OK_TENDENCY]->(ok:OKTendency) "
            "OPTIONAL MATCH (c)-[:CLUSTER_NG_TENDENCY]->(ng:NGTendency) "
            "OPTIONAL MATCH (c)-[:CLUSTER_BOUNDARY]->(b:Boundary) "
            "RETURN c.cluster_id AS id, c.objective AS objective, c.process AS process, "
            "       c.equipment AS equipment, c.challenge AS challenge, c.dominant_okng AS okng, "
            "       c.is_catchall AS is_catchall, s.name AS segment, "
            "       ok.segment_level AS ok_tendency, ng.segment_level AS ng_tendency, "
            "       b.okng_boundary AS boundary LIMIT 1",
            cid=cluster_id,
        )
        if not rows:
            return json.dumps({"error": f"cluster_id {cluster_id} not found"}, ensure_ascii=False)
        return json.dumps(rows[0], ensure_ascii=False, default=str)

    def _tool_finish(self, args: dict) -> str:
        return args.get("final_answer", "")
