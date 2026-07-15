"""改善前後の比較レポート生成."""
from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\hitomi\source\eigyo\RAG\rag_benchmark\output")
BEFORE = ROOT / "before_improvement"
AFTER = ROOT


def load_ranking(p: Path) -> dict[str, dict]:
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    out = {}
    for r in rows:
        for k in ("avg_relevance", "avg_accuracy", "avg_completeness",
                  "avg_specificity", "avg_structure", "avg_quality",
                  "avg_keyword", "avg_speed", "avg_composite"):
            r[k] = float(r[k])
        r["n"] = int(r["n"])
        out[r["method_id"]] = r
    return out


def load_summary(p: Path) -> list[dict]:
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    for r in rows:
        for k in ("relevance", "accuracy", "completeness", "specificity",
                  "structure", "quality_score", "keyword_coverage",
                  "speed_score", "composite_score"):
            r[k] = float(r[k])
    return rows


def load_all_results(p: Path) -> dict[tuple[str, str], dict]:
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    out = {}
    for r in rows:
        for k in ("total_time_ms", "retrieval_time_ms", "generation_time_ms",
                  "context_token_count", "input_tokens", "output_tokens"):
            if r.get(k) and r[k] != "":
                try:
                    r[k] = float(r[k])
                except ValueError:
                    pass
        out[(r["method_id"], r["query_id"])] = r
    return out


b_rank = load_ranking(BEFORE / "evaluation_ranking.csv")
a_rank = load_ranking(AFTER / "evaluation_ranking.csv")

b_sum = load_summary(BEFORE / "evaluation_summary.csv")
a_sum = load_summary(AFTER / "evaluation_summary.csv")

b_all = load_all_results(BEFORE / "all_results.csv")
a_all = load_all_results(AFTER / "all_results.csv")


# ------------------------------------------------------------
# 1. 総合スコアの比較
# ------------------------------------------------------------
print("=" * 90)
print("【 総合 composite スコア 改善前 → 改善後 】 (左から: 改善後ランク順)")
print("=" * 90)
print(f"{'ID':4} {'手法':24} {'BEFORE':>8} {'AFTER':>8} {'Δ':>8} {'順位変動':>10}")
print("-" * 90)

# 順位
b_order = sorted(b_rank.values(), key=lambda x: -x["avg_composite"])
a_order = sorted(a_rank.values(), key=lambda x: -x["avg_composite"])
b_pos = {r["method_id"]: i + 1 for i, r in enumerate(b_order)}
a_pos = {r["method_id"]: i + 1 for i, r in enumerate(a_order)}

for r in a_order:
    mid = r["method_id"]
    b = b_rank[mid]["avg_composite"]
    a = r["avg_composite"]
    delta = a - b
    bp, ap = b_pos[mid], a_pos[mid]
    move = bp - ap  # 正なら上昇
    arrow = f"{bp}→{ap}"
    if move > 0:
        arrow += f" (↑{move})"
    elif move < 0:
        arrow += f" (↓{-move})"
    else:
        arrow += " (=)"
    sign = "+" if delta >= 0 else ""
    print(f"{mid:4} {r['method_name']:24} {b:>8.2f} {a:>8.2f} {sign}{delta:>6.2f} {arrow:>14}")

avg_b = statistics.mean(r["avg_composite"] for r in b_rank.values())
avg_a = statistics.mean(r["avg_composite"] for r in a_rank.values())
print("-" * 90)
print(f"{'平均':28} {'':>4} {avg_b:>8.2f} {avg_a:>8.2f} {'+' if avg_a-avg_b>=0 else ''}{avg_a-avg_b:>6.2f}")


# ------------------------------------------------------------
# 2. 5軸 + speed/keyword の細分化比較
# ------------------------------------------------------------
print()
print("=" * 110)
print("【 各軸の改善幅 (After - Before, ※ quality/speed/keyword は 0-1, 5軸は 0-10) 】")
print("=" * 110)
axes = ["avg_quality", "avg_keyword", "avg_speed",
        "avg_relevance", "avg_accuracy", "avg_completeness",
        "avg_specificity", "avg_structure"]
header = " ".join(f"{a.replace('avg_', '')[:9]:>10}" for a in axes)
print(f"{'ID':4} {header}")
for mid in sorted(a_rank):
    parts = []
    for ax in axes:
        d = a_rank[mid][ax] - b_rank[mid][ax]
        s = f"{'+' if d >= 0 else ''}{d:.3f}"
        parts.append(f"{s:>10}")
    print(f"{mid:4} {' '.join(parts)}")


# ------------------------------------------------------------
# 3. 速度比較 (retrieval_ms / total_ms)
# ------------------------------------------------------------
print()
print("=" * 90)
print("【 retrieval_ms 平均の改善 】")
print("=" * 90)
print(f"{'ID':4} {'BEFORE':>10} {'AFTER':>10} {'Δ':>10} {'削減率':>8}")

methods = sorted(a_rank.keys())
for mid in methods:
    b_vals = [v["retrieval_time_ms"] for (m, q), v in b_all.items()
              if m == mid and isinstance(v.get("retrieval_time_ms"), float)]
    a_vals = [v["retrieval_time_ms"] for (m, q), v in a_all.items()
              if m == mid and isinstance(v.get("retrieval_time_ms"), float)]
    bm = statistics.mean(b_vals) if b_vals else 0
    am = statistics.mean(a_vals) if a_vals else 0
    d = am - bm
    rate = (-d / bm * 100) if bm else 0
    print(f"{mid:4} {bm:>10.0f} {am:>10.0f} {d:>+10.0f} {rate:>+7.1f}%")


# ------------------------------------------------------------
# 4. 失敗 (composite<50) の変化
# ------------------------------------------------------------
print()
print("=" * 90)
print("【 失敗ジョブ (composite < 50) の手法別件数 】")
print("=" * 90)
b_fail = Counter(r["method_id"] for r in b_sum if r["composite_score"] < 50)
a_fail = Counter(r["method_id"] for r in a_sum if r["composite_score"] < 50)
all_ids = set(b_fail) | set(a_fail) | set(b_rank)
print(f"{'ID':4} {'BEFORE':>8} {'AFTER':>8} {'Δ':>6}")
for mid in sorted(all_ids):
    bv, av = b_fail.get(mid, 0), a_fail.get(mid, 0)
    print(f"{mid:4} {bv:>8} {av:>8} {av - bv:>+6}")
print(f"{'計':6} {sum(b_fail.values()):>6} {sum(a_fail.values()):>8} {sum(a_fail.values()) - sum(b_fail.values()):>+6}")


# ------------------------------------------------------------
# 5. 弱点タグの変化
# ------------------------------------------------------------
print()
print("=" * 90)
print("【 弱点タグ全体の出現回数 (Before / After) 】")
print("=" * 90)
def collect_tags(rows):
    c = Counter()
    for r in rows:
        for t in (r.get("weakness_tags") or "").split("|"):
            t = t.strip()
            if t:
                c[t] += 1
    return c

bt = collect_tags(b_sum)
at = collect_tags(a_sum)
keys = sorted(set(bt) | set(at), key=lambda k: -(bt.get(k, 0) + at.get(k, 0)))
print(f"{'タグ':16} {'BEFORE':>8} {'AFTER':>8} {'Δ':>6}")
for k in keys[:15]:
    bv, av = bt.get(k, 0), at.get(k, 0)
    print(f"{k:16} {bv:>8} {av:>8} {av - bv:>+6}")


# ------------------------------------------------------------
# 6. クエリ別の改善ヒートマップ風
# ------------------------------------------------------------
print()
print("=" * 110)
print("【 各手法 × 各クエリの composite Δ (After - Before)  +大幅改善 -悪化 】")
print("=" * 110)

# クエリリスト
qids = sorted(set(r["query_id"] for r in b_sum))
print(f"{'ID':4} " + " ".join(f"{q:>4}" for q in qids))
for mid in sorted(a_rank):
    b_q = {r["query_id"]: r["composite_score"] for r in b_sum if r["method_id"] == mid}
    a_q = {r["query_id"]: r["composite_score"] for r in a_sum if r["method_id"] == mid}
    parts = []
    for q in qids:
        d = a_q.get(q, 0) - b_q.get(q, 0)
        if abs(d) < 0.5:
            parts.append(f"  ・ ")
        elif d > 0:
            parts.append(f"{'+' + str(round(d)):>4}")
        else:
            parts.append(f"{round(d):>4}")
    print(f"{mid:4} " + " ".join(parts))


# ------------------------------------------------------------
# 7. クエリ別ベスト手法の変化
# ------------------------------------------------------------
print()
print("=" * 90)
print("【 クエリ別 best 手法 】")
print("=" * 90)
print(f"{'QID':6} {'BEFORE 1位':28} {'AFTER 1位':28} {'BEFORE→AFTER スコア':>22}")
b_by_q = defaultdict(list)
a_by_q = defaultdict(list)
for r in b_sum:
    b_by_q[r["query_id"]].append(r)
for r in a_sum:
    a_by_q[r["query_id"]].append(r)
for q in qids:
    b_best = max(b_by_q[q], key=lambda x: x["composite_score"])
    a_best = max(a_by_q[q], key=lambda x: x["composite_score"])
    b_label = f"{b_best['method_id']} ({b_best['composite_score']:.1f})"
    a_label = f"{a_best['method_id']} ({a_best['composite_score']:.1f})"
    changed = "" if b_best['method_id'] == a_best['method_id'] else "  ★交代"
    print(f"{q:6} {b_label:22} → {a_label:22} {changed}")


# ------------------------------------------------------------
# 8. CSV 出力
# ------------------------------------------------------------
out_csv = ROOT / "comparison_report.csv"
with out_csv.open("w", encoding="utf-8-sig", newline="") as fp:
    w = csv.writer(fp)
    w.writerow(["method_id", "method_name",
                "before_composite", "after_composite", "delta_composite",
                "before_rank", "after_rank",
                "before_quality", "after_quality", "delta_quality",
                "before_keyword", "after_keyword", "delta_keyword",
                "before_speed", "after_speed", "delta_speed",
                "before_specificity", "after_specificity", "delta_specificity",
                "before_completeness", "after_completeness", "delta_completeness",
                ])
    for mid in sorted(a_rank):
        b = b_rank[mid]; a = a_rank[mid]
        w.writerow([
            mid, a["method_name"],
            f"{b['avg_composite']:.2f}", f"{a['avg_composite']:.2f}", f"{a['avg_composite']-b['avg_composite']:+.2f}",
            b_pos[mid], a_pos[mid],
            f"{b['avg_quality']:.3f}", f"{a['avg_quality']:.3f}", f"{a['avg_quality']-b['avg_quality']:+.3f}",
            f"{b['avg_keyword']:.3f}", f"{a['avg_keyword']:.3f}", f"{a['avg_keyword']-b['avg_keyword']:+.3f}",
            f"{b['avg_speed']:.3f}", f"{a['avg_speed']:.3f}", f"{a['avg_speed']-b['avg_speed']:+.3f}",
            f"{b['avg_specificity']:.2f}", f"{a['avg_specificity']:.2f}", f"{a['avg_specificity']-b['avg_specificity']:+.2f}",
            f"{b['avg_completeness']:.2f}", f"{a['avg_completeness']:.2f}", f"{a['avg_completeness']-b['avg_completeness']:+.2f}",
        ])
print()
print(f"比較 CSV: {out_csv}")
