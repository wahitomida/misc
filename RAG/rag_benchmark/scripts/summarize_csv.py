"""all_results.csv の確認と簡易集計."""
import csv
from pathlib import Path
from collections import defaultdict

CSV = Path(r"C:\Users\hitomi\source\eigyo\RAG\rag_benchmark\output\all_results.csv")
rows = list(csv.DictReader(CSV.open(encoding="utf-8-sig")))
print(f"総行数: {len(rows)}")
print(f"カラム: {list(rows[0].keys())}")
print()

# 手法別の集計
agg = defaultdict(lambda: {"count": 0, "ret_ms": 0.0, "gen_ms": 0.0, "total_ms": 0.0,
                            "ctx_tok": 0, "in_tok": 0, "out_tok": 0, "deals": 0})
for r in rows:
    mid = r["method_id"]
    a = agg[mid]
    a["count"] += 1
    a["ret_ms"] += float(r["retrieval_time_ms"])
    a["gen_ms"] += float(r["generation_time_ms"])
    a["total_ms"] += float(r["total_time_ms"])
    a["ctx_tok"] += int(r["context_token_count"])
    a["in_tok"] += int(r["input_tokens"])
    a["out_tok"] += int(r["output_tokens"])
    a["deals"] += int(r["source_deal_count"])
    a["name"] = r["method_name"]

print(f"{'method':6} {'name':<22} {'n':>3} {'avg_ret':>9} {'avg_gen':>9} {'avg_total':>10} {'avg_ctx':>8} {'avg_in':>8} {'avg_out':>8} {'avg_deals':>9}")
print("-" * 110)
for mid in sorted(agg):
    a = agg[mid]
    n = a["count"]
    print(f"{mid:6} {a['name']:<22} {n:>3} "
          f"{a['ret_ms']/n:>8.0f}ms {a['gen_ms']/n:>8.0f}ms {a['total_ms']/n:>9.0f}ms "
          f"{a['ctx_tok']/n:>8.0f} {a['in_tok']/n:>8.0f} {a['out_tok']/n:>8.0f} "
          f"{a['deals']/n:>9.1f}")

# クエリ別の手法カバレッジ
print()
queries = defaultdict(set)
for r in rows:
    queries[r["query_id"]].add(r["method_id"])
all_methods = sorted({r["method_id"] for r in rows})
print(f"クエリ数: {len(queries)}, 手法数: {len(all_methods)}")
missing = [q for q, ms in queries.items() if len(ms) < len(all_methods)]
if missing:
    print(f"未完了クエリ: {missing}")
else:
    print(f"全 {len(queries)} クエリ × {len(all_methods)} 手法 = {len(queries)*len(all_methods)} 件 揃った")
