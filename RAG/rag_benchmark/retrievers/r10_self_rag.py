"""R10: Self-RAG (Self-Reflective Retrieval-Augmented Generation).

Asai et al. ICLR 2024.

3 段階の自己反省を内部で実行する:
  1. Retrieve判定: そもそも検索が必要か (yes/no)
  2. Relevance判定: 各文書が relevant / partially_relevant / irrelevant
  3. 内部で回答生成
  4. Support判定: 回答が fully / partially / not_supported
  5. not_supported なら query をリフレーズして再検索 (最大 max_reflection_loops)

RetrievalResult.pre_generated_answer に最終回答を入れて返し、
main.py は generate_answer をスキップしてその回答を採用する.
"""
from __future__ import annotations

import json
import logging
import time

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import count_tokens, pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


# 循環 import 回避のため answer_generator から複製
_GEN_SYSTEM = """
あなたはセンサ商談の専門家です。
提供されたコンテキスト情報のみを根拠に、質問に対して正確かつ具体的に回答してください。
コンテキストに含まれない情報は「情報が不足しています」と明示してください。
回答は日本語で、以下の構造で記述してください:
1. 結論（1-2文）
2. 根拠（箇条書き、コンテキストから引用）
3. 補足事項（あれば）
""".strip()


RETRIEVE_JUDGE_PROMPT = (
    "以下の質問に回答するために、センサ商談データベースの検索が必要ですか? "
    "デフォルトは \"yes\". 以下のいずれかに明確に該当する場合のみ \"no\" と答えてください:\n"
    "  - 質問が「あなたは誰?」「こんにちは」等の雑談に限定される場合\n"
    "  - センサや商談に一切関係ない一般論のみを説明すればよい場合\n"
    "具体事例、クラスタ傾向、OK/NG 判定理由、製品名・工程名を含む質問は \"yes\".\n\n"
    "質問: {query}\n\n"
    "JSON で回答: {{\"need_retrieval\": true|false, \"reason\": \"<短い理由>\"}}"
)


RELEVANCE_JUDGE_SYSTEM = (
    "あなたは Self-RAG の Relevance 判定器です. ユーザの質問と各候補文書について、"
    "以下のいずれかで判定してください.\n"
    "  - relevant: クエリに直接答えられる重要情報を含む\n"
    "  - partially_relevant: 部分的に関連する\n"
    "  - irrelevant: 質問と無関係\n"
    "JSON {\"judgments\": [{\"id\": <int>, \"relevance\": \"relevant|partially_relevant|irrelevant\", "
    "\"reason\": \"<短い理由>\"}, ...]} で返してください."
)


SUPPORT_JUDGE_SYSTEM = (
    "あなたは Self-RAG の Support 判定器です. 生成された回答が提供コンテキストに裏付けられているか判定してください.\n"
    "  - fully_supported: 回答全体がコンテキストの内容で完全に裏付けられる\n"
    "  - partially_supported: 一部のみ裏付けられ、推測や不確実な部分を含む\n"
    "  - not_supported: コンテキストに裏付けが見当たらない / 矛盾する\n"
    "JSON {\"support\": \"fully_supported|partially_supported|not_supported\", "
    "\"unsupported_claims\": [\"<裏付け不足の主張>\", ...]} で返してください."
)


REPHRASE_SYSTEM = (
    "あなたは検索クエリの言い換え器です. 与えられたクエリを別の表現で言い換えてください. "
    "同義語、関連用語、別の角度からの問いを織り込み、検索ヒットを改善する狙い.\n"
    "出力は言い換えクエリ 1 行のみ (前置きや説明なし)."
)


_RELEVANCE_RANK = {"relevant": 2, "partially_relevant": 1, "irrelevant": 0}
_SUPPORT_RANK = {"fully_supported": 2, "partially_supported": 1, "not_supported": 0}


class SelfRAGRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R10"

    @property
    def method_name(self) -> str:
        return "Self-RAG"

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        top_k = int(self.config.get("initial_top_k", 10))
        max_loops = int(self.config.get("max_reflection_loops", 2))
        rel_threshold_name = str(self.config.get("relevance_threshold", "partially_relevant"))
        sup_threshold_name = str(self.config.get("support_threshold", "partially_supported"))
        rel_threshold = _RELEVANCE_RANK.get(rel_threshold_name, 1)
        sup_threshold = _SUPPORT_RANK.get(sup_threshold_name, 1)
        rephrase_on_failure = bool(self.config.get("rephrase_on_failure", True))

        # ========== Step 1: Retrieve 判定 ==========
        try:
            judge = self.llm.chat(
                "あなたは Self-RAG の Retrieve 判定器です. JSON で yes/no を返します.",
                RETRIEVE_JUDGE_PROMPT.format(query=query),
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            need_retrieval = bool(json.loads(judge.text).get("need_retrieval", True))
        except Exception as e:  # noqa: BLE001
            logger.warning("Retrieve 判定失敗: %s", e)
            need_retrieval = True

        # 検索不要 → 保険として safety_top_k 件だけ取得し LLM で回答生成
        if not need_retrieval:
            safety_k = int(self.config.get("safety_top_k_when_no_retrieve", 3))
            safety_contexts: list[str] = []
            safety_deal_ids: list[int] = []
            if safety_k > 0:
                try:
                    qvec_s = self.llm.embed(query)
                    rows_s = self.neo4j.run_read(
                        "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                        "YIELD node, score "
                        "RETURN node.deal_id AS deal_id, node.okng AS okng, "
                        "       node.okng_reason AS reason, node.content AS content, score "
                        "ORDER BY score DESC",
                        k=safety_k, q=qvec_s,
                    )
                    for r in rows_s:
                        safety_deal_ids.append(int(r["deal_id"]))
                        safety_contexts.append(
                            f"[Deal#{int(r['deal_id'])} {r['okng']} sim={r['score']:.3f} (safety)]\n"
                            f"理由: {r.get('reason') or ''}\n"
                            f"内容: {(r.get('content') or '')[:600]}"
                        )
                except Exception as e:  # noqa: BLE001
                    logger.warning("safety 検索失敗: %s", e)
            packed_s, tok_s = pack_contexts_within_budget(safety_contexts, config.CONTEXT_MAX_TOKENS)
            joined_s = "\n\n---\n\n".join(packed_s) if packed_s else "(検索スキップ)"
            direct = self.llm.chat(
                _GEN_SYSTEM,
                f"【質問】\n{query}\n\n【コンテキスト】\n{joined_s}\n\n【回答】",
                temperature=0.2,
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RetrievalResult(
                contexts=packed_s or ["[Self-RAG] 検索不要 (need_retrieval=false)"],
                source_deal_ids=safety_deal_ids[: len(packed_s)],
                retrieval_time_ms=elapsed,
                context_token_count=tok_s,
                metadata={
                    "retrieval_needed": False,
                    "initial_results": len(safety_deal_ids),
                    "relevant_results": len(safety_deal_ids),
                    "irrelevant_filtered": 0,
                    "support_level": "n/a",
                    "reflection_loops": 0,
                    "rephrase_used": False,
                    "safety_search_used": safety_k > 0,
                },
                pre_generated_answer=direct.text,
                pre_gen_input_tokens=direct.input_tokens,
                pre_gen_output_tokens=direct.output_tokens,
                pre_gen_model=direct.model,
            )

        # ========== 検索 + Relevance + Support のループ ==========
        current_query = query
        rephrase_used = False
        loop_count = 0
        final_support_level = "not_supported"
        final_contexts: list[str] = []
        final_deal_ids: list[int] = []
        final_answer: str = ""
        final_gen_input = 0
        final_gen_output = 0
        final_gen_model = ""
        initial_results = 0
        relevant_results = 0
        irrelevant_filtered = 0
        unsupported_claims_final: list[str] = []

        for loop in range(max_loops):
            loop_count = loop + 1

            # Step 2: Vector 検索
            qvec = self.llm.embed(current_query)
            rows = self.neo4j.run_read(
                "CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) "
                "YIELD node, score "
                "RETURN node.deal_id AS deal_id, node.okng AS okng, "
                "       node.okng_reason AS reason, node.content AS content, score "
                "ORDER BY score DESC",
                k=top_k, q=qvec,
            )
            if loop == 0:
                initial_results = len(rows)

            # Step 3: Relevance 判定 (1 回の LLM 呼び出しで全件)
            docs_block = "\n\n".join(
                f"[id={int(r['deal_id'])}] {(r.get('content') or '')[:400]}"
                for r in rows
            )
            try:
                rel_resp = self.llm.chat(
                    RELEVANCE_JUDGE_SYSTEM,
                    f"質問: {query}\n\n候補文書:\n{docs_block}",
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                rel_data = json.loads(rel_resp.text).get("judgments", [])
                rel_map = {int(j["id"]): str(j.get("relevance", "irrelevant")) for j in rel_data}
            except Exception as e:  # noqa: BLE001
                logger.warning("Relevance 判定失敗: %s", e)
                rel_map = {int(r["deal_id"]): "relevant" for r in rows}  # フォールバック

            kept: list[dict] = []
            irrelevant_count = 0
            for r in rows:
                did = int(r["deal_id"])
                lvl = rel_map.get(did, "irrelevant")
                if _RELEVANCE_RANK.get(lvl, 0) >= rel_threshold:
                    kept.append({**r, "_rel": lvl})
                else:
                    irrelevant_count += 1
            if loop == 0:
                relevant_results = len(kept)
                irrelevant_filtered = irrelevant_count

            if not kept:
                # 関連 0 件 → リフレーズして再検索
                if rephrase_on_failure and loop + 1 < max_loops:
                    rep = self.llm.chat(
                        REPHRASE_SYSTEM,
                        f"元クエリ: {current_query}\n\n言い換えクエリ:",
                        temperature=0.5,
                    )
                    current_query = rep.text.strip().split("\n")[0][:200] or current_query
                    rephrase_used = True
                    continue
                break

            # Step 4: 内部で回答生成
            contexts_full = [
                (f"[Deal#{int(d['deal_id'])} {d['okng']} rel={d['_rel']} sim={d['score']:.3f}]\n"
                 f"理由: {d.get('reason') or ''}\n"
                 f"内容: {(d.get('content') or '')[:1000]}")
                for d in kept
            ]
            packed, _tok = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
            joined = "\n\n---\n\n".join(packed)
            gen = self.llm.chat(
                _GEN_SYSTEM,
                f"【質問】\n{query}\n\n【コンテキスト】\n{joined}\n\n【回答】",
                temperature=0.2,
            )
            answer = gen.text

            # Step 5: Support 判定
            try:
                sup_resp = self.llm.chat(
                    SUPPORT_JUDGE_SYSTEM,
                    f"質問: {query}\n\n回答: {answer}\n\nコンテキスト:\n{joined}",
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                sup_data = json.loads(sup_resp.text)
                support_level = str(sup_data.get("support", "not_supported"))
                unsupported_claims = list(sup_data.get("unsupported_claims", []))
            except Exception as e:  # noqa: BLE001
                logger.warning("Support 判定失敗: %s", e)
                support_level = "partially_supported"
                unsupported_claims = []

            # 暫定的に最後の結果を保存
            final_support_level = support_level
            final_contexts = packed
            final_deal_ids = [int(d["deal_id"]) for d in kept][: len(packed)]
            final_answer = answer
            final_gen_input = gen.input_tokens
            final_gen_output = gen.output_tokens
            final_gen_model = gen.model
            unsupported_claims_final = unsupported_claims

            if _SUPPORT_RANK.get(support_level, 0) >= sup_threshold:
                # partially_supported なら注記を付加
                if support_level == "partially_supported":
                    final_answer = answer + "\n\n※一部推測を含みます (Self-RAG: partially_supported)"
                break

            # not_supported → リフレーズして再検索
            if rephrase_on_failure and loop + 1 < max_loops:
                rep = self.llm.chat(
                    REPHRASE_SYSTEM,
                    f"元クエリ: {current_query}\n言い換え対象の不足点: " +
                    ", ".join(unsupported_claims[:3]) + "\n\n言い換えクエリ:",
                    temperature=0.5,
                )
                current_query = rep.text.strip().split("\n")[0][:200] or current_query
                rephrase_used = True
                continue
            break

        # 万一何も取れなかった場合のフォールバック
        if not final_contexts:
            final_contexts = ["[Self-RAG] 関連文書なし"]
            if not final_answer:
                final_answer = "情報が不足しています。"

        ctx_tokens = sum(count_tokens(c) for c in final_contexts)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=final_contexts,
            source_deal_ids=final_deal_ids,
            retrieval_time_ms=elapsed,
            context_token_count=ctx_tokens,
            metadata={
                "retrieval_needed": True,
                "initial_results": initial_results,
                "relevant_results": relevant_results,
                "irrelevant_filtered": irrelevant_filtered,
                "support_level": final_support_level,
                "reflection_loops": loop_count,
                "rephrase_used": rephrase_used,
                "final_query": current_query,
                "unsupported_claims": unsupported_claims_final,
            },
            pre_generated_answer=final_answer,
            pre_gen_input_tokens=final_gen_input,
            pre_gen_output_tokens=final_gen_output,
            pre_gen_model=final_gen_model,
        )
