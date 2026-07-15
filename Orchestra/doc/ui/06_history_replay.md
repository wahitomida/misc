# AI Orchestra — 履歴・Replay ページ設計

> `/history` と `/replay/{session_id}` の全仕様

---

## 1. 概要

| ページ | URL | 機能 |
|--------|-----|------|
| 履歴一覧 | `/history` | 過去セッションの検索・フィルタ・管理 |
| セッション再表示 | `/replay/{session_id}` | 過去セッションの内容閲覧 |

---

## 2. /history — 履歴一覧ページ

### 2.1 全体レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  📚 セッション履歴                                             │
│                                                                │
│  ┌── フィルターバー ────────────────────────────────────────┐  │
│  │                                                          │  │
│  │  [タイプ ▼]  [ソート ▼]  [─── 検索 ─── 🔍]             │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── チェーン表示切替 ─────────────────────────────────────┐  │
│  │  ☐ フォローアップチェーンを表示                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── セッションリスト ─────────────────────────────────────┐  │
│  │                                                          │  │
│  │  (セッションカード × n)                                  │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── ページネーション ──────────────────────────────────────┐  │
│  │  [← 前へ]  ページ 1 / 3  [次へ →]                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── 統計サマリー ─────────────────────────────────────────┐  │
│  │  全25セッション │ idea: 18 │ review: 7 │ 今月: 12       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 フィルターバー

```html
<div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mb-6">
<!-- タイプフィルタ -->
<select x-model="filter.type"
@change="loadSessions()"
class="rounded-xl border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-4 py-2.5
focus:ring-2 focus:ring-indigo-500">
<option value="">全タイプ</option>
<option value="idea">💡 Idea</option>
<option value="review">🔍 Review</option>
</select>

<!-- ソート -->
<select x-model="filter.sort"
@change="loadSessions()"
class="rounded-xl border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-4 py-2.5
focus:ring-2 focus:ring-indigo-500">
<option value="date_desc">新しい順</option>
<option value="date_asc">古い順</option>
<option value="duration_desc">時間長い順</option>
<option value="convergence_desc">収束度高い順</option>
</select>

<!-- 検索 -->
<div class="flex-1 relative">
<input type="text"
x-model="filter.search"
@input.debounce.300ms="loadSessions()"
placeholder="テーマを検索..."
class="w-full rounded-xl border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-4 py-2.5 pr-10
focus:ring-2 focus:ring-indigo-500">
<span class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
</div>
</div>
```

### 2.3 セッションカード

```html
<template x-for="session in sessions" :key="session.id">
<div class="bg-white dark:bg-gray-800 rounded-2xl p-5
border border-gray-200 dark:border-gray-700
hover:border-indigo-300 dark:hover:border-indigo-600
hover:shadow-md transition-all duration-200
animate-fade-in"
:style="'animation-delay: ' + (sessions.indexOf(session) * 50) + 'ms'">

<!-- ヘッダー行 -->
<div class="flex items-center justify-between mb-3">
<div class="flex items-center gap-3">
<!-- タイプバッジ -->
<span class="px-2.5 py-1 rounded-lg text-xs font-medium"
:class="{
'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300':
session.type === 'idea',
'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300':
session.type === 'review',
}">
<span x-text="session.type === 'idea' ? '💡 idea' : '🔍 review'"></span>
</span>

<!-- 日時 -->
<span class="text-sm text-gray-500 dark:text-gray-400"
x-text="formatDate(session.date)">
</span>
</div>

<!-- チェーンバッジ (フォローアップ時) -->
<span x-show="session.chain_depth > 0"
class="text-xs px-2 py-0.5 rounded-full
bg-amber-100 dark:bg-amber-900/30
text-amber-700 dark:text-amber-300">
🔗 chain: <span x-text="session.chain_depth"></span>
</span>
</div>

<!-- テーマ -->
<h3 class="text-sm font-medium text-gray-800 dark:text-gray-200 mb-3 line-clamp-2"
x-text="session.theme">
</h3>

<!-- メタ情報行 -->
<div class="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400 mb-4">
<!-- 所要時間 -->
<span class="flex items-center gap-1" x-show="session.duration_sec">
<span>⏱️</span>
<span x-text="formatTime(session.duration_sec)"></span>
</span>

<!-- 収束度 (idea) -->
<span class="flex items-center gap-1" x-show="session.convergence">
<span>🎯</span>
<span x-text="session.convergence?.toFixed(2)"></span>
</span>

<!-- MVP (idea) -->
<span class="flex items-center gap-1" x-show="session.mvp_emoji">
<span>🏆</span>
<span x-text="session.mvp_emoji"></span>
</span>

<!-- Focus (review) -->
<span class="flex items-center gap-1" x-show="session.focus">
<span>🎯</span>
<span x-text="session.focus"></span>
</span>
</div>

<!-- アクション行 -->
<div class="flex items-center gap-2">
<!-- 表示ボタン -->
<a :href="'/replay/' + session.id"
class="px-3 py-1.5 rounded-lg text-xs font-medium
bg-indigo-100 dark:bg-indigo-900/30
text-indigo-700 dark:text-indigo-300
hover:bg-indigo-200 dark:hover:bg-indigo-900/50
transition flex items-center gap-1">
<span>👁️</span>
<span>表示</span>
</a>

<!-- フォローアップ (idea のみ) -->
<a x-show="session.type === 'idea'"
:href="'/idea?follow_up=' + session.id"
class="px-3 py-1.5 rounded-lg text-xs font-medium
bg-green-100 dark:bg-green-900/30
text-green-700 dark:text-green-300
hover:bg-green-200 dark:hover:bg-green-900/50
transition flex items-center gap-1">
<span>🔄</span>
<span>FU</span>
</a>

<!-- 削除ボタン -->
<button @click="confirmDelete(session.id)"
class="px-3 py-1.5 rounded-lg text-xs font-medium
bg-red-100 dark:bg-red-900/30
text-red-700 dark:text-red-300
hover:bg-red-200 dark:hover:bg-red-900/50
transition flex items-center gap-1 ml-auto">
<span>🗑️</span>
</button>
</div>
</div>
</template>
```

### 2.4 チェーン表示モード

```html
<!-- チェーン表示トグル -->
<label class="flex items-center gap-2 mb-4 cursor-pointer">
<input type="checkbox"
x-model="showChains"
@change="loadSessions()"
class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500">
<span class="text-sm text-gray-600 dark:text-gray-400">
フォローアップチェーンを表示
</span>
</label>

<!-- チェーン表示 -->
<template x-if="showChains && chains.length > 0">
<div class="space-y-4 mb-6">
<template x-for="chain in chains" :key="chain[0].id">
<div class="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/50
border border-gray-200 dark:border-gray-700">
<div class="text-xs text-gray-500 mb-2">
🔗 チェーン (<span x-text="chain.length"></span>セッション)
</div>
<div class="flex items-center gap-2 overflow-x-auto pb-2">
<template x-for="(session, index) in chain" :key="session.id">
<div class="flex items-center gap-2 flex-shrink-0">
<!-- セッションノード -->
<a :href="'/replay/' + session.id"
class="px-3 py-2 rounded-lg text-xs
bg-white dark:bg-gray-700
border border-gray-200 dark:border-gray-600
hover:border-indigo-400 transition
whitespace-nowrap">
<div class="font-medium" x-text="session.date.slice(5, 10)"></div>
<div class="text-gray-400 truncate max-w-[100px]"
x-text="session.theme"></div>
</a>
<!-- 矢印 (最後以外) -->
<span x-show="index < chain.length - 1"
class="text-gray-400 text-sm">→</span>
</div>
</template>
</div>
</div>
</template>
</div>
</template>
```

### 2.5 ページネーション

```html
<div class="flex items-center justify-center gap-4 mt-8"
x-show="totalPages > 1">
<!-- 前へ -->
<button @click="goToPage(currentPage - 1)"
:disabled="currentPage <= 1"
class="px-4 py-2 rounded-xl text-sm
bg-white dark:bg-gray-800
border border-gray-200 dark:border-gray-700
hover:bg-gray-50 dark:hover:bg-gray-700
disabled:opacity-40 disabled:cursor-not-allowed
transition">
← 前へ
</button>

<!-- ページ表示 -->
<span class="text-sm text-gray-500 dark:text-gray-400">
ページ <span class="font-medium" x-text="currentPage">1</span>
/
<span x-text="totalPages">3</span>
</span>

<!-- 次へ -->
<button @click="goToPage(currentPage + 1)"
:disabled="currentPage >= totalPages"
class="px-4 py-2 rounded-xl text-sm
bg-white dark:bg-gray-800
border border-gray-200 dark:border-gray-700
hover:bg-gray-50 dark:hover:bg-gray-700
disabled:opacity-40 disabled:cursor-not-allowed
transition">
次へ →
</button>
</div>
```

### 2.6 空状態

```html
<template x-if="sessions.length === 0 && !loading">
<div class="text-center py-16">
<div class="text-6xl mb-4">📭</div>
<h3 class="text-lg font-medium text-gray-700 dark:text-gray-300 mb-2">
セッションがありません
</h3>
<p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
議論やレビューを実行すると、ここに履歴が表示されます
</p>
<div class="flex items-center justify-center gap-4">
<a href="/idea"
class="px-4 py-2 rounded-xl text-sm font-medium
bg-indigo-600 text-white hover:bg-indigo-700 transition">
💡 議論を始める
</a>
<a href="/review"
class="px-4 py-2 rounded-xl text-sm font-medium
bg-purple-600 text-white hover:bg-purple-700 transition">
🔍 レビューを始める
</a>
</div>
</div>
</template>
```

### 2.7 Alpine.js 状態管理 (historyPage)

```javascript
function historyPage() {
return {
// State
sessions: [],
chains: [],
loading: true,
filter: {
type: '',
sort: 'date_desc',
search: '',
},
showChains: false,
currentPage: 1,
totalPages: 1,
totalSessions: 0,
perPage: 10,

// Methods
async loadSessions() {
this.loading = true;
try {
const params = new URLSearchParams({
page: this.currentPage,
limit: this.perPage,
...(this.filter.type && { type: this.filter.type }),
...(this.filter.search && { search: this.filter.search }),
...(this.filter.sort && { sort: this.filter.sort }),
...(this.showChains && { show_chains: 'true' }),
});

const res = await fetch(`/api/sessions?${params}`);
const data = await res.json();
this.sessions = data.sessions;
this.totalPages = data.pages;
this.totalSessions = data.total;
if (data.chains) this.chains = data.chains;
} catch (err) {
toast('履歴の読み込みに失敗しました', 'error');
} finally {
this.loading = false;
}
},

goToPage(page) {
if (page < 1 || page > this.totalPages) return;
this.currentPage = page;
this.loadSessions();
window.scrollTo({ top: 0, behavior: 'smooth' });
},

confirmDelete(sessionId) {
window.dispatchEvent(new CustomEvent('open-modal', {
detail: {
title: 'セッションを削除しますか？',
message: `セッション ${sessionId} と全出力ファイルが削除されます。この操作は取り消せません。`,
action: () => this.deleteSession(sessionId),
},
}));
},

async deleteSession(sessionId) {
try {
const res = await fetch(`/api/sessions/${sessionId}`, {
method: 'DELETE',
});
if (!res.ok) throw new Error('削除に失敗しました');
toast('セッションを削除しました', 'success');
this.loadSessions();
} catch (err) {
toast(err.message, 'error');
}
},

// Lifecycle
init() {
this.loadSessions();
},
};
}
```

---

## 3. /replay/{session_id} — セッション再表示ページ

### 3.1 全体レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ┌── パンくずリスト ───────────────────────────────────────┐   │
│  │  Home › History › 20260622_133204_idea                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── セッションヘッダー ───────────────────────────────────┐   │
│  │                                                         │   │
│  │  💡 idea — 2026/06/22 13:32                             │   │
│  │  "LLMの推論効率を改善する手法を議論して"                │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── フォローアップチェーン (該当時のみ) ──────────────────┐   │
│  │  [20260620] → [20260621] → [20260622 ← 現在]           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── 統計カード ────────────────────────────────────────────┐  │
│  │ ⏱️ 4:32  │ 💬 14発言 │ 📊 2,850tk │ 🎯 0.87 │         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── MVP (idea のみ) ─────────────────────────────────────┐   │
│  │  🏆 MVP: 🧮 理論屋 — "数式による明確な根拠提示が..."   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── タブ ─────────────────────────────────────────────────┐  │
│  │ [📄 レポート] [💬 全会話] [📊 評価] [📋 要約] [🔧*]     │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │                                                         │  │
│  │  (Markdown レンダリング表示)                             │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── アクション ──                                              │
│  [🔄 フォローアップ] [📥 ダウンロード ▼] [📚 履歴に戻る]      │
│                                                                │
│  * review セッションのみ「🔧 修正指示書」タブが追加される       │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 セッションヘッダー

```html
<div class="mb-6">
<!-- パンくず -->
<nav class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
<a href="/" class="hover:text-indigo-600 dark:hover:text-indigo-400 transition">Home</a>
<span>›</span>
<a href="/history" class="hover:text-indigo-600 dark:hover:text-indigo-400 transition">History</a>
<span>›</span>
<span class="text-gray-900 dark:text-gray-100 font-medium"
x-text="sessionId"></span>
</nav>

<!-- タイトル + メタ -->
<div class="flex items-start gap-4">
<!-- タイプアイコン -->
<div class="w-12 h-12 rounded-xl flex items-center justify-center text-2xl
bg-blue-100 dark:bg-blue-900/30"
:class="{
'bg-blue-100 dark:bg-blue-900/30': meta.type === 'idea',
'bg-purple-100 dark:bg-purple-900/30': meta.type === 'review',
}">
<span x-text="meta.type === 'idea' ? '💡' : '🔍'"></span>
</div>

<div class="flex-1">
<div class="flex items-center gap-3 mb-1">
<span class="text-xs px-2 py-0.5 rounded-full font-medium"
:class="{
'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300':
meta.type === 'idea',
'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300':
meta.type === 'review',
}"
x-text="meta.type"></span>
<span class="text-sm text-gray-500" x-text="formatDate(meta.created_at)"></span>
</div>
<h1 class="text-xl font-bold text-gray-900 dark:text-white"
x-text="meta.theme"></h1>
</div>
</div>
</div>
```

### 3.3 フォローアップチェーン表示

```html
<div x-show="chain && chain.length > 1"
class="mb-6 p-4 rounded-xl bg-amber-50 dark:bg-amber-900/10
border border-amber-200 dark:border-amber-800">
<div class="text-xs font-medium text-amber-700 dark:text-amber-300 mb-3">
🔗 セッションチェーン
</div>

<div class="flex items-center gap-2 overflow-x-auto pb-2">
<template x-for="(item, index) in chain" :key="item.id">
<div class="flex items-center gap-2 flex-shrink-0">
<!-- セッションノード -->
<a :href="'/replay/' + item.id"
class="px-3 py-2 rounded-lg text-xs transition
border whitespace-nowrap"
:class="{
'bg-indigo-100 dark:bg-indigo-900/30
border-indigo-400 dark:border-indigo-600
text-indigo-700 dark:text-indigo-300 font-bold':
item.id === sessionId,
'bg-white dark:bg-gray-700
border-gray-200 dark:border-gray-600
hover:border-indigo-300 dark:hover:border-indigo-500':
item.id !== sessionId,
}">
<div x-text="item.date?.slice(5, 10) || item.id.slice(0, 8)"></div>
<div class="text-gray-400 text-[10px]"
x-show="item.id === sessionId">← 現在</div>
</a>

<!-- 矢印 -->
<span x-show="index < chain.length - 1"
class="text-gray-400 text-sm flex-shrink-0">→</span>
</div>
</template>
</div>
</div>
```

### 3.4 統計カード (review用の拡張)

```html
<!-- idea の場合 -->
<template x-if="meta.type === 'idea'">
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
<div class="text-center p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20
border border-blue-200 dark:border-blue-800">
<div class="text-2xl font-bold font-mono text-blue-600 dark:text-blue-400"
x-text="formatTime(meta.statistics.duration_sec)"></div>
<div class="text-xs text-gray-500 mt-1">所要時間</div>
</div>
<div class="text-center p-4 rounded-xl bg-green-50 dark:bg-green-900/20
border border-green-200 dark:border-green-800">
<div class="text-2xl font-bold font-mono text-green-600 dark:text-green-400"
x-text="meta.statistics.total_utterances"></div>
<div class="text-xs text-gray-500 mt-1">発言数</div>
</div>
<div class="text-center p-4 rounded-xl bg-purple-50 dark:bg-purple-900/20
border border-purple-200 dark:border-purple-800">
<div class="text-2xl font-bold font-mono text-purple-600 dark:text-purple-400"
x-text="meta.statistics.total_tokens?.toLocaleString()"></div>
<div class="text-xs text-gray-500 mt-1">トークン</div>
</div>
<div class="text-center p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20
border border-amber-200 dark:border-amber-800">
<div class="text-2xl font-bold font-mono text-amber-600 dark:text-amber-400"
x-text="meta.statistics.final_convergence?.toFixed(2)"></div>
<div class="text-xs text-gray-500 mt-1">収束度</div>
</div>
</div>
</template>

<!-- review の場合 -->
<template x-if="meta.type === 'review'">
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
<div class="text-center p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20
border border-blue-200 dark:border-blue-800">
<div class="text-2xl font-bold font-mono text-blue-600 dark:text-blue-400"
x-text="formatTime(meta.statistics.duration_sec)"></div>
<div class="text-xs text-gray-500 mt-1">所要時間</div>
</div>
<div class="text-center p-4 rounded-xl bg-green-50 dark:bg-green-900/20
border border-green-200 dark:border-green-800">
<div class="text-2xl font-bold font-mono text-green-600 dark:text-green-400"
x-text="meta.statistics.files_reviewed"></div>
<div class="text-xs text-gray-500 mt-1">対象ファイル</div>
</div>
<div class="text-center p-4 rounded-xl bg-red-50 dark:bg-red-900/20
border border-red-200 dark:border-red-800">
<div class="text-2xl font-bold font-mono text-red-600 dark:text-red-400"
x-text="meta.statistics.total_findings"></div>
<div class="text-xs text-gray-500 mt-1">指摘事項</div>
</div>
<div class="text-center p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20
border border-amber-200 dark:border-amber-800">
<div class="flex items-center justify-center gap-1">
<span class="text-xs">🔴</span><span class="font-mono" x-text="meta.statistics.critical || 0"></span>
<span class="text-xs">🟠</span><span class="font-mono" x-text="meta.statistics.major || 0"></span>
<span class="text-xs">🟡</span><span class="font-mono" x-text="meta.statistics.minor || 0"></span>
</div>
<div class="text-xs text-gray-500 mt-1">深刻度</div>
</div>
</div>
</template>
```

### 3.5 タブコンテンツ

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl
border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">

<!-- タブヘッダー -->
<div class="flex border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
<template x-for="tab in availableTabs" :key="tab.id">
<button @click="activeTab = tab.id"
class="flex-shrink-0 px-4 py-3 text-sm font-medium transition-colors
border-b-2 whitespace-nowrap"
:class="{
'border-indigo-600 text-indigo-600 dark:text-indigo-400
dark:border-indigo-400 bg-indigo-50/50 dark:bg-indigo-900/10':
activeTab === tab.id,
'border-transparent text-gray-500 hover:text-gray-700
dark:hover:text-gray-300':
activeTab !== tab.id,
}"
x-text="tab.label">
</button>
</template>
</div>

<!-- タブコンテンツ -->
<div class="p-6 max-h-[70vh] overflow-y-auto custom-scrollbar">

<!-- Markdown系タブ (report, conversation, evaluation, summary, vibe_prompt) -->
<template x-for="tab in availableTabs" :key="tab.id">
<div x-show="activeTab === tab.id">
<template x-if="tab.format === 'markdown'">
<div class="prose-orchestra"
x-html="renderMarkdown(content[tab.id] || '')">
</div>
</template>
<template x-if="tab.format === 'text'">
<div class="text-sm text-gray-700 dark:text-gray-300
whitespace-pre-wrap font-mono"
x-text="content[tab.id] || ''">
</div>
</template>
</div>
</template>
</div>
</div>
```

### 3.6 アクションバー

```html
<div class="flex flex-wrap items-center justify-center gap-4 mt-8">
<!-- フォローアップ (idea のみ) -->
<a x-show="meta.type === 'idea'"
:href="'/idea?follow_up=' + sessionId"
class="px-6 py-3 rounded-xl text-indigo-600 dark:text-indigo-400
bg-indigo-50 dark:bg-indigo-900/20
border border-indigo-200 dark:border-indigo-800
hover:bg-indigo-100 dark:hover:bg-indigo-900/40
transition flex items-center gap-2">
<span>🔄</span>
<span>フォローアップ議論</span>
</a>

<!-- 修正指示書コピー (review のみ) -->
<button x-show="meta.type === 'review' && content.vibe_prompt"
@click="copyVibePrompt()"
class="px-6 py-3 rounded-xl text-green-600 dark:text-green-400
bg-green-50 dark:bg-green-900/20
border border-green-200 dark:border-green-800
hover:bg-green-100 dark:hover:bg-green-900/40
transition flex items-center gap-2">
<span>📋</span>
<span x-text="copied ? '✓ コピー済み' : '修正指示書をコピー'"></span>
</button>

<!-- ダウンロード -->
<div x-data="{ downloadOpen: false }" class="relative">
<button @click="downloadOpen = !downloadOpen"
class="px-6 py-3 rounded-xl text-gray-700 dark:text-gray-300
bg-gray-100 dark:bg-gray-700
hover:bg-gray-200 dark:hover:bg-gray-600
transition flex items-center gap-2">
<span>📥</span>
<span>ダウンロード</span>
<span class="text-xs">▼</span>
</button>

<div x-show="downloadOpen"
@click.away="downloadOpen = false"
x-transition
class="absolute bottom-full mb-2 right-0 w-48
bg-white dark:bg-gray-800 rounded-xl shadow-lg
border border-gray-200 dark:border-gray-700
overflow-hidden z-40">
<a :href="'/api/sessions/' + sessionId + '/download?file=report'"
class="block px-4 py-2 text-sm hover:bg-gray-50
dark:hover:bg-gray-700 transition">
📄 レポート (.md)
</a>
<a x-show="meta.type === 'review'"
:href="'/api/sessions/' + sessionId + '/download?file=vibe_prompt'"
class="block px-4 py-2 text-sm hover:bg-gray-50
dark:hover:bg-gray-700 transition">
🔧 修正指示書 (.md)
</a>
<a :href="'/api/sessions/' + sessionId + '/download?file=all'"
class="block px-4 py-2 text-sm hover:bg-gray-50
dark:hover:bg-gray-700 transition">
📦 全ファイル (.zip)
</a>
</div>
</div>

<!-- 履歴に戻る -->
<a href="/history"
class="px-6 py-3 rounded-xl text-gray-700 dark:text-gray-300
bg-gray-100 dark:bg-gray-700
hover:bg-gray-200 dark:hover:bg-gray-600
transition flex items-center gap-2">
<span>📚</span>
<span>履歴に戻る</span>
</a>
</div>
```

### 3.7 Alpine.js 状態管理 (replayPage)

```javascript
function replayPage(sessionId) {
return {
// State
sessionId: sessionId,
meta: {},
content: {},
chain: [],
loading: true,
activeTab: 'report',
copied: false,

// Computed
get availableTabs() {
const tabs = [
{ id: 'report', label: '📄 レポート', format: 'markdown' },
{ id: 'conversation', label: '💬 全会話', format: 'markdown' },
{ id: 'evaluation', label: '📊 評価', format: 'markdown' },
{ id: 'summary', label: '📋 要約', format: 'text' },
];
// review の場合は修正指示書タブを追加
if (this.meta.type === 'review' && this.content.vibe_prompt) {
tabs.splice(1, 0, {
id: 'vibe_prompt',
label: '🔧 修正指示書',
format: 'markdown',
});
}
return tabs;
},

// Methods
async loadSession() {
this.loading = true;
try {
// メタ情報
const metaRes = await fetch(`/api/sessions/${this.sessionId}`);
if (!metaRes.ok) {
if (metaRes.status === 404) {
toast('セッションが見つかりません', 'error');
window.location.href = '/history';
return;
}
throw new Error('読み込みに失敗しました');
}
this.meta = await metaRes.json();

// コンテンツ
const contentRes = await fetch(`/api/sessions/${this.sessionId}/content`);
const data = await contentRes.json();
this.content = data.files;
this.chain = data.chain || [];
} catch (err) {
toast(err.message, 'error');
} finally {
this.loading = false;
}
},

async copyVibePrompt() {
try {
await navigator.clipboard.writeText(this.content.vibe_prompt);
this.copied = true;
toast('修正指示書をコピーしました', 'success');
setTimeout(() => { this.copied = false; }, 3000);
} catch (err) {
toast('コピーに失敗しました', 'error');
}
},

// Lifecycle
init() {
this.loadSession();
},
};
}
```

---

## 4. API エンドポイント詳細

### 4.1 GET /api/sessions

```
Query Parameters:
- page: int (default: 1)
- limit: int (default: 10, max: 50)
- type: "idea" | "review" | null
- search: string | null (テーマ部分一致)
- sort: "date_desc" | "date_asc" | "duration_desc" | "convergence_desc"
- show_chains: "true" | null

Response:
{
"sessions": [
{
"id": "20260622_133204_idea",
"type": "idea",
"theme": "LLMの推論効率を改善する手法を議論して",
"date": "2026-06-22T13:32:04",
"duration_sec": 272.5,
"convergence": 0.87,
"mvp_emoji": "🧮",
"mvp_role_id": "theorist",
"focus": null,
"chain_depth": 0
}
],
"total": 25,
"page": 1,
"pages": 3,
"chains": [  // show_chains=true の場合のみ
[
{"id": "20260620_...", "date": "2026-06-20T..."},
{"id": "20260621_...", "date": "2026-06-21T..."},
{"id": "20260622_...", "date": "2026-06-22T..."}
]
]
}
```

### 4.2 GET /api/sessions/{id}

```
Response:
{
"id": "20260622_133204_idea",
"type": "idea",
"theme": "LLMの推論効率を改善する手法を議論して",
"created_at": "2026-06-22T13:32:04",
"parameters": {
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"time_limit": 300,
"max_agents": 5,
"expertise": "intermediate"
},
"agents": ["theorist", "experimentalist", "implementer", "literature", "devil"],
"statistics": {
"duration_sec": 272.5,
"total_utterances": 14,
"total_tokens": 2850,
"rounds_completed": 3,
"final_convergence": 0.87,
"mvp": "theorist"
},
"follow_up": {
"previous_session_id": null,
"chain_depth": 0
}
}
```

### 4.3 GET /api/sessions/{id}/content

```
Response:
{
"session_id": "20260622_133204_idea",
"files": {
"report": "# 議論レポート\n\n## ...",
"conversation": "# 全会話ログ\n\n## ...",
"evaluation": "# 評価結果\n\n## ...",
"summary": "このセッションでは...",
"vibe_prompt": "# 修正指示書\n\n## ..."  // review のみ
},
"chain": [
"20260620_idea",
"20260621_idea",
"20260622_133204_idea"
],
"hypotheses": [  // idea のみ
{"id": "H1", "text": "...", "status": "unverified", "evidence": "..."}
]
}
```

### 4.4 GET /api/sessions/{id}/download

```
Query Parameters:
- file: "report" | "vibe_prompt" | "conversation" | "evaluation" | "summary" | "all"

Response:
- file != "all": 単一ファイルのダウンロード (Content-Disposition: attachment)
- file == "all": ZIPファイルのダウンロード
```

### 4.5 DELETE /api/sessions/{id}

```
Response (200):
{
"status": "deleted",
"session_id": "20260622_133204_idea"
}

Response (404):
{
"detail": "Session not found"
}
```

---

## 5. バックエンド実装 (routes/api_sessions.py)

```python
"""セッション管理API。"""

import json
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions(
page: int = Query(1, ge=1),
limit: int = Query(10, ge=1, le=50),
type: str | None = None,
search: str | None = None,
sort: str = "date_desc",
show_chains: bool = False,
):
"""セッション一覧を返す。"""
output_dir = Path("output")
sessions = []

for session_dir in output_dir.iterdir():
if not session_dir.is_dir():
continue
meta_path = session_dir / "session_meta.json"
if not meta_path.exists():
continue

meta = json.loads(meta_path.read_text())

# フィルタ
if type and meta.get("type") != type:
continue
if search and search.lower() not in meta.get("theme", "").lower():
continue

sessions.append(_format_session_summary(meta, session_dir.name))

# ソート
sessions.sort(key=lambda s: _sort_key(s, sort), reverse="desc" in sort)

# ページネーション
total = len(sessions)
pages = (total + limit - 1) // limit
start = (page - 1) * limit
end = start + limit

result = {
"sessions": sessions[start:end],
"total": total,
"page": page,
"pages": pages,
}

if show_chains:
result["chains"] = _build_chains(sessions)

return result


@router.get("/api/sessions/recent")
async def recent_sessions(limit: int = 5, type: str | None = None):
"""最新N件のセッションを返す。"""
result = await list_sessions(page=1, limit=limit, type=type, sort="date_desc")
return result


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
"""セッション詳細を返す。"""
session_dir = Path("output") / session_id
meta_path = session_dir / "session_meta.json"

if not meta_path.exists():
raise HTTPException(status_code=404, detail="Session not found")

return json.loads(meta_path.read_text())


@router.get("/api/sessions/{session_id}/content")
async def get_session_content(session_id: str):
"""セッション全コンテンツを返す。"""
session_dir = Path("output") / session_id

if not session_dir.exists():
raise HTTPException(status_code=404, detail="Session not found")

files = {}
file_map = {
"report": "report.md",
"conversation": "full_conversation.md",
"evaluation": "evaluation.md",
"summary": "summary.txt",
"vibe_prompt": "vibe_coding_prompt.md",
}

for key, filename in file_map.items():
path = session_dir / filename
if path.exists():
files[key] = path.read_text()

# チェーン構築
chain = _build_session_chain(session_id)

# 仮説抽出 (discussion.json から)
hypotheses = _extract_hypotheses(session_dir)

return {
"session_id": session_id,
"files": files,
"chain": chain,
"hypotheses": hypotheses,
}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
"""セッションを削除する。"""
session_dir = Path("output") / session_id

if not session_dir.exists():
raise HTTPException(status_code=404, detail="Session not found")

shutil.rmtree(session_dir)
return {"status": "deleted", "session_id": session_id}


@router.get("/api/sessions/{session_id}/download")
async def download_session_file(session_id: str, file: str = "report"):
"""セッションファイルをダウンロードする。"""
session_dir = Path("output") / session_id

if not session_dir.exists():
raise HTTPException(status_code=404, detail="Session not found")

if file == "all":
# ZIP生成
return _create_zip_response(session_dir, session_id)

file_map = {
"report": "report.md",
"vibe_prompt": "vibe_coding_prompt.md",
"conversation": "full_conversation.md",
"evaluation": "evaluation.md",
"summary": "summary.txt",
}

filename = file_map.get(file)
if not filename:
raise HTTPException(status_code=400, detail=f"Unknown file: {file}")

path = session_dir / filename
if not path.exists():
raise HTTPException(status_code=404, detail=f"File not found: {filename}")

return FileResponse(
path,
filename=f"{session_id}_{filename}",
media_type="application/octet-stream",
)
```

---

## 6. レスポンシブ対応

### 6.1 履歴カードのモバイル表示

```
Mobile (< md):
┌─────────────────────────┐
│ 💡 idea  2026/06/22     │
│                         │
│ "LLMの推論効率を改善..." │
│                         │
│ ⏱️4:32 🎯0.87 🏆🧮     │
│                         │
│ [👁️表示] [🔄FU] [🗑️]   │
└─────────────────────────┘

Desktop (≥ md):
(上記 §2.3 のカードレイアウト — 横に広く使う)
```

### 6.2 チェーン表示のモバイル

```
Mobile: 横スクロール可能 (overflow-x-auto)
Desktop: 折り返さず1行表示
```

---

## 7. パフォーマンス考慮

| 項目 | 対策 |
|------|------|
| 大量セッション | サーバーサイドページネーション (10件/ページ) |
| 検索 | debounce 300ms でAPI呼び出し抑制 |
| 大きなMarkdown | max-h + overflow-y-auto で表示領域制限 |
| ファイルDL | StreamingResponse でメモリ効率化 |
| 画像なし | 絵文字で代替、追加リソース不要 |
