"""Plan 2 全体完了検証: 全ページで
- Jinja2 render エラーなし
- 絵文字残存が AI ロール系フォールバックのみか
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parent / "web" / "templates"
env = Environment(loader=FileSystemLoader(str(TEMPLATES)))

# 保持対象 AI ロール系絵文字 (残っていて OK)
AI_ROLE_EMOJIS = frozenset([
    "🎭", "🧮", "🔬", "🤖", "📚", "😈", "🎯", "📐", "📝", "🏆",
])

# render + emoji 検査対象
PAGES = [
    "pages/home.html",
    "pages/roles.html",
    "pages/history.html",
    "pages/replay.html",
    "pages/idea.html",
    "pages/review.html",
    "errors/500.html",
    "errors/404.html",
    "partials/header.html",
    "partials/toast.html",
    "components/agent_badge.html",
    "components/chat_bubble.html",
    "components/evaluation.html",
    "components/plan_card.html",
    "components/hypothesis_table.html",
    "components/file_drop.html",
    "components/timer.html",
]

# UI 装飾で残置を許容するもの (小さな装飾で SVG 化不要または UI 制約)
ALLOWED_LEFTOVER_PER_FILE = {
    # focusModes / reviewAspects の icon フィールド (JS 配列内、動的表示、AI 観点扱い)
    "pages/review.html": {"🎯", "📝", "⚡", "🤝", "🧮", "🔬", "🤖", "📐", "🎭"},
    # AI ロールフォールバック
    "pages/idea.html": {"🎭", "🏆"} | AI_ROLE_EMOJIS,
    "pages/replay.html": {"🎭"} | AI_ROLE_EMOJIS,
    "pages/history.html": {"🎭"} | AI_ROLE_EMOJIS,
    "pages/roles.html": {"🎭"} | AI_ROLE_EMOJIS,
    "pages/home.html": AI_ROLE_EMOJIS,
    "components/agent_badge.html": AI_ROLE_EMOJIS,
    "components/chat_bubble.html": AI_ROLE_EMOJIS,
    "components/evaluation.html": AI_ROLE_EMOJIS,
    "components/plan_card.html": AI_ROLE_EMOJIS,
    "components/hypothesis_table.html": set(),
    "components/file_drop.html": set(),
    "components/timer.html": set(),
    "partials/header.html": set(),
    "partials/toast.html": set(),
    "errors/500.html": set(),
    "errors/404.html": set(),
}

# 全ての SVG 化検討対象絵文字パターン (これらが残ってたら警告)
CHECK_EMOJIS = [
    "📂", "📁", "📝", "📄", "📋", "📚", "📊", "📈", "📉", "📭",
    "📌", "📍", "📢", "🎯", "🎬", "🎭", "🎼", "🎵", "🎶", "🎉",
    "🎊", "🎈", "🎓", "🏆", "🚀", "💡", "🧠", "🔍", "🔬", "🔎",
    "🔧", "🔨", "🔒", "🔓", "🔗", "🔥", "🔔", "❓", "❗", "❌",
    "✅", "✔", "✨", "⚙", "⚠", "⏰", "⏱", "⏳", "⌛", "👥",
    "👤", "🐍", "📏", "▶", "⏹", "▼", "▲", "◀", "←", "→",
    "↑", "↓", "↻", "↺", "🌙", "☀", "☰", "🛑", "📞", "💬",
    "🤝", "🌟", "⚡", "📅", "✏", "ℹ", "📐", "🖥", "💻", "😈",
    "🧮", "🤖", "🏠", "🗑",
]

all_ok = True
for tpl_path in PAGES:
    try:
        tpl = env.get_template(tpl_path)
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {tpl_path}: load error {e}")
        all_ok = False
        continue
    # render (dummy context)
    try:
        rendered = tpl.render(request=None, session_id="test-session", error_detail="")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {tpl_path}: render error {e}")
        all_ok = False
        continue

    # 絵文字検査 (許容リストにないものが残っていたら警告)
    allowed = ALLOWED_LEFTOVER_PER_FILE.get(tpl_path, AI_ROLE_EMOJIS)
    leftover: dict[str, int] = {}
    for emoji in CHECK_EMOJIS:
        count = rendered.count(emoji)
        if count > 0 and emoji not in allowed:
            leftover[emoji] = count

    if leftover:
        preview = ", ".join(f"{e}x{c}" for e, c in leftover.items())
        print(f"[WARN] {tpl_path}: leftover {preview}")
    else:
        print(f"[OK]   {tpl_path}: render OK, no unwanted emoji")

print("\n=== Result ===")
if all_ok:
    print("All templates render successfully.")
else:
    print("Some templates failed to render.")
