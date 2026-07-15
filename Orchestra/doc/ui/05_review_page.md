# AI Orchestra — Code Review ページ詳細設計

> `/review` ページの5ステップウィザード全仕様

---

## 1. 概要

| 項目 | 内容 |
|------|------|
| URL | `/review` |
| テンプレート | `pages/review.html` |
| Alpine.js | `reviewPage()` |
| ステップ数 | 5 (入力 → スキャン → 調査 → 会議 → 結果) |
| 通信 | REST (plan) + SSE (stream) |
| 所要時間 | 5〜30分 (設定次第) |

---

## 2. ステップ全体図

```
● 1 入力 ─── ● 2 スキャン ─── ● 3 調査 ─── ● 4 会議 ─── ● 5 結果
│              │                │             │             │
│ パス指定     │ ファイルツリー   │ 個別調査    │ 全体議論    │ レポート
│ 設定調整     │ 構造確認       │ +相互質問   │ リアルタイム │ 修正指示書
│              │                │             │             │
│ POST         │ (自動)         │ SSE         │ SSE         │ GET
│ /api/review/ │                │ (streaming) │ (streaming) │ /api/sessions/
│ plan         │                │             │             │ {id}/content
```

### Code Review の5フェーズとUIステップの対応

| バックエンド Phase | UIステップ | 表示内容 |
|-------------------|-----------|---------|
| Phase 1: 構造スキャン | Step 2 | ファイルツリー + 統計 |
| Phase 2: 個別調査 | Step 3 前半 | パートリーダー × 6 並列進捗 |
| Phase 3: 相互質問 | Step 3 後半 | 質疑応答ログ |
| Phase 4: 全体会議 | Step 4 | リアルタイムチャット (idea同様) |
| Phase 5: レポート生成 | Step 5 | レポート + vibe_coding_prompt |

---

## 3. Step 1: 入力設定

### 3.1 レイアウト

```
┌──── 左カラム (md:w-2/5) ──────────────┐ ┌──── 右カラム (md:w-3/5) ──┐
│                                        │ │                           │
│  📂 レビュー対象                        │ │  🔍 レビュー観点          │
│  ┌──────────────────────────────────┐  │ │                           │
│  │  [パス入力 or ファイルドロップ]   │  │ │  ┌────┐ ┌────┐ ┌────┐  │
│  └──────────────────────────────────┘  │ │  │algo│ │repr│ │perf│  │
│                                        │ │  └────┘ └────┘ └────┘  │
│  🎯 重点モード                          │ │  ┌────┐ ┌────┐ ┌────┐  │
│  [all] [pre_submission] [performance]  │ │  │strc│ │read│ │rslt│  │
│  [structure] [handover] [algorithm]    │ │  └────┘ └────┘ └────┘  │
│                                        │ │                           │
│  ⚙️ モデル設定                          │ │  ⏱️ 推定所要時間          │
│  ▶ (アコーディオン)                    │ │  10分00秒                  │
│                                        │ │                           │
│  🎛️ レビュー設定                       │ │  📊 対象ファイル見積       │
│  ▶ (アコーディオン)                    │ │  (パス入力後に表示)        │
│                                        │ │                           │
│  ┌──────────────────────────────────┐  │ │                           │
│  │  🔍 レビューを開始する           │  │ │                           │
│  └──────────────────────────────────┘  │ │                           │
│                                        │ │                           │
└────────────────────────────────────────┘ └───────────────────────────┘
```

### 3.2 パス入力

```html
<div class="space-y-2">
<label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
📂 レビュー対象ディレクトリ <span class="text-red-500">*</span>
</label>

<div class="relative">
<input type="text"
x-model="targetPath"
@input="saveToStorage(); validatePath()"
placeholder="例: ./src  または  /home/user/project/src"
class="w-full rounded-xl border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800
text-gray-900 dark:text-gray-100
px-4 py-3 pl-10 text-sm font-mono
focus:ring-2 focus:ring-indigo-500 focus:border-transparent
transition"
:class="{ 'border-red-400': pathError }">

<!-- フォルダアイコン -->
<span class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">📁</span>
</div>

<!-- バリデーションメッセージ -->
<p x-show="pathError"
class="text-xs text-red-500"
x-text="pathError">
</p>

<!-- パスヒント -->
<p class="text-xs text-gray-400">
サーバー上のディレクトリパスを指定してください。相対パスも可。
</p>
</div>
```

### 3.3 重点モード選択

```html
<div class="space-y-2">
<label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
🎯 重点モード
</label>

<div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
<template x-for="mode in focusModes" :key="mode.id">
<label class="relative cursor-pointer">
<input type="radio" name="focus"
:value="mode.id"
x-model="settings.focus"
class="peer sr-only">
<div class="p-3 rounded-xl border text-center transition
peer-checked:border-indigo-500 peer-checked:bg-indigo-50
dark:peer-checked:bg-indigo-900/30
border-gray-200 dark:border-gray-700
hover:border-gray-300 dark:hover:border-gray-600">
<div class="text-lg mb-1" x-text="mode.icon"></div>
<div class="text-xs font-medium" x-text="mode.label"></div>
</div>
</label>
</template>
</div>

<!-- 選択中のモード説明 -->
<p class="text-xs text-gray-500 dark:text-gray-400 mt-2"
x-text="focusModes.find(m => m.id === settings.focus)?.description || ''">
</p>
</div>
```

### 3.4 重点モード定義

```javascript
focusModes: [
{
id: 'all',
icon: '🔍',
label: '全体',
description: '6観点すべてを均等にレビューします'
},
{
id: 'pre_submission',
icon: '📝',
label: '投稿前',
description: '論文投稿前チェック: 再現性・結果整合性を重点的に'
},
{
id: 'performance',
icon: '⚡',
label: '性能',
description: 'ボトルネック・メモリ・並列化を重点的に'
},
{
id: 'structure',
icon: '🏗️',
label: '構造',
description: 'モジュール分割・DRY・SOLIDを重点的に'
},
{
id: 'handover',
icon: '🤝',
label: '引き継ぎ',
description: '可読性・ドキュメント・命名を重点的に'
},
{
id: 'algorithm',
icon: '🧮',
label: 'アルゴリズム',
description: '数式対応・境界条件・数値安定性を重点的に'
},
],
```

### 3.5 除外パターン設定

```html
<div class="space-y-2">
<label class="block text-xs text-gray-500">
除外パターン (カンマ区切り)
</label>
<input type="text"
x-model="settings.ignorePatterns"
placeholder="例: __pycache__,*.pyc,.git,node_modules"
class="w-full rounded-lg border border-gray-300 dark:border-gray-600
bg-white dark:bg-gray-800 text-sm px-3 py-2 font-mono">
<p class="text-xs text-gray-400">
デフォルト除外: .git, __pycache__, node_modules, .env, *.pyc
</p>
</div>
```

---

## 4. Step 2: スキャン結果

### 4.1 レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  📊 スキャン結果                                               │
│                                                                │
│  ┌── 統計カード (grid-cols-4) ─────────────────────────────┐  │
│  │ 📁 12ファイル │ 📝 1,540行 │ 🐍 Python │ 📏 avg 128行 │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── ファイルツリー ───────────────────────────────────────┐   │
│  │                                                         │   │
│  │  📂 src/                                                │   │
│  │  ├── 📄 main.py (45行)                                 │   │
│  │  ├── 📂 core/                                           │   │
│  │  │   ├── 📄 agent.py (230行)                           │   │
│  │  │   ├── 📄 conductor.py (280行)                       │   │
│  │  │   └── 📄 memory.py (150行)                          │   │
│  │  └── 📂 utils/                                          │   │
│  │      └── 📄 helpers.py (85行)                           │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── レビュー計画 ─────────────────────────────────────────┐  │
│  │ パートリーダー割当:                                      │  │
│  │ 🧮 algorithm: agent.py, conductor.py                    │  │
│  │ 🔬 reproducibility: main.py, config/                    │  │
│  │ 🤖 performance: conductor.py, memory.py                 │  │
│  │ 📐 structure: 全ファイル                                 │  │
│  │ 📝 readability: 全ファイル                               │  │
│  │ 🔬 results: main.py                                     │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  [← 設定を修正]              [▶️ 調査を開始する]               │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 ファイルツリー表示

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>📂</span> ファイルツリー
</h3>

<div class="font-mono text-sm space-y-0.5 max-h-80 overflow-y-auto
custom-scrollbar bg-gray-50 dark:bg-gray-900 rounded-xl p-4">
<template x-for="line in scanResult.treeLines" :key="line.path">
<div class="flex items-center gap-2 hover:bg-gray-100 dark:hover:bg-gray-800
rounded px-2 py-0.5 transition">
<!-- インデント -->
<span class="text-gray-400 whitespace-pre" x-text="line.indent"></span>
<!-- アイコン -->
<span x-text="line.isDir ? '📂' : '📄'" class="text-sm"></span>
<!-- ファイル名 -->
<span class="text-gray-700 dark:text-gray-300" x-text="line.name"></span>
<!-- 行数 (ファイルのみ) -->
<span x-show="!line.isDir"
class="text-xs text-gray-400 ml-auto"
x-text="'(' + line.lines + '行)'"></span>
</div>
</template>
</div>
</div>
```

### 4.3 パートリーダー割当表示

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>👥</span> パートリーダー割当
</h3>

<div class="space-y-3">
<template x-for="leader in scanResult.partLeaders" :key="leader.aspect">
<div class="flex items-start gap-3 p-3 rounded-xl
bg-gray-50 dark:bg-gray-700/50">
<!-- アイコン + 観点名 -->
<div class="flex items-center gap-2 min-w-[140px]">
<span class="text-xl" x-text="leader.emoji"></span>
<div>
<div class="text-sm font-medium text-gray-700 dark:text-gray-300"
x-text="leader.aspect_label"></div>
<div class="text-xs text-gray-400" x-text="leader.role_name"></div>
</div>
</div>

<!-- 担当ファイル -->
<div class="flex flex-wrap gap-1">
<template x-for="file in leader.files" :key="file">
<span class="text-xs px-2 py-0.5 rounded-full font-mono
bg-gray-200 dark:bg-gray-600
text-gray-600 dark:text-gray-300"
x-text="file">
</span>
</template>
</div>
</div>
</template>
</div>
</div>
```

---

## 5. Step 3: 個別調査 + 相互質問

### 5.1 レイアウト

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  🔬 個別調査 (Phase 2)                                         │
│                                                                │
│  ┌── 並列進捗表示 ─────────────────────────────────────────┐  │
│  │                                                         │  │
│  │ 🧮 algorithm     ████████████░░░░  75%  3件発見          │  │
│  │ 🔬 reproducibility ██████████████  100% ✓ 2件発見       │  │
│  │ 🤖 performance   ████████░░░░░░░░  50%  1件発見          │  │
│  │ 📐 structure     ████████████████  100% ✓ 4件発見       │  │
│  │ 📝 readability   ████████████░░░░  80%  2件発見          │  │
│  │ 🔬 results       ██████░░░░░░░░░░  40%  0件              │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── 発見事項 (リアルタイム追加) ──────────────────────────┐  │
│  │                                                         │  │
│  │ 🔴 critical │ algorithm │ agent.py:45-60                 │  │
│  │ "境界条件チェックが欠落..."                              │  │
│  │                                                         │  │
│  │ 🟠 major │ structure │ conductor.py                      │  │
│  │ "300行超過、分割が必要..."                               │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── 相互質問 (Phase 3) ──                                      │
│                                                                │
│  ┌── 質疑応答ログ ─────────────────────────────────────────┐  │
│  │                                                         │  │
│  │ 📐→🧮: "構造的にagent.pyが肥大化しているが、           │  │
│  │         アルゴリズム観点でも問題は?"                     │  │
│  │                                                         │  │
│  │ 🧮→📐: "計算フローが1ファイルに集中しており、           │  │
│  │         テスタビリティに影響する"                        │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 並列進捗バー

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>🔬</span> 個別調査進捗
</h3>

<div class="space-y-4">
<template x-for="leader in investigationProgress" :key="leader.aspect">
<div>
<!-- ラベル行 -->
<div class="flex items-center justify-between mb-1">
<div class="flex items-center gap-2">
<span class="text-sm" x-text="leader.emoji"></span>
<span class="text-sm font-medium text-gray-700 dark:text-gray-300"
x-text="leader.aspect_label"></span>
</div>
<div class="flex items-center gap-2">
<span class="text-xs text-gray-500"
x-text="leader.findings_count + '件発見'"></span>
<span x-show="leader.progress >= 100"
class="text-green-500 text-sm">✓</span>
</div>
</div>

<!-- プログレスバー -->
<div class="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
<div class="h-full rounded-full transition-all duration-500 ease-out"
:class="{
'bg-indigo-500': leader.progress < 100,
'bg-green-500': leader.progress >= 100,
}"
:style="'width: ' + leader.progress + '%'">
</div>
</div>
</div>
</template>
</div>
</div>
```

### 5.3 発見事項リスト (リアルタイム追加)

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>📋</span> 発見事項
<span class="text-sm font-normal text-gray-400"
x-text="'(' + findings.length + '件)'"></span>
</h3>

<div class="space-y-3 max-h-96 overflow-y-auto custom-scrollbar">
<template x-for="finding in findings" :key="finding.id">
<div class="p-3 rounded-xl border animate-slide-up"
:class="{
'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/10':
finding.severity === 'critical',
'border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900/10':
finding.severity === 'major',
'border-yellow-300 dark:border-yellow-700 bg-yellow-50 dark:bg-yellow-900/10':
finding.severity === 'minor',
'border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/10':
finding.severity === 'suggestion',
}">

<!-- ヘッダー -->
<div class="flex items-center gap-2 mb-1 flex-wrap">
<!-- 深刻度バッジ -->
<span class="text-xs px-2 py-0.5 rounded-full font-medium"
:class="{
'bg-red-200 text-red-800 dark:bg-red-900 dark:text-red-200':
finding.severity === 'critical',
'bg-orange-200 text-orange-800 dark:bg-orange-900 dark:text-orange-200':
finding.severity === 'major',
'bg-yellow-200 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200':
finding.severity === 'minor',
'bg-blue-200 text-blue-800 dark:bg-blue-900 dark:text-blue-200':
finding.severity === 'suggestion',
}"
x-text="finding.severity"></span>

<!-- 観点バッジ -->
<span class="text-xs px-2 py-0.5 rounded bg-gray-200 dark:bg-gray-600
text-gray-600 dark:text-gray-300"
x-text="finding.aspect"></span>

<!-- ファイル + 行 -->
<span class="text-xs font-mono text-gray-500"
x-text="finding.file_path + (finding.line_range ? ':' + finding.line_range[0] + '-' + finding.line_range[1] : '')">
</span>
</div>

<!-- タイトル -->
<div class="text-sm font-medium text-gray-800 dark:text-gray-200"
x-text="finding.title"></div>

<!-- 説明 (展開可能) -->
<details class="mt-1">
<summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-700
dark:hover:text-gray-300 transition">
詳細を見る
</summary>
<div class="mt-2 text-xs text-gray-600 dark:text-gray-400 space-y-1">
<p x-text="finding.description"></p>
<p x-show="finding.suggestion"
class="text-green-700 dark:text-green-400">
💡 <span x-text="finding.suggestion"></span>
</p>
</div>
</details>
</div>
</template>
</div>
</div>
```

### 5.4 相互質問ログ

```html
<div class="bg-white dark:bg-gray-800 rounded-2xl p-6
border border-gray-200 dark:border-gray-700 shadow-sm mt-6"
x-show="crossQuestions.length > 0">
<h3 class="text-lg font-bold mb-4 flex items-center gap-2">
<span>💬</span> 相互質問
</h3>

<div class="space-y-4">
<template x-for="qa in crossQuestions" :key="qa.id">
<div class="space-y-2">
<!-- 質問 -->
<div class="flex items-start gap-3">
<div class="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30
flex items-center justify-center text-sm"
x-text="qa.questioner_emoji"></div>
<div class="flex-1">
<div class="text-xs text-gray-500 mb-0.5">
<span x-text="qa.questioner_name"></span> → <span x-text="qa.target_name"></span>
</div>
<div class="p-2 rounded-xl rounded-tl-sm
bg-blue-50 dark:bg-blue-900/20
text-sm text-gray-700 dark:text-gray-300"
x-text="qa.question">
</div>
</div>
</div>

<!-- 回答 -->
<div class="flex items-start gap-3 pl-11" x-show="qa.answer">
<div class="flex-shrink-0 w-8 h-8 rounded-full bg-green-100 dark:bg-green-900/30
flex items-center justify-center text-sm"
x-text="qa.target_emoji"></div>
<div class="flex-1">
<div class="p-2 rounded-xl rounded-tl-sm
bg-green-50 dark:bg-green-900/20
text-sm text-gray-700 dark:text-gray-300"
x-text="qa.answer">
</div>
</div>
</div>
</div>
</template>
</div>
</div>
```

---

## 6. Step 4: 全体会議

### 6.1 概要

全体会議は Idea 議論の Step 3 とほぼ同じUIを共有する。
3ラウンド固定: 課題報告 → 深掘り → 合意形成

### 6.2 レイアウト

```
┌──── サイドバー (md:w-72) ─────────┐ ┌──── チャットエリア (flex-1) ───────┐
│                                    │ │                                    │
│  ⏱️ タイマー                       │ │  (idea Step 3 と同じチャットUI)     │
│                                    │ │                                    │
│  📊 会議ラウンド                    │ │  Round 1: 課題報告                 │
│  R1: 課題報告 (one_shot)           │ │  各パートリーダーが重要発見を報告   │
│  R2: 深掘り (free_talk)            │ │                                    │
│  R3: 合意形成 (free_talk)          │ │  Round 2: 深掘り                   │
│                                    │ │  相互の指摘について議論             │
│  👥 参加パートリーダー              │ │                                    │
│  🧮 algorithm    ● 発言中          │ │  Round 3: 合意形成                 │
│  🔬 reproducibility ○             │ │  優先度合意 + 修正方針決定          │
│  🤖 performance  ○                │ │                                    │
│  📐 structure    ✓                 │ │                                    │
│  📝 readability  ○                │ │                                    │
│  🔬 results     ○                 │ │                                    │
│                                    │ │                                    │
│  📋 発見サマリー                    │ │                                    │
│  🔴 Critical: 2件                  │ │                                    │
│  🟠 Major: 5件                     │ │                                    │
│  🟡 Minor: 3件                     │ │                                    │
│  💡 Suggestion: 2件                │ │                                    │
│                                    │ │                                    │
│  [🛑 中断]                         │ │                                    │
│                                    │ │                                    │
└────────────────────────────────────┘ └────────────────────────────────────┘
```

### 6.3 サイドバーの発見サマリー

```html
<div class="bg-white dark:bg-gray-800 rounded-xl p-4
border border-gray-200 dark:border-gray-700 shadow-sm">
<h4 class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">
発見サマリー
</h4>
<div class="space-y-2">
<div class="flex items-center justify-between text-sm">
<span class="flex items-center gap-1">
<span class="w-2.5 h-2.5 rounded-full bg-red-500"></span>
<span class="text-gray-600 dark:text-gray-400">Critical</span>
</span>
<span class="font-mono font-medium text-red-600 dark:text-red-400"
x-text="findingsCounts.critical">0</span>
</div>
<div class="flex items-center justify-between text-sm">
<span class="flex items-center gap-1">
<span class="w-2.5 h-2.5 rounded-full bg-orange-500"></span>
<span class="text-gray-600 dark:text-gray-400">Major</span>
</span>
<span class="font-mono font-medium text-orange-600 dark:text-orange-400"
x-text="findingsCounts.major">0</span>
</div>
<div class="flex items-center justify-between text-sm">
<span class="flex items-center gap-1">
<span class="w-2.5 h-2.5 rounded-full bg-yellow-500"></span>
<span class="text-gray-600 dark:text-gray-400">Minor</span>
</span>
<span class="font-mono font-medium text-yellow-600 dark:text-yellow-400"
x-text="findingsCounts.minor">0</span>
</div>
<div class="flex items-center justify-between text-sm">
<span class="flex items-center gap-1">
<span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
<span class="text-gray-600 dark:text-gray-400">Suggestion</span>
</span>
<span class="font-mono font-medium text-blue-600 dark:text-blue-400"
x-text="findingsCounts.suggestion">0</span>
</div>
</div>
</div>
```

---

## 7. Step 5: 結果表示

### 7.1 レイアウト (idea Step 4 拡張)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│  ✅ レビュー完了！                                             │
│                                                                │
│  ┌── 統計カード ────────────────────────────────────────────┐  │
│  │ ⏱️9:58 │ 📁12files │ 📋12件 │ 🔴2 🟠5 🟡3 💡2 │      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌── タブ ─────────────────────────────────────────────────┐  │
│  │ [📄 レポート] [🔧 修正指示書] [💬 会議録] [📊 評価]     │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │                                                         │  │
│  │  (Markdown レンダリング表示)                             │  │
│  │                                                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ── アクション ──                                              │
│  [📋 修正指示書をコピー] [📥 ダウンロード ▼] [🏠 ホームへ]    │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 7.2 修正指示書タブ (vibe_coding_prompt)

```html
<!-- 修正指示書タブ -->
<div x-show="activeTab === 'vibe_prompt'">
<!-- コピーボタン -->
<div class="flex justify-end mb-4">
<button @click="copyVibePrompt()"
class="px-3 py-1.5 rounded-lg text-xs font-medium
bg-indigo-100 dark:bg-indigo-900/30
text-indigo-700 dark:text-indigo-300
hover:bg-indigo-200 dark:hover:bg-indigo-900/50
transition flex items-center gap-1">
<span x-text="copied ? '✓ コピー済み' : '📋 クリップボードにコピー'"></span>
</button>
</div>

<!-- 内容表示 -->
<div class="prose-orchestra"
x-html="renderMarkdown(result.files.vibe_prompt)">
</div>
</div>
```

### 7.3 コピー機能

```javascript
copied: false,

async copyVibePrompt() {
try {
await navigator.clipboard.writeText(this.result.files.vibe_prompt);
this.copied = true;
toast('修正指示書をコピーしました', 'success');
setTimeout(() => { this.copied = false; }, 3000);
} catch (err) {
toast('コピーに失敗しました', 'error');
}
},
```

---

## 8. SSE イベント (Review 固有)

### 8.1 追加イベント型

```javascript
// Phase 1: スキャン
{"type": "scan_start"}
{"type": "scan_complete", "scan_result": { files: [...], tree_text: "...", ... }}

// Phase 2: 個別調査
{"type": "investigation_start", "aspect": "algorithm", "emoji": "🧮"}
{"type": "investigation_progress", "aspect": "algorithm", "progress": 50}
{"type": "investigation_finding", "aspect": "algorithm", "finding": {...}}
{"type": "investigation_complete", "aspect": "algorithm", "findings_count": 3}

// Phase 3: 相互質問
{"type": "cross_question_start"}
{"type": "cross_question", "questioner": "structure", "target": "algorithm", "question": "..."}
{"type": "cross_answer", "answerer": "algorithm", "questioner": "structure", "answer": "..."}
{"type": "cross_question_complete"}

// Phase 4: 全体会議 (idea と同じ utterance/round_start 等)
{"type": "meeting_start"}
// ... round_start, utterance, round_end 等

// Phase 5: レポート生成
{"type": "report_start"}
{"type": "report_complete", "preview": "..."}

// 完了
{"type": "done", "session_id": "...", "statistics": {...}}
```

### 8.2 SSE ハンドリング

```javascript
async startReview() {
this.step = 2;  // まずスキャン表示

this.sse = new OrchestraSSE('/api/review/stream');

// Phase 1: スキャン
this.sse.on('scan_complete', (data) => {
this.scanResult = data.scan_result;
// Step 2 に留まる（ユーザーが確認して「調査開始」を押す）
// → 自動遷移の場合はここで step = 3;
});

// Phase 2: 個別調査
this.sse.on('investigation_start', (data) => {
this.step = 3;
this.updateInvestigationProgress(data.aspect, 0);
});

this.sse.on('investigation_progress', (data) => {
this.updateInvestigationProgress(data.aspect, data.progress);
});

this.sse.on('investigation_finding', (data) => {
this.findings.push(data.finding);
this.updateFindingsCounts();
});

this.sse.on('investigation_complete', (data) => {
this.updateInvestigationProgress(data.aspect, 100);
});

// Phase 3: 相互質問
this.sse.on('cross_question', (data) => {
this.crossQuestions.push({
id: 'q_' + this.crossQuestions.length,
...data,
answer: null,
});
});

this.sse.on('cross_answer', (data) => {
const q = this.crossQuestions.find(
q => q.questioner === data.questioner && !q.answer
);
if (q) q.answer = data.answer;
});

// Phase 4: 全体会議
this.sse.on('meeting_start', () => {
this.step = 4;
this.startTimer();
});

// (utterance, round_start 等は idea と同じハンドリング)
this.sse.on('utterance', (data) => { /* same as idea */ });
this.sse.on('round_start', (data) => { /* same as idea */ });

// Phase 5: 完了
this.sse.on('done', async (data) => {
this.stopTimer();
const res = await fetch(`/api/sessions/${data.session_id}/content`);
this.result = await res.json();
this.result.session_id = data.session_id;
this.result.statistics = data.statistics;
this.step = 5;
});

this.sse.on('error', (data) => {
this.stopTimer();
toast(data.message, 'error');
});

await this.sse.start({
target_path: this.targetPath,
planner_model: this.settings.plannerModel,
conductor_model: this.settings.conductorModel,
synth_model: this.settings.synthModel,
time_limit: this.settings.timeLimit,
max_agents: this.settings.maxAgents,
focus: this.settings.focus,
ignore_patterns: this.settings.ignorePatterns.split(',').map(s => s.trim()).filter(Boolean),
});
},
```

---

## 9. Alpine.js 状態管理 (reviewPage)

```javascript
function reviewPage() {
return {
// === State ===
step: 1,
steps: [
{ num: 1, label: '入力' },
{ num: 2, label: 'スキャン' },
{ num: 3, label: '調査' },
{ num: 4, label: '会議' },
{ num: 5, label: '結果' },
],

// Step 1
targetPath: '',
pathError: '',
settings: {
plannerModel: 'gpt-5.4',
conductorModel: 'gpt-4.1',
synthModel: 'gpt-5.4',
timeLimit: 600,
maxAgents: 6,
focus: 'all',
ignorePatterns: '',
},

// Step 2
scanResult: null,

// Step 3
investigationProgress: [],
findings: [],
crossQuestions: [],
findingsCounts: { critical: 0, major: 0, minor: 0, suggestion: 0 },

// Step 4 (meeting — idea Step 3 と共通)
sse: null,
chatItems: [],
utterances: [],
currentRound: 0,
totalRounds: 3,
currentPhase: '',
currentPattern: '',
participatingAgents: [],
stats: { utteranceCount: 0, totalTokens: 0, convergence: 0 },
remainingSec: 0,
timeLimit: 600,
timePressure: 'relaxed',
timerInterval: null,
isAtBottom: true,

// Step 5
result: null,
activeTab: 'report',
copied: false,

// === Computed ===
get isPathValid() {
return this.targetPath.trim().length > 0 && !this.pathError;
},

// === Methods ===
validatePath() {
const path = this.targetPath.trim();
if (!path) {
this.pathError = '';
return;
}
// 基本的なパスバリデーション
if (path.includes('..') && path.includes('/')) {
this.pathError = '相対パスは ".." を含めないでください';
return;
}
this.pathError = '';
},

async startReview() { /* 上記のSSEハンドリング */ },

updateInvestigationProgress(aspect, progress) {
const item = this.investigationProgress.find(p => p.aspect === aspect);
if (item) {
item.progress = progress;
} else {
this.investigationProgress.push({
aspect,
progress,
findings_count: 0,
emoji: this.getAspectEmoji(aspect),
aspect_label: this.getAspectLabel(aspect),
});
}
},

updateFindingsCounts() {
this.findingsCounts = {
critical: this.findings.filter(f => f.severity === 'critical').length,
major: this.findings.filter(f => f.severity === 'major').length,
minor: this.findings.filter(f => f.severity === 'minor').length,
suggestion: this.findings.filter(f => f.severity === 'suggestion').length,
};
},

getAspectEmoji(aspect) {
const map = {
algorithm: '🧮', reproducibility: '🔬', performance: '🤖',
structure: '📐', readability: '📝', results: '🔬',
};
return map[aspect] || '📋';
},

getAspectLabel(aspect) {
const map = {
algorithm: 'アルゴリズム', reproducibility: '再現性',
performance: '性能', structure: '構造',
readability: '可読性', results: '結果',
};
return map[aspect] || aspect;
},

async copyVibePrompt() { /* 上記のコピー機能 */ },

// Timer / scroll / storage は idea と共通
startTimer() { /* ... */ },
stopTimer() { /* ... */ },

saveToStorage() {
localStorage.setItem('review_target', this.targetPath);
localStorage.setItem('review_settings', JSON.stringify(this.settings));
},

restoreFromStorage() {
this.targetPath = localStorage.getItem('review_target') || '';
const saved = localStorage.getItem('review_settings');
if (saved) {
try { Object.assign(this.settings, JSON.parse(saved)); } catch {}
}
},

init() {
this.restoreFromStorage();
},
};
}
```

---

## 10. API 連携仕様

### 10.1 POST /api/review/stream

```
Request:
{
"target_path": "./src",
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 600,
"max_agents": 6,
"focus": "all",
"ignore_patterns": ["__pycache__", "*.pyc"]
}

Response: text/event-stream
data: {"type": "scan_start"}\n\n
data: {"type": "scan_complete", "scan_result": {...}}\n\n
data: {"type": "investigation_start", "aspect": "algorithm"}\n\n
...
data: {"type": "done", "session_id": "...", "statistics": {...}}\n\n
```

### 10.2 出力ファイル (review固有)

| ファイル | 説明 |
|---------|------|
| `report.md` | 全体レビューレポート |
| `vibe_coding_prompt.md` | AIコーディング向け修正指示書 |
| `full_conversation.md` | 全体会議の会話ログ |
| `evaluation.md` | 評価結果 |
| `summary.txt` | 1ページ要約 |
| `session_meta.json` | メタ情報 |
| `discussion.json` | 全ログ (JSON) |

---

## 11. Idea ページとの共通化

### 11.1 共有コンポーネント

| コンポーネント | Idea | Review | 備考 |
|---------------|------|--------|------|
| chat_bubble.html | ✅ | ✅ (Step 4) | 完全共通 |
| timer.html | ✅ | ✅ (Step 4) | 完全共通 |
| agent_badge.html | ✅ | ✅ | 完全共通 |
| evaluation.html | ✅ | ✅ | 完全共通 |
| step_indicator.html | ✅ | ✅ | ステップ数が異なるだけ |
| plan_card.html | ✅ | ❌ | Idea のみ |
| hypothesis_table.html | ✅ | ❌ | Idea のみ |
| file_drop.html | ✅ | ❌ | Idea のみ (添付ファイル) |

### 11.2 共通ロジック (抽出候補)

```javascript
// 将来的に mixin 化する共通ロジック
const discussionMixin = {
// チャット関連
chatItems: [],
utterances: [],
isAtBottom: true,
addChatItem(item) { /* ... */ },
scrollToBottom() { /* ... */ },
handleScroll() { /* ... */ },

// タイマー関連
remainingSec: 0,
timePressure: 'relaxed',
timerInterval: null,
startTimer() { /* ... */ },
stopTimer() { /* ... */ },
updateTimePressure() { /* ... */ },

// エージェント状態
getAgentStatus(roleId) { /* ... */ },
updateAgentStatus(roleId, status) { /* ... */ },
resetAgentStatuses() { /* ... */ },
};
```

---

## 12. モバイル対応

### 12.1 Step 3 (調査) のモバイル表示

```
┌────────────────────────────┐
│  🔬 個別調査               │
│                            │
│  🧮 algo  ████████ 75%     │  ← コンパクトな進捗バー
│  🔬 repr  ██████████ 100%  │
│  🤖 perf  ████░░░░ 50%    │
│  📐 strc  ██████████ 100%  │
│  📝 read  ████████░ 80%   │
│  🔬 rslt  ██████░░ 40%    │
│                            │
│  ── 発見事項 (3件) ──       │
│  🔴 境界条件チェック欠落    │
│  🟠 300行超過...           │
│  🟡 型ヒント不足...        │
│                            │
└────────────────────────────┘
```

### 12.2 Step 4 (会議) のモバイル

Idea Step 3 のモバイルレイアウトと同じ:
- 上部固定バー (タイマー + ラウンド)
- フルスクリーンチャット
- 下部固定バー (統計 + 中断)