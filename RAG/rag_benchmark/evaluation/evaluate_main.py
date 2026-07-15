"""評価実行 CLI.

output/results/R*_*.json を読み込み、各回答を LLM で採点して
  - output/evaluation_results.json (詳細)
  - output/evaluation_summary.csv  (集計用)
  - output/evaluation_ranking.csv  (手法別ランキング)
を生成する.

並列実行対応 (--concurrency).
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

from tqdm import tqdm

from .....RAG.rag_benchmark.evaluation import config
from .evaluator import EvaluationResult, evaluate_answer
from .query_set import QUERY_SET
from .retrievers import RETRIEVER_REGISTRY
from .utils.llm_client import get_llm_client

logger = logging.getLogger("rag_benchmark.evaluate")


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


_METHOD_FILE_SUFFIX = {
    "R01": "naive_vector", "R02": "vector_reranker", "R03": "hyde",
    "R04": "graphrag_local", "R05": "graphrag_global", "R06": "lightrag_hybrid",
    "R07": "contextual_retrieval", "R08": "agentic_rag", "R09": "raptor",
    "R10": "self_rag", "R11": "corrective_rag",
}


def _load_all_benchmark_rows() -> list[dict]:
    """全 method JSON を読み込み、フラットな行リストにする."""
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="rag_benchmark.evaluate")
    p.add_argument("--methods", nargs="+", choices=list(RETRIEVER_REGISTRY.keys()),
                   help="評価する手法 ID (省略時は全手法)")
    p.add_argument("--queries", nargs="+", help="評価するクエリ ID (省略時は全クエリ)")
    p.add_argument("--concurrency", type=int, default=5,
                   help="LLM 評価の並列度 (default 5)")
    p.add_argument("--speed-norm-ms", type=float, default=50000.0,
                   help="速度スコア正規化基準 ms. これ以上で speed_score=0 (default 50000)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--log-file", type=Path, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(args.verbose, args.log_file)

    query_map = {q["id"]: q for q in QUERY_SET}
    method_filter = set(args.methods) if args.methods else None
    query_filter = set(args.queries) if args.queries else None

    rows = _load_all_benchmark_rows()
    if method_filter:
        rows = [r for r in rows if r["method_id"] in method_filter]
    if query_filter:
        rows = [r for r in rows if r["query_id"] in query_filter]
    logger.info("評価対象: %d ジョブ", len(rows))

    llm = get_llm_client()

    def _eval_one(r: dict) -> EvaluationResult:
        q = query_map.get(r["query_id"])
        if q is None:
            logger.warning("クエリ %s が QUERY_SET に存在しません", r["query_id"])
            return EvaluationResult(
                query_id=r["query_id"], method_id=r["method_id"], method_name=r["method_name"],
                scores={k: 0 for k in ("relevance", "accuracy", "completeness", "specificity", "structure")},
                comment="[ERROR] query not found", weakness_tags=["query不在"],
                keyword_coverage=0.0, speed_score=0.0, quality_score=0.0, composite_score=0.0,
                eval_time_ms=0.0, eval_input_tokens=0, eval_output_tokens=0,
            )
        return evaluate_answer(
            llm=llm,
            query_id=r["query_id"],
            query_text=r["query_text"],
            expected_direction=q["expected_answer_direction"],
            ground_truth_keywords=q["ground_truth_keywords"],
            method_id=r["method_id"],
            method_name=r["method_name"],
            answer=r.get("generation", {}).get("answer", ""),
            total_time_ms=float(r.get("total_time_ms", -1)),
            speed_norm_total_ms=args.speed_norm_ms,
        )

    results: list[EvaluationResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency), thread_name_prefix="eval") as ex:
        futures = {ex.submit(_eval_one, r): (r["method_id"], r["query_id"]) for r in rows}
        with tqdm(total=len(futures), desc="Evaluating", ascii=True) as pbar:
            for fut in as_completed(futures):
                mid, qid = futures[fut]
                try:
                    er = fut.result()
                    results.append(er)
                    logger.info(
                        "[%s %s] quality=%.2f kw=%.2f speed=%.2f composite=%.1f tags=%s",
                        er.method_id, er.query_id, er.quality_score,
                        er.keyword_coverage, er.speed_score, er.composite_score,
                        ",".join(er.weakness_tags) if er.weakness_tags else "-",
                    )
                except Exception as e:  # noqa: BLE001
                    logger.exception("[%s %s] 評価失敗: %s", mid, qid, e)
                pbar.update(1)

    # ---- 詳細 JSON ----
    out_json = config.OUTPUT_DIR / "evaluation_results.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({
            "execution_timestamp": datetime.now().isoformat(timespec="seconds"),
            "speed_norm_ms": args.speed_norm_ms,
            "results": [asdict(r) for r in results],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("評価詳細 JSON 保存: %s", out_json)

    # ---- ジョブ別 CSV ----
    out_csv = config.OUTPUT_DIR / "evaluation_summary.csv"
    cols = [
        "query_id", "method_id", "method_name",
        "relevance", "accuracy", "completeness", "specificity", "structure",
        "quality_score", "keyword_coverage", "speed_score", "composite_score",
        "weakness_tags", "comment",
    ]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(results, key=lambda x: (x.method_id, x.query_id)):
            w.writerow({
                "query_id": r.query_id,
                "method_id": r.method_id,
                "method_name": r.method_name,
                "relevance": r.scores["relevance"],
                "accuracy": r.scores["accuracy"],
                "completeness": r.scores["completeness"],
                "specificity": r.scores["specificity"],
                "structure": r.scores["structure"],
                "quality_score": r.quality_score,
                "keyword_coverage": r.keyword_coverage,
                "speed_score": r.speed_score,
                "composite_score": r.composite_score,
                "weakness_tags": "|".join(r.weakness_tags),
                "comment": r.comment,
            })
    logger.info("ジョブ別 CSV 保存: %s (%d rows)", out_csv, len(results))

    # ---- 手法別ランキング CSV ----
    by_method: dict[str, list[EvaluationResult]] = {}
    for r in results:
        by_method.setdefault(r.method_id, []).append(r)
    ranking_rows = []
    for mid, lst in by_method.items():
        n = len(lst)
        ranking_rows.append({
            "method_id": mid,
            "method_name": lst[0].method_name,
            "n": n,
            "avg_relevance":    round(sum(r.scores["relevance"] for r in lst) / n, 2),
            "avg_accuracy":     round(sum(r.scores["accuracy"] for r in lst) / n, 2),
            "avg_completeness": round(sum(r.scores["completeness"] for r in lst) / n, 2),
            "avg_specificity":  round(sum(r.scores["specificity"] for r in lst) / n, 2),
            "avg_structure":    round(sum(r.scores["structure"] for r in lst) / n, 2),
            "avg_quality":      round(sum(r.quality_score for r in lst) / n, 3),
            "avg_keyword":      round(sum(r.keyword_coverage for r in lst) / n, 3),
            "avg_speed":        round(sum(r.speed_score for r in lst) / n, 3),
            "avg_composite":    round(sum(r.composite_score for r in lst) / n, 2),
            "top_weakness_tags": ",".join(_top_weakness(lst, n=3)),
        })
    ranking_rows.sort(key=lambda r: r["avg_composite"], reverse=True)
    rank_csv = config.OUTPUT_DIR / "evaluation_ranking.csv"
    cols2 = list(ranking_rows[0].keys()) if ranking_rows else []
    if cols2:
        with rank_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols2)
            w.writeheader()
            w.writerows(ranking_rows)
        logger.info("手法ランキング CSV 保存: %s", rank_csv)

    # ---- 標準出力にもランキング表示 ----
    print()
    print(f"{'rank':>4} {'method':6} {'name':<22} {'composite':>10} {'quality':>8} {'keyword':>8} {'speed':>6}  top_weakness")
    print("-" * 105)
    for i, r in enumerate(ranking_rows, 1):
        print(f"{i:>4} {r['method_id']:6} {r['method_name']:<22} "
              f"{r['avg_composite']:>10.2f} {r['avg_quality']:>8.2f} {r['avg_keyword']:>8.2f} {r['avg_speed']:>6.2f}  "
              f"{r['top_weakness_tags']}")


def _top_weakness(items: list[EvaluationResult], n: int = 3) -> list[str]:
    from collections import Counter
    c: Counter[str] = Counter()
    for r in items:
        c.update(r.weakness_tags)
    return [t for t, _ in c.most_common(n)]


if __name__ == "__main__":
    main()
