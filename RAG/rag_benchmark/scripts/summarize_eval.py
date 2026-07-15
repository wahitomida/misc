"""評価結果サマリ + 弱点タグの全体集計."""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# rag_benchmark をパッケージとして import できるよう sys.path を追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

OUTPUT = Path(r"C:\Users\hitomi\source\eigyo\RAG\rag_benchmark\output")

# ========== ランキング ==========
rank_csv = OUTPUT / "evaluation_ranking.csv"
rank_rows = list(csv.DictReader(rank_csv.open(encoding="utf-8-sig")))

print("=" * 110)
print("【 RAG 11 手法 総合ランキング 】(composite_score = quality * 0.7 + keyword * 0.15 + speed * 0.15) × 100")
print("=" * 110)
print(f"{'rank':>4} {'ID':4} {'手法名':<22} {'合成':>6} {'品質':>6} {'KW':>5} {'速度':>5} | "
      f"{'関連':>4} {'正確':>4} {'網羅':>4} {'具体':>4} {'構造':>4}  top 弱点")
print("-" * 110)
for i, r in enumerate(rank_rows, 1):
    print(f"{i:>4} {r['method_id']:4} {r['method_name']:<22} "
          f"{float(r['avg_composite']):>6.2f} "
          f"{float(r['avg_quality'])*100:>6.1f} "
          f"{float(r['avg_keyword'])*100:>5.1f} "
          f"{float(r['avg_speed'])*100:>5.1f} | "
          f"{float(r['avg_relevance']):>4.1f} {float(r['avg_accuracy']):>4.1f} "
          f"{float(r['avg_completeness']):>4.1f} {float(r['avg_specificity']):>4.1f} "
          f"{float(r['avg_structure']):>4.1f}  "
          f"{r['top_weakness_tags']}")

# ========== 弱点タグの全体集計 ==========
print()
print("=" * 110)
print("【 弱点タグ 全体集計 (220 件) 】")
print("=" * 110)
sum_csv = OUTPUT / "evaluation_summary.csv"
all_rows = list(csv.DictReader(sum_csv.open(encoding="utf-8-sig")))
tag_counter: Counter[str] = Counter()
for r in all_rows:
    if r["weakness_tags"]:
        for t in r["weakness_tags"].split("|"):
            t = t.strip()
            if t:
                tag_counter[t] += 1
for t, c in tag_counter.most_common(15):
    pct = 100.0 * c / len(all_rows)
    print(f"  {t:<22} {c:>3} 件  ({pct:>5.1f}%)")

# ========== クエリ別ベスト手法 ==========
print()
print("=" * 110)
print("【 クエリ別ベスト手法 (composite_score 最高) 】")
print("=" * 110)
by_query: dict[str, list[dict]] = defaultdict(list)
for r in all_rows:
    by_query[r["query_id"]].append(r)
print(f"{'Q':4} {'type':<10} {'best':4} {'method':<22} {'comp':>5} {'品質':>5} {'KW':>5} | 質問")

# クエリ本文を取得
from misc_26.RAG.rag_benchmark.query_set import QUERY_SET
q_text = {q["id"]: (q["query"], q["type"]) for q in QUERY_SET}

for qid in sorted(by_query):
    rows = sorted(by_query[qid], key=lambda r: float(r["composite_score"]), reverse=True)
    best = rows[0]
    qtext, qtype = q_text.get(qid, ("?", "?"))
    print(f"{qid:4} {qtype:<10} {best['method_id']:4} {best['method_name']:<22} "
          f"{float(best['composite_score']):>5.1f} "
          f"{float(best['quality_score'])*100:>5.1f} "
          f"{float(best['keyword_coverage'])*100:>5.1f} | {qtext[:50]}")
