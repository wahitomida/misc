# AI Orchestra — 共通コンポーネント仕様

> 全ページで再利用されるUIコンポーネントの詳細定義

---

## 1. コンポーネント一覧

| コンポーネント | ファイル | 使用ページ |
|---------------|---------|-----------|
| チャットバブル | `components/chat_bubble.html` | idea, review, replay |
| 計画カード | `components/plan_card.html` | idea, review |
| タイマー | `components/timer.html` | idea, review |
| 評価表示 | `components/evaluation.html` | idea, review, replay |
| 仮説テーブル | `components/hypothesis_table.html` | idea, replay |
| ファイルドロップ | `components/file_drop.html` | idea, review |
| エージェントバッジ | `components/agent_badge.html` | idea, review, roles |
| トースト | `partials/toast.html` | 全ページ (base.html) |
| モーダル | `partials/modal.html` | 全ページ (base.html) |
| ステップインジケーター | `partials/step_indicator.html` | idea, review |
| ローディング | `partials/loading.html` | 全ページ |

---

## 2. チャットバブル (chat_bubble.html)

### 2.1 バリエーション

| 種類 | 用途 | 視覚的特徴 |
|------|------|-----------|
| 通常発言 | AI同士の議論発言 | 左寄せ、ロール色背景 |
| ラウンド結論 | 各ラウンド末の結論 | 中央、アンバー枠、強調 |
| システムイベント | 方向転換、停滞検知等 | 中央、イタリック、小さめ |
| ラウンド区切り | ラウンドの境界線 | 中央線 + ラベル |

### 2.2 通常発言バブル

```html
<!--
変数:
- utterance.emoji: "🧮"
- utterance.role_name: "理論屋"
- utterance.content: "計算量の観点から..."
- utterance.round_num: 1
- utterance.tokens: 150
-->

<div class="flex items-start gap-3 mb-4 animate-slide-up">
<!-- アバター -->
<div class="flex-shrink-0 w-10 h-10 rounded-full
bg-gray-100 dark:bg-gray-800
flex items-center justify-center text-xl
shadow-sm">
<span x-text="utterance.agent.emoji">🧮</span>
</div>

<!-- 発言本体 -->
<div class="flex-1 min-w-0">
<!-- 名前 + メタ -->
<div class="flex items-center gap-2 mb-1">
<span class="text-sm font-semibold text-gray-700 dark:text-gray-300"
x-text="utterance.agent.name">理論屋</span>
<span class="text-xs text-gray-400"
x-text="'Round ' + utterance.round">Round 1</span>
</div>

<!-- バブル -->
<div class="p-3 rounded-2xl rounded-tl-sm max-w-[600px]
bg-white dark:bg-gray-800
border border-gray-200 dark:border-gray-700
shadow-sm">
<p class="text-sm text-gray-800 dark:text-gray-200 leading-relaxed"
x-text="utterance.content">
</p>
</div>

<!-- フッター -->
<div class="flex items-center gap-3 mt-1 text-xs text-gray-400">
<span x-text="utterance.tokens + ' tokens'">150 tokens</span>
</div>
</div>
</div>
```

### 2.3 ラウンド結論バブル

```html
<!--
変数:
- conclusion.round: 1
- conclusion.concluder: "theorist"
- conclusion.concluder_emoji: "🧮"
- conclusion.concluder_name: "理論屋"
- conclusion.content: "KV-cache圧縮が..."
-->

<div class="my-6 mx-4 animate-scale-in">
<div class="p-4 rounded-xl
border-2 border-amber-400 dark:border-amber-500
bg-gradient-to-r from-amber-50 to-orange-50
dark:from-amber-900/20 dark:to-orange-900/20
shadow-md">
<!-- ヘッダー -->
<div class="flex items-center gap-2 mb-2">
<span class="text-lg">🎯</span>
<span class="font-bold text-amber-700 dark:text-amber-300 text-sm">
Round <span x-text="conclusion.round">1</span> 結論
</span>
<span class="text-xs text-gray-500 dark:text-gray-400">
(by <span x-text="conclusion.concluder_emoji + conclusion.concluder_name">🧮理論屋</span>)
</span>
</div>

<!-- 結論テキスト -->
<p class="text-sm text-gray-800 dark:text-gray-200 leading-relaxed font-medium"
x-text="conclusion.content">
</p>
</div>
</div>
```

### 2.4 システムイベント

```html
<!--
変数:
- event.icon: "⚡"
- event.message: "議論の方向転換を指示しました"
-->

<div class="flex items-center justify-center my-4 gap-2 animate-fade-in">
<span class="text-sm" x-text="event.icon">⚡</span>
<span class="text-sm text-orange-500 dark:text-orange-400 italic"
x-text="event.message">
議論の方向転換を指示しました
</span>
</div>
```

### 2.5 ラウンド区切り

```html
<!--
変数:
- round.number: 2
- round.topic: "深掘り"
- round.pattern: "ping_pong"
-->

<div class="flex items-center my-8 gap-4">
<div class="flex-1 border-t border-gray-300 dark:border-gray-600"></div>
<div class="flex items-center gap-2 px-4 py-1
bg-gray-100 dark:bg-gray-800 rounded-full">
<span class="text-xs font-medium text-gray-500 dark:text-gray-400">
Round <span x-text="round.number">2</span>
</span>
<span class="text-xs text-indigo-600 dark:text-indigo-400 font-medium"
x-text="round.topic">深掘り</span>
<span class="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700
text-gray-600 dark:text-gray-300"
x-text="round.pattern">ping_pong</span>
</div>
<div class="flex-1 border-t border-gray-300 dark:border-gray-600"></div>
</div>
```

---

## 3. 計画カード (plan_card.html)

### 3.1 全体構造

```html
<!--
変数:
- plan.odsc: { objective, deliverables, scope, criteria }
- plan.agents: [{ role_id, emoji, name, specialty }]
- plan.rounds: [{ number, phase, pattern, leader, topic, estimated_sec }]
- plan.estimated_total_sec: 270
- plan.estimated_requests: 15
- remaining_quota: 9850
-->

<div class="space-y-6">

<!-- ODSC セクション -->
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>📋</span> 議論の枠組み (ODSC)
</h3>

<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
<div class="p-3 rounded-xl bg-blue-50 dark:bg-blue-900/20">
<div class="flex items-center gap-2 mb-1">
<span class="text-sm">🎯</span>
<span class="text-xs font-bold text-blue-700 dark:text-blue-300">Objective</span>
</div>
<p class="text-sm text-gray-700 dark:text-gray-300" x-text="plan.odsc.objective"></p>
</div>

<div class="p-3 rounded-xl bg-green-50 dark:bg-green-900/20">
<div class="flex items-center gap-2 mb-1">
<span class="text-sm">📦</span>
<span class="text-xs font-bold text-green-700 dark:text-green-300">Deliverables</span>
</div>
<p class="text-sm text-gray-700 dark:text-gray-300" x-text="plan.odsc.deliverables"></p>
</div>

<div class="p-3 rounded-xl bg-purple-50 dark:bg-purple-900/20">
<div class="flex items-center gap-2 mb-1">
<span class="text-sm">🔲</span>
<span class="text-xs font-bold text-purple-700 dark:text-purple-300">Scope</span>
</div>
<p class="text-sm text-gray-700 dark:text-gray-300" x-text="plan.odsc.scope"></p>
</div>

<div class="p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20">
<div class="flex items-center gap-2 mb-1">
<span class="text-sm">✅</span>
<span class="text-xs font-bold text-amber-700 dark:text-amber-300">Criteria</span>
</div>
<p class="text-sm text-gray-700 dark:text-gray-300" x-text="plan.odsc.criteria"></p>
</div>
</div>
</div>

<!-- 参加AI セクション -->
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>🎭</span> 参加AI
</h3>

<div class="flex flex-wrap gap-3">
<template x-for="agent in plan.agents" :key="agent.role_id">
<div class="flex items-center gap-2 px-3 py-2 rounded-xl
bg-gray-100 dark:bg-gray-700
hover:bg-indigo-50 dark:hover:bg-indigo-900/30
transition cursor-default group"
:title="agent.specialty">
<span class="text-xl" x-text="agent.emoji"></span>
<span class="text-sm font-medium text-gray-700 dark:text-gray-300"
x-text="agent.name"></span>
</div>
</template>
</div>
</div>

<!-- ラウンド計画 セクション -->
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>📅</span> ラウンド計画
</h3>

<div class="space-y-3">
<template x-for="round in plan.rounds" :key="round.number">
<div class="flex items-center gap-4 p-3 rounded-xl
bg-gray-50 dark:bg-gray-700/50">
<!-- ラウンド番号 -->
<div class="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900/50
flex items-center justify-center
text-sm font-bold text-indigo-600 dark:text-indigo-400">
<span x-text="round.number"></span>
</div>

<!-- 情報 -->
<div class="flex-1 min-w-0">
<div class="flex items-center gap-2 flex-wrap">
<!-- フェーズバッジ -->
<span class="text-xs px-2 py-0.5 rounded-full font-medium"
:class="{
'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300':
round.phase === 'diverge',
'bg-purple-100 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300':
round.phase === 'deepen',
'bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300':
round.phase === 'converge',
}"
x-text="round.phase"></span>

<!-- パターンバッジ -->
<span class="text-xs px-2 py-0.5 rounded bg-gray-200 dark:bg-gray-600
text-gray-600 dark:text-gray-300"
x-text="round.pattern"></span>

<!-- トピック -->
<span class="text-sm text-gray-600 dark:text-gray-400 truncate"
x-text="round.topic"></span>
</div>

<div class="text-xs text-gray-400 mt-1">
主導: <span x-text="round.leader"></span>
</div>
</div>

<!-- 見積時間 -->
<div class="text-sm font-mono text-gray-500 dark:text-gray-400">
<span x-text="formatTime(round.estimated_sec)"></span>
</div>
</div>
</template>
</div>
</div>

<!-- リソース見積 セクション -->
<div class="flex flex-wrap gap-4">
<div class="flex items-center gap-2 px-4 py-2 rounded-xl
bg-blue-50 dark:bg-blue-900/20 text-sm">
<span>⏱️</span>
<span class="text-gray-600 dark:text-gray-400">予想時間:</span>
<span class="font-medium text-blue-700 dark:text-blue-300"
x-text="formatTime(plan.estimated_total_sec)"></span>
</div>

<div class="flex items-center gap-2 px-4 py-2 rounded-xl
bg-green-50 dark:bg-green-900/20 text-sm">
<span>📊</span>
<span class="text-gray-600 dark:text-gray-400">API見積:</span>
<span class="font-medium text-green-700 dark:text-green-300"
x-text="'約' + plan.estimated_requests + 'リクエスト'"></span>
</div>

<div class="flex items-center gap-2 px-4 py-2 rounded-xl
bg-gray-100 dark:bg-gray-700 text-sm">
<span>💰</span>
<span class="text-gray-600 dark:text-gray-400">残り:</span>
<span class="font-medium" x-text="remaining_quota.toLocaleString()"></span>
</div>
</div>

</div>
```

---

## 4. タイマー (timer.html)

### 4.1 仕様

```
表示内容:
- カウントダウン数字 (MM:SS)
- プログレスバー (経過割合)
- 時間逼迫度に応じた色変化

色変化:
- RELAXED (> 60%): 緑 (green-500)
- MODERATE (30-60%): 黄 (yellow-500)
- URGENT (10-30%): オレンジ (orange-500)
- CRITICAL (< 10%): 赤 (red-500) + パルスアニメーション
```

### 4.2 テンプレート

```html
<!--
変数 (Alpine.js):
- remainingSec: 残り秒数
- timeLimit: 制限時間 (秒)
- timePressure: "relaxed" | "moderate" | "urgent" | "critical"
-->

<div class="rounded-xl p-4 bg-white dark:bg-gray-800
border border-gray-200 dark:border-gray-700 shadow-sm">

<!-- カウントダウン表示 -->
<div class="text-center mb-3">
<div class="text-3xl font-mono font-bold transition-colors duration-300"
:class="{
'text-green-600 dark:text-green-400': timePressure === 'relaxed',
'text-yellow-600 dark:text-yellow-400': timePressure === 'moderate',
'text-orange-600 dark:text-orange-400': timePressure === 'urgent',
'text-red-600 dark:text-red-400 animate-pulse': timePressure === 'critical',
}"
x-text="formatTime(remainingSec)">
5:00
</div>
<div class="text-xs text-gray-400 mt-1">残り時間</div>
</div>

<!-- プログレスバー -->
<div class="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
<div class="h-full rounded-full transition-all duration-1000 ease-linear"
:class="{
'bg-gradient-to-r from-green-400 to-green-600': timePressure === 'relaxed',
'bg-gradient-to-r from-yellow-400 to-yellow-600': timePressure === 'moderate',
'bg-gradient-to-r from-orange-400 to-orange-600': timePressure === 'urgent',
'bg-gradient-to-r from-red-400 to-red-600': timePressure === 'critical',
}"
:style="'width: ' + Math.max(0, (remainingSec / timeLimit) * 100) + '%'">
</div>
</div>

<!-- 制限時間表示 -->
<div class="flex justify-between text-xs text-gray-400 mt-1">
<span>0:00</span>
<span x-text="formatTime(timeLimit)">5:00</span>
</div>
</div>
```

### 4.3 タイマー更新ロジック (Alpine.js)

```javascript
// ideaPage() 内
startTimer() {
this.timerInterval = setInterval(() => {
if (this.remainingSec > 0) {
this.remainingSec--;
this.updateTimePressure();
}
}, 1000);
},

updateTimePressure() {
const ratio = this.remainingSec / this.timeLimit;
if (ratio > 0.6) this.timePressure = 'relaxed';
else if (ratio > 0.3) this.timePressure = 'moderate';
else if (ratio > 0.1) this.timePressure = 'urgent';
else this.timePressure = 'critical';
},

stopTimer() {
if (this.timerInterval) {
clearInterval(this.timerInterval);
this.timerInterval = null;
}
},
```

---

## 5. 評価表示 (evaluation.html)

### 5.1 構造

```html
<!--
変数:
- evaluation.overall_quality: 4
- evaluation.mvp: { role_id, emoji, name, reason }
- evaluation.agent_scores: [{ role_id, emoji, name, self_avg, peer_avg }]
- evaluation.odsc_achievement: 0.87
-->

<div class="space-y-6">

<!-- MVP カード -->
<div class="p-4 rounded-xl bg-gradient-to-r from-yellow-50 to-amber-50
dark:from-yellow-900/20 dark:to-amber-900/20
border border-yellow-300 dark:border-yellow-700">
<div class="flex items-center gap-3">
<span class="text-4xl" x-text="evaluation.mvp.emoji">🧮</span>
<div>
<div class="text-xs text-yellow-600 dark:text-yellow-400 font-medium">🏆 MVP</div>
<div class="text-lg font-bold text-gray-800 dark:text-gray-200"
x-text="evaluation.mvp.name">理論屋</div>
<div class="text-sm text-gray-600 dark:text-gray-400"
x-text="evaluation.mvp.reason">
数式を使った明確な根拠提示が議論を牽引した
</div>
</div>
</div>
</div>

<!-- 全体品質 -->
<div class="flex items-center gap-4">
<span class="text-sm font-medium text-gray-600 dark:text-gray-400">全体品質:</span>
<div class="flex items-center gap-1">
<template x-for="i in 5">
<span class="text-lg"
:class="i <= evaluation.overall_quality ? 'opacity-100' : 'opacity-30'"
>⭐</span>
</template>
</div>
<span class="text-sm text-gray-500"
x-text="evaluation.overall_quality + '/5'"></span>
</div>

<!-- ODSC 達成度バー -->
<div>
<div class="flex justify-between text-sm mb-1">
<span class="text-gray-600 dark:text-gray-400">ODSC達成度</span>
<span class="font-medium"
x-text="Math.round(evaluation.odsc_achievement * 100) + '%'"></span>
</div>
<div class="w-full h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
<div class="h-full bg-gradient-to-r from-indigo-400 to-indigo-600 rounded-full
transition-all duration-500"
:style="'width: ' + (evaluation.odsc_achievement * 100) + '%'">
</div>
</div>
</div>

<!-- 各AI スコアテーブル -->
<div class="overflow-x-auto">
<table class="w-full text-sm">
<thead>
<tr class="text-left text-gray-500 dark:text-gray-400 border-b
border-gray-200 dark:border-gray-700">
<th class="pb-2">AI</th>
<th class="pb-2 text-center">自己評価</th>
<th class="pb-2 text-center">他者評価</th>
<th class="pb-2 text-center">総合</th>
</tr>
</thead>
<tbody>
<template x-for="agent in evaluation.agent_scores" :key="agent.role_id">
<tr class="border-b border-gray-100 dark:border-gray-800">
<td class="py-2">
<div class="flex items-center gap-2">
<span x-text="agent.emoji"></span>
<span x-text="agent.name"></span>
</div>
</td>
<td class="py-2 text-center">
<span class="font-mono" x-text="agent.self_avg.toFixed(1)"></span>
</td>
<td class="py-2 text-center">
<span class="font-mono" x-text="agent.peer_avg.toFixed(1)"></span>
</td>
<td class="py-2 text-center">
<span class="font-mono font-bold"
x-text="((agent.self_avg + agent.peer_avg) / 2).toFixed(1)">
</span>
</td>
</tr>
</template>
</tbody>
</table>
</div>

</div>
```

---

## 6. 仮説テーブル (hypothesis_table.html)

### 6.1 仕様

```
ステータス表示:
- 🔲 unverified (未検証) — グレー背景
- ✅ confirmed (確認) — グリーン背景
- ❌ rejected (棄却) — レッド背景
- 🔄 modified (修正) — イエロー背景

フォローアップ時:
- 各仮説にチェックボックス表示
- 選択した仮説を重点検証対象として指定可能
```

### 6.2 テンプレート

```html
<!--
変数:
- hypotheses: [{ id, text, status, evidence, source_round }]
- selectable: true/false (フォローアップ時のみ true)
- selectedHypotheses: [] (選択された仮説IDリスト)
-->

<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>🔬</span> 仮説テーブル
</h3>

<div class="space-y-3">
<template x-for="h in hypotheses" :key="h.id">
<div class="flex items-start gap-3 p-3 rounded-xl transition-colors"
:class="{
'bg-gray-50 dark:bg-gray-700/30': h.status === 'unverified',
'bg-green-50 dark:bg-green-900/20': h.status === 'confirmed',
'bg-red-50 dark:bg-red-900/20': h.status === 'rejected',
'bg-yellow-50 dark:bg-yellow-900/20': h.status === 'modified',
}">

<!-- チェックボックス (選択モード) -->
<template x-if="selectable">
<input type="checkbox"
:value="h.id"
x-model="selectedHypotheses"
class="mt-1 rounded border-gray-300 text-indigo-600
focus:ring-indigo-500">
</template>

<!-- ステータスアイコン -->
<div class="flex-shrink-0 text-lg mt-0.5">
<span x-show="h.status === 'unverified'">🔲</span>
<span x-show="h.status === 'confirmed'">✅</span>
<span x-show="h.status === 'rejected'">❌</span>
<span x-show="h.status === 'modified'">🔄</span>
</div>

<!-- 内容 -->
<div class="flex-1 min-w-0">
<div class="flex items-center gap-2 mb-1">
<span class="text-xs font-mono font-bold text-gray-500"
x-text="h.id">H1</span>
<span class="text-xs px-1.5 py-0.5 rounded text-gray-500
bg-gray-200 dark:bg-gray-600"
x-text="'R' + h.source_round">R1</span>
</div>
<p class="text-sm text-gray-800 dark:text-gray-200"
x-text="h.text"></p>
<p class="text-xs text-gray-500 dark:text-gray-400 mt-1"
x-show="h.evidence"
x-text="'根拠: ' + h.evidence"></p>
</div>
</div>
</template>
</div>

<!-- 選択中の数 (選択モード) -->
<template x-if="selectable && selectedHypotheses.length > 0">
<div class="mt-3 text-sm text-indigo-600 dark:text-indigo-400">
<span x-text="selectedHypotheses.length"></span> 件の仮説を重点検証に選択中
</div>
</template>
</div>
```

---

## 7. ファイルドロップ (file_drop.html)

### 7.1 仕様

```
機能:
- ドラッグ&ドロップでファイル追加
- クリックでファイル選択ダイアログ
- 追加済みファイルリスト表示
- 個別削除
- サイズ表示
制約:
- 最大5ファイル
- 1ファイル最大10,000文字
- 拡張子: .py, .yaml, .json, .md, .txt, .csv
```

### 7.2 テンプレート

```html
<!--
変数:
- attachedFiles: [{ name, size, content }]
- MAX_FILES: 5
-->

<div class="space-y-3">
<!-- ドロップゾーン -->
<div class="relative border-2 border-dashed rounded-xl p-6 text-center
transition-colors cursor-pointer"
:class="{
'border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20':
isDragging,
'border-gray-300 dark:border-gray-600
hover:border-indigo-300 dark:hover:border-indigo-600':
!isDragging,
}"
@dragover.prevent="isDragging = true"
@dragleave.prevent="isDragging = false"
@drop.prevent="handleDrop($event)"
@click="$refs.fileInput.click()">

<input type="file" multiple
x-ref="fileInput"
@change="handleFileSelect($event)"
accept=".py,.yaml,.json,.md,.txt,.csv"
class="hidden">

<div class="text-3xl mb-2">📎</div>
<p class="text-sm text-gray-600 dark:text-gray-400">
ファイルをドラッグ&ドロップ、またはクリックして選択
</p>
<p class="text-xs text-gray-400 mt-1">
.py, .yaml, .json, .md, .txt, .csv (最大5ファイル)
</p>
</div>

<!-- 追加済みファイルリスト -->
<template x-if="attachedFiles.length > 0">
<div class="space-y-2">
<template x-for="(file, index) in attachedFiles" :key="index">
<div class="flex items-center justify-between p-2 rounded-lg
bg-gray-50 dark:bg-gray-700/50">
<div class="flex items-center gap-2 min-w-0">
<span class="text-sm">📄</span>
<span class="text-sm text-gray-700 dark:text-gray-300 truncate"
x-text="file.name"></span>
<span class="text-xs text-gray-400"
x-text="formatFileSize(file.size)"></span>
</div>
<button @click="removeFile(index)"
class="text-red-400 hover:text-red-600 transition p-1"
aria-label="削除">
✕
</button>
</div>
</template>
</div>
</template>

<!-- ファイル数表示 -->
<div class="text-xs text-gray-400 text-right"
x-show="attachedFiles.length > 0"
x-text="attachedFiles.length + ' / ' + MAX_FILES + ' ファイル'">
</div>
</div>
```

### 7.3 ロジック

```javascript
// Alpine.js 内メソッド
isDragging: false,
attachedFiles: [],
MAX_FILES: 5,
ALLOWED_EXTENSIONS: ['.py', '.yaml', '.json', '.md', '.txt', '.csv'],
MAX_FILE_SIZE: 50000, // 50KB

handleDrop(event) {
this.isDragging = false;
const files = Array.from(event.dataTransfer.files);
this.addFiles(files);
},

handleFileSelect(event) {
const files = Array.from(event.target.files);
this.addFiles(files);
event.target.value = ''; // リセット
},

async addFiles(files) {
for (const file of files) {
if (this.attachedFiles.length >= this.MAX_FILES) {
toast('最大ファイル数に達しています', 'warning');
break;
}
const ext = '.' + file.name.split('.').pop().toLowerCase();
if (!this.ALLOWED_EXTENSIONS.includes(ext)) {
toast(`非対応の拡張子: ${ext}`, 'warning');
continue;
}
if (file.size > this.MAX_FILE_SIZE) {
toast(`ファイルサイズ超過: ${file.name}`, 'warning');
continue;
}
const content = await file.text();
this.attachedFiles.push({
name: file.name,
size: file.size,
content: content.slice(0, 10000), // 10,000文字に制限
});
}
},

removeFile(index) {
this.attachedFiles.splice(index, 1);
},

formatFileSize(bytes) {
if (bytes < 1024) return bytes + ' B';
return (bytes / 1024).toFixed(1) + ' KB';
},
```

---

## 8. エージェントバッジ (agent_badge.html)

### 8.1 バリエーション

| サイズ | 用途 | 表示内容 |
|--------|------|---------|
| `sm` | 一覧表示、参加者プレビュー | 絵文字 + 名前 |
| `md` | 計画カード、詳細表示 | 絵文字 + 名前 + 専門 (tooltip) |
| `lg` | ロール詳細パネル | 絵文字 + 名前 + 専門 + 統計 |

### 8.2 テンプレート

```html
<!--
変数:
- agent: { role_id, emoji, name, specialty }
- size: "sm" | "md" | "lg"
- status: "speaking" | "waiting" | "done" | null
-->

<!-- Small -->
<template x-if="size === 'sm'">
<span class="inline-flex items-center gap-1 px-2 py-1 rounded-lg
bg-gray-100 dark:bg-gray-700 text-sm">
<span x-text="agent.emoji"></span>
<span class="text-gray-700 dark:text-gray-300" x-text="agent.name"></span>
</span>
</template>

<!-- Medium (with status indicator) -->
<template x-if="size === 'md'">
<div class="flex items-center gap-2 px-3 py-2 rounded-xl
bg-gray-100 dark:bg-gray-700"
:title="agent.specialty">
<!-- ステータスインジケーター -->
<div class="relative">
<span class="text-xl" x-text="agent.emoji"></span>
<template x-if="status === 'speaking'">
<span class="absolute -bottom-0.5 -right-0.5 w-3 h-3
bg-green-500 rounded-full
animate-pulse border-2 border-white dark:border-gray-700">
</span>
</template>
<template x-if="status === 'done'">
<span class="absolute -bottom-0.5 -right-0.5 w-3 h-3
bg-blue-500 rounded-full
border-2 border-white dark:border-gray-700
flex items-center justify-center text-[8px] text-white">
✓
</span>
</template>
</div>
<div>
<div class="text-sm font-medium text-gray-700 dark:text-gray-300"
x-text="agent.name"></div>
<div class="text-xs text-gray-400"
x-show="status"
x-text="status === 'speaking' ? '発言中...' :
status === 'done' ? '発言済' : '待機中'"></div>
</div>
</div>
</template>

<!-- Large (roles page) -->
<template x-if="size === 'lg'">
<div class="p-4 rounded-2xl bg-white dark:bg-gray-800
border border-gray-200 dark:border-gray-700
hover:shadow-lg hover:border-indigo-300 dark:hover:border-indigo-600
transition-all cursor-pointer card-glow"
@click="selectRole(agent.role_id)">
<div class="text-center">
<div class="text-4xl mb-2" x-text="agent.emoji"></div>
<div class="text-sm font-bold text-gray-800 dark:text-gray-200"
x-text="agent.name"></div>
<div class="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2"
x-text="agent.specialty"></div>
<div class="flex items-center justify-center gap-2 mt-3"
x-show="agent.stats">
<span class="text-xs">★</span>
<span class="text-xs font-mono"
x-text="agent.stats?.avg?.toFixed(1) || '-'"></span>
<span class="text-xs text-gray-400"
x-text="(agent.stats?.sessions || 0) + '回'"></span>
</div>
</div>
</div>
</template>
```

---

## 9. トースト通知 (partials/toast.html)

### 9.1 仕様

```
位置: 右上固定 (top-4 right-4)
幅: max-w-sm
最大同時表示: 3件
自動消去:
- success / info: 3秒
- warning: 5秒
- error: 手動消去のみ
アニメーション: 右からスライドイン → 左へスライドアウト
```

### 9.2 テンプレート

```html
<div id="toast-container"
x-data="toastManager()"
class="fixed top-20 right-4 z-50 space-y-3 pointer-events-none">

<template x-for="t in toasts" :key="t.id">
<div class="pointer-events-auto max-w-sm w-full
bg-white dark:bg-gray-800
border rounded-xl shadow-lg p-4
flex items-start gap-3
animate-slide-in-right"
:class="{
'border-green-300 dark:border-green-700': t.type === 'success',
'border-blue-300 dark:border-blue-700': t.type === 'info',
'border-amber-300 dark:border-amber-700': t.type === 'warning',
'border-red-300 dark:border-red-700': t.type === 'error',
}"
x-show="t.visible"
x-transition:leave="transition ease-in duration-200"
x-transition:leave-start="opacity-100 translate-x-0"
x-transition:leave-end="opacity-0 translate-x-4">

<!-- アイコン -->
<div class="flex-shrink-0 text-lg">
<span x-show="t.type === 'success'">✅</span>
<span x-show="t.type === 'info'">ℹ️</span>
<span x-show="t.type === 'warning'">⚠️</span>
<span x-show="t.type === 'error'">❌</span>
</div>

<!-- メッセージ -->
<div class="flex-1 min-w-0">
<p class="text-sm text-gray-800 dark:text-gray-200" x-text="t.message"></p>
</div>

<!-- 閉じるボタン -->
<button @click="dismiss(t.id)"
class="flex-shrink-0 text-gray-400 hover:text-gray-600
dark:hover:text-gray-300 transition">
✕
</button>
</div>
</template>
</div>
```

### 9.3 ロジック (app.js)

```javascript
const TOAST_DURATIONS = {
success: 3000,
info: 3000,
warning: 5000,
error: null, // 手動消去
};
const MAX_TOASTS = 3;
let toastId = 0;

function toastManager() {
return {
toasts: [],

add(message, type = 'info') {
const id = ++toastId;
this.toasts.push({ id, message, type, visible: true });

// 最大数制限
while (this.toasts.length > MAX_TOASTS) {
this.toasts.shift();
}

// 自動消去
const duration = TOAST_DURATIONS[type];
if (duration) {
setTimeout(() => this.dismiss(id), duration);
}
},

dismiss(id) {
const t = this.toasts.find(t => t.id === id);
if (t) {
t.visible = false;
setTimeout(() => {
this.toasts = this.toasts.filter(t => t.id !== id);
}, 200);
}
},
};
}

// グローバルヘルパー
function toast(message, type = 'info') {
const container = document.getElementById('toast-container');
if (container && container.__x) {
container.__x.$data.add(message, type);
}
}
```

---

## 10. モーダル (partials/modal.html)

### 10.1 仕様

```
表示トリガー: Alpine.js の変数 (modalOpen, modalContent)
閉じ方:
- ESCキー
- 背景クリック
- ✕ ボタン
- アクションボタン (確認/キャンセル)
アニメーション:
- 背景: フェードイン (opacity)
- 本体: スケールイン (scale 0.95 → 1)
```

### 10.2 テンプレート

```html
<div x-data="{ modalOpen: false, modalTitle: '', modalMessage: '', modalAction: null }"
x-show="modalOpen"
x-cloak
@keydown.escape.window="modalOpen = false"
class="fixed inset-0 z-60"
@open-modal.window="
modalOpen = true;
modalTitle = $event.detail.title;
modalMessage = $event.detail.message;
modalAction = $event.detail.action;
">

<!-- 背景オーバーレイ -->
<div class="absolute inset-0 bg-black/50 backdrop-blur-sm"
x-show="modalOpen"
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0"
x-transition:enter-end="opacity-100"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100"
x-transition:leave-end="opacity-0"
@click="modalOpen = false">
</div>

<!-- モーダル本体 -->
<div class="absolute inset-0 flex items-center justify-center p-4">
<div class="relative w-full max-w-lg bg-white dark:bg-gray-800
rounded-2xl shadow-2xl p-6"
x-show="modalOpen"
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0 scale-95"
x-transition:enter-end="opacity-100 scale-100"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100 scale-100"
x-transition:leave-end="opacity-0 scale-95"
@click.stop>

<!-- ヘッダー -->
<div class="flex items-center justify-between mb-4">
<h3 class="text-lg font-bold text-gray-900 dark:text-white"
x-text="modalTitle"></h3>
<button @click="modalOpen = false"
class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300
transition text-xl">
✕
</button>
</div>

<!-- コンテンツ -->
<div class="text-sm text-gray-600 dark:text-gray-400 mb-6"
x-text="modalMessage">
</div>

<!-- アクション -->
<div class="flex justify-end gap-3">
<button @click="modalOpen = false"
class="px-4 py-2 text-sm rounded-xl
bg-gray-100 dark:bg-gray-700
hover:bg-gray-200 dark:hover:bg-gray-600
transition">
キャンセル
</button>
<button @click="if(modalAction) modalAction(); modalOpen = false;"
class="px-4 py-2 text-sm rounded-xl
bg-red-600 text-white
hover:bg-red-700 transition">
確認
</button>
</div>
</div>
</div>
</div>
```

### 10.3 使用例

```javascript
// セッション削除の確認
function confirmDelete(sessionId) {
window.dispatchEvent(new CustomEvent('open-modal', {
detail: {
title: 'セッションを削除しますか？',
message: `セッション ${sessionId} とその全出力ファイルが削除されます。この操作は取り消せません。`,
action: () => deleteSession(sessionId),
}
}));
}
```

---

## 11. ローディング (partials/loading.html)

### 11.1 バリエーション

| 種類 | 用途 | 表示 |
|------|------|------|
| ページ全体 | API応答待ち (計画立案等) | フルスクリーンオーバーレイ |
| インライン | ボタン押下後 | ボタン内スピナー |
| スケルトン | コンテンツ読み込み中 | グレーの点滅ブロック |

### 11.2 フルスクリーンローディング

```html
<template x-if="loading">
<div class="fixed inset-0 z-50 flex items-center justify-center
bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm">
<div class="text-center">
<div class="inline-flex items-center gap-3 px-6 py-4 rounded-2xl
bg-white dark:bg-gray-800 shadow-xl
border border-gray-200 dark:border-gray-700">
<!-- スピナー -->
<svg class="animate-spin h-5 w-5 text-indigo-600" viewBox="0 0 24 24">
<circle class="opacity-25" cx="12" cy="12" r="10"
stroke="currentColor" stroke-width="4" fill="none"></circle>
<path class="opacity-75" fill="currentColor"
d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
</svg>
<span class="text-sm font-medium text-gray-700 dark:text-gray-300"
x-text="loadingMessage || '読み込み中...'"></span>
</div>
</div>
</div>
</template>
```

### 11.3 ボタンスピナー

```html
<button @click="submitPlan()"
:disabled="planLoading"
class="px-6 py-3 rounded-xl bg-indigo-600 text-white
hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed
transition flex items-center gap-2">
<svg x-show="planLoading" class="animate-spin h-4 w-4" viewBox="0 0 24 24">
<circle class="opacity-25" cx="12" cy="12" r="10"
stroke="currentColor" stroke-width="4" fill="none"></circle>
<path class="opacity-75" fill="currentColor"
d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
</svg>
<span x-text="planLoading ? '計画立案中...' : '🚀 議論を計画する'"></span>
</button>
```

---

## 12. 共通CSSクラス (custom.css に定義)

```css
/* === アニメーション === */
@keyframes fadeIn {
from { opacity: 0; }
to { opacity: 1; }
}
@keyframes slideUp {
from { opacity: 0; transform: translateY(8px); }
to { opacity: 1; transform: translateY(0); }
}
@keyframes scaleIn {
from { opacity: 0; transform: scale(0.95); }
to { opacity: 1; transform: scale(1); }
}
@keyframes slideInRight {
from { opacity: 0; transform: translateX(16px); }
to { opacity: 1; transform: translateX(0); }
}

.animate-fade-in { animation: fadeIn 300ms ease-out both; }
.animate-slide-up { animation: slideUp 400ms ease-out both; }
.animate-scale-in { animation: scaleIn 200ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.animate-slide-in-right { animation: slideInRight 300ms ease-out both; }

/* stagger (順次表示) */
.stagger-1 { animation-delay: 100ms; }
.stagger-2 { animation-delay: 200ms; }
.stagger-3 { animation-delay: 300ms; }
.stagger-4 { animation-delay: 400ms; }
.stagger-5 { animation-delay: 500ms; }

/* === カード効果 === */
.card-glow {
transition: box-shadow 200ms ease, transform 200ms ease;
}
.card-glow:hover {
box-shadow: 0 0 20px rgba(99, 102, 241, 0.2);
transform: translateY(-2px);
}
.dark .card-glow:hover {
box-shadow: 0 0 20px rgba(129, 140, 248, 0.3);
}

/* === Markdown prose (レポート表示用) === */
.prose-orchestra {
@apply prose prose-sm dark:prose-invert max-w-none;
@apply prose-headings:text-gray-800 dark:prose-headings:text-gray-200;
@apply prose-a:text-indigo-600 dark:prose-a:text-indigo-400;
@apply prose-code:bg-gray-100 dark:prose-code:bg-gray-800;
@apply prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded;
}

/* === スクロールバー (議論チャット用) === */
.custom-scrollbar::-webkit-scrollbar {
width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
background: rgba(156, 163, 175, 0.4);
border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
background: rgba(156, 163, 175, 0.6);
}

/* === フォーカスリング (アクセシビリティ) === */
.focus-ring:focus-visible {
@apply outline-none ring-2 ring-indigo-500 ring-offset-2
dark:ring-offset-gray-900;
}