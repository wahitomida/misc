"""icon.html マクロの Jinja2 構文検証 + import 動作 + fallback 検証。

サブステップ 2 (A/B/C) を通じて随時アイコンを追加する検証用スクリプト。
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent / "web" / "templates"

env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

# 1) 構文検証
src, _, _ = env.loader.get_source(env, "components/icon.html")
env.parse(src)
print("[OK] icon.html: parse")

# 定義済みアイコン一覧 (フェーズごとに追加)
PHASE_A = ["folder", "document", "arrow-right", "check-circle", "x-circle"]
PHASE_B = [
    "folder-open", "clipboard-list", "book-open", "chart-bar",
    "arrow-trending-up", "arrow-trending-down", "inbox", "adjustments",
    "code-bracket", "rocket-launch", "play-circle", "stop-circle",
]
PHASE_C: list[str] = [
    # 2-C-1: 通知・状態系
    "sparkles", "exclamation-triangle", "information-circle",
    "bolt", "cog", "clock", "trophy",
    # 2-C-2: ナビ・矢印・UI テーマ系
    "arrow-left", "arrow-down",
    "chevron-up", "chevron-down", "chevron-right",
    "arrow-path",
    "moon", "sun", "bars-3",
    # 2-C-3: コンテンツ系
    "chat-bubble", "pencil-square", "pencil",
    "film", "musical-note", "flag",
    "magnifying-glass", "beaker", "wrench",
    "link", "light-bulb", "calendar", "user-group",
]

# Plan 2-A-1 で追加した icon (components/ 置換用の補完)
PLAN_2A1_EXTRA = ["paper-clip", "x-mark", "cube"]

DEFINED_ICONS = PHASE_A + PHASE_B + PHASE_C + PLAN_2A1_EXTRA

# 2) 全アイコン + fallback を render
lines = ["{% import 'components/icon.html' as ui %}"]
for name in DEFINED_ICONS:
    lines.append(f"{name}::{{{{ ui.icon('{name}', 'w-4 h-4 text-sky-500') }}}}::END")
lines.append("UNKNOWN::{{ ui.icon('typoed-name', 'w-4 h-4') }}::END")
tpl = env.from_string("\n".join(lines))
rendered = tpl.render()
print("[OK] icon.html: render", len(DEFINED_ICONS), "icons +", "fallback")

# 3) 各アイコンが SVG として描画されたか確認
for name in DEFINED_ICONS:
    marker = f"{name}::"
    assert marker in rendered, f"{name}: marker not rendered"
    start = rendered.index(marker) + len(marker)
    end = rendered.index("::END", start)
    section = rendered[start:end]
    assert "<svg" in section, f"{name}: <svg> missing"
    assert 'stroke="currentColor"' in section, f"{name}: stroke missing"
    assert "<path" in section, f"{name}: <path> missing"
    # fallback (question-mark) の d="M9.879..." を含んでいないこと
    assert "M9.879" not in section, f"{name}: fell back to question-mark (未定義)"
print(f"[OK] all {len(DEFINED_ICONS)} icons rendered with unique paths")

# 4) fallback (typo) は question-mark-circle
unk_section = rendered.split("UNKNOWN::")[1].split("::END")[0]
assert "M9.879" in unk_section, "fallback (question-mark-circle) not used for unknown name"
print("[OK] fallback works for unknown icon name")

print("\nAll checks passed.")
