"""全 Q 技術検討書のための集計スクリプト. v2 評価 + NEW results を統合."""
from __future__ import annotations
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# Windows console の cp932 エラー回避
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(r"c:\Users\hitomi\source\eigyo\RAG\rag_benchmark")
OUT = ROOT / "output"
RESULTS = OUT / "results"
DOCS = ROOT / "docs"

# query_set 取得（importできるが面倒なので直書きでも可。ここではjson読み）
sys.path.insert(0, str(ROOT.parent))
from misc_26.RAG.rag_benchmark.query_set import QUERY_SET  # type: ignore

# v2 summary 読み込み
v2_rows: list[dict] = []
with (OUT / "evaluation_v2_summary.csv").open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        for k in ("context_precision","context_recall","context_relevancy","retrieval_score",
                  "faithfulness","answer_relevancy","answer_completeness","generation_score",
                  "hallucination_rate","keyword_coverage","latency_ms","composite_score"):
            r[k] = float(r[k])
        v2_rows.append(r)

# Q別×手法別の v2 スコア
by_qm: dict[tuple[str,str], dict] = {(r["query_id"], r["method_id"]): r for r in v2_rows}

# クエリ別ランキング（composite降順）
by_q: dict[str, list[dict]] = defaultdict(list)
for r in v2_rows:
    by_q[r["query_id"]].append(r)
for q in by_q:
    by_q[q].sort(key=lambda x: -x["composite_score"])

# 手法別の Q ごと
by_m: dict[str, list[dict]] = defaultdict(list)
for r in v2_rows:
    by_m[r["method_id"]].append(r)

# v2 手法別ランキング
v2_rank: list[dict] = []
with (OUT / "evaluation_v2_ranking.csv").open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        for k in ("n","context_precision","context_recall","context_relevancy","retrieval_score",
                  "faithfulness","answer_relevancy","answer_completeness","generation_score",
                  "hallucination_rate","keyword_coverage","composite_score","avg_latency_ms"):
            r[k] = float(r[k])
        v2_rank.append(r)
v2_rank.sort(key=lambda x: -x["composite_score"])

# 全 Q 揃っているのは v2_evaluated_snapshot/*.bak.json のほう (OLD)
# NEW results は Q01 のみ
SNAPSHOT = OUT / "v2_evaluated_snapshot"

def load_answers() -> dict[tuple[str,str], dict]:
    out: dict[tuple[str,str], dict] = {}
    for p in sorted(SNAPSHOT.glob("R*.bak.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data["results"]:
            out[(r["query_id"], r["method_id"])] = {
                "answer": r["generation"]["answer"],
                "source_deal_ids": r["retrieval"]["source_deal_ids"],
                "context_token_count": r["retrieval"]["context_token_count"],
                "retrieval_time_ms": r["retrieval"]["retrieval_time_ms"],
                "generation_time_ms": r["generation"]["generation_time_ms"],
                "total_time_ms": r["total_time_ms"],
            }
    # NEW results の Q01 のみ上書き（NEW 改善版があるなら優先）
    for p in sorted(RESULTS.glob("R*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data["results"]:
            out[(r["query_id"], r["method_id"])] = {
                "answer": r["generation"]["answer"],
                "source_deal_ids": r["retrieval"]["source_deal_ids"],
                "context_token_count": r["retrieval"]["context_token_count"],
                "retrieval_time_ms": r["retrieval"]["retrieval_time_ms"],
                "generation_time_ms": r["generation"]["generation_time_ms"],
                "total_time_ms": r["total_time_ms"],
            }
    return out

new_ans = load_answers()

# === 出力 1: クエリ別の手法ランキングサマリ ===
print("=" * 110)
print("全 20 クエリ × 13 手法 v2 ランキング (composite_score 降順) ")
print("=" * 110)
for q in sorted(by_q):
    qmeta = next(x for x in QUERY_SET if x["id"] == q)
    print(f"\n--- {q} [{qmeta['type']}] {qmeta['query'][:60]}")
    print(f"    keywords: {qmeta['ground_truth_keywords']} / direction: {qmeta['expected_answer_direction']}")
    print(f"    {'rank':>4} {'M':<4} {'手法':<22} {'comp':>6} {'ret':>5} {'gen':>5} {'fait':>5} {'hal':>5} {'kw':>5} {'lat':>6} {'diag':<20}")
    for i, r in enumerate(by_q[q][:13], 1):
        print(f"    {i:>4} {r['method_id']:<4} {r['method_name']:<22} "
              f"{r['composite_score']:>6.1f} "
              f"{r['retrieval_score']:>5.2f} "
              f"{r['generation_score']:>5.2f} "
              f"{r['faithfulness']:>5.2f} "
              f"{r['hallucination_rate']:>5.2f} "
              f"{r['keyword_coverage']:>5.2f} "
              f"{r['latency_ms']/1000:>5.1f}s "
              f"{r['diagnosis']:<20}")

# === 出力 2: Q ごとのベスト手法と回答プレビュー ===
print("\n" + "=" * 110)
print("Q ごとのベスト手法 + 回答冒頭")
print("=" * 110)
for q in sorted(by_q):
    qmeta = next(x for x in QUERY_SET if x["id"] == q)
    best = by_q[q][0]
    worst = by_q[q][-1]
    ans_best = new_ans.get((q, best["method_id"]), {}).get("answer", "")[:200]
    ans_worst = new_ans.get((q, worst["method_id"]), {}).get("answer", "")[:200]
    print(f"\n{q} [{qmeta['type']}] {qmeta['query']}")
    print(f"  ベスト: {best['method_id']} {best['method_name']:<22} comp={best['composite_score']:.1f} ret={best['retrieval_score']:.2f} gen={best['generation_score']:.2f}")
    print(f"    答え: {ans_best[:150].replace(chr(10),' ')}")
    print(f"  ワースト: {worst['method_id']} {worst['method_name']:<22} comp={worst['composite_score']:.1f} ret={worst['retrieval_score']:.2f} gen={worst['generation_score']:.2f}")
    print(f"    答え: {ans_worst[:150].replace(chr(10),' ')}")

# === 出力 3: 手法別の Q ごと composite ヒートマップ ===
print("\n" + "=" * 110)
print("手法別 Q ごと composite_score ヒートマップ")
print("=" * 110)
qs = sorted({r["query_id"] for r in v2_rows})
print(f"  {'M':<4}|" + " ".join(f"{q[1:]:>5}" for q in qs) + " | avg")
print("-" * (5 + 6 * len(qs) + 8))
for m in sorted({r["method_id"] for r in v2_rows}):
    row = []
    avg = 0.0
    n = 0
    for q in qs:
        s = by_qm.get((q, m), {}).get("composite_score")
        if s is not None:
            row.append(f"{s:>5.1f}")
            avg += s
            n += 1
        else:
            row.append(f"{'--':>5}")
    avg = avg / n if n else 0
    print(f"  {m:<4}| " + " ".join(row) + f" | {avg:>5.1f}")

# === 出力 4: 手法別 retrieval_score / generation_score / hallucination ヒートマップ ===
for metric in ("retrieval_score", "generation_score", "hallucination_rate"):
    print("\n" + "=" * 110)
    print(f"手法別 Q ごと {metric}")
    print("=" * 110)
    print(f"  {'M':<4}|" + " ".join(f"{q[1:]:>5}" for q in qs) + " | avg")
    print("-" * (5 + 6 * len(qs) + 8))
    for m in sorted({r["method_id"] for r in v2_rows}):
        row = []
        avg = 0.0
        n = 0
        for q in qs:
            s = by_qm.get((q, m), {}).get(metric)
            if s is not None:
                row.append(f"{s:>5.2f}")
                avg += s
                n += 1
            else:
                row.append(f"{'--':>5}")
        avg = avg / n if n else 0
        print(f"  {m:<4}| " + " ".join(row) + f" | {avg:>5.2f}")
