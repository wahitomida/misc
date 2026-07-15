"""R11: Corrective RAG (CRAG).

Yan et al. 2024.

検索結果全体の品質を 3 段階で評価し、戦略レベルで修正する.
  - Correct (信頼度高): Knowledge Refinement → 回答生成
  - Ambiguous (中): Knowledge Refinement + サブクエリで追加検索 → 結合 → 回答生成
  - Incorrect (低): 検索戦略変更 (A/B/C を LLM に選ばせる) → 再検索 → 再評価 (最大 max_correction_loops)
"""
from __future__ import annotations

import json
import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


QUALITY_EVALUATOR_SYSTEM = (
    "あなたは Corrective RAG の検索品質評価器です. クエリと検索結果群を見て、回答に必要な情報が"
    "含まれているかを 3 段階で判定してください.\n"
    "  - correct:    回答に必要な情報が明確に含まれている\n"
    "  - ambiguous:  部分的に関連するが、情報が不足しているか矛盾がある\n"
    "  - incorrect:  質問と無関係、または完全に的外れ\n"
    "JSON で返してください: "
    "{\"quality\": \"correct|ambiguous|incorrect\", \"reason\": \"<判定理由>\", "
    "\"missing_info\": \"<不足情報 (ambiguous の場合)>\", \"confidence\": 0.0-1.0}"
)


KNOWLEDGE_REFINEMENT_SYSTEM_TEMPLATE = (
    "あなたは Corrective RAG の知識精鍊器です. クエリへの回答に直接必要な情報のみを文書群から"
    "抽出してください. 不要な情報、重複、ノイズは除去し、Deal# ID 付きで簡潔に整理してください.\n"
    "出力: 各 Deal について 1 行の要点 (合計 {max_chars} 字以内、簡潔を最優先)."
)


SUBQUERY_GEN_SYSTEM = (
    "あなたは Corrective RAG の補完検索器です. 元クエリと、不足している情報をもとに、"
    "不足を補うための具体的な検索キーワード (Lucene 全文検索向け) を生成してください.\n"
    "JSON で返してください: {\"subquery_keyword\": \"<Lucene OR で繋いだキーワード>\"}"
)


STRATEGY_SELECTOR_SYSTEM = (
    "Vector 検索の結果が不十分でした. 以下から最適な代替戦略を選択してください.\n"
    "  A: キーワード全文検索 (deal_content_fulltext)\n"
    "  B: グラフ構造探索 (Equipment/Process/Workpiece fulltext → Cluster → Deal)\n"
    "  C: クエリをリフレーズして Vector 再検索\n"
    "JSON で返してください: "
    "{\"strategy\": \"A|B|C\", \"revised_query_or_keyword\": \"<戦略に渡すテキスト>\"}"
)


def _sanitize_lucene(text: str) -> str:
    special = '+-&|!(){}[]^"~*?:\\/'
    cleaned = "".join(" " if c in special else c for c in text)
    terms = [t for t in cleaned.split() if t and len(t) > 1]
    return " ".join(terms) or text


class CorrectiveRAGRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R11"

    @property
    def method_name(self) -> str:
        return "Corrective RAG"

    # =========================================================
    # 検索ストラテジー (Vector / Fulltext / Graph / Vector-rephrase)
    # =========================================================
    def _search_vector(self, query: str, top_k: int = 10) -> list[dict]:
        qvec = self.llm.embed(query)
        rows = self.neo4j.run_read(
            "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
            "YIELD node, score "
            "RETURN node.deal_id AS deal_id, node.okng AS okng, "
            "       node.okng_reason AS reason, node.content AS content, score "
            "ORDER BY score DESC",
            k=top_k, q=qvec,
        )
        return [{**r, "_origin": "vector"} for r in rows]

    def _search_fulltext(self, keyword: str, top_k: int = 10) -> list[dict]:
        try:
            rows = self.neo4j.run_read(
                "CALL db.index.fulltext.queryNodes('deal_content_fulltext', $kw) "
                "YIELD node, score "
                "RETURN node.deal_id AS deal_id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC LIMIT $k",
                kw=_sanitize_lucene(keyword), k=top_k,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("fulltext 検索失敗: %s", e)
            return []
        return [{**r, "_origin": "fulltext"} for r in rows]

    def _search_graph(self, keyword: str, top_k: int = 10) -> list[dict]:
        results: list[dict] = []
        kw = _sanitize_lucene(keyword)
        for idx in ("equipment_name_fulltext", "process_name_fulltext", "workpiece_name_fulltext"):
            try:
                rows = self.neo4j.run_read(
                    "CALL db.index.fulltext.queryNodes($idx, $kw) "
                    "YIELD node AS entity, score "
                    "MATCH (entity)<-[r]-(c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
                    "WHERE coalesce(d.in_catchall_cluster, false) = false "
                    "  AND type(r) IN ['USES_EQUIPMENT','HAS_PROCESS','TARGETS_WORKPIECE'] "
                    "RETURN d.deal_id AS deal_id, d.okng AS okng, d.okng_reason AS reason, "
                    "       d.content AS content, c.cluster_id AS cluster_id, "
                    "       entity.name AS entity_name, score "
                    "ORDER BY score DESC LIMIT $k",
                    idx=idx, kw=kw, k=top_k,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("graph 検索失敗 idx=%s: %s", idx, e)
                continue
            for r in rows:
                results.append({**r, "_origin": f"graph:{idx}"})
        # 上位を採用
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _format_context(self, r: dict) -> str:
        origin_tag = r.get("_origin", "")
        extra = f" cluster={r.get('cluster_id')}" if r.get("cluster_id") else ""
        return (
            f"[Deal#{int(r['deal_id'])} {r['okng']} score={r['score']:.3f} "
            f"origin={origin_tag}{extra}]\n"
            f"理由: {r.get('reason') or ''}\n"
            f"内容: {(r.get('content') or '')[:800]}"
        )

    # =========================================================
    # 品質評価
    # =========================================================
    def _evaluate_quality(self, query: str, docs: list[dict]) -> dict:
        summary = "\n\n".join(self._format_context(d)[:400] for d in docs[:5])
        try:
            resp = self.llm.chat(
                QUALITY_EVALUATOR_SYSTEM,
                f"クエリ: {query}\n\n検索結果 (上位5件):\n{summary}",
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(resp.text)
            return {
                "quality": str(parsed.get("quality", "ambiguous")),
                "reason": str(parsed.get("reason", "")),
                "missing_info": str(parsed.get("missing_info", "")),
                "confidence": float(parsed.get("confidence", 0.5)),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("品質評価失敗: %s", e)
            return {"quality": "ambiguous", "reason": str(e), "missing_info": "", "confidence": 0.5}

    # =========================================================
    # Knowledge Refinement
    # =========================================================
    def _refine_knowledge(self, query: str, docs: list[dict]) -> str:
        if not docs:
            return ""
        max_chars = int(self.config.get("refinement_max_chars", 400))
        block = "\n\n".join(self._format_context(d) for d in docs)
        try:
            resp = self.llm.chat(
                KNOWLEDGE_REFINEMENT_SYSTEM_TEMPLATE.format(max_chars=max_chars),
                f"クエリ: {query}\n\n文書群:\n{block}\n\n精鍊済み要点 (Deal# 付き、{max_chars} 字以内):",
                temperature=0.2,
                max_tokens=max(256, max_chars),
            )
            return resp.text.strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("Knowledge Refinement 失敗: %s", e)
            return ""
    # =========================================================
    # メイン
    # =========================================================
    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        top_k = int(self.config.get("initial_top_k", 10))
        max_loops = int(self.config.get("max_correction_loops", 2))
        conf_threshold = float(self.config.get("quality_confidence_threshold", 0.6))
        refinement_enabled = bool(self.config.get("refinement_enabled", True))

        strategies_used: list[str] = ["vector"]
        eval_history: list[dict] = []
        refined_block = ""
        sub_search_block = ""
        knowledge_refined = False
        loop_count = 0

        # ========== 初回 Vector 検索 ==========
        docs = self._search_vector(query, top_k=top_k)
        initial_eval = self._evaluate_quality(query, docs)
        eval_history.append({"loop": 0, "strategy": "vector", **initial_eval})
        initial_quality = initial_eval["quality"]
        current_quality = initial_quality
        current_docs = docs
        current_confidence = initial_eval["confidence"]
        missing_info_final = initial_eval["missing_info"]

        # ========== Correct ==========
        if current_quality == "correct" and current_confidence >= conf_threshold:
            if refinement_enabled:
                refined_block = self._refine_knowledge(query, current_docs)
                knowledge_refined = bool(refined_block)

        # ========== Ambiguous ==========
        elif current_quality == "ambiguous":
            if refinement_enabled:
                refined_block = self._refine_knowledge(query, current_docs)
                knowledge_refined = bool(refined_block)
            # サブクエリ生成 → 追加検索
            try:
                sq_resp = self.llm.chat(
                    SUBQUERY_GEN_SYSTEM,
                    f"元クエリ: {query}\n不足情報: {initial_eval['missing_info']}",
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                sub_kw = str(json.loads(sq_resp.text).get("subquery_keyword", "")).strip()
            except Exception as e:  # noqa: BLE001
                logger.warning("subquery 生成失敗: %s", e)
                sub_kw = ""
            if sub_kw:
                add_docs = self._search_fulltext(sub_kw, top_k=top_k)
                strategies_used.append("fulltext_subquery")
                if add_docs:
                    sub_search_block = "\n\n".join(self._format_context(d) for d in add_docs)
                    current_docs = current_docs + add_docs

        # ========== Incorrect ==========
        else:  # incorrect or low confidence with non-correct
            # LLM に戦略 A/B/C を選ばせて再検索. 最大 max_correction_loops 回ループ.
            for loop in range(max_loops):
                loop_count = loop + 1
                try:
                    sel = self.llm.chat(
                        STRATEGY_SELECTOR_SYSTEM,
                        (f"元クエリ: {query}\n失敗の理由: {current_quality}/{eval_history[-1]['reason']}\n"
                         f"これまで使った戦略: {strategies_used}"),
                        temperature=0.0,
                        response_format={"type": "json_object"},
                    )
                    sel_data = json.loads(sel.text)
                    strategy = str(sel_data.get("strategy", "A")).upper()
                    revised = str(sel_data.get("revised_query_or_keyword", "") or query)
                except Exception as e:  # noqa: BLE001
                    logger.warning("strategy 選択失敗: %s", e)
                    strategy = "A"
                    revised = query

                if strategy == "A":
                    new_docs = self._search_fulltext(revised, top_k=top_k)
                    strategies_used.append("fulltext")
                elif strategy == "B":
                    new_docs = self._search_graph(revised, top_k=top_k)
                    strategies_used.append("graph")
                else:  # C
                    new_docs = self._search_vector(revised, top_k=top_k)
                    strategies_used.append("vector_rephrase")

                if not new_docs:
                    continue
                current_docs = new_docs
                new_eval = self._evaluate_quality(query, current_docs)
                eval_history.append({"loop": loop + 1, "strategy": strategy, **new_eval})
                current_quality = new_eval["quality"]
                current_confidence = new_eval["confidence"]
                missing_info_final = new_eval["missing_info"]
                if current_quality == "correct" and current_confidence >= conf_threshold:
                    if refinement_enabled:
                        refined_block = self._refine_knowledge(query, current_docs)
                        knowledge_refined = bool(refined_block)
                    break
                if current_quality == "ambiguous" and refinement_enabled:
                    refined_block = self._refine_knowledge(query, current_docs)
                    knowledge_refined = bool(refined_block)
                    break  # ambiguous は Knowledge Refinement で確定

        # ========== コンテキスト構築 ==========
        contexts_full: list[str] = []
        if refined_block:
            contexts_full.append(f"[CRAG Knowledge Refinement (quality={current_quality})]\n{refined_block}")
        if sub_search_block:
            contexts_full.append(f"[CRAG Sub-query 追加検索結果]\n{sub_search_block}")
        # 元/最新の docs を contexts に並べる (refined と重複してもよい)
        for d in current_docs:
            contexts_full.append(self._format_context(d))

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        deal_ids: list[int] = []
        for d in current_docs:
            did = int(d["deal_id"])
            if did not in deal_ids:
                deal_ids.append(did)

        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=contexts,
            source_deal_ids=deal_ids[: len(contexts)],
            retrieval_time_ms=elapsed,
            context_token_count=tokens,
            metadata={
                "initial_quality": initial_quality,
                "final_quality": current_quality,
                "confidence": current_confidence,
                "correction_loops": loop_count,
                "strategies_used": strategies_used,
                "knowledge_refined": knowledge_refined,
                "missing_info_detected": missing_info_final,
                "eval_history": eval_history,
            },
        )
