"""RAGAS 準拠評価 (v2) 実行 CLI.

v1 (`evaluate_main.py`) と独立して動作する. 既存の v1 結果ファイルは上書きしない.

入力 (再利用):
  output/results/R*_*.json     - 各手法のベンチマーク結果

出力:
  output/evaluation_v2_results.json   - 詳細
  output/evaluation_v2_summary.csv    - ジョブ別
  output/evaluation_v2_ranking.csv    - 手法別ランキング
  output/evaluation_v2_diagnosis.csv  - 失敗原因切り分け表

オプション:
  --skip-hallucination : Hallucination 検出を省略 (LLM call 3→2)
  --diagnosis-only     : 既存の v2 結果から診断 CSV のみ再生成
  --compare-v1         : v1 結果との Pearson 相関を表示
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .. import config
from ..query_set import QUERY_SET
from ..retrievers import RETRIEVER_REGISTRY
from ..utils.llm_client import LLMClient
from .evaluator_v2 import (
    DEFAULT_WEIGHTS,
    EvaluationResultV2,
    diagnose,
    evaluate_job,
)


logger = logging.getLogger("rag_benchmark.evaluate_v2")


# 既存 v1 と同じファイル名規約 (v1 の関数は import せず独立)
_METHOD_FILE_SUFFIX = {
    "R01": "naive_vector", "R02": "vector_reranker", "R03": "hyde",
    "R04": "graphrag_local", "R05": "graphrag_global", "R06": "lightrag_hybrid",
    "R07": "contextual_retrieval", "R08": "agentic_rag", "R09": "raptor",
    "R10": "self_rag", "R11": "corrective_rag", "R12": "rag_fusion",
    "R13": "adaptive_ensemble",
}


def setup_logger(verbose: bool = False, log_file: Path | None = None) -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


# =============================================================================
# 入力ロード
# =============================================================================


def _load_all_benchmark_rows() -> list[dict]:
    """全手法の結果 JSON を読み込み、ジョブ行 (dict) のリストを返す."""
    rows: list[dict] = []
    for mid in RETRIEVER_REGISTRY:
        suffix = _METHOD_FILE_SUFFIX.get(mid, mid.lower())
        p = config.RESULTS_DIR / f"{mid}_{suffix}.json"
        if not p.exists():
            logger.warning("結果 JSON が見つかりません: %s", p)
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            rows.append(r)
    return rows


# =============================================================================
# 出力先パス
# =============================================================================


def _path_results() -> Path:
    return config.OUTPUT_DIR / "evaluation_v2_results.json"


def _path_summary() -> Path:
    return config.OUTPUT_DIR / "evaluation_v2_summary.csv"


def _path_ranking() -> Path:
    return config.OUTPUT_DIR / "evaluation_v2_ranking.csv"


def _path_diagnosis() -> Path:
    return config.OUTPUT_DIR / "evaluation_v2_diagnosis.csv"


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="rag_benchmark.evaluation.evaluate_main_v2")
    p.add_argument("--methods", nargs="+", choices=list(RETRIEVER_REGISTRY.keys()),
                   help="評価する手法 ID (省略時は全手法)")
    p.add_argument("--queries", nargs="+", help="評価するクエリ ID (省略時は全クエリ)")
    p.add_argument("--concurrency", type=int, default=5, help="LLM 評価の並列度")
    p.add_argument("--skip-hallucination", action="store_true",
                   help="Hallucination 検出を省略 (LLM call 3→2)")
    p.add_argument("--diagnosis-only", action="store_true",
                   help="既存の v2 結果 JSON から診断 CSV のみ再生成")
    p.add_argument("--compare-v1", action="store_true",
                   help="v1 (evaluation_results.json) との Pearson 相関を表示")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--log-file", type=Path, default=None)
    return p.parse_args()


# =============================================================================
# 評価実行
# =============================================================================


def _run_evaluation(args: argparse.Namespace) -> list[EvaluationResultV2]:
    query_map = {q["id"]: q for q in QUERY_SET}
    method_filter = set(args.methods) if args.methods else None
    query_filter = set(args.queries) if args.queries else None

    rows = _load_all_benchmark_rows()
    if method_filter:
        rows = [r for r in rows if r["method_id"] in method_filter]
    if query_filter:
        rows = [r for r in rows if r["query_id"] in query_filter]
    logger.info("評価対象: %d ジョブ (skip_hallucination=%s)",
                len(rows), args.skip_hallucination)

    llm = LLMClient()

    def _eval_one(r: dict) -> EvaluationResultV2:
        q = query_map.get(r["query_id"])
        ret = r.get("retrieval", {}) or {}
        gen = r.get("generation", {}) or {}
        contexts = list(ret.get("contexts") or [])
        answer = gen.get("answer", "") or ""
        latency = float(r.get("total_time_ms", -1))
        if q is None:
            logger.warning("クエリ %s が QUERY_SET に存在しません", r["query_id"])
            return evaluate_job(
                llm=llm,
                query_id=r["query_id"],
                query_text=r.get("query_text", ""),
                expected_direction="",
                keywords=[],
                method_id=r["method_id"],
                method_name=r["method_name"],
                contexts=contexts,
                answer=answer,
                latency_ms=latency,
                skip_hallucination=args.skip_hallucination,
            )
        return evaluate_job(
            llm=llm,
            query_id=q["id"],
            query_text=q["query"],
            expected_direction=q["expected_answer_direction"],
            keywords=list(q.get("ground_truth_keywords") or []),
            method_id=r["method_id"],
            method_name=r["method_name"],
            contexts=contexts,
            answer=answer,
            latency_ms=latency,
            skip_hallucination=args.skip_hallucination,
        )

    results: list[EvaluationResultV2] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency),
                            thread_name_prefix="eval_v2") as ex:
        futures = {ex.submit(_eval_one, r): (r["method_id"], r["query_id"]) for r in rows}
        with tqdm(total=len(futures), desc="Evaluating(v2)", ascii=True) as pbar:
            for fut in as_completed(futures):
                mid, qid = futures[fut]
                try:
                    er = fut.result()
                    results.append(er)
                    logger.info(
                        "[%s %s] retrieval=%.2f generation=%.2f kw=%.2f "
                        "hallu=%.2f composite=%.1f diag=%s",
                        er.method_id, er.query_id,
                        er.retrieval_eval.retrieval_score,
                        er.generation_eval.generation_score,
                        er.supplementary.keyword_coverage,
                        er.supplementary.hallucination_rate,
                        er.composite_score,
                        diagnose(er.retrieval_eval.retrieval_score,
                                 er.generation_eval.generation_score),
                    )
                except Exception as e:  # noqa: BLE001
                    logger.exception("[%s %s] 評価失敗: %s", mid, qid, e)
                pbar.update(1)
    return results


# =============================================================================
# 出力
# =============================================================================


def _save_results_json(results: list[EvaluationResultV2], skip_hallu: bool) -> Path:
    out = _path_results()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "evaluation_version": "v2_ragas_aligned",
                "execution_timestamp": datetime.now().isoformat(timespec="seconds"),
                "weights": DEFAULT_WEIGHTS,
                "skip_hallucination": skip_hallu,
                "results": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("v2 詳細 JSON 保存: %s", out)
    return out


def _save_summary_csv(results: list[EvaluationResultV2]) -> Path:
    out = _path_summary()
    cols = [
        "query_id", "method_id", "method_name",
        "context_precision", "context_recall", "context_relevancy", "retrieval_score",
        "faithfulness", "answer_relevancy", "answer_completeness", "generation_score",
        "hallucination_rate", "keyword_coverage", "latency_ms", "composite_score",
        "diagnosis", "keyword_matched_count", "keyword_only_in_context_count",
        "missing_aspects", "comment",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(results, key=lambda x: (x.method_id, x.query_id)):
            w.writerow({
                "query_id": r.query_id,
                "method_id": r.method_id,
                "method_name": r.method_name,
                "context_precision": r.retrieval_eval.context_precision,
                "context_recall": r.retrieval_eval.context_recall,
                "context_relevancy": r.retrieval_eval.context_relevancy,
                "retrieval_score": r.retrieval_eval.retrieval_score,
                "faithfulness": r.generation_eval.faithfulness,
                "answer_relevancy": r.generation_eval.answer_relevancy,
                "answer_completeness": r.generation_eval.answer_completeness,
                "generation_score": r.generation_eval.generation_score,
                "hallucination_rate": r.supplementary.hallucination_rate,
                "keyword_coverage": r.supplementary.keyword_coverage,
                "latency_ms": r.supplementary.latency_ms,
                "composite_score": r.composite_score,
                "diagnosis": diagnose(
                    r.retrieval_eval.retrieval_score,
                    r.generation_eval.generation_score,
                ),
                "keyword_matched_count": len(r.supplementary.keyword_matched),
                "keyword_only_in_context_count": len(r.supplementary.keyword_only_in_context),
                "missing_aspects": "|".join(r.generation_eval.missing_aspects),
                "comment": r.generation_eval.comment,
            })
    logger.info("v2 ジョブ別 CSV 保存: %s (%d rows)", out, len(results))
    return out


def _save_ranking_csv(results: list[EvaluationResultV2]) -> Path:
    by_method: dict[str, list[EvaluationResultV2]] = {}
    for r in results:
        by_method.setdefault(r.method_id, []).append(r)

    rows: list[dict[str, Any]] = []
    for mid, lst in by_method.items():
        n = len(lst)
        rows.append({
            "method_id": mid,
            "method_name": lst[0].method_name,
            "n": n,
            "context_precision":   round(sum(r.retrieval_eval.context_precision for r in lst) / n, 3),
            "context_recall":      round(sum(r.retrieval_eval.context_recall for r in lst) / n, 3),
            "context_relevancy":   round(sum(r.retrieval_eval.context_relevancy for r in lst) / n, 3),
            "retrieval_score":     round(sum(r.retrieval_eval.retrieval_score for r in lst) / n, 3),
            "faithfulness":        round(sum(r.generation_eval.faithfulness for r in lst) / n, 3),
            "answer_relevancy":    round(sum(r.generation_eval.answer_relevancy for r in lst) / n, 3),
            "answer_completeness": round(sum(r.generation_eval.answer_completeness for r in lst) / n, 3),
            "generation_score":    round(sum(r.generation_eval.generation_score for r in lst) / n, 3),
            "hallucination_rate":  round(sum(r.supplementary.hallucination_rate for r in lst) / n, 3),
            "keyword_coverage":    round(sum(r.supplementary.keyword_coverage for r in lst) / n, 3),
            "composite_score":     round(sum(r.composite_score for r in lst) / n, 2),
            "avg_latency_ms":      round(sum(r.supplementary.latency_ms for r in lst) / n, 1),
        })
    rows.sort(key=lambda x: x["composite_score"], reverse=True)

    out = _path_ranking()
    if rows:
        cols = list(rows[0].keys())
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        logger.info("v2 ランキング CSV 保存: %s", out)

    print()
    print(f"{'rank':>4} {'method':6} {'name':<22} {'composite':>10} "
          f"{'retr':>6} {'gen':>6} {'faith':>6} {'hallu':>6} {'kw':>6}")
    print("-" * 90)
    for i, r in enumerate(rows, 1):
        print(f"{i:>4} {r['method_id']:6} {r['method_name']:<22} "
              f"{r['composite_score']:>10.2f} {r['retrieval_score']:>6.2f} "
              f"{r['generation_score']:>6.2f} {r['faithfulness']:>6.2f} "
              f"{r['hallucination_rate']:>6.2f} {r['keyword_coverage']:>6.2f}")
    return out


def _save_diagnosis_csv(results: list[EvaluationResultV2]) -> Path:
    out = _path_diagnosis()
    rows: list[dict[str, Any]] = []
    for r in results:
        r_score = r.retrieval_eval.retrieval_score
        g_score = r.generation_eval.generation_score
        rows.append({
            "query_id": r.query_id,
            "method_id": r.method_id,
            "method_name": r.method_name,
            "composite": r.composite_score,
            "diagnosis": diagnose(r_score, g_score),
            "retrieval_score": r_score,
            "generation_score": g_score,
            "gap": round(r_score - g_score, 3),
            "faithfulness": r.generation_eval.faithfulness,
            "hallucination_rate": r.supplementary.hallucination_rate,
            "keyword_coverage": r.supplementary.keyword_coverage,
            "recall_gaps": r.retrieval_eval.recall_gaps,
            "noise_examples": r.retrieval_eval.noise_examples,
        })
    rows.sort(key=lambda x: (x["composite"], x["diagnosis"]))

    if rows:
        cols = list(rows[0].keys())
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        logger.info("v2 診断 CSV 保存: %s", out)

    from collections import Counter
    dc = Counter(r["diagnosis"] for r in rows)
    print()
    print("[diagnosis breakdown]")
    for k, v in dc.most_common():
        print(f"  {k:<22} {v}")
    return out


# =============================================================================
# 診断のみ再生成
# =============================================================================


def _rebuild_from_existing() -> None:
    p = _path_results()
    if not p.exists():
        raise SystemExit(f"v2 結果 JSON が存在しません: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    raw_results = data.get("results", [])
    results: list[EvaluationResultV2] = []
    for r in raw_results:
        try:
            from .evaluator_v2 import (
                GenerationEvaluation,
                HallucinationDetail,
                RetrievalEvaluation,
                SupplementaryMetrics,
            )
            retr = RetrievalEvaluation(**r["retrieval_eval"])
            gen = GenerationEvaluation(**r["generation_eval"])
            supp_raw = dict(r["supplementary"])
            hc = [HallucinationDetail(**c) for c in supp_raw.get("hallucination_claims", []) or []]
            supp_raw["hallucination_claims"] = hc
            supp = SupplementaryMetrics(**supp_raw)
            results.append(EvaluationResultV2(
                query_id=r["query_id"],
                method_id=r["method_id"],
                method_name=r["method_name"],
                retrieval_eval=retr,
                generation_eval=gen,
                supplementary=supp,
                composite_score=r["composite_score"],
                eval_time_ms=r.get("eval_time_ms", 0.0),
                eval_input_tokens=r.get("eval_input_tokens", 0),
                eval_output_tokens=r.get("eval_output_tokens", 0),
                eval_metadata=r.get("eval_metadata", {}),
            ))
        except Exception as e:  # noqa: BLE001
            logger.warning("既存結果の復元失敗: %s", e)
    _save_summary_csv(results)
    _save_ranking_csv(results)
    _save_diagnosis_csv(results)


# =============================================================================
# v1 との相関
# =============================================================================


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((xs[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ys[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return round(num / (dx * dy), 3)


def _compare_with_v1() -> None:
    v1_path = config.OUTPUT_DIR / "evaluation_results.json"
    v2_path = _path_results()
    if not v1_path.exists() or not v2_path.exists():
        logger.warning("v1 または v2 結果が不足のため比較スキップ (%s, %s)", v1_path, v2_path)
        return
    v1 = {(r["method_id"], r["query_id"]): r for r in json.loads(v1_path.read_text(encoding="utf-8")).get("results", [])}
    v2 = {(r["method_id"], r["query_id"]): r for r in json.loads(v2_path.read_text(encoding="utf-8")).get("results", [])}
    keys = sorted(set(v1) & set(v2))
    if not keys:
        logger.warning("v1/v2 で共通する (method, query) がありません")
        return
    v1_scores = [float(v1[k]["composite_score"]) for k in keys]
    v2_scores = [float(v2[k]["composite_score"]) for k in keys]
    corr_job = _pearson(v1_scores, v2_scores)
    print()
    print(f"[v1 vs v2] job-level Pearson correlation: {corr_job} (n={len(keys)})")

    by_method_v1: dict[str, list[float]] = {}
    by_method_v2: dict[str, list[float]] = {}
    for (mid, _qid), s1, s2 in zip(keys, v1_scores, v2_scores):
        by_method_v1.setdefault(mid, []).append(s1)
        by_method_v2.setdefault(mid, []).append(s2)
    print(f"{'method':6} {'v1_avg':>8} {'v2_avg':>8} {'delta':>8}")
    print("-" * 38)
    for mid in sorted(by_method_v1):
        a1 = sum(by_method_v1[mid]) / len(by_method_v1[mid])
        a2 = sum(by_method_v2[mid]) / len(by_method_v2[mid])
        print(f"{mid:6} {a1:>8.2f} {a2:>8.2f} {a2 - a1:>+8.2f}")


# =============================================================================
# main
# =============================================================================


def main() -> None:
    args = parse_args()
    setup_logger(args.verbose, args.log_file)

    if args.diagnosis_only:
        _rebuild_from_existing()
        if args.compare_v1:
            _compare_with_v1()
        return

    results = _run_evaluation(args)
    if not results:
        logger.warning("評価対象が 0 件でした")
        return
    _save_results_json(results, args.skip_hallucination)
    _save_summary_csv(results)
    _save_ranking_csv(results)
    _save_diagnosis_csv(results)
    if args.compare_v1:
        _compare_with_v1()


if __name__ == "__main__":
    main()
