"""Q01 のスモークテスト結果を一覧表示."""
import json
from pathlib import Path

RESULTS = Path(__file__).parent.parent / "output" / "results"

rows = []
for p in sorted(RESULTS.glob("R*.json")):
    if "bak" in p.name:
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    for r in data["results"]:
        rows.append(r)

print(f"{'method':<28} {'q':<4} {'ret_ms':>8} {'gen_ms':>8} {'ctx_tok':>7} {'in_tok':>7} {'out_tok':>7} {'deals':>5}  preview")
print("-" * 120)
for r in rows:
    name = f"{r['method_id']} {r['method_name'][:22]}"
    ans = (r['generation']['answer'] or "").replace("\n", " ")[:60]
    print(
        f"{name:<28} {r['query_id']:<4} "
        f"{r['retrieval']['retrieval_time_ms']:>8.0f} "
        f"{r['generation']['generation_time_ms']:>8.0f} "
        f"{r['retrieval']['context_token_count']:>7} "
        f"{r['generation']['input_tokens']:>7} "
        f"{r['generation']['output_tokens']:>7} "
        f"{len(r['retrieval']['source_deal_ids']):>5}  "
        f"{ans}"
    )

# 各手法の総時間
print("\n=== 総時間 (Q01) ===")
total_per_method = {}
for r in rows:
    mid = r['method_id']
    total_per_method.setdefault(mid, 0)
    total_per_method[mid] += r['total_time_ms']
for mid, t in sorted(total_per_method.items()):
    print(f"  {mid}: {t / 1000:.1f}s")
print(f"  合計: {sum(total_per_method.values()) / 1000:.1f}s")
