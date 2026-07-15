"""RAG ベンチマーク CLI エントリポイント.

全 11 手法 × 全 20 クエリを実行し、結果を JSON / CSV に保存する.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from . import config
from .generator.answer_generator import generate_answer
from .query_set import QUERY_SET, get_queries_by_ids
from .retrievers import RETRIEVER_REGISTRY, BenchmarkResult, GenerationResult
from .retrievers.base import BaseRetriever
from .utils.context_compressor import ContextCompressor
from .utils.llm_client import get_llm_client
from .utils.neo4j_client import get_neo4j_client
from .utils.token_counter import count_tokens

logger = logging.getLogger("rag_benchmark")


# =============================================================================
# ログ設定
# =============================================================================

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
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


# =============================================================================
# ファイル名規約
# =============================================================================

_METHOD_FILE_SUFFIX = {
    "R01": "naive_vector",
    "R02": "vector_reranker",
    "R03": "hyde",
    "R04": "graphrag_local",
    "R05": "graphrag_global",
    "R06": "lightrag_hybrid",
    "R07": "contextual_retrieval",
    "R08": "agentic_rag",
    "R09": "raptor",
    "R10": "self_rag",
    "R11": "corrective_rag",
    "R12": "rag_fusion",
    "R13": "adaptive_ensemble",
}


def _result_json_path(method_id: str) -> Path:
    suffix = _METHOD_FILE_SUFFIX.get(method_id, method_id.lower())
    return config.RESULTS_DIR / f"{method_id}_{suffix}.json"


# =============================================================================
# 個別実行
# =============================================================================

def run_query_for_method(
    retriever: BaseRetriever,
    query: dict,
    dry_run: bool,
    enable_compression: bool = True,
) -> BenchmarkResult:
    method_id = retriever.method_id
    method_name = retriever.method_name
    query_id = query["id"]
    logger.info("[%s] %s 開始", method_id, query_id)
    t_total = time.perf_counter()

    try:
        ret = retriever.retrieve(query["query"])
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] %s Retrieval エラー", method_id, query_id)
        from .retrievers.base import RetrievalResult
        ret = RetrievalResult(
            contexts=[f"[ERROR] {e}"],
            source_deal_ids=[],
            retrieval_time_ms=-1.0,
            context_token_count=0,
            metadata={"error": str(e)},
        )

    # ── コンテキスト圧縮 (Generation 前) ──
    # Self-RAG など pre_generated_answer がある手法はスキップ
    if (
        enable_compression
        and config.ENABLE_CONTEXT_COMPRESSION
        and ret.pre_generated_answer is None
        and ret.context_token_count > 0
    ):
        threshold = int(config.CONTEXT_MAX_TOKENS * config.COMPRESSION_THRESHOLD_RATIO)
        if ret.context_token_count > threshold:
            compressor = ContextCompressor(retriever.llm, config.COMPRESSION_MAX_CHARS)
            try:
                new_contexts, comp_info = compressor.compress(
                    query["query"], ret.contexts, threshold,
                )
                ret.contexts = new_contexts
                ret.context_token_count = comp_info["after_tokens"]
                ret.metadata["compression"] = comp_info
                logger.info(
                    "[%s %s] context compressed: %d→%d tokens",
                    method_id, query_id,
                    comp_info["before_tokens"], comp_info["after_tokens"],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s %s] compression failed: %s", method_id, query_id, e)

    if dry_run:
        gen = GenerationResult(
            answer="[DRY-RUN] generation skipped",
            generation_time_ms=0.0,
            input_tokens=0,
            output_tokens=0,
            model="(dry-run)",
        )
    elif ret.pre_generated_answer is not None:
        # Retriever が内部で生成済み (Self-RAG 等). 外部生成はスキップして採用.
        gen = GenerationResult(
            answer=ret.pre_generated_answer,
            generation_time_ms=0.0,  # 計測は retrieval_time に含まれる
            input_tokens=ret.pre_gen_input_tokens,
            output_tokens=ret.pre_gen_output_tokens,
            model=ret.pre_gen_model or "(pre-generated)",
        )
    else:
        try:
            gen = generate_answer(retriever.llm, query["query"], ret.contexts)
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] %s Generation エラー", method_id, query_id)
            gen = GenerationResult(
                answer=f"[ERROR] {e}",
                generation_time_ms=-1.0,
                input_tokens=0,
                output_tokens=0,
                model="(error)",
            )

    total_ms = (time.perf_counter() - t_total) * 1000.0
    return BenchmarkResult(
        query_id=query_id,
        query_text=query["query"],
        query_type=query["type"],
        method_id=method_id,
        method_name=method_name,
        retrieval=ret,
        generation=gen,
        total_time_ms=total_ms,
    )


def _to_serializable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: _to_serializable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


def save_method_results(method_id: str, method_name: str, retriever_cfg: dict,
                        results: list[BenchmarkResult]) -> Path:
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _result_json_path(method_id)
    if path.exists():
        backup = path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak.json")
        shutil.copy2(path, backup)
        logger.info("既存結果をバックアップ: %s", backup.name)

    data = {
        "method_id": method_id,
        "method_name": method_name,
        "execution_timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": retriever_cfg,
        "results": [_to_serializable(r) for r in results],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("結果保存: %s (%d results)", path, len(results))
    return path


# =============================================================================
# CSV 集計
# =============================================================================

def aggregate_csv(
    methods: list[str] | None = None,
    output_csv: Path | None = None,
) -> Path:
    """全手法 JSON から all_results.csv を再生成."""
    output_csv = output_csv or config.SUMMARY_CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    method_ids = methods or list(RETRIEVER_REGISTRY.keys())
    rows: list[dict] = []
    for mid in method_ids:
        path = _result_json_path(mid)
        if not path.exists():
            logger.warning("結果 JSON が見つかりません: %s", path)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            ret = r.get("retrieval", {}) or {}
            gen = r.get("generation", {}) or {}
            ans_text = gen.get("answer", "") or ""
            rows.append({
                "query_id": r.get("query_id"),
                "query_type": r.get("query_type"),
                "method_id": r.get("method_id"),
                "method_name": r.get("method_name"),
                "retrieval_time_ms": round(ret.get("retrieval_time_ms", -1), 2),
                "generation_time_ms": round(gen.get("generation_time_ms", -1), 2),
                "total_time_ms": round(r.get("total_time_ms", -1), 2),
                "context_token_count": ret.get("context_token_count", 0),
                "input_tokens": gen.get("input_tokens", 0),
                "output_tokens": gen.get("output_tokens", 0),
                "source_deal_count": len(ret.get("source_deal_ids") or []),
                "answer_preview": ans_text[:200].replace("\n", " "),
            })
    if not rows:
        logger.warning("集計対象が 0 件です")
    else:
        cols = list(rows[0].keys())
        with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        logger.info("集計 CSV 保存: %s (%d rows)", output_csv, len(rows))
    return output_csv


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="rag_benchmark",
        description="Neo4j ベース RAG 11 手法のベンチマーク実行",
    )
    p.add_argument("--all", action="store_true", help="全手法 × 全クエリ実行")
    p.add_argument(
        "--methods", nargs="+", choices=list(RETRIEVER_REGISTRY.keys()),
        help="実行する手法 ID (R01〜R11)",
    )
    p.add_argument("--queries", nargs="+", help="実行するクエリ ID (Q01〜Q20)")
    p.add_argument("--repeat", type=int, default=1, help="各クエリの繰り返し回数")
    p.add_argument(
        "--concurrency", type=int, default=1, metavar="N",
        help="1 手法内でクエリを並列実行する数 (デフォルト 1 = 直列). "
             "Azure OpenAI レート制限を考慮し 2-4 程度を推奨",
    )
    p.add_argument("--dry-run", action="store_true", help="Retrieval のみ、Generation 行わない")
    p.add_argument("--aggregate-only", action="store_true", help="既存 JSON から CSV のみ再生成")
    p.add_argument("--no-compression", action="store_true",
                   help="config.ENABLE_CONTEXT_COMPRESSION を無効化 (この実行のみ)")
    p.add_argument("--no-okng-filter", action="store_true",
                   help="config.ENABLE_OKNG_FILTER を無効化 (この実行のみ)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--log-file", type=Path, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(args.verbose, args.log_file)

    # この実行のみ共通フラグを上書き
    if args.no_compression:
        config.ENABLE_CONTEXT_COMPRESSION = False
    if args.no_okng_filter:
        config.ENABLE_OKNG_FILTER = False

    if args.aggregate_only:
        aggregate_csv(methods=args.methods)
        return

    method_ids = (
        list(RETRIEVER_REGISTRY.keys()) if args.all else (args.methods or list(RETRIEVER_REGISTRY.keys()))
    )
    queries = get_queries_by_ids(args.queries)
    repeat = max(1, args.repeat)
    concurrency = max(1, args.concurrency)
    logger.info(
        "実行計画: %d 手法 × %d クエリ × %d 回 = %d ジョブ (dry_run=%s, concurrency=%d, compression=%s, okng_filter=%s)",
        len(method_ids), len(queries), repeat,
        len(method_ids) * len(queries) * repeat, args.dry_run, concurrency,
        config.ENABLE_CONTEXT_COMPRESSION, config.ENABLE_OKNG_FILTER,
    )

    neo4j = get_neo4j_client()
    llm = get_llm_client()

    try:
        for mid in method_ids:
            ret_cls = RETRIEVER_REGISTRY[mid]
            cfg = config.RETRIEVER_CONFIGS.get(mid, {})
            retriever = ret_cls(neo4j, llm, cfg)
            results: list[BenchmarkResult] = []
            label = f"{mid} {retriever.method_name}"

            # ジョブ列 (query × rep) を作成. 表示順は実行順を保つため (q, rep) インデックス付き.
            jobs: list[tuple[int, dict, int]] = []
            idx = 0
            for q in queries:
                for rep in range(repeat):
                    jobs.append((idx, q, rep))
                    idx += 1

            def _log_one(res: BenchmarkResult, q: dict, rep: int) -> None:
                logger.info(
                    "[%s %s rep=%d] total=%.1fms ret=%.1fms gen=%.1fms tokens(ctx/in/out)=%d/%d/%d",
                    mid, q["id"], rep + 1, res.total_time_ms,
                    res.retrieval.retrieval_time_ms, res.generation.generation_time_ms,
                    res.retrieval.context_token_count,
                    res.generation.input_tokens, res.generation.output_tokens,
                )

            if concurrency <= 1:
                # ── 直列実行 ──
                for _, q, rep in tqdm(jobs, desc=label, leave=False, ascii=True):
                    res = run_query_for_method(retriever, q, args.dry_run, enable_compression=True)
                    results.append(res)
                    _log_one(res, q, rep)
            else:
                # ── 並列実行 (1 手法内, ThreadPoolExecutor) ──
                # 注意: retrievers は self.neo4j / self.llm を読むだけで状態を持たない前提.
                # Neo4j Driver / openai.AzureOpenAI client はスレッドセーフ.
                results_by_idx: dict[int, BenchmarkResult] = {}
                with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=f"{mid}-job") as ex:
                    fut_to_meta = {
                        ex.submit(run_query_for_method, retriever, q, args.dry_run, True): (i, q, rep)
                        for i, q, rep in jobs
                    }
                    with tqdm(total=len(fut_to_meta), desc=label, leave=False, ascii=True) as pbar:
                        for fut in as_completed(fut_to_meta):
                            i, q, rep = fut_to_meta[fut]
                            try:
                                res = fut.result()
                            except Exception as e:  # noqa: BLE001
                                logger.exception("[%s %s rep=%d] ジョブ例外: %s", mid, q["id"], rep + 1, e)
                                from .retrievers.base import RetrievalResult
                                res = BenchmarkResult(
                                    query_id=q["id"], query_text=q["query"], query_type=q["type"],
                                    method_id=mid, method_name=retriever.method_name,
                                    retrieval=RetrievalResult([], [], -1.0, 0, {"error": str(e)}),
                                    generation=GenerationResult(f"[ERROR] {e}", -1.0, 0, 0, "(error)"),
                                    total_time_ms=-1.0,
                                )
                            results_by_idx[i] = res
                            _log_one(res, q, rep)
                            pbar.update(1)
                # 元の順序で並べ替え
                results = [results_by_idx[i] for i in sorted(results_by_idx)]

            save_method_results(mid, retriever.method_name, cfg, results)

        aggregate_csv(methods=method_ids)
    finally:
        neo4j.close()


if __name__ == "__main__":
    main()
