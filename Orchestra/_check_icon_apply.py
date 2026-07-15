"""サブステップ 3 試験適用検証: 500.html / header.html / file_drop.html / toast.html
のマクロ展開確認。
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent / "web" / "templates"

env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

# 1) 500.html を load + render
tpl_500 = env.get_template("errors/500.html")
print("[OK] 500.html load")

# base.html は request グローバル参照するので、簡易的な dummy を渡す
rendered_500 = tpl_500.render(request=None, error_detail="Test error")
print("[OK] 500.html render", len(rendered_500), "chars")

# 検証: exclamation-triangle の path が展開されたか
assert "M12 9v3.75" in rendered_500, "exclamation-triangle SVG が展開されていない"
assert "w-24 h-24 mb-6 text-red-500" in rendered_500, "custom class が適用されていない"
# 検証: もう手書き SVG は存在しないか (macro 経由になったか)
handwritten_count = rendered_500.count(
    '<svg class="w-24 h-24 mb-6 text-red-500 dark:text-red-400"'
)
assert handwritten_count == 0, f"手書き SVG が残っている: {handwritten_count}"
# macro 経由の svg (xmlns 属性つき) が 1 つあるはず
macro_svg_count = rendered_500.count("xmlns=\"http://www.w3.org/2000/svg\"")
assert macro_svg_count >= 1, f"macro SVG が展開されていない (count={macro_svg_count})"
print("[OK] 500.html: exclamation-triangle SVG が macro 経由で展開された")

# 2) header.html を load + render (単体、base に組み込まず)
tpl_header = env.get_template("partials/header.html")
print("[OK] header.html load")

rendered_header = tpl_header.render(request=None)
print("[OK] header.html render", len(rendered_header), "chars")

# 検証: 3 箇所の macro (moon x2, sun x2, bars-3 x1) が展開されたか
# moon の d 属性
assert "M21.752 15.002" in rendered_header, "moon SVG が展開されていない"
# sun の d 属性
assert "M12 3v2.25m6.364" in rendered_header, "sun SVG が展開されていない"
# bars-3 の d 属性
assert "M3.75 6.75h16.5" in rendered_header, "bars-3 SVG が展開されていない"

# 絵文字が残っていないか
for emoji in ("🌙", "☀", "☰"):
    assert emoji not in rendered_header, f"絵文字 {emoji!r} が header.html に残っている"
print("[OK] header.html: 3 箇所 (moon/sun/bars-3) が macro 経由で展開・絵文字ゼロ")

# 3) file_drop.html を load + render (component 単体)
tpl_drop = env.get_template("components/file_drop.html")
print("[OK] file_drop.html load")
rendered_drop = tpl_drop.render()
print("[OK] file_drop.html render", len(rendered_drop), "chars")

# 検証: paper-clip, document, x-mark の d 属性が展開
assert "M18.375 12.739" in rendered_drop, "paper-clip SVG が展開されていない"
# document は 500 だと展開されない (500 は exclamation-triangle) が、file_drop では document が入る
assert "M19.5 14.25v-2.625" in rendered_drop, "document SVG が展開されていない"
assert "M6 18L18 6" in rendered_drop, "x-mark SVG が展開されていない"
# 絵文字ゼロ
for emoji in ("📎", "📄", "✕"):
    assert emoji not in rendered_drop, f"絵文字 {emoji!r} が file_drop.html に残っている"
print("[OK] file_drop.html: 3 箇所 (paper-clip/document/x-mark) が macro 経由・絵文字ゼロ")

# 4) partials/toast.html を load + render
tpl_toast = env.get_template("partials/toast.html")
print("[OK] toast.html load")
rendered_toast = tpl_toast.render()
print("[OK] toast.html render", len(rendered_toast), "chars")

# 検証: 4 status icon + x-mark の d 属性
# check-circle
assert "M9 12.75L11.25 15 15 9.75" in rendered_toast, "check-circle SVG が展開されていない"
# information-circle
assert "M11.25 11.25l.041-.02" in rendered_toast, "information-circle SVG が展開されていない"
# exclamation-triangle
assert "M12 9v3.75m-9.303 3.376" in rendered_toast, "exclamation-triangle SVG が展開されていない"
# x-circle
assert "M9.75 9.75l4.5 4.5" in rendered_toast, "x-circle SVG が展開されていない"
# x-mark
assert "M6 18L18 6" in rendered_toast, "x-mark SVG が展開されていない"
# 絵文字ゼロ
for emoji in ("✅", "ℹ", "⚠", "❌", "✕"):
    assert emoji not in rendered_toast, f"絵文字 {emoji!r} が toast.html に残っている"
print("[OK] toast.html: 5 箇所 (4 status + x-mark) が macro 経由・絵文字ゼロ")

# 5) hypothesis_table.html を load + render
tpl_hyp = env.get_template("components/hypothesis_table.html")
print("[OK] hypothesis_table.html load")
rendered_hyp = tpl_hyp.render()
print("[OK] hypothesis_table.html render", len(rendered_hyp), "chars")

# 検証: beaker, stop-circle, check-circle, x-circle, arrow-path の d 属性
assert "M9.75 3.104v5.714" in rendered_hyp, "beaker SVG が展開されていない"
assert "M9 9.563C9 9.252" in rendered_hyp, "stop-circle SVG が展開されていない"
assert "M9 12.75L11.25 15 15 9.75" in rendered_hyp, "check-circle SVG が展開されていない"
assert "M9.75 9.75l4.5 4.5" in rendered_hyp, "x-circle SVG が展開されていない"
assert "M16.023 9.348" in rendered_hyp, "arrow-path SVG が展開されていない"
# 絵文字ゼロ
for emoji in ("🔬", "🔲", "✅", "❌", "🔄"):
    assert emoji not in rendered_hyp, f"絵文字 {emoji!r} が hypothesis_table.html に残っている"
print("[OK] hypothesis_table.html: 5 箇所が macro 経由・絵文字ゼロ")

# 6) plan_card.html を load + render
tpl_plan = env.get_template("components/plan_card.html")
print("[OK] plan_card.html load")
rendered_plan = tpl_plan.render()
print("[OK] plan_card.html render", len(rendered_plan), "chars")

# 検証: 主要な macro 経由 SVG (代表 6 個の d 属性)
assert "M9 12h3.75" in rendered_plan, "clipboard-list SVG が展開されていない"
assert "M3 3v1.5M3 21v-6" in rendered_plan, "flag SVG が展開されていない"
assert "M21 7.5l-9-5.25" in rendered_plan, "cube SVG が展開されていない"
assert "M15 19.128" in rendered_plan, "user-group SVG が展開されていない"
assert "M9 9l10.5-3" in rendered_plan, "musical-note SVG が展開されていない"
assert "M6.75 3v2.25M17.25 3v2.25" in rendered_plan, "calendar SVG が展開されていない"
# 絵文字ゼロ (AI ロールフォールバック 🎭 は render 時に評価されないので存在しない)
# ※ agent.emoji || '🎭' は Alpine.js の x-text の中の文字列で、Jinja render では消えない (x-text 属性内は普通の HTML 属性値扱い)
# ↓ そこは AI ロール系フォールバックなので保持対象
for emoji in ("📋", "🎯", "📦", "🎚", "🎼", "🔍", "⚠", "📅"):
    assert emoji not in rendered_plan, f"絵文字 {emoji!r} が plan_card.html に残っている"
# 参加AI の 🎭 (プレフィックス) は削除、agent.emoji フォールバックの 🎭 は残る (2 箇所)
maskcount = rendered_plan.count("🎭")
assert maskcount == 2, f"🎭 は AI ロールフォールバックのみ 2 箇所残る想定 (実際: {maskcount})"
print("[OK] plan_card.html: 12 箇所が macro 経由・AI ロールフォールバック 🎭 のみ残存 (2 箇所)")

# 7) idea.html 中の 🎭 参加予定AI 部分だけ検証
tpl_idea = env.get_template("pages/idea.html")
print("[OK] idea.html load")
rendered_idea = tpl_idea.render(request=None)
print("[OK] idea.html render", len(rendered_idea), "chars")

# 参加予定AI ラベル部の user-group SVG があること
assert "参加予定AI" in rendered_idea, "参加予定AI ラベルが消えている"
# 「🎭 参加予定AI」形式で 🎭 が付いていないこと
assert "🎭 参加予定AI" not in rendered_idea, "🎭 参加予定AI が残っている"
# user-group SVG が展開されている (idea.html の該当箇所付近)
idx = rendered_idea.index("参加予定AI")
# 該当行の前 500 chars 以内に user-group の d 属性がある
snippet = rendered_idea[max(0, idx - 500):idx]
assert "M15 19.128" in snippet, "参加予定AI 付近に user-group SVG が展開されていない"
print("[OK] idea.html: 🎭 参加予定AI 部分が user-group SVG に置換")

print("\nAll checks passed.")
