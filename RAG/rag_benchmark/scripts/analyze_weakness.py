"""手法別の弱点深掘り分析: 5軸別の詳細スコア + 弱点タグの手法別集計."""
import csv
from collections import Counter, defaultdict
from pathlib import Path

OUTPUT = Path(r"C:\Users\hitomi\source\eigyo\RAG\rag_benchmark\output")
all_rows = list(csv.DictReader((OUTPUT / "evaluation_summary.csv").open(encoding="utf-8-sig")))

# 手法別の弱点タグ分布
print("=" * 100)
print("【 手法別 弱点タグ分布 (タグ出現件数 / 20 ジョブ) 】")
print("=" * 100)
by_method_tags: dict[str, Counter[str]] = defaultdict(Counter)
for r in all_rows:
    mid = r["method_id"]
    for t in (r["weakness_tags"] or "").split("|"):
        t = t.strip()
        if t:
            by_method_tags[mid][t] += 1
for mid in sorted(by_method_tags):
    top = by_method_tags[mid].most_common(5)
    print(f"  {mid}: " + ", ".join(f"{t}({c})" for t, c in top))

# 5軸スコアの手法別詳細
print()
print("=" * 100)
print("【 手法別 5軸スコア詳細 + 標準偏差 】")
print("=" * 100)
import statistics
print(f"{'ID':4} {'関連':>10} {'正確':>10} {'網羅':>10} {'具体':>10} {'構造':>10}")
by_method_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
for r in all_rows:
    mid = r["method_id"]
    for axis in ("relevance", "accuracy", "completeness", "specificity", "structure"):
        by_method_scores[mid][axis].append(float(r[axis]))
for mid in sorted(by_method_scores):
    parts = []
    for axis in ("relevance", "accuracy", "completeness", "specificity", "structure"):
        vals = by_method_scores[mid][axis]
        m = statistics.mean(vals)
        s = statistics.stdev(vals) if len(vals) > 1 else 0
        parts.append(f"{m:>5.1f}±{s:>3.1f}")
    print(f"{mid:4} " + " ".join(parts))

# 失敗ケース (composite < 50) の手法別件数
print()
print("=" * 100)
print("【 composite < 50 の失敗ケース 手法別件数 】")
print("=" * 100)
fail_by_method: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
for r in all_rows:
    c = float(r["composite_score"])
    if c < 50:
        fail_by_method[r["method_id"]].append((r["query_id"], c, r["weakness_tags"]))
for mid in sorted(fail_by_method):
    cnt = len(fail_by_method[mid])
    print(f"  {mid}: {cnt} 件")
    for qid, c, tags in fail_by_method[mid][:5]:
        print(f"    {qid} composite={c:.1f} tags={tags}")

# クエリ type 別の平均 composite
print()
print("=" * 100)
print("【 手法 × クエリタイプ (specific/global) 別 平均 composite 】")
print("=" * 100)
sys_path_root = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(sys_path_root))
from misc_26.RAG.rag_benchmark.query_set import QUERY_SET
q_type = {q["id"]: q["type"] for q in QUERY_SET}

agg: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
for r in all_rows:
    mid = r["method_id"]
    qid = r["query_id"]
    t = q_type.get(qid, "?")
    agg[mid][t].append(float(r["composite_score"]))

print(f"{'ID':4} {'specific':>10} {'global':>10} {'差':>6}")
for mid in sorted(agg):
    sp = statistics.mean(agg[mid].get("specific", [0]))
    gl = statistics.mean(agg[mid].get("global", [0]))
    print(f"{mid:4} {sp:>10.2f} {gl:>10.2f} {sp - gl:>6.2f}")

# keyword 0 の手法別カウント
print()
print("=" * 100)
print("【 KW 一致率 0 (キーワード皆無の回答) の手法別件数 】")
print("=" * 100)
kw_zero: dict[str, int] = defaultdict(int)
for r in all_rows:
    if float(r["keyword_coverage"]) == 0.0:
        kw_zero[r["method_id"]] += 1
for mid in sorted(kw_zero):
    print(f"  {mid}: {kw_zero[mid]} 件")
