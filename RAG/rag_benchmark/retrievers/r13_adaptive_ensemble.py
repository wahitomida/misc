"""R13: Adaptive Ensemble (動的手法選択).

クエリ特性を LLM で分析し、最適な 2-3 手法を STRATEGY_MAP から選択して実行.
複数手法の結果を Deal ID で merge + 出現回数でブースト.

R13 から R13 自身を呼ぶ無限ループは STRATEGY_MAP に R13 を含めないことで防止.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import BaseRetriever, RetrievalResult
from ..utils.token_counter import pack_contexts_within_budget
from .. import config

logger = logging.getLogger(__name__)


QUERY_CLASSIFIER_SYSTEM = (
    "あなたは RAG 検索の戦略アドバイザーです.\n"
    "以下のクエリを分析し、最適な検索戦略を決定してください.\n\n"
    "分析観点:\n"
    "  - type:\n"
    "      \"specific\": 具体事例 / 条件確認\n"
    "      \"global\":   傾向 / 比較 / 一覧 / 集約\n"
    "      \"hybrid\":   両方が必要\n"
    "  - complexity:\n"
    "      \"simple\":   1 つの情報で回答可能\n"
    "      \"moderate\": 複数情報の統合が必要\n"
    "      \"complex\":  多面的分析が必要\n"
    "  - required_info: 必要な情報種別のリスト\n"
    "      [\"deal_examples\", \"ok_ng_trends\", \"boundary_conditions\", \"cluster_summaries\",\n"
    "       \"equipment_info\", \"process_comparison\", \"statistics\", \"recommendations\"]\n"
    "  - okng_filter: \"OK\" / \"NG\" / \"BOTH\" / null\n\n"
    "JSON で返してください:\n"
    "{\n"
    "  \"type\": \"specific|global|hybrid\",\n"
    "  \"complexity\": \"simple|moderate|complex\",\n"
    "  \"required_info\": [...],\n"
    "  \"okng_filter\": \"OK|NG|BOTH|null\",\n"
    "  \"reasoning\": \"<分析理由50字以内>\"\n"
    "}"
)


# 手法選択マッピング (ベンチマーク結果から経験的に決定)
STRATEGY_MAP: dict[tuple[str, str], list[str]] = {
    ("specific", "simple"):   ["R07", "R01"],
    ("specific", "moderate"): ["R07", "R04"],
    ("specific", "complex"):  ["R11", "R04", "R07"],
    ("global", "simple"):     ["R09", "R06"],
    ("global", "moderate"):   ["R09", "R06", "R05"],
    ("global", "complex"):    ["R09", "R06", "R05"],
    ("hybrid", "simple"):     ["R09", "R07"],
    ("hybrid", "moderate"):   ["R09", "R07", "R04"],
    ("hybrid", "complex"):    ["R09", "R04", "R06"],
}


class AdaptiveEnsembleRetriever(BaseRetriever):
    @property
    def method_id(self) -> str:
        return "R13"

    @property
    def method_name(self) -> str:
        return "Adaptive Ensemble"

    def _classify_query(self, query: str) -> dict:
        try:
            result = self.llm.chat(
                QUERY_CLASSIFIER_SYSTEM,
                f"クエリ: {query}",
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(result.text)
            t = str(parsed.get("type", "hybrid")).lower()
            c = str(parsed.get("complexity", "moderate")).lower()
            if t not in ("specific", "global", "hybrid"):
                t = "hybrid"
            if c not in ("simple", "moderate", "complex"):
                c = "moderate"
            okng = parsed.get("okng_filter")
            if okng not in ("OK", "NG", "BOTH"):
                okng = None
            return {
                "type": t,
                "complexity": c,
                "required_info": parsed.get("required_info", []),
                "okng_filter": okng,
                "reasoning": str(parsed.get("reasoning", ""))[:120],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("R13 query 分類失敗: %s", e)
            return {
                "type": "hybrid", "complexity": "moderate",
                "required_info": [], "okng_filter": None,
                "reasoning": f"classify_failed: {e}",
            }

    def _ensemble_merge(
        self,
        sub_results: list[tuple[str, RetrievalResult]],
        analysis: dict,
    ) -> dict:
        """複数手法の結果を Deal ID で dedup し、出現回数でブースト."""
        # Deal ID → {"text": str, "count": int, "first_method": str, "methods": list}
        deal_data: dict[int, dict] = {}
        # Deal 紐付けの無いコンテキスト (Cluster/Segment 等) は別バケット
        extra_contexts: list[tuple[str, str]] = []

        for mid, ret in sub_results:
            seen_in_this = set()
            for ctx, did in zip(ret.contexts, ret.source_deal_ids):
                if did in seen_in_this:
                    continue
                seen_in_this.add(did)
                if did not in deal_data:
                    deal_data[did] = {
                        "text": ctx,
                        "count": 0,
                        "first_method": mid,
                        "methods": [],
                    }
                deal_data[did]["count"] += 1
                deal_data[did]["methods"].append(mid)
            # Deal 紐付けの無い余分なコンテキスト
            for ctx in ret.contexts[len(ret.source_deal_ids):]:
                extra_contexts.append((mid, ctx))

        # 出現回数降順 → 多手法でヒットした Deal を優先
        sorted_deals = sorted(deal_data.items(), key=lambda x: (-x[1]["count"], x[0]))
        boost_count = sum(1 for _, d in sorted_deals if d["count"] > 1)

        # コンテキスト構築: ブーストされた Deal を先頭に
        contexts_full: list[str] = []
        ordered_deal_ids: list[int] = []
        for did, info in sorted_deals:
            prefix = (
                f"[R13 boost x{info['count']} via {','.join(info['methods'])}]\n"
                if info["count"] > 1 else ""
            )
            contexts_full.append(prefix + info["text"])
            ordered_deal_ids.append(did)
        # 余分なコンテキストは末尾に少量 (Cluster サマリ等)
        for mid, ctx in extra_contexts[:5]:
            contexts_full.append(f"[R13 supplementary from {mid}]\n{ctx}")

        contexts, tokens = pack_contexts_within_budget(contexts_full, config.CONTEXT_MAX_TOKENS)
        return {
            "contexts": contexts,
            "deal_ids": ordered_deal_ids[: len(contexts)],
            "boost_count": boost_count,
            "tokens": tokens,
        }

    def retrieve(self, query: str) -> RetrievalResult:
        t0 = time.perf_counter()
        max_sub = int(self.config.get("max_sub_methods", 3))
        parallel = bool(self.config.get("parallel_execution", False))
        fallback = list(self.config.get("fallback_methods", ["R09", "R07"]))

        # 循環 import 回避のため retrieve() 内で import
        from . import RETRIEVER_REGISTRY  # noqa: PLC0415

        # Step 1: クエリ分類
        analysis = self._classify_query(query)
        key = (analysis["type"], analysis["complexity"])
        selected = STRATEGY_MAP.get(key, fallback)[:max_sub]

        # 自分自身を選ばないように防御 (STRATEGY_MAP に R13 は含めていないが念のため)
        selected = [m for m in selected if m != "R13"]
        if not selected:
            selected = [m for m in fallback if m != "R13"][:max_sub]

        logger.info(
            "[R13] query analysis: type=%s complexity=%s → methods=%s",
            analysis["type"], analysis["complexity"], selected,
        )

        # Step 2: 選択された手法を実行
        def _run(mid: str) -> tuple[str, RetrievalResult]:
            ret_cls = RETRIEVER_REGISTRY[mid]
            sub = ret_cls(self.neo4j, self.llm, config.RETRIEVER_CONFIGS.get(mid, {}))
            return mid, sub.retrieve(query)

        sub_results: list[tuple[str, RetrievalResult]] = []
        if parallel and len(selected) > 1:
            with ThreadPoolExecutor(max_workers=len(selected),
                                    thread_name_prefix="R13-sub") as ex:
                futures = [ex.submit(_run, m) for m in selected]
                for fut in as_completed(futures):
                    try:
                        sub_results.append(fut.result())
                    except Exception as e:  # noqa: BLE001
                        logger.warning("R13 sub method failed: %s", e)
        else:
            for m in selected:
                try:
                    sub_results.append(_run(m))
                except Exception as e:  # noqa: BLE001
                    logger.warning("R13 sub method %s failed: %s", m, e)

        if not sub_results:
            return RetrievalResult(
                contexts=["[R13] 全 sub method 失敗"],
                source_deal_ids=[],
                retrieval_time_ms=(time.perf_counter() - t0) * 1000.0,
                context_token_count=0,
                metadata={"query_analysis": analysis, "selected_methods": selected,
                          "error": "all_sub_failed"},
            )

        # Step 3: アンサンブル統合
        merged = self._ensemble_merge(sub_results, analysis)

        elapsed = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(
            contexts=merged["contexts"],
            source_deal_ids=merged["deal_ids"],
            retrieval_time_ms=elapsed,
            context_token_count=merged["tokens"],
            metadata={
                "query_analysis": analysis,
                "selected_methods": selected,
                "sub_results_summary": [
                    {
                        "method": mid,
                        "deals": len(r.source_deal_ids),
                        "contexts": len(r.contexts),
                        "time_ms": round(r.retrieval_time_ms, 1),
                    }
                    for mid, r in sub_results
                ],
                "ensemble_boost_count": merged["boost_count"],
                "parallel_execution": parallel,
            },
        )
