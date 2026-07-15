# AI Orchestra — ロール管理ページ設計

> `/roles` ページのロール一覧・詳細・統計の全仕様

---

## 1. 概要

| 項目 | 内容 |
|------|------|
| URL | `/roles` |
| テンプレート | `pages/roles.html` |
| Alpine.js | `rolesPage()` |
| 機能 | ロール一覧表示、詳細閲覧、統計表示 |
| データソース | `config/roles/*.yaml` + フィードバック履歴 |

---

## 2. 全体レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  🎭 AIロール一覧                                               │
│                                                                │
│  ┌── 説明テキスト ─────────────────────────────────────────┐   │
│  │  AI Orchestra で利用できる専門家ロール。                  │   │
│  │  各AIは独自の性格・専門性を持ち、議論に多角的な視点を     │   │
│  │  もたらします。                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── ロールカードグリッド (grid-cols-2 md:grid-cols-4) ────┐   │
│  │                                                          │   │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │   │
│  │  │ 🧮   │ │ 🔬   │ │ 🤖   │ │ 📚   │                  │   │
│  │  │理論屋│ │実験屋│ │実装屋│ │文献屋│                  │   │
│  │  │★4.2 │ │★3.8 │ │★4.5 │ │★4.0 │                  │   │
│  │  │8回   │ │6回   │ │7回   │ │5回   │                  │   │
│  │  └──────┘ └──────┘ └──────┘ └──────┘                  │   │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                  │   │
│  │  │ 😈   │ │ 🎯   │ │ 📐   │ │ 📝   │                  │   │
│  │  │穴探し│ │鳥の目│ │設計LD│ │可読LD│                  │   │
│  │  │★4.1 │ │★4.3 │ │★3.9 │ │★4.0 │                  │   │
│  │  └──────┘ └──────┘ └──────┘ └──────┘                  │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── 詳細パネル (カード選択時に展開) ──────────────────────┐   │
│  │                                                          │   │
│  │  (選択されたロールの詳細情報)                             │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── 全体統計 ─────────────────────────────────────────────┐   │
│  │  (ロール間比較チャート)                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. ロールカードグリッド

### 3.1 カード仕様

```
状態:
- 通常: 白背景、グレー枠
- ホバー: glow効果、scale、枠色変更
- 選択中: indigo枠、薄indigo背景
```

### 3.2 カードテンプレート

```html
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
<template x-for="role in roles" :key="role.id">
<button @click="selectRole(role.id)"
class="p-5 rounded-2xl border text-center transition-all duration-200
focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500
card-glow"
:class="{
'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20
shadow-lg shadow-indigo-100 dark:shadow-indigo-900/30':
selectedRoleId === role.id,
'border-gray-200 dark:border-gray-700
bg-white dark:bg-gray-800
hover:border-gray-300 dark:hover:border-gray-600':
selectedRoleId !== role.id,
}">

<!-- 絵文字 -->
<div class="text-4xl mb-2" x-text="role.emoji"></div>

<!-- 名前 -->
<div class="text-sm font-bold text-gray-800 dark:text-gray-200 mb-1"
x-text="role.name"></div>

<!-- ID (小さく) -->
<div class="text-xs text-gray-400 font-mono mb-3"
x-text="role.id"></div>

<!-- 統計 (あれば) -->
<div class="flex items-center justify-center gap-2"
x-show="role.stats">
<!-- 平均スコア -->
<div class="flex items-center gap-0.5">
<span class="text-xs text-amber-500">★</span>
<span class="text-xs font-mono font-medium text-gray-600 dark:text-gray-400"
x-text="role.stats?.avg_score?.toFixed(1) || '-'"></span>
</div>
<!-- セッション数 -->
<div class="text-xs text-gray-400">
<span x-text="role.stats?.session_count || 0"></span>回
</div>
</div>

<!-- 統計なし -->
<div class="text-xs text-gray-400 italic"
x-show="!role.stats || role.stats.session_count === 0">
未参加
</div>
</button>
</template>
</div>
```

---

## 4. 詳細パネル

### 4.1 レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ┌── 左: 基本情報 (md:w-1/2) ──┐ ┌── 右: 統計 (md:w-1/2) ──┐ │
│  │                              │ │                           │ │
│  │  🧮 理論屋 (theorist)        │ │  📊 パフォーマンス        │ │
│  │                              │ │                           │ │
│  │  専門分野:                    │ │  ┌── スコアチャート ──┐   │ │
│  │  数学的定式化、計算量解析、   │ │  │  (レーダーチャート)  │   │ │
│  │  収束証明                     │ │  └────────────────────┘   │ │
│  │                              │ │                           │ │
│  │  性格:                        │ │  自己評価: ★4.2 (↗️上昇)  │ │
│  │  厳密・論理的。数式で語り     │ │  他者評価: ★4.0            │ │
│  │  たがる                       │ │  MVP回数: 3 / 8            │ │
│  │                              │ │  トレンド: ↗️ improving     │ │
│  │  弱み:                        │ │                           │ │
│  │  実装コストを軽視しがち       │ │  セッション: 8回            │ │
│  │                              │ │                           │ │
│  │  発言ルール:                   │ │                           │ │
│  │  • 主張には計算量の根拠を添える│ │                           │ │
│  │  • 他者の直感を数式で再解釈する│ │                           │ │
│  │  • 実装不可能な理論に走らない  │ │                           │ │
│  │                              │ │                           │ │
│  └──────────────────────────────┘ └───────────────────────────┘ │
│                                                                │
│  ┌── フィードバック履歴 ───────────────────────────────────┐   │
│  │                                                          │   │
│  │  📅 2026/06/22 — "LLMの推論効率..."                      │   │
│  │  自己: 4.2 | 他者: 4.0 | "もう少し具体例を交えて..."     │   │
│  │                                                          │   │
│  │  📅 2026/06/20 — "Attention機構の..."                    │   │
│  │  自己: 4.5 | 他者: 4.3 | "数式の展開が丁寧で良い"        │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 詳細パネルテンプレート

```html
<div x-show="selectedRoleId"
x-transition:enter="transition ease-out duration-300"
x-transition:enter-start="opacity-0 translate-y-4"
x-transition:enter-end="opacity-100 translate-y-0"
class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm mb-8">

<!-- ヘッダー -->
<div class="flex items-center justify-between mb-6">
<div class="flex items-center gap-3">
<span class="text-3xl" x-text="selectedRole?.emoji"></span>
<div>
<h2 class="text-xl font-bold text-gray-900 dark:text-white"
x-text="selectedRole?.name"></h2>
<span class="text-sm text-gray-500 font-mono"
x-text="selectedRole?.id"></span>
</div>
</div>
<!-- 閉じるボタン -->
<button @click="selectedRoleId = null"
class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700
transition text-gray-400 hover:text-gray-600">
✕
</button>
</div>

<!-- 2カラム -->
<div class="grid grid-cols-1 md:grid-cols-2 gap-6">

<!-- 左: 基本情報 -->
<div class="space-y-4">
<!-- 専門分野 -->
<div>
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
専門分野
</h4>
<p class="text-sm text-gray-700 dark:text-gray-300"
x-text="selectedRole?.specialty"></p>
</div>

<!-- 性格 -->
<div>
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
性格
</h4>
<p class="text-sm text-gray-700 dark:text-gray-300"
x-text="selectedRole?.personality"></p>
</div>

<!-- 弱み -->
<div>
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">
弱み (自覚すべき点)
</h4>
<p class="text-sm text-orange-600 dark:text-orange-400"
x-text="selectedRole?.weaknesses"></p>
</div>

<!-- 発言ルール -->
<div>
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
発言ルール
</h4>
<ul class="space-y-1">
<template x-for="rule in selectedRole?.speaking_rules || []" :key="rule">
<li class="text-sm text-gray-600 dark:text-gray-400 flex items-start gap-2">
<span class="text-indigo-500 flex-shrink-0 mt-0.5">•</span>
<span x-text="rule"></span>
</li>
</template>
</ul>
</div>
</div>

<!-- 右: 統計 -->
<div class="space-y-4">
<!-- パフォーマンス概要 -->
<div class="p-4 rounded-xl bg-gray-50 dark:bg-gray-700/50">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
📊 パフォーマンス
</h4>

<template x-if="selectedRole?.stats?.session_count > 0">
<div class="space-y-3">
<!-- 自己評価 -->
<div class="flex items-center justify-between">
<span class="text-sm text-gray-600 dark:text-gray-400">自己評価</span>
<div class="flex items-center gap-2">
<div class="flex items-center gap-0.5">
<template x-for="i in 5">
<span class="text-sm"
:class="i <= Math.round(selectedRole.stats.self_avg) ?
'text-amber-400' : 'text-gray-300 dark:text-gray-600'">★</span>
</template>
</div>
<span class="text-sm font-mono font-medium"
x-text="selectedRole.stats.self_avg.toFixed(1)"></span>
</div>
</div>

<!-- 他者評価 -->
<div class="flex items-center justify-between">
<span class="text-sm text-gray-600 dark:text-gray-400">他者評価</span>
<div class="flex items-center gap-2">
<div class="flex items-center gap-0.5">
<template x-for="i in 5">
<span class="text-sm"
:class="i <= Math.round(selectedRole.stats.peer_avg) ?
'text-amber-400' : 'text-gray-300 dark:text-gray-600'">★</span>
</template>
</div>
<span class="text-sm font-mono font-medium"
x-text="selectedRole.stats.peer_avg.toFixed(1)"></span>
</div>
</div>

<!-- MVP -->
<div class="flex items-center justify-between">
<span class="text-sm text-gray-600 dark:text-gray-400">MVP回数</span>
<span class="text-sm font-medium">
<span x-text="selectedRole.stats.mvp_count"></span>
/
<span x-text="selectedRole.stats.session_count"></span>
セッション
</span>
</div>

<!-- トレンド -->
<div class="flex items-center justify-between">
<span class="text-sm text-gray-600 dark:text-gray-400">トレンド</span>
<span class="text-sm font-medium px-2 py-0.5 rounded-full"
:class="{
'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300':
selectedRole.stats.trend === 'improving',
'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300':
selectedRole.stats.trend === 'declining',
'bg-gray-100 text-gray-600 dark:bg-gray-600 dark:text-gray-300':
selectedRole.stats.trend === 'stable',
}">
<span x-text="{
improving: '↗️ 上昇',
declining: '↘️ 下降',
stable: '→ 安定'
}[selectedRole.stats.trend]"></span>
</span>
</div>

<!-- セッション数 -->
<div class="flex items-center justify-between">
<span class="text-sm text-gray-600 dark:text-gray-400">参加回数</span>
<span class="text-sm font-medium"
x-text="selectedRole.stats.session_count + '回'"></span>
</div>
</div>
</template>

<!-- 統計なし -->
<template x-if="!selectedRole?.stats || selectedRole?.stats?.session_count === 0">
<div class="text-center py-4">
<div class="text-2xl mb-2">📭</div>
<p class="text-sm text-gray-500">まだ参加履歴がありません</p>
</div>
</template>
</div>

<!-- スコア推移チャート (Chart.js) -->
<div x-show="selectedRole?.stats?.history?.length > 1">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
📈 スコア推移
</h4>
<canvas x-ref="scoreChart" class="w-full h-32"></canvas>
</div>
</div>
</div>

<!-- フィードバック履歴 -->
<div class="mt-6" x-show="selectedRole?.stats?.recent_feedback?.length > 0">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
💬 最近のフィードバック
</h4>
<div class="space-y-3 max-h-60 overflow-y-auto custom-scrollbar">
<template x-for="fb in selectedRole?.stats?.recent_feedback || []" :key="fb.session_id">
<div class="p-3 rounded-xl bg-gray-50 dark:bg-gray-700/50
border border-gray-100 dark:border-gray-600">
<!-- 日付 + テーマ -->
<div class="flex items-center gap-2 mb-1">
<span class="text-xs text-gray-400" x-text="fb.date"></span>
<span class="text-xs text-gray-500 truncate" x-text="'— ' + fb.topic"></span>
</div>
<!-- スコア -->
<div class="flex items-center gap-3 mb-1 text-xs">
<span class="text-gray-500">
自己: <span class="font-mono" x-text="fb.self_eval_avg.toFixed(1)"></span>
</span>
<span class="text-gray-500">
他者: <span class="font-mono" x-text="fb.peer_eval_avg.toFixed(1)"></span>
</span>
</div>
<!-- フィードバックテキスト -->
<p class="text-sm text-gray-700 dark:text-gray-300 italic"
x-text="'\"' + fb.orchestrator_feedback + '\"'"></p>
</div>
</template>
</div>
</div>
</div>
```

---

## 5. 全体統計セクション

### 5.1 ロール間比較

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm"
x-show="hasAnyStats">

<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>📊</span> ロール間比較
</h3>

<!-- 比較テーブル -->
<div class="overflow-x-auto">
<table class="w-full text-sm">
<thead>
<tr class="text-left text-gray-500 dark:text-gray-400
border-b border-gray-200 dark:border-gray-700">
<th class="pb-3 pl-2">ロール</th>
<th class="pb-3 text-center">参加回数</th>
<th class="pb-3 text-center">自己評価</th>
<th class="pb-3 text-center">他者評価</th>
<th class="pb-3 text-center">MVP率</th>
<th class="pb-3 text-center">トレンド</th>
</tr>
</thead>
<tbody>
<template x-for="role in rolesWithStats" :key="role.id">
<tr class="border-b border-gray-100 dark:border-gray-800
hover:bg-gray-50 dark:hover:bg-gray-700/30 transition cursor-pointer"
@click="selectRole(role.id)">
<!-- ロール名 -->
<td class="py-3 pl-2">
<div class="flex items-center gap-2">
<span x-text="role.emoji"></span>
<span class="font-medium text-gray-700 dark:text-gray-300"
x-text="role.name"></span>
</div>
</td>
<!-- 参加回数 -->
<td class="py-3 text-center">
<span class="font-mono" x-text="role.stats.session_count"></span>
</td>
<!-- 自己評価 -->
<td class="py-3 text-center">
<div class="flex items-center justify-center gap-1">
<span class="font-mono" x-text="role.stats.self_avg.toFixed(1)"></span>
<div class="w-16 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
<div class="h-full bg-amber-400 rounded-full"
:style="'width: ' + (role.stats.self_avg / 5 * 100) + '%'"></div>
</div>
</div>
</td>
<!-- 他者評価 -->
<td class="py-3 text-center">
<div class="flex items-center justify-center gap-1">
<span class="font-mono" x-text="role.stats.peer_avg.toFixed(1)"></span>
<div class="w-16 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
<div class="h-full bg-indigo-400 rounded-full"
:style="'width: ' + (role.stats.peer_avg / 5 * 100) + '%'"></div>
</div>
</div>
</td>
<!-- MVP率 -->
<td class="py-3 text-center">
<span class="font-mono"
x-text="Math.round(role.stats.mvp_count / role.stats.session_count * 100) + '%'">
</span>
</td>
<!-- トレンド -->
<td class="py-3 text-center">
<span x-text="{
improving: '↗️',
declining: '↘️',
stable: '→'
}[role.stats.trend]"></span>
</td>
</tr>
</template>
</tbody>
</table>
</div>

<!-- ランキングハイライト -->
<div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
<!-- 最高評価 -->
<div class="p-3 rounded-xl bg-amber-50 dark:bg-amber-900/10
border border-amber-200 dark:border-amber-800 text-center">
<div class="text-xs text-amber-600 dark:text-amber-400 mb-1">🏆 最高評価</div>
<div class="text-xl" x-text="topRated?.emoji || '-'"></div>
<div class="text-sm font-medium" x-text="topRated?.name || '-'"></div>
<div class="text-xs text-gray-500"
x-text="topRated ? '★' + topRated.stats.peer_avg.toFixed(1) : ''"></div>
</div>

<!-- 最多MVP -->
<div class="p-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/10
border border-indigo-200 dark:border-indigo-800 text-center">
<div class="text-xs text-indigo-600 dark:text-indigo-400 mb-1">⭐ 最多MVP</div>
<div class="text-xl" x-text="topMVP?.emoji || '-'"></div>
<div class="text-sm font-medium" x-text="topMVP?.name || '-'"></div>
<div class="text-xs text-gray-500"
x-text="topMVP ? topMVP.stats.mvp_count + '回' : ''"></div>
</div>

<!-- 最多参加 -->
<div class="p-3 rounded-xl bg-green-50 dark:bg-green-900/10
border border-green-200 dark:border-green-800 text-center">
<div class="text-xs text-green-600 dark:text-green-400 mb-1">🎯 最多参加</div>
<div class="text-xl" x-text="mostActive?.emoji || '-'"></div>
<div class="text-sm font-medium" x-text="mostActive?.name || '-'"></div>
<div class="text-xs text-gray-500"
x-text="mostActive ? mostActive.stats.session_count + '回' : ''"></div>
</div>
</div>
</div>
```

---

## 6. スコア推移チャート (Chart.js)

### 6.1 チャート描画

```javascript
drawScoreChart() {
if (!this.selectedRole?.stats?.history?.length) return;

const ctx = this.$refs.scoreChart?.getContext('2d');
if (!ctx) return;

// 既存チャートを破棄
if (this.chartInstance) {
this.chartInstance.destroy();
}

const history = this.selectedRole.stats.history;
const labels = history.map(h => h.date.slice(5, 10)); // "06/22" 形式

this.chartInstance = new Chart(ctx, {
type: 'line',
data: {
labels: labels,
datasets: [
{
label: '自己評価',
data: history.map(h => h.self_eval_avg),
borderColor: '#f59e0b',
backgroundColor: 'rgba(245, 158, 11, 0.1)',
tension: 0.3,
fill: true,
pointRadius: 3,
},
{
label: '他者評価',
data: history.map(h => h.peer_eval_avg),
borderColor: '#6366f1',
backgroundColor: 'rgba(99, 102, 241, 0.1)',
tension: 0.3,
fill: true,
pointRadius: 3,
},
],
},
options: {
responsive: true,
maintainAspectRatio: false,
plugins: {
legend: {
position: 'bottom',
labels: { boxWidth: 12, padding: 16, font: { size: 11 } },
},
},
scales: {
y: {
min: 1,
max: 5,
ticks: { stepSize: 1, font: { size: 10 } },
grid: { color: 'rgba(156, 163, 175, 0.2)' },
},
x: {
ticks: { font: { size: 10 } },
grid: { display: false },
},
},
},
});
},
```

---

## 7. Alpine.js 状態管理 (rolesPage)

```javascript
function rolesPage() {
return {
// State
roles: [],
selectedRoleId: null,
selectedRole: null,
loading: true,
chartInstance: null,

// Computed
get hasAnyStats() {
return this.roles.some(r => r.stats && r.stats.session_count > 0);
},

get rolesWithStats() {
return this.roles
.filter(r => r.stats && r.stats.session_count > 0)
.sort((a, b) => b.stats.peer_avg - a.stats.peer_avg);
},

get topRated() {
const sorted = this.rolesWithStats.sort((a, b) =>
b.stats.peer_avg - a.stats.peer_avg
);
return sorted[0] || null;
},

get topMVP() {
const sorted = this.rolesWithStats.sort((a, b) =>
b.stats.mvp_count - a.stats.mvp_count
);
return sorted[0] || null;
},

get mostActive() {
const sorted = this.rolesWithStats.sort((a, b) =>
b.stats.session_count - a.stats.session_count
);
return sorted[0] || null;
},

// Methods
async loadRoles() {
this.loading = true;
try {
const res = await fetch('/api/roles');
this.roles = await res.json();
} catch (err) {
toast('ロール情報の読み込みに失敗しました', 'error');
} finally {
this.loading = false;
}
},

async selectRole(roleId) {
if (this.selectedRoleId === roleId) {
// 同じカードをクリックで閉じる
this.selectedRoleId = null;
this.selectedRole = null;
return;
}

this.selectedRoleId = roleId;

try {
const res = await fetch(`/api/roles/${roleId}`);
this.selectedRole = await res.json();

// 統計もロード
const statsRes = await fetch(`/api/roles/${roleId}/stats`);
if (statsRes.ok) {
const stats = await statsRes.json();
this.selectedRole.stats = stats;
}

// チャート描画
this.$nextTick(() => this.drawScoreChart());
} catch (err) {
toast('ロール詳細の読み込みに失敗しました', 'error');
}

// 詳細パネルまでスクロール
this.$nextTick(() => {
const panel = document.querySelector('[x-show="selectedRoleId"]');
if (panel) {
panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
});
},

drawScoreChart() { /* 上記 §6.1 */ },

// Lifecycle
init() {
this.loadRoles();
},

destroy() {
if (this.chartInstance) {
this.chartInstance.destroy();
}
},
};
}
```

---

## 8. API エンドポイント

### 8.1 GET /api/roles

```
Response:
[
{
"id": "theorist",
"name": "理論屋",
"emoji": "🧮",
"specialty": "数学的定式化、計算量解析、収束証明",
"stats": {
"session_count": 8,
"avg_score": 4.1
}
},
...
]
```

### 8.2 GET /api/roles/{role_id}

```
Response:
{
"id": "theorist",
"name": "理論屋",
"emoji": "🧮",
"specialty": "数学的定式化、計算量解析、収束証明",
"personality": "厳密・論理的。数式で語りたがる",
"weaknesses": "実装コストを軽視しがち",
"speaking_rules": [
"主張には必ず計算量や証明の根拠を添える",
"他者の直感的主張を数式で再解釈する",
"実装不可能な理論に走りすぎない"
]
}
```

### 8.3 GET /api/roles/{role_id}/stats

```
Response:
{
"role_id": "theorist",
"session_count": 8,
"self_avg": 4.2,
"peer_avg": 4.0,
"mvp_count": 3,
"trend": "improving",
"history": [
{
"session_id": "20260618_...",
"date": "2026-06-18",
"topic": "Transformer最適化...",
"self_eval_avg": 3.8,
"peer_eval_avg": 3.5
},
{
"session_id": "20260620_...",
"date": "2026-06-20",
"topic": "Attention機構...",
"self_eval_avg": 4.5,
"peer_eval_avg": 4.3
},
{
"session_id": "20260622_...",
"date": "2026-06-22",
"topic": "LLM推論効率...",
"self_eval_avg": 4.2,
"peer_eval_avg": 4.0
}
],
"recent_feedback": [
{
"session_id": "20260622_133204_idea",
"date": "2026/06/22",
"topic": "LLM推論効率...",
"self_eval_avg": 4.2,
"peer_eval_avg": 4.0,
"orchestrator_feedback": "もう少し具体例を交えて説明すると良い"
}
]
}
```

---

## 9. バックエンド実装 (routes/api_roles.py)

```python
"""ロール管理API。"""

from fastapi import APIRouter, HTTPException
from pathlib import Path

import yaml

router = APIRouter()


@router.get("/api/roles")
async def list_roles():
"""全ロール一覧を返す (統計サマリー付き)。"""
roles_dir = Path("config/roles")
roles = []

for yaml_path in sorted(roles_dir.glob("*.yaml")):
role = yaml.safe_load(yaml_path.read_text())
stats = _get_role_stats_summary(role["id"])
roles.append({
"id": role["id"],
"name": role["name"],
"emoji": role["emoji"],
"specialty": role["specialty"],
"stats": stats,
})

return roles


@router.get("/api/roles/{role_id}")
async def get_role(role_id: str):
"""ロール詳細を返す。"""
roles_dir = Path("config/roles")
yaml_path = roles_dir / f"{role_id}.yaml"

if not yaml_path.exists():
raise HTTPException(status_code=404, detail=f"Role not found: {role_id}")

role = yaml.safe_load(yaml_path.read_text())
return {
"id": role["id"],
"name": role["name"],
"emoji": role["emoji"],
"specialty": role["specialty"],
"personality": role.get("personality", ""),
"weaknesses": role.get("weaknesses", ""),
"speaking_rules": role.get("speaking_rules", []),
}


@router.get("/api/roles/{role_id}/stats")
async def get_role_stats(role_id: str):
"""ロール別統計を返す。"""
roles_dir = Path("config/roles")
yaml_path = roles_dir / f"{role_id}.yaml"

if not yaml_path.exists():
raise HTTPException(status_code=404, detail=f"Role not found: {role_id}")

role = yaml.safe_load(yaml_path.read_text())
feedback_history = role.get("feedback_history", [])

if not feedback_history:
return {
"role_id": role_id,
"session_count": 0,
"self_avg": 0.0,
"peer_avg": 0.0,
"mvp_count": 0,
"trend": "stable",
"history": [],
"recent_feedback": [],
}

# 統計計算
self_scores = [h["self_eval_avg"] for h in feedback_history if "self_eval_avg" in h]
peer_scores = [h["peer_eval_avg"] for h in feedback_history if "peer_eval_avg" in h]
mvp_count = _count_mvp(role_id)
trend = _calculate_trend(peer_scores)

return {
"role_id": role_id,
"session_count": len(feedback_history),
"self_avg": sum(self_scores) / len(self_scores) if self_scores else 0.0,
"peer_avg": sum(peer_scores) / len(peer_scores) if peer_scores else 0.0,
"mvp_count": mvp_count,
"trend": trend,
"history": feedback_history[-10:],  # 直近10件
"recent_feedback": feedback_history[-5:],  # 直近5件
}
```

---

## 10. 将来機能: カスタムロール作成

### 10.1 UIモックアップ (未実装)

```
┌── カスタムロール作成 (将来機能) ──────────────────────────────┐
│                                                               │
│  [+ 新しいロールを作成]                                       │
│                                                               │
│  ┌── フォーム ─────────────────────────────────────────────┐  │
│  │ ID:       [custom_ceo     ]                             │  │
│  │ 名前:     [孫正義AI        ]                             │  │
│  │ 絵文字:   [🦅             ]                             │  │
│  │ 専門:     [ビジョン提示、大局観  ]                       │  │
│  │ 性格:     [大胆・挑戦的。300年ビジョンで語る ]           │  │
│  │ 弱み:     [詳細な実装計画を軽視しがち ]                  │  │
│  │ ルール:                                                  │  │
│  │   [+ ルール追加]                                         │  │
│  │                                                          │  │
│  │ [プレビュー]  [保存]                                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 10.2 プレースホルダーボタン

```html
<!-- 将来機能のプレースホルダー -->
<div class="mt-8 text-center">
<button disabled
class="px-6 py-3 rounded-xl text-gray-400 dark:text-gray-600
bg-gray-100 dark:bg-gray-800
border border-dashed border-gray-300 dark:border-gray-700
cursor-not-allowed">
<span class="flex items-center gap-2">
<span>+</span>
<span>カスタムロールを追加 (Coming Soon)</span>
</span>
</button>
</div>
```

---

## 11. レスポンシブ対応

### 11.1 カードグリッド

```
Mobile (< md): grid-cols-2 (2列)
Tablet+ (≥ md): grid-cols-4 (4列)
```

### 11.2 詳細パネル

```
Mobile (< md): 1列 (基本情報 → 統計 → フィードバック 縦積み)
Tablet+ (≥ md): 2列 (左: 基本情報 | 右: 統計)
```

### 11.3 比較テーブル

```
Mobile: 横スクロール (overflow-x-auto)
Desktop: 全列表示
```

---

## 12. アクセシビリティ

| 要素 | 対応 |
|------|------|
| ロールカード | `<button>` で実装 (キーボード操作可能) |
| 選択状態 | `aria-selected` 属性 |
| 詳細パネル | `aria-expanded` + `aria-controls` |
| チャート | `aria-label` で代替テキスト |
| 色のみに依存しない | トレンドは矢印テキスト + 色で表現 |
