# AI Orchestra — Idea 議論ページ詳細設計

> `/idea` ページの4ステップウィザード全仕様

---

## 1. 概要

| 項目 | 内容 |
|------|------|
| URL | `/idea` (クエリ: `?follow_up={session_id}`) |
| テンプレート | `pages/idea.html` |
| Alpine.js | `ideaPage()` |
| ステップ数 | 4 (入力 → 計画確認 → 議論 → 結果) |
| 通信 | REST (plan) + SSE (stream) |
| 所要時間 | 1〜30分 (設定次第) |

---

## 2. ステップ全体図

```
● 1 入力 ─── ● 2 計画確認 ─── ● 3 議論 ─── ● 4 結果
│              │                │              │
│ フォーム入力  │ 計画レビュー    │ リアルタイム   │ レポート表示
│ 設定調整     │ 修正 or 承認   │ チャットUI    │ DL/フォローアップ
│              │                │              │
│ POST         │ POST           │ SSE          │ GET
│ /api/idea/   │ /api/idea/     │ (streaming)  │ /api/sessions/
│ plan         │ stream         │              │ {id}/content
```

---

## 3. Step 1: テーマ入力

### 3.1 レイアウト

```
┌──── 左カラム (md:w-2/5) ──────────────┐ ┌──── 右カラム (md:w-3/5) ──┐
│                                        │ │                           │
│  📝 テーマを入力                        │ │  🎭 参加予定AI             │
│  ┌──────────────────────────────────┐  │ │                           │
│  │                                  │  │ │  🧮🔬🤖📚😈              │
│  │  (テキストエリア 5行)             │  │ │  (max_agents分表示)        │
│  │                                  │  │ │                           │
│  │  placeholder: "例: LLMの推論     │  │ │  ⏱️ 推定所要時間           │
│  │  効率を改善する手法を議論して"    │  │ │  5分00秒                   │
│  │                                  │  │ │                           │
│  └──────────────────────────────────┘  │ │  📊 リソース見積           │
│  文字数: 42 / 5000                     │ │  約36リクエスト             │
│                                        │ │  残り: 9,964 / 10,000      │
│  ⚙️ モデル設定                          │ │                           │
│  ▶ (アコーディオン — 閉じた状態)       │ │  ── 過去の類似議論 ──      │
│                                        │ │  (あれば表示)              │
│  🎛️ 議論設定                           │ │                           │
│  ▶ (アコーディオン — 閉じた状態)       │ │                           │
│                                        │ │                           │
│  🔧 高度な設定                          │ │                           │
│  ▶ (アコーディオン — 閉じた状態)       │ │                           │
│                                        │ │                           │
│  ┌──────────────────────────────────┐  │ │                           │
│  │  🚀 議論を計画する               │  │ │                           │
│  └──────────────────────────────────┘  │ │                           │
│                                        │ │                           │
└────────────────────────────────────────┘ └───────────────────────────┘
```

### 3.2 テーマ入力フィールド

```html
<div class="space-y-2">
<label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
📝 議論テーマ <span class="text-red-500">*</span>
</label>

<textarea x-model="prompt"
@input="saveToStorage()"
rows="5"
maxlength="5000"
placeholder="例: LLMの推論効率を改善する手法を議論して"
class="w-full rounded-xl border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800
text-gray-900 dark:text-gray-100
px-4 py-3 text-sm
focus:ring-2 focus:ring-indigo-500 focus:border-transparent
resize-none transition"
:class="{ 'border-red-400': prompt.length > 0 && prompt.length < 5 }">
</textarea>

<!-- 文字数カウンター -->
<div class="flex justify-between text-xs">
<span :class="{
'text-red-500': prompt.length > 0 && prompt.length < 5,
'text-gray-400': prompt.length === 0 || prompt.length >= 5,
}">
<span x-show="prompt.length > 0 && prompt.length < 5">
5文字以上入力してください
</span>
</span>
<span class="text-gray-400">
<span x-text="prompt.length">0</span> / 5,000
</span>
</div>
</div>
```

### 3.3 モデル設定 (アコーディオン)

```html
<details class="group rounded-xl border border-gray-200 dark:border-gray-700">
<summary class="flex items-center justify-between p-4 cursor-pointer
hover:bg-gray-50 dark:hover:bg-gray-800/50 transition rounded-xl">
<span class="text-sm font-medium text-gray-700 dark:text-gray-300">
⚙️ モデル設定
</span>
<span class="text-gray-400 transition-transform group-open:rotate-180">▼</span>
</summary>

<div class="p-4 pt-0 space-y-4">
<!-- 計画モデル -->
<div>
<label class="block text-xs text-gray-500 mb-1">計画立案モデル (Phase 1)</label>
<select x-model="settings.plannerModel"
class="w-full rounded-lg border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-3 py-2">
<option value="gpt-5.4">gpt-5.4 (高品質)</option>
<option value="gpt-4.1">gpt-4.1 (標準)</option>
</select>
</div>

<!-- 議論モデル -->
<div>
<label class="block text-xs text-gray-500 mb-1">議論進行モデル (Phase 2)</label>
<select x-model="settings.conductorModel"
class="w-full rounded-lg border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-3 py-2">
<option value="gpt-4.1">gpt-4.1 (推奨)</option>
<option value="gpt-5.4">gpt-5.4 (高品質)</option>
</select>
</div>

<!-- 統合モデル -->
<div>
<label class="block text-xs text-gray-500 mb-1">統合モデル (Phase 3)</label>
<select x-model="settings.synthModel"
class="w-full rounded-lg border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-3 py-2">
<option value="gpt-5.4">gpt-5.4 (推奨)</option>
<option value="gpt-4.1">gpt-4.1 (標準)</option>
</select>
</div>
</div>
</details>
```

### 3.4 議論設定 (アコーディオン)

```html
<details class="group rounded-xl border border-gray-200 dark:border-gray-700">
<summary class="flex items-center justify-between p-4 cursor-pointer
hover:bg-gray-50 dark:hover:bg-gray-800/50 transition rounded-xl">
<span class="text-sm font-medium text-gray-700 dark:text-gray-300">
🎛️ 議論設定
</span>
<span class="text-gray-400 transition-transform group-open:rotate-180">▼</span>
</summary>

<div class="p-4 pt-0 space-y-6">
<!-- 時間制限スライダー -->
<div>
<div class="flex justify-between items-center mb-2">
<label class="text-xs text-gray-500">制限時間</label>
<span class="text-sm font-mono font-medium text-indigo-600 dark:text-indigo-400"
x-text="formatTime(settings.timeLimit)">5:00</span>
</div>
<input type="range"
x-model.number="settings.timeLimit"
min="60" max="1800" step="30"
@input="saveToStorage()"
class="w-full h-2 rounded-full appearance-none cursor-pointer
bg-gray-200 dark:bg-gray-700
accent-indigo-600">
<div class="flex justify-between text-xs text-gray-400 mt-1">
<span>1分</span>
<span>30分</span>
</div>
</div>

<!-- 最大AI数 -->
<div>
<div class="flex justify-between items-center mb-2">
<label class="text-xs text-gray-500">最大参加AI数</label>
<span class="text-sm font-mono font-medium text-indigo-600 dark:text-indigo-400"
x-text="settings.maxAgents + '名'">5名</span>
</div>
<input type="range"
x-model.number="settings.maxAgents"
min="2" max="8" step="1"
class="w-full h-2 rounded-full appearance-none cursor-pointer
bg-gray-200 dark:bg-gray-700
accent-indigo-600">
<div class="flex justify-between text-xs text-gray-400 mt-1">
<span>2名</span>
<span>8名</span>
</div>
</div>

<!-- 専門レベル -->
<div>
<label class="block text-xs text-gray-500 mb-2">専門レベル</label>
<div class="grid grid-cols-3 gap-2">
<template x-for="level in [
{id: 'beginner', label: '初級', desc: '平易な表現で'},
{id: 'intermediate', label: '中級', desc: '研究者レベル'},
{id: 'expert', label: '上級', desc: '数式・引用含む'},
]" :key="level.id">
<label class="relative cursor-pointer">
<input type="radio" name="expertise"
:value="level.id"
x-model="settings.expertise"
class="peer sr-only">
<div class="p-3 rounded-xl border text-center transition
peer-checked:border-indigo-500 peer-checked:bg-indigo-50
dark:peer-checked:bg-indigo-900/30
border-gray-200 dark:border-gray-700
hover:border-gray-300 dark:hover:border-gray-600">
<div class="text-sm font-medium" x-text="level.label"></div>
<div class="text-xs text-gray-400 mt-0.5" x-text="level.desc"></div>
</div>
</label>
</template>
</div>
</div>
</div>
</details>
```

### 3.5 高度な設定 (アコーディオン)

```html
<details class="group rounded-xl border border-gray-200 dark:border-gray-700">
<summary class="flex items-center justify-between p-4 cursor-pointer
hover:bg-gray-50 dark:hover:bg-gray-800/50 transition rounded-xl">
<span class="text-sm font-medium text-gray-700 dark:text-gray-300">
🔧 高度な設定
</span>
<span class="text-gray-400 transition-transform group-open:rotate-180">▼</span>
</summary>

<div class="p-4 pt-0 space-y-4">
<!-- フォローアップ選択 -->
<div>
<label class="block text-xs text-gray-500 mb-1">
フォローアップ (前回セッションを引き継ぐ)
</label>
<select x-model="settings.followUpId"
@change="loadFollowUpContext()"
class="w-full rounded-lg border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-3 py-2">
<option value="">なし (新規議論)</option>
<template x-for="session in previousSessions" :key="session.id">
<option :value="session.id"
x-text="session.date + ' — ' + session.theme.slice(0, 30)">
</option>
</template>
</select>
</div>

<!-- フォローアップ選択時: 仮説リスト -->
<template x-if="followUpContext">
<div class="p-3 rounded-xl bg-indigo-50 dark:bg-indigo-900/20
border border-indigo-200 dark:border-indigo-700">
<div class="text-xs font-medium text-indigo-700 dark:text-indigo-300 mb-2">
📋 前回の仮説 (重点検証する仮説を選択)
</div>
{% include "components/hypothesis_table.html" %}
</div>
</template>

<!-- 添付ファイル -->
<div>
<label class="block text-xs text-gray-500 mb-1">
添付ファイル (議論の参考資料)
</label>
{% include "components/file_drop.html" %}
</div>
</div>
</details>
```

### 3.6 右カラム (プレビューパネル)

```html
<div class="sticky top-24 space-y-4">

<!-- 参加予定AI -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-sm font-medium text-gray-500 mb-3">🎭 参加予定AI</h4>
<div class="flex flex-wrap gap-2">
<template x-for="i in settings.maxAgents" :key="i">
<div class="w-10 h-10 rounded-full bg-gray-100 dark:bg-gray-700
flex items-center justify-center text-lg
animate-fade-in"
:style="'animation-delay: ' + (i * 50) + 'ms'"
x-text="defaultAgentEmojis[i-1] || '?'">
</div>
</template>
</div>
</div>

<!-- 推定所要時間 -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-sm font-medium text-gray-500 mb-2">⏱️ 推定所要時間</h4>
<div class="text-2xl font-mono font-bold text-indigo-600 dark:text-indigo-400"
x-text="formatTime(settings.timeLimit)">
5:00
</div>
<div class="text-xs text-gray-400 mt-1">
Phase 1 (計画) + Phase 2 (議論) + Phase 3 (統合)
</div>
</div>

<!-- リソース見積 -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-sm font-medium text-gray-500 mb-2">📊 リソース見積</h4>
<div class="space-y-2 text-sm">
<div class="flex justify-between">
<span class="text-gray-500">推定リクエスト</span>
<span class="font-medium" x-text="'約' + estimatedRequests">約36</span>
</div>
<div class="flex justify-between">
<span class="text-gray-500">残りクォータ</span>
<span class="font-medium" x-text="remainingQuota.toLocaleString()">9,964</span>
</div>
<!-- クォータバー -->
<div class="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full">
<div class="h-full bg-green-500 rounded-full"
:style="'width: ' + ((10000 - remainingQuota) / 10000 * 100) + '%'">
</div>
</div>
</div>
</div>

<!-- フォローアップ情報 (選択時のみ) -->
<template x-if="followUpContext">
<div class="bg-amber-50 dark:bg-amber-900/20 rounded-xl p-4
border border-amber-200 dark:border-amber-700 shadow-sm">
<h4 class="text-sm font-medium text-amber-700 dark:text-amber-300 mb-2">
🔄 フォローアップ
</h4>
<div class="text-xs text-gray-600 dark:text-gray-400">
<div class="mb-1">前回: <span x-text="followUpContext.previous_session_id"></span></div>
<div class="mb-1">チェーン深度: <span x-text="followUpContext.chain_depth"></span></div>
<div>仮説数: <span x-text="followUpContext.hypotheses.length"></span></div>
</div>
</div>
</template>
</div>
```

### 3.7 送信ボタン + バリデーション

```html
<div class="mt-6">
<button @click="submitPlan()"
:disabled="!isPromptValid || planLoading"
class="w-full py-3 px-6 rounded-xl text-white font-medium
bg-indigo-600 hover:bg-indigo-700
disabled:opacity-50 disabled:cursor-not-allowed
transition flex items-center justify-center gap-2">
<!-- スピナー -->
<svg x-show="planLoading" class="animate-spin h-4 w-4" viewBox="0 0 24 24">
<circle class="opacity-25" cx="12" cy="12" r="10"
stroke="currentColor" stroke-width="4" fill="none"></circle>
<path class="opacity-75" fill="currentColor"
d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
</svg>
<span x-text="planLoading ? '計画を立案中...' : '🚀 議論を計画する'"></span>
</button>

<!-- バリデーションメッセージ -->
<p x-show="!isPromptValid && prompt.length > 0"
class="text-xs text-red-500 mt-2 text-center">
テーマは5文字以上入力してください
</p>
</div>
```

---

## 4. Step 2: 計画確認

### 4.1 レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  📋 議論計画                                                   │
│                                                                │
│  ┌── plan_card.html ───────────────────────────────────────┐   │
│  │ (ODSC + 参加AI + ラウンド計画 + リソース見積)           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌── アクションバー ───────────────────────────────────────┐   │
│  │                                                         │   │
│  │  [← テーマを修正]              [🎬 議論を開始する]      │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 アクションバー

```html
<div class="flex flex-col sm:flex-row items-center justify-between gap-4 mt-8">
<!-- 戻るボタン -->
<button @click="step = 1"
class="px-6 py-3 rounded-xl text-gray-700 dark:text-gray-300
bg-gray-100 dark:bg-gray-700
hover:bg-gray-200 dark:hover:bg-gray-600
transition flex items-center gap-2">
<span>←</span>
<span>テーマを修正</span>
</button>

<!-- 開始ボタン -->
<button @click="startDiscussion()"
:disabled="startLoading"
class="px-8 py-3 rounded-xl text-white font-medium
bg-gradient-to-r from-indigo-600 to-purple-600
hover:from-indigo-700 hover:to-purple-700
disabled:opacity-50 disabled:cursor-not-allowed
transition shadow-lg shadow-indigo-200 dark:shadow-indigo-900/50
flex items-center gap-2">
<svg x-show="startLoading" class="animate-spin h-4 w-4" viewBox="0 0 24 24">
<circle class="opacity-25" cx="12" cy="12" r="10"
stroke="currentColor" stroke-width="4" fill="none"></circle>
<path class="opacity-75" fill="currentColor"
d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
</svg>
<span x-text="startLoading ? '準備中...' : '🎬 議論を開始する'"></span>
</button>
</div>
```

---

## 5. Step 3: 議論リアルタイム表示

### 5.1 レイアウト

```
┌──── サイドバー (md:w-72) ─────────┐ ┌──── チャットエリア (flex-1) ──────────────┐
│                                    │ │                                           │
│  ┌── タイマー ──────────────────┐  │ │  ┌── チャットヘッダー ─────────────────┐  │
│  │ timer.html                   │  │ │  │ "Round 1: 発散 (one_shot)"          │  │
│  └──────────────────────────────┘  │ │  └───────────────────────────────────────┘  │
│                                    │ │                                           │
│  ┌── ラウンド情報 ──────────────┐  │ │  ┌── メッセージ一覧 (overflow-y-auto) ──┐  │
│  │ Round: 2 / 3                 │  │ │  │                                       │  │
│  │ Phase: deepen                │  │ │  │  (chat_bubble.html × n)               │  │
│  │ Pattern: ping_pong           │  │ │  │                                       │  │
│  └──────────────────────────────┘  │ │  │  (ラウンド区切り)                     │  │
│                                    │ │  │                                       │  │
│  ┌── 参加AI ────────────────────┐  │ │  │  (chat_bubble.html × n)               │  │
│  │ agent_badge (md) × n         │  │ │  │                                       │  │
│  │ (ステータス付き)              │  │ │  │  (結論バブル)                         │  │
│  └──────────────────────────────┘  │ │  │                                       │  │
│                                    │ │  └───────────────────────────────────────┘  │
│  ┌── リアルタイム統計 ──────────┐  │ │                                           │
│  │ 発言数: 8                    │  │ │  ┌── "↓ 最新へ" ボタン (条件表示) ─────┐  │
│  │ トークン: 1,200              │  │ │  └───────────────────────────────────────┘  │
│  │ 収束度: 0.72                 │  │ │                                           │
│  └──────────────────────────────┘  │ │                                           │
│                                    │ │                                           │
│  ┌── 制御 ──────────────────────┐  │ │                                           │
│  │ [🛑 中断]                    │  │ │                                           │
│  └──────────────────────────────┘  │ │                                           │
│                                    │ │                                           │
└────────────────────────────────────┘ └───────────────────────────────────────────┘
```

### 5.2 チャットエリア実装

```html
<div class="flex-1 flex flex-col h-[calc(100vh-180px)]">

<!-- チャットヘッダー -->
<div class="flex items-center justify-between px-4 py-3
bg-white dark:bg-gray-800
border-b border-gray-200 dark:border-gray-700 rounded-t-xl">
<div class="flex items-center gap-3">
<span class="text-sm font-medium text-gray-600 dark:text-gray-400">
Round <span x-text="currentRound">1</span>
</span>
<span class="text-xs px-2 py-0.5 rounded-full"
:class="phaseColorClass"
x-text="currentPhase">diverge</span>
<span class="text-xs px-2 py-0.5 rounded bg-gray-200 dark:bg-gray-700
text-gray-600 dark:text-gray-300"
x-text="currentPattern">one_shot</span>
</div>
<div class="text-xs text-gray-400">
<span x-text="utterances.length">0</span> 発言
</div>
</div>

<!-- メッセージ一覧 -->
<div class="flex-1 overflow-y-auto p-4 space-y-1 custom-scrollbar"
x-ref="chatContainer"
@scroll="handleScroll()">

<template x-for="item in chatItems" :key="item.id">
<!-- ラウンド区切り -->
<template x-if="item.type === 'round_divider'">
{% include "components/chat_bubble.html" with context "divider" %}
</template>

<!-- 通常発言 -->
<template x-if="item.type === 'utterance'">
{% include "components/chat_bubble.html" with context "normal" %}
</template>

<!-- ラウンド結論 -->
<template x-if="item.type === 'conclusion'">
{% include "components/chat_bubble.html" with context "conclusion" %}
</template>

<!-- システムイベント -->
<template x-if="item.type === 'system_event'">
{% include "components/chat_bubble.html" with context "system" %}
</template>
</template>

<!-- タイピングインジケーター -->
<template x-if="isAgentThinking">
<div class="flex items-center gap-3 mb-4 animate-fade-in">
<div class="w-10 h-10 rounded-full bg-gray-100 dark:bg-gray-800
flex items-center justify-center text-xl">
<span x-text="thinkingAgent.emoji">🧮</span>
</div>
<div class="px-4 py-2 rounded-2xl rounded-tl-sm
bg-gray-100 dark:bg-gray-700">
<div class="flex items-center gap-1">
<span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
style="animation-delay: 0ms"></span>
<span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
style="animation-delay: 150ms"></span>
<span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
style="animation-delay: 300ms"></span>
</div>
</div>
<span class="text-xs text-gray-400"
x-text="thinkingAgent.name + ' が考え中...'"></span>
</div>
</template>
</div>

<!-- "最新へ" ボタン -->
<div x-show="!isAtBottom"
x-transition
class="absolute bottom-20 left-1/2 -translate-x-1/2">
<button @click="scrollToBottom()"
class="px-4 py-2 rounded-full bg-indigo-600 text-white text-sm
shadow-lg hover:bg-indigo-700 transition flex items-center gap-1">
<span>↓</span>
<span>最新へ</span>
</button>
</div>
</div>
```

### 5.3 サイドバー実装

```html
<aside class="w-72 flex-shrink-0 space-y-4 hidden md:block">

<!-- タイマー -->
{% include "components/timer.html" %}

<!-- ラウンド情報 -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
ラウンド情報
</h4>
<div class="space-y-2 text-sm">
<div class="flex justify-between">
<span class="text-gray-500">ラウンド</span>
<span class="font-medium">
<span x-text="currentRound">1</span> / <span x-text="totalRounds">3</span>
</span>
</div>
<div class="flex justify-between">
<span class="text-gray-500">フェーズ</span>
<span class="text-xs px-2 py-0.5 rounded-full"
:class="phaseColorClass"
x-text="currentPhase"></span>
</div>
<div class="flex justify-between">
<span class="text-gray-500">パターン</span>
<span class="font-medium text-xs" x-text="currentPattern"></span>
</div>
</div>
</div>

<!-- 参加AI -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
参加AI
</h4>
<div class="space-y-2">
<template x-for="agent in participatingAgents" :key="agent.role_id">
<div class="flex items-center gap-2"
x-data="{ status: getAgentStatus(agent.role_id) }">
{% include "components/agent_badge.html" %}
</div>
</template>
</div>
</div>

<!-- リアルタイム統計 -->
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
統計
</h4>
<div class="space-y-2 text-sm">
<div class="flex justify-between">
<span class="text-gray-500">発言数</span>
<span class="font-mono font-medium" x-text="stats.utteranceCount">0</span>
</div>
<div class="flex justify-between">
<span class="text-gray-500">トークン</span>
<span class="font-mono font-medium"
x-text="stats.totalTokens.toLocaleString()">0</span>
</div>
<div class="flex justify-between">
<span class="text-gray-500">収束度</span>
<span class="font-mono font-medium"
x-text="stats.convergence.toFixed(2)">0.00</span>
</div>
</div>
</div>

<!-- 中断ボタン -->
<button @click="confirmAbort()"
class="w-full py-2 px-4 rounded-xl text-red-600 dark:text-red-400
bg-red-50 dark:bg-red-900/20
border border-red-200 dark:border-red-800
hover:bg-red-100 dark:hover:bg-red-900/40
transition text-sm font-medium">
🛑 中断する
</button>
</aside>
```

### 5.4 スクロール制御

```javascript
// 自動スクロール制御
isAtBottom: true,

handleScroll() {
const el = this.$refs.chatContainer;
if (!el) return;
const threshold = 50;
this.isAtBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < threshold;
},

scrollToBottom() {
const el = this.$refs.chatContainer;
if (el) {
el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
this.isAtBottom = true;
}
},

// 新発言追加時
addChatItem(item) {
this.chatItems.push(item);
if (this.isAtBottom) {
this.$nextTick(() => this.scrollToBottom());
}
},
```

---

## 6. Step 4: 結果表示

### 6.1 レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  🎉 議論完了！                                                 │
│                                                                │
│  ┌── 統計カード (grid-cols-2 md:grid-cols-4) ──────────────┐  │
│  │ ⏱️4:32 │ 💬14発言 │ 📊2,850tk │ 🎯0.87 │             │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── MVP表示 ─────────────────────────────────────────────┐   │
│  │ 🏆 MVP: 🧮 理論屋 — "数式による明確な根拠提示が..."    │   │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── タブ ─────────────────────────────────────────────────┐  │
│  │ [📄 レポート]  [💬 全会話]  [📊 評価]  [📋 要約]       │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │                                                         │  │
│  │  (Markdown レンダリング表示)                             │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── アクション ──                                              │
│  [🔄 フォローアップ]  [📥 ダウンロード ▼]  [🏠 ホームへ]      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 6.2 統計カード

```html
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
<div class="text-center p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20
border border-blue-200 dark:border-blue-800">
<div class="text-2xl font-bold font-mono text-blue-600 dark:text-blue-400"
x-text="formatTime(result.statistics.duration_sec)">4:32</div>
<div class="text-xs text-gray-500 mt-1">所要時間</div>
</div>

<div class="text-center p-4 rounded-xl bg-green-50 dark:bg-green-900/20
border border-green-200 dark:border-green-800">
<div class="text-2xl font-bold font-mono text-green-600 dark:text-green-400"
x-text="result.statistics.utterance_count">14</div>
<div class="text-xs text-gray-500 mt-1">発言数</div>
</div>

<div class="text-center p-4 rounded-xl bg-purple-50 dark:bg-purple-900/20
border border-purple-200 dark:border-purple-800">
<div class="text-2xl font-bold font-mono text-purple-600 dark:text-purple-400"
x-text="result.statistics.total_tokens.toLocaleString()">2,850</div>
<div class="text-xs text-gray-500 mt-1">トークン</div>
</div>

<div class="text-center p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20
border border-amber-200 dark:border-amber-800">
<div class="text-2xl font-bold font-mono text-amber-600 dark:text-amber-400"
x-text="result.statistics.final_convergence.toFixed(2)">0.87</div>
<div class="text-xs text-gray-500 mt-1">収束度</div>
</div>
</div>
```

### 6.3 タブ切替

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl
border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">

<!-- タブヘッダー -->
<div class="flex border-b border-gray-200 dark:border-gray-700">
<template x-for="tab in [
{id: 'report', label: '📄 レポート'},
{id: 'conversation', label: '💬 全会話'},
{id: 'evaluation', label: '📊 評価'},
{id: 'summary', label: '📋 要約'},
]" :key="tab.id">
<button @click="activeTab = tab.id"
class="flex-1 px-4 py-3 text-sm font-medium transition-colors
border-b-2"
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
<div class="p-6 max-h-[600px] overflow-y-auto custom-scrollbar">
<!-- レポート (Markdown) -->
<div x-show="activeTab === 'report'"
class="prose-orchestra"
x-html="renderMarkdown(result.files.report)">
</div>

<!-- 全会話 (Markdown) -->
<div x-show="activeTab === 'conversation'"
class="prose-orchestra"
x-html="renderMarkdown(result.files.conversation)">
</div>

<!-- 評価 -->
<div x-show="activeTab === 'evaluation'">
{% include "components/evaluation.html" %}
</div>

<!-- 要約 -->
<div x-show="activeTab === 'summary'"
class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap"
x-text="result.files.summary">
</div>
</div>
</div>
```

### 6.4 アクションバー

```html
<div class="flex flex-wrap items-center justify-center gap-4 mt-8">
<!-- フォローアップ -->
<button @click="startFollowUp()"
class="px-6 py-3 rounded-xl text-indigo-600 dark:text-indigo-400
bg-indigo-50 dark:bg-indigo-900/20
border border-indigo-200 dark:border-indigo-800
hover:bg-indigo-100 dark:hover:bg-indigo-900/40
transition flex items-center gap-2">
<span>🔄</span>
<span>フォローアップ議論</span>
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

<!-- ドロップダウン -->
<div x-show="downloadOpen"
@click.away="downloadOpen = false"
x-transition
class="absolute top-full mt-2 right-0 w-48
bg-white dark:bg-gray-800 rounded-xl shadow-lg
border border-gray-200 dark:border-gray-700
overflow-hidden z-40">
<a :href="'/api/sessions/' + result.session_id + '/download?file=report'"
class="block px-4 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700
transition">
📄 レポート (.md)
</a>
<a :href="'/api/sessions/' + result.session_id + '/download?file=all'"
class="block px-4 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700
transition">
📦 全ファイル (.zip)
</a>
</div>
</div>

<!-- ホームへ -->
<a href="/"
class="px-6 py-3 rounded-xl text-gray-700 dark:text-gray-300
bg-gray-100 dark:bg-gray-700
hover:bg-gray-200 dark:hover:bg-gray-600
transition flex items-center gap-2">
<span>🏠</span>
<span>ホームへ</span>
</a>
</div>
```

---

## 7. Alpine.js 状態管理 (ideaPage)

```javascript
function ideaPage() {
return {
// === State ===
step: 1,
steps: [
{ num: 1, label: '入力' },
{ num: 2, label: '計画' },
{ num: 3, label: '議論' },
{ num: 4, label: '結果' },
],

// Step 1
prompt: '',
settings: {
plannerModel: 'gpt-5.4',
conductorModel: 'gpt-4.1',
synthModel: 'gpt-5.4',
timeLimit: 300,
maxAgents: 5,
expertise: 'intermediate',
followUpId: '',
},
attachedFiles: [],
selectedHypotheses: [],
previousSessions: [],
followUpContext: null,

// Step 2
plan: null,
planLoading: false,
startLoading: false,
remainingQuota: 10000,
estimatedRequests: 36,

// Step 3
sse: null,
chatItems: [],
utterances: [],
currentRound: 0,
totalRounds: 0,
currentPhase: '',
currentPattern: '',
participatingAgents: [],
stats: { utteranceCount: 0, totalTokens: 0, convergence: 0 },
remainingSec: 0,
timeLimit: 300,
timePressure: 'relaxed',
timerInterval: null,
isAtBottom: true,
isAgentThinking: false,
thinkingAgent: null,

// Step 4
result: null,
activeTab: 'report',

// === Computed ===
get isPromptValid() {
return this.prompt.length >= 5 && this.prompt.length <= 5000;
},

get phaseColorClass() {
const map = {
diverge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300',
deepen: 'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300',
converge: 'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300',
};
return map[this.currentPhase] || '';
},

defaultAgentEmojis: ['🧮', '🔬', '🤖', '📚', '😈', '🎯', '📐', '📝'],

// === Methods ===

// Step 1 → Step 2
async submitPlan() {
this.planLoading = true;
try {
const res = await fetch('/api/idea/plan', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify({
prompt: this.prompt,
planner_model: this.settings.plannerModel,
conductor_model: this.settings.conductorModel,
synth_model: this.settings.synthModel,
time_limit: this.settings.timeLimit,
max_agents: this.settings.maxAgents,
expertise: this.settings.expertise,
follow_up_id: this.settings.followUpId || null,
attached_files: this.attachedFiles.map(f => f.name),
}),
});
if (!res.ok) throw new Error(await res.text());
const data = await res.json();
this.plan = data.plan;
this.remainingQuota = data.remaining_quota;
this.estimatedRequests = data.estimated_requests;
this.step = 2;
} catch (err) {
toast(err.message, 'error');
} finally {
this.planLoading = false;
}
},

// Step 2 → Step 3
async startDiscussion() {
this.startLoading = true;
this.step = 3;
this.remainingSec = this.settings.timeLimit;
this.timeLimit = this.settings.timeLimit;
this.totalRounds = this.plan.rounds?.length || 3;
this.participatingAgents = this.plan.agents || [];

this.startTimer();

this.sse = new OrchestraSSE('/api/idea/stream');

this.sse.on('round_start', (data) => {
this.currentRound = data.round;
this.currentPhase = data.config.phase;
this.currentPattern = data.config.pattern;
this.addChatItem({
id: 'divider_' + data.round,
type: 'round_divider',
round: data,
});
});

this.sse.on('utterance', (data) => {
this.isAgentThinking = false;
this.utterances.push(data);
this.stats.utteranceCount++;
this.stats.totalTokens += data.tokens;
this.addChatItem({
id: 'utt_' + this.utterances.length,
type: 'utterance',
utterance: data,
});
this.updateAgentStatus(data.agent.role_id, 'done');
});

this.sse.on('round_conclusion', (data) => {
this.addChatItem({
id: 'conclusion_' + data.round,
type: 'conclusion',
conclusion: data,
});
});

this.sse.on('round_end', (data) => {
this.stats.convergence = data.convergence;
this.resetAgentStatuses();
});

this.sse.on('stagnation_detected', () => {
this.addChatItem({
id: 'sys_' + Date.now(),
type: 'system_event',
event: { icon: '⚡', message: '議論の方向転換を指示しました' },
});
});

this.sse.on('time_pressure', (data) => {
this.remainingSec = data.remaining_sec;
this.timePressure = data.pressure;
});

this.sse.on('progress', (data) => {
this.remainingSec = data.remaining_sec;
});

this.sse.on('synthesis_start', () => {
this.stopTimer();
this.addChatItem({
id: 'sys_synth',
type: 'system_event',
event: { icon: '📊', message: '統合・評価フェーズを開始...' },
});
});

this.sse.on('done', async (data) => {
this.stopTimer();
this.startLoading = false;
// 結果を取得
const res = await fetch(`/api/sessions/${data.session_id}/content`);
this.result = await res.json();
this.result.session_id = data.session_id;
this.result.statistics = data.statistics;
this.step = 4;
});

this.sse.on('error', (data) => {
this.stopTimer();
this.startLoading = false;
toast(data.message, 'error');
if (!data.recoverable) { this.step = 1; }
});

await this.sse.start({
plan: this.plan,
prompt: this.prompt,
conductor_model: this.settings.conductorModel,
synth_model: this.settings.synthModel,
time_limit: this.settings.timeLimit,
expertise: this.settings.expertise,
});
},

// Follow-up
startFollowUp() {
this.settings.followUpId = this.result.session_id;
this.prompt = '';
this.plan = null;
this.chatItems = [];
this.utterances = [];
this.result = null;
this.step = 1;
this.loadFollowUpContext();
},

// Abort
confirmAbort() {
window.dispatchEvent(new CustomEvent('open-modal', {
detail: {
title: '議論を中断しますか？',
message: 'ここまでの議論は部分的に保存されます。',
action: () => {
if (this.sse) this.sse.abort();
this.stopTimer();
toast('議論を中断しました', 'warning');
this.step = 1;
},
},
}));
},

// Helpers
getAgentStatus(roleId) {
// 最新の発言者かどうか判定
const lastUtt = this.utterances[this.utterances.length - 1];
if (this.isAgentThinking && this.thinkingAgent?.role_id === roleId) return 'speaking';
if (lastUtt?.agent?.role_id === roleId) return 'done';
return 'waiting';
},

updateAgentStatus(roleId, status) {
// 状態更新 (リアクティブ)
},

resetAgentStatuses() {
// 全員waitingに戻す
},

async loadFollowUpContext() {
if (!this.settings.followUpId) {
this.followUpContext = null;
return;
}
try {
const res = await fetch(`/api/sessions/${this.settings.followUpId}`);
this.followUpContext = await res.json();
} catch (err) {
toast('フォローアップ情報の読み込みに失敗', 'error');
}
},

// Timer (defined in timer section)
startTimer() { /* ... */ },
stopTimer() { /* ... */ },
updateTimePressure() { /* ... */ },

// Storage
saveToStorage() {
localStorage.setItem('idea_prompt', this.prompt);
localStorage.setItem('idea_settings', JSON.stringify(this.settings));
},

restoreFromStorage() {
this.prompt = localStorage.getItem('idea_prompt') || '';
const saved = localStorage.getItem('idea_settings');
if (saved) {
try { Object.assign(this.settings, JSON.parse(saved)); } catch {}
}
},

// Lifecycle
async init() {
this.restoreFromStorage();

// URL パラメータからフォローアップIDを取得
const params = new URLSearchParams(window.location.search);
const followUp = params.get('follow_up');
if (followUp) {
this.settings.followUpId = followUp;
await this.loadFollowUpContext();
}

// 過去セッション一覧を取得 (フォローアップ選択用)
try {
const res = await fetch('/api/sessions/recent?limit=20&type=idea');
const data = await res.json();
this.previousSessions = data.sessions || [];
} catch {}
},
};
}
```

---

## 8. API 連携仕様

### 8.1 POST /api/idea/plan

```
Request:
{
"prompt": "LLMの推論効率を改善する手法を議論して",
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 300,
"max_agents": 5,
"expertise": "intermediate",
"follow_up_id": null,
"attached_files": []
}

Response (200):
{
"plan": {
"theme": "...",
"odsc": { "objective": "...", "deliverables": "...", "scope": "...", "criteria": "..." },
"agents": [{ "role_id": "theorist", "emoji": "🧮", "name": "理論屋", "specialty": "..." }],
"rounds": [{ "number": 1, "phase": "diverge", "pattern": "one_shot", ... }],
"private_instructions": [...]
},
"estimated_requests": 36,
"remaining_quota": 9964
}

Error (422): バリデーションエラー
Error (500): サーバーエラー
```

### 8.2 POST /api/idea/stream

```
Request:
{
"plan": { ... },
"prompt": "...",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 300,
"expertise": "intermediate"
}

Response: text/event-stream
data: {"type": "round_start", ...}\n\n
data: {"type": "utterance", ...}\n\n
...
data: {"type": "done", ...}\n\n
```

---

## 9. モバイル対応

### 9.1 Step 3 のモバイルレイアウト

```
┌────────────────────────────┐
│  ⏱️ 3:24  Round 2/3  65%  │ ← 固定上部バー
├────────────────────────────┤
│                            │
│  (チャットメッセージ一覧)   │ ← フルスクリーン
│                            │
│  🧮 理論屋:                │
│  計算量の観点から...        │
│                            │
│  🔬 実験屋:                │
│  実験的には...              │
│                            │
├────────────────────────────┤
│  💬8  📊1.2k  🎯0.72      │ ← 固定下部バー (統計)
└────────────────────────────┘
```

### 9.2 実装

```html
<!-- モバイル: 上部固定バー (md未満で表示) -->
<div class="md:hidden fixed top-16 left-0 right-0 z-30
bg-white dark:bg-gray-800
border-b border-gray-200 dark:border-gray-700
px-4 py-2">
<div class="flex items-center justify-between">
<span class="font-mono text-sm font-bold"
:class="timePressure === 'critical' ? 'text-red-500 animate-pulse' : 'text-indigo-600'"
x-text="formatTime(remainingSec)"></span>
<span class="text-xs text-gray-500">
R<span x-text="currentRound"></span>/<span x-text="totalRounds"></span>
</span>
<div class="w-20 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full">
<div class="h-full rounded-full bg-indigo-500"
:style="'width:' + ((timeLimit - remainingSec) / timeLimit * 100) + '%'"></div>
</div>
</div>
</div>

<!-- モバイル: 下部統計バー (md未満で表示) -->
<div class="md:hidden fixed bottom-0 left-0 right-0 z-30
bg-white dark:bg-gray-800
border-t border-gray-200 dark:border-gray-700
px-4 py-2">
<div class="flex items-center justify-around text-xs text-gray-500">
<span>💬 <span x-text="stats.utteranceCount" class="font-mono"></span></span>
<span>📊 <span x-text="(stats.totalTokens/1000).toFixed(1)+'k'" class="font-mono"></span></span>
<span>🎯 <span x-text="stats.convergence.toFixed(2)" class="font-mono"></span></span>
<button @click="confirmAbort()" class="text-red-500">🛑</button>
</div>
</div>
