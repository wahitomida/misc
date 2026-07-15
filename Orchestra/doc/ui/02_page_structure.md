# AI Orchestra — ページ構成・ルーティング・レイアウト

> 全ページの構造、URLルーティング、レイアウトパターンの定義

---

## 1. URL ルーティング一覧

### 1.1 ページルーティング (HTML)

| Method | URL | テンプレート | 説明 |
|--------|-----|------------|------|
| GET | `/` | `pages/home.html` | Heroランディング + モード選択 |
| GET | `/idea` | `pages/idea.html` | Idea議論 (4ステップウィザード) |
| GET | `/review` | `pages/review.html` | Code Review (5ステップウィザード) |
| GET | `/history` | `pages/history.html` | セッション履歴一覧 |
| GET | `/replay/{session_id}` | `pages/replay.html` | 過去セッション再表示 |
| GET | `/roles` | `pages/roles.html` | ロール一覧・詳細・統計 |

### 1.2 API ルーティング (JSON / SSE)

| Method | URL | レスポンス | 説明 |
|--------|-----|-----------|------|
| POST | `/api/idea/plan` | JSON | 計画立案 |
| POST | `/api/idea/stream` | SSE | 議論実行ストリーム |
| POST | `/api/review/plan` | JSON | レビュー計画 |
| POST | `/api/review/stream` | SSE | レビュー実行ストリーム |
| GET | `/api/sessions` | JSON | セッション一覧 (ページネーション) |
| GET | `/api/sessions/recent` | JSON | 最新N件 |
| GET | `/api/sessions/{id}` | JSON | セッション詳細 |
| GET | `/api/sessions/{id}/content` | JSON | セッション全コンテンツ |
| GET | `/api/sessions/{id}/download` | File | ファイルダウンロード |
| DELETE | `/api/sessions/{id}` | JSON | セッション削除 |
| GET | `/api/roles` | JSON | ロール一覧 |
| GET | `/api/roles/{id}` | JSON | ロール詳細 |
| GET | `/api/roles/{id}/stats` | JSON | ロール統計 |
| GET | `/api/health` | JSON | ヘルスチェック |

### 1.3 ルーティング実装

```python
# web/routes/pages.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
"""Heroランディングページ。"""
return templates.TemplateResponse("pages/home.html", {"request": request})

@router.get("/idea", response_class=HTMLResponse)
async def idea(request: Request, follow_up: str | None = None):
"""Idea議論ページ。follow_upパラメータでフォローアップモード。"""
return templates.TemplateResponse("pages/idea.html", {
"request": request,
"follow_up_id": follow_up,
})

@router.get("/review", response_class=HTMLResponse)
async def review(request: Request):
"""Code Reviewページ。"""
return templates.TemplateResponse("pages/review.html", {"request": request})

@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
"""セッション履歴ページ。"""
return templates.TemplateResponse("pages/history.html", {"request": request})

@router.get("/replay/{session_id}", response_class=HTMLResponse)
async def replay(request: Request, session_id: str):
"""セッション再表示ページ。"""
return templates.TemplateResponse("pages/replay.html", {
"request": request,
"session_id": session_id,
})

@router.get("/roles", response_class=HTMLResponse)
async def roles(request: Request):
"""ロール管理ページ。"""
return templates.TemplateResponse("pages/roles.html", {"request": request})
```

---

## 2. レイアウトパターン

### 2.1 ベースレイアウト (base.html)

```
┌────────────────────────────────────────────────────────────────┐
│ [Header] position: fixed, top: 0, z: 50                       │
│  ┌────────────────────────────────────────────────────────┐   │
│  │ 🎵 AI Orchestra  │ Home │ Idea │ Review │ History │ 🌙 │   │
│  └────────────────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  [Main Content Area]                                           │
│  max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8                 │
│  pt-20 (header分のpadding)                                    │
│                                                                │
│  {% block content %}{% endblock %}                             │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│ [Toast Container] position: fixed, top: 20, right: 4, z: 50   │
│ [Modal Container] position: fixed, inset: 0, z: 60            │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Heroページレイアウト (home.html)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│          ┌───────────────────────────────────┐                 │
│          │  🎵 AI Orchestra                  │  ← グラデ文字   │
│          │  複数のAI専門家が、                │                 │
│          │  あなたのアイデアを磨く             │                 │
│          └───────────────────────────────────┘                 │
│                                                                │
│     ┌────────────────┐      ┌────────────────┐                │
│     │ 💡 Idea        │      │ 🔍 Review      │  ← カード2枚   │
│     │ Discussion     │      │ Code Review    │                │
│     │                │      │                │                │
│     │ 5〜6人のAI専門家│      │ 6観点からAIが   │                │
│     │ が多角的に議論  │      │ レビュー       │                │
│     │                │      │                │                │
│     │ 🧮🔬🤖📚😈🎯  │      │ 📐📝🧮🔬🤖📚  │                │
│     │                │      │                │                │
│     │ [→ 議論を始める]│      │ [→ レビュー開始]│                │
│     └────────────────┘      └────────────────┘                │
│                                                                │
│     ── 最近のセッション ──────────────────────                  │
│     ┌──────────────────────────────────────────┐              │
│     │ 💡 13:32 │ LLMの推論効率...  │ 4:32 │ → │              │
│     │ 🔍 09:15 │ src/ レビュー     │ 9:58 │ → │              │
│     └──────────────────────────────────────────┘              │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.3 ウィザードレイアウト (idea.html / review.html)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  [Step Indicator]                                              │
│  ● 1 入力 ───── ● 2 計画 ───── ○ 3 議論 ───── ○ 4 結果      │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌────── 左カラム (md:w-2/5) ──────┐ ┌── 右カラム (md:w-3/5) ─┐│
│  │                                 │ │                         ││
│  │  [入力フォーム]                  │ │  [プレビュー/結果]       ││
│  │                                 │ │                         ││
│  │  ・テーマ入力                    │ │  ・参加AI表示            ││
│  │  ・設定 (アコーディオン)         │ │  ・推定時間              ││
│  │  ・高度な設定                    │ │  ・関連情報              ││
│  │                                 │ │                         ││
│  │                                 │ │  (sticky: top-24)       ││
│  │  [🚀 計画する]                  │ │                         ││
│  │                                 │ │                         ││
│  └─────────────────────────────────┘ └─────────────────────────┘│
│                                                                │
│  ※ モバイル (< md): 1カラム (上: フォーム → 下: プレビュー)     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.4 議論進行レイアウト (Step 3)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ┌─── サイドバー (md:w-1/4) ───┐ ┌── チャットエリア (md:w-3/4)─┐│
│  │                             │ │                             ││
│  │  ⏱️ 残り: 3:24              │ │  ─── Round 1: 発散 ───      ││
│  │  ████████░░ 65%             │ │                             ││
│  │                             │ │  🧮 理論屋:                  ││
│  │  📊 Round 2/3               │ │  ┌───────────────────┐      ││
│  │  Pattern: ping_pong         │ │  │ 計算量の観点から... │      ││
│  │                             │ │  └───────────────────┘      ││
│  │  ── 参加AI ──               │ │                             ││
│  │  🧮 理論屋   ● 発言中       │ │  🔬 実験屋:                  ││
│  │  🔬 実験屋   ○ 待機         │ │  ┌───────────────────┐      ││
│  │  🤖 実装屋   ○ 待機         │ │  │ 実験的にはKV-...   │      ││
│  │  📚 文献屋   ✓ 発言済       │ │  └───────────────────┘      ││
│  │  😈 穴探し   ○ 待機         │ │                             ││
│  │                             │ │  🎯 Round 1 結論:            ││
│  │  ── 統計 ──                 │ │  ┌═══════════════════┐      ││
│  │  発言数: 8                  │ │  ║ KV-cache圧縮が... ║      ││
│  │  トークン: 1,200            │ │  └═══════════════════┘      ││
│  │  収束度: 0.72               │ │                             ││
│  │                             │ │  ─── Round 2: 深掘り ───    ││
│  │  [🛑 中断]                  │ │  ...                        ││
│  │                             │ │                             ││
│  └─────────────────────────────┘ └─────────────────────────────┘│
│                                                                │
│  ※ モバイル: タイマーは上部固定バー、チャットはフルスクリーン    │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.5 結果表示レイアウト (Step 4 / replay)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  🎉 議論完了！                                                 │
│                                                                │
│  ┌── 統計カード (4列グリッド) ──────────────────────────────┐  │
│  │ ⏱️ 4:32  │ 💬 14発言 │ 📊 2,850tk │ 🎯 0.87収束 │       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── タブ切替 ──────────────────────────────────────────────┐  │
│  │ [📄 レポート] [💬 全会話] [📊 評価] [📋 要約]             │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │                                                          │  │
│  │  (選択されたタブの Markdown 内容を表示)                    │  │
│  │                                                          │  │
│  │  ┌────────────────────────────────────────────────┐      │  │
│  │  │ # 議論レポート                                  │      │  │
│  │  │                                                │      │  │
│  │  │ ## 1. 概要                                      │      │  │
│  │  │ LLM推論効率化について5名のAIが議論し...         │      │  │
│  │  │                                                │      │  │
│  │  │ ## 2. 主要な洞察                                │      │  │
│  │  │ ...                                            │      │  │
│  │  └────────────────────────────────────────────────┘      │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── アクション ──                                              │
│  [🔄 フォローアップ]  [📥 ダウンロード ▼]  [🏠 ホームへ]       │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.6 一覧ページレイアウト (history.html)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  📚 セッション履歴                                             │
│                                                                │
│  ┌── フィルターバー ────────────────────────────────────────┐  │
│  │ [タイプ: 全て ▼]  [検索: _____________ 🔍]              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── セッションカード ──────────────────────────────────────┐  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────┐     │  │
│  │  │ 💡 idea  2026/06/22 13:32                       │     │  │
│  │  │ "LLMの推論効率を改善する手法を議論して"          │     │  │
│  │  │ 4:32 | 🧮MVP | 収束: 0.87                      │     │  │
│  │  │ [👁️ 表示] [🔄 FU] [🗑️]                         │     │  │
│  │  └─────────────────────────────────────────────────┘     │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────┐     │  │
│  │  │ 🔍 review  2026/06/21 09:15                     │     │  │
│  │  │ "src/ のコードレビュー"                          │     │  │
│  │  │ 9:58 | focus: all                              │     │  │
│  │  │ [👁️ 表示] [🗑️]                                 │     │  │
│  │  └─────────────────────────────────────────────────┘     │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── ページネーション ──┐                                      │
│  │ [← 前] 1 / 3 [次 →] │                                      │
│  └──────────────────────┘                                      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.7 ロール管理レイアウト (roles.html)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  🎭 AIロール一覧                                               │
│                                                                │
│  ┌── ロールカードグリッド (grid-cols-2 md:grid-cols-4) ──────┐ │
│  │                                                          │ │
│  │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                    │ │
│  │ │ 🧮   │ │ 🔬   │ │ 🤖   │ │ 📚   │                    │ │
│  │ │理論屋│ │実験屋│ │実装屋│ │文献屋│                    │ │
│  │ │★4.2 │ │★3.8 │ │★4.5 │ │★4.0 │                    │ │
│  │ │8回   │ │6回   │ │7回   │ │5回   │                    │ │
│  │ └──────┘ └──────┘ └──────┘ └──────┘                    │ │
│  │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                    │ │
│  │ │ 😈   │ │ 🎯   │ │ 📐   │ │ 📝   │                    │ │
│  │ │穴探し│ │鳥の目│ │設計LD│ │可読LD│                    │ │
│  │ │★4.1 │ │★4.3 │ │★3.9 │ │★4.0 │                    │ │
│  │ │6回   │ │8回   │ │4回   │ │3回   │                    │ │
│  │ └──────┘ └──────┘ └──────┘ └──────┘                    │ │
│  │                                                          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌── 詳細パネル (選択時に展開) ──────────────────────────────┐ │
│  │                                                          │ │
│  │  🧮 理論屋 (theorist)                                    │ │
│  │                                                          │ │
│  │  ┌─── 基本情報 ───────┐  ┌─── パフォーマンス ──────────┐ │ │
│  │  │ 専門: 数学的定式化  │  │ 自己評価: ★4.2 (↗️ 上昇)   │ │ │
│  │  │ 性格: 厳密・論理的  │  │ 他者評価: ★4.0              │ │ │
│  │  │ 弱み: 実装コスト軽視│  │ MVP回数: 3 / 8セッション    │ │ │
│  │  └────────────────────┘  └──────────────────────────────┘ │ │
│  │                                                          │ │
│  │  💬 最近のフィードバック:                                  │ │
│  │  "もう少し具体例を交えて説明すると良い"                    │ │
│  │                                                          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. base.html 詳細仕様

### 3.1 HTML構造

```html
<!DOCTYPE html>
<html lang="ja" class="">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}AI Orchestra{% endblock %}</title>

<!-- ダークモード初期化 (白フラッシュ防止) -->
<script>
(function() {
const stored = localStorage.getItem('darkMode');
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
if (stored === 'true' || (stored === null && prefersDark)) {
document.documentElement.classList.add('dark');
}
})();
</script>

<!-- Tailwind CSS (Play CDN) -->
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
darkMode: 'class',
theme: {
extend: {
maxWidth: { '8xl': '1440px' },
animation: {
'fade-in': 'fadeIn 300ms ease-out',
'slide-up': 'slideUp 400ms ease-out',
'pulse-slow': 'pulse 3s infinite',
},
}
}
}
</script>

<!-- Alpine.js -->
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>

<!-- Marked + DOMPurify -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>

<!-- Custom CSS -->
<link rel="stylesheet" href="/static/css/custom.css">

{% block head_extra %}{% endblock %}
</head>

<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100
min-h-screen transition-colors duration-200">

<!-- Header -->
{% include "partials/header.html" %}

<!-- Main Content -->
<main class="max-w-8xl mx-auto px-4 sm:px-6 lg:px-8 pt-20 pb-12">
{% block content %}{% endblock %}
</main>

<!-- Toast Container -->
{% include "partials/toast.html" %}

<!-- Modal Container -->
{% include "partials/modal.html" %}

<!-- Custom JS -->
<script src="/static/js/dark-mode.js"></script>
<script src="/static/js/app.js"></script>
<script src="/static/js/sse.js"></script>
<script src="/static/js/markdown.js"></script>

{% block scripts_extra %}{% endblock %}
</body>
</html>
```

### 3.2 ヘッダー (partials/header.html)

```html
<header class="fixed top-0 left-0 right-0 z-50
bg-white/80 dark:bg-gray-900/80
backdrop-blur-md
border-b border-gray-200 dark:border-gray-700"
x-data="{ mobileMenuOpen: false }">

<div class="max-w-8xl mx-auto px-4 sm:px-6 lg:px-8">
<div class="flex items-center justify-between h-16">

<!-- Logo -->
<a href="/" class="flex items-center gap-2 text-lg font-bold
text-gray-900 dark:text-white hover:opacity-80 transition">
<span class="text-2xl">🎵</span>
<span class="hidden sm:inline">AI Orchestra</span>
</a>

<!-- Desktop Nav -->
<nav class="hidden md:flex items-center gap-6">
<a href="/" class="nav-link">Home</a>
<a href="/idea" class="nav-link">Idea</a>
<a href="/review" class="nav-link">Review</a>
<a href="/history" class="nav-link">History</a>
<a href="/roles" class="nav-link">Roles</a>
</nav>

<!-- Right: Dark Mode Toggle -->
<div class="flex items-center gap-4">
<button @click="toggleDarkMode()"
class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800
transition" aria-label="ダークモード切替">
<span x-text="document.documentElement.classList.contains('dark') ? '☀️' : '🌙'"
class="text-xl"></span>
</button>

<!-- Mobile Menu Button -->
<button @click="mobileMenuOpen = !mobileMenuOpen"
class="md:hidden p-2 rounded-lg hover:bg-gray-100
dark:hover:bg-gray-800 transition"
aria-label="メニュー">
<span class="text-xl">☰</span>
</button>
</div>
</div>
</div>

<!-- Mobile Menu -->
<div x-show="mobileMenuOpen"
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0 -translate-y-2"
x-transition:enter-end="opacity-100 translate-y-0"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100 translate-y-0"
x-transition:leave-end="opacity-0 -translate-y-2"
class="md:hidden border-t border-gray-200 dark:border-gray-700
bg-white dark:bg-gray-900">
<nav class="flex flex-col p-4 gap-2">
<a href="/" class="mobile-nav-link">🏠 Home</a>
<a href="/idea" class="mobile-nav-link">💡 Idea</a>
<a href="/review" class="mobile-nav-link">🔍 Review</a>
<a href="/history" class="mobile-nav-link">📚 History</a>
<a href="/roles" class="mobile-nav-link">🎭 Roles</a>
</nav>
</div>
</header>
```

---

## 4. ステップインジケーター

### 4.1 仕様

```
アクティブ: ● (indigo-600) + ラベル太字
完了済み:   ● (green-500) + チェックマーク
未到達:     ○ (gray-300) + ラベル薄字
接続線:     完了=green, 未到達=gray
```

### 4.2 テンプレート (partials/step_indicator.html)

```html
<!--
使用方法:
{% set steps = [
{"num": 1, "label": "入力"},
{"num": 2, "label": "計画"},
{"num": 3, "label": "議論"},
{"num": 4, "label": "結果"},
] %}
{% include "partials/step_indicator.html" %}

Alpine.js から step 変数を参照
-->

<div class="flex items-center justify-center mb-8">
<template x-for="(s, i) in steps" :key="s.num">
<div class="flex items-center">
<!-- ステップ丸 + ラベル -->
<div class="flex flex-col items-center">
<div class="w-10 h-10 rounded-full flex items-center justify-center
text-sm font-bold transition-all duration-300"
:class="{
'bg-indigo-600 text-white shadow-lg shadow-indigo-200 dark:shadow-indigo-900':
step === s.num,
'bg-green-500 text-white': step > s.num,
'bg-gray-200 dark:bg-gray-700 text-gray-500': step < s.num,
}">
<span x-show="step <= s.num" x-text="s.num"></span>
<span x-show="step > s.num">✓</span>
</div>
<span class="text-xs mt-1 transition-colors"
:class="{
'text-indigo-600 dark:text-indigo-400 font-bold': step === s.num,
'text-green-600 dark:text-green-400': step > s.num,
'text-gray-400': step < s.num,
}"
x-text="s.label">
</span>
</div>

<!-- 接続線 -->
<div x-show="i < steps.length - 1"
class="w-12 sm:w-20 h-0.5 mx-2 transition-colors duration-300"
:class="{
'bg-green-500': step > s.num,
'bg-gray-200 dark:bg-gray-700': step <= s.num,
}">
</div>
</div>
</template>
</div>
```

---

## 5. ページ間のデータ受け渡し

### 5.1 URL パラメータ

| 遷移元 | 遷移先 | パラメータ | 例 |
|--------|--------|-----------|-----|
| history → replay | `/replay/{id}` | path parameter | `/replay/20260622_133204_idea` |
| history → idea | `/idea?follow_up={id}` | query parameter | `/idea?follow_up=20260622_133204_idea` |
| home → idea | `/idea` | なし | — |
| idea結果 → idea | `/idea?follow_up={id}` | query parameter | フォローアップ |

### 5.2 localStorage 経由

```javascript
// idea 結果ページ → idea 入力ページ (フォローアップ)
function startFollowUp(sessionId) {
localStorage.setItem('idea_follow_up', sessionId);
window.location.href = '/idea?follow_up=' + sessionId;
}

// idea 入力ページで復元
init() {
const params = new URLSearchParams(window.location.search);
this.followUpId = params.get('follow_up') || localStorage.getItem('idea_follow_up');
if (this.followUpId) {
this.loadFollowUpContext();
}
}
```

---

## 6. テンプレート継承構造

```
base.html
├── pages/home.html        (extends base)
├── pages/idea.html        (extends base)
│   ├── includes components/chat_bubble.html
│   ├── includes components/plan_card.html
│   ├── includes components/timer.html
│   ├── includes components/evaluation.html
│   └── includes components/hypothesis_table.html
├── pages/review.html      (extends base)
│   ├── includes components/chat_bubble.html
│   ├── includes components/plan_card.html
│   ├── includes components/timer.html
│   └── includes components/file_drop.html
├── pages/history.html     (extends base)
├── pages/replay.html      (extends base)
│   ├── includes components/evaluation.html
│   └── includes components/hypothesis_table.html
└── pages/roles.html       (extends base)
    └── includes components/agent_badge.html
```

---

## 7. エラーページ

### 7.1 404 ページ

```html
{% extends "base.html" %}
{% block title %}404 - ページが見つかりません{% endblock %}
{% block content %}
<div class="flex flex-col items-center justify-center min-h-[60vh] text-center">
<div class="text-8xl mb-4">🎵</div>
<h1 class="text-3xl font-bold mb-2">404</h1>
<p class="text-gray-500 dark:text-gray-400 mb-6">
お探しのページは見つかりませんでした
</p>
<a href="/" class="px-6 py-3 bg-indigo-600 text-white rounded-xl
hover:bg-indigo-700 transition">
ホームに戻る
</a>
</div>
{% endblock %}
```

### 7.2 500 ページ

```html
{% extends "base.html" %}
{% block title %}500 - サーバーエラー{% endblock %}
{% block content %}
<div class="flex flex-col items-center justify-center min-h-[60vh] text-center">
<div class="text-8xl mb-4">⚠️</div>
<h1 class="text-3xl font-bold mb-2">500</h1>
<p class="text-gray-500 dark:text-gray-400 mb-2">
内部エラーが発生しました
</p>
<p class="text-sm text-gray-400 mb-6" x-data x-text="'Error ID: ' + Date.now()"></p>
<div class="flex gap-4">
<button onclick="window.location.reload()"
class="px-6 py-3 bg-gray-200 dark:bg-gray-700 rounded-xl
hover:bg-gray-300 dark:hover:bg-gray-600 transition">
再読み込み
</button>
<a href="/" class="px-6 py-3 bg-indigo-600 text-white rounded-xl
hover:bg-indigo-700 transition">
ホームに戻る
</a>
</div>
</div>
{% endblock %}
```

---

## 8. ナビゲーション設計

### 8.1 ナビバーのアクティブ状態

```html
<!-- 現在のURLに基づいてアクティブ状態を切替 -->
<a href="/idea"
class="nav-link"
:class="{ 'nav-link-active': window.location.pathname === '/idea' }">
Idea
</a>
```

```css
/* custom.css */
.nav-link {
@apply text-sm font-medium text-gray-600 dark:text-gray-300
hover:text-indigo-600 dark:hover:text-indigo-400
transition-colors px-3 py-2 rounded-lg;
}
.nav-link-active {
@apply text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/20;
}
.mobile-nav-link {
@apply px-4 py-3 rounded-lg text-gray-700 dark:text-gray-200
hover:bg-gray-100 dark:hover:bg-gray-800 transition;
}
```

### 8.2 パンくずリスト (replay ページ)

```html
<!-- /replay/{id} ページ上部 -->
<nav class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-6">
<a href="/" class="hover:text-indigo-600 transition">Home</a>
<span>›</span>
<a href="/history" class="hover:text-indigo-600 transition">History</a>
<span>›</span>
<span class="text-gray-900 dark:text-gray-100" x-text="sessionId"></span>
</nav>
```

---

## 9. コンテンツ幅の統一

| コンテキスト | max-width | 用途 |
|-------------|-----------|------|
| メインコンテナ | `max-w-8xl` (1440px) | 全ページ共通 |
| テキストコンテンツ | `max-w-3xl` (768px) | レポート・要約表示 |
| フォーム | `max-w-2xl` (672px) | 入力フォーム |
| チャットバブル | `max-w-[600px]` | 発言バブル |
| モーダル | `max-w-lg` (512px) | 確認ダイアログ |
| トースト | `max-w-sm` (384px) | 通知 |

---

## 10. z-index レイヤー

| z-index | 要素 | 説明 |
|---------|------|------|
| 0 | ページコンテンツ | 通常のフロー |
| 10 | sticky 要素 | サイドバー、プレビュー |
| 40 | ドロップダウン | セレクト、メニュー |
| 50 | ヘッダー + トースト | 固定UI |
| 60 | モーダル背景 | backdrop |
| 70 | モーダル本体 | ダイアログ |
