# AI Orchestra — スタイル・アニメーション・ダークモード

> UIの視覚表現に関する全仕様

---

## 1. カラーパレット

### 1.1 ブランドカラー

| 用途 | Light | Dark | Tailwind クラス |
|------|-------|------|----------------|
| プライマリ | indigo-600 | indigo-400 | `text-indigo-600 dark:text-indigo-400` |
| プライマリBG | indigo-50 | indigo-900/20 | `bg-indigo-50 dark:bg-indigo-900/20` |
| セカンダリ | purple-600 | purple-400 | `text-purple-600 dark:text-purple-400` |
| アクセント | amber-500 | amber-400 | `text-amber-500 dark:text-amber-400` |

### 1.2 セマンティックカラー

| 意味 | Light | Dark | 用途 |
|------|-------|------|------|
| 成功 | green-600 | green-400 | 完了、確認、正常 |
| 警告 | amber-600 | amber-400 | 注意、時間逼迫 |
| エラー | red-600 | red-400 | エラー、Critical |
| 情報 | blue-600 | blue-400 | ヒント、info |

### 1.3 深刻度カラー (Code Review)

| 深刻度 | Light BG | Dark BG | Border | Text |
|--------|----------|---------|--------|------|
| critical | red-50 | red-900/10 | red-300 / red-700 | red-800 / red-200 |
| major | orange-50 | orange-900/10 | orange-300 / orange-700 | orange-800 / orange-200 |
| minor | yellow-50 | yellow-900/10 | yellow-300 / yellow-700 | yellow-800 / yellow-200 |
| suggestion | blue-50 | blue-900/10 | blue-300 / blue-700 | blue-800 / blue-200 |

### 1.4 フェーズカラー (議論ラウンド)

| フェーズ | Light | Dark | 意味 |
|---------|-------|------|------|
| diverge (発散) | blue-100 / blue-700 | blue-900/50 / blue-300 | 自由に広げる |
| deepen (深掘り) | purple-100 / purple-700 | purple-900/50 / purple-300 | 掘り下げる |
| converge (収束) | green-100 / green-700 | green-900/50 / green-300 | まとめる |

### 1.5 タイマーカラー (時間逼迫度)

| 逼迫度 | カラー | 条件 |
|--------|--------|------|
| RELAXED | green-600 / green-400 | 残り > 60% |
| MODERATE | yellow-600 / yellow-400 | 残り 30-60% |
| URGENT | orange-600 / orange-400 | 残り 10-30% |
| CRITICAL | red-600 / red-400 + pulse | 残り < 10% |

---

## 2. タイポグラフィ

### 2.1 フォントスタック

```css
/* Tailwind デフォルト (カスタマイズなし) */
font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;

/* モノスペース (タイマー、コード) */
font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
"Liberation Mono", "Courier New", monospace;
```

### 2.2 テキストサイズ体系

| 用途 | サイズ | クラス |
|------|--------|--------|
| ページタイトル | 2xl〜3xl | `text-2xl md:text-3xl font-bold` |
| セクション見出し | lg | `text-lg font-bold` |
| カード見出し | sm〜base | `text-sm font-medium` or `text-base font-bold` |
| 本文 | sm | `text-sm` |
| チャット発言 | sm | `text-sm leading-relaxed` |
| メタ情報 | xs | `text-xs text-gray-400` |
| バッジ | xs | `text-xs font-medium` |
| タイマー数字 | 3xl | `text-3xl font-mono font-bold` |

### 2.3 行間

| コンテンツ | leading | 用途 |
|-----------|---------|------|
| チャット発言 | relaxed (1.625) | 読みやすさ重視 |
| レポート本文 | normal (1.5) | prose クラスのデフォルト |
| UI テキスト | tight (1.25) | コンパクトな表示 |

---

## 3. 間隔・余白体系

### 3.1 コンテナ

```css
/* メインコンテナ */
max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8

/* ページ内余白 */
pt-20  /* ヘッダー分 */
pb-12  /* 下部余白 */
```

### 3.2 コンポーネント間隔

| 関係 | 間隔 | クラス |
|------|------|--------|
| ページセクション間 | 32px | `mb-8` |
| カード間 | 16px | `gap-4` |
| カード内要素間 | 12〜16px | `space-y-3` or `space-y-4` |
| テキスト行間 | 8px | `space-y-2` |
| インラインアイテム間 | 8px | `gap-2` |
| バッジ・タグ間 | 8px | `gap-2` |

### 3.3 カード内パディング

| カードサイズ | padding | クラス |
|-------------|---------|--------|
| 小 (バッジ) | 4-8px | `px-2 py-1` or `px-3 py-1.5` |
| 中 (リストアイテム) | 12px | `p-3` |
| 大 (セクションカード) | 24px | `p-6` |
| 特大 (Heroカード) | 32px | `p-8` |

---

## 4. 角丸・ボーダー

### 4.1 角丸体系

| 要素 | 角丸 | クラス |
|------|------|--------|
| ページカード | 16px | `rounded-2xl` |
| 入力フィールド | 12px | `rounded-xl` |
| ボタン | 12px | `rounded-xl` |
| バッジ | 8px or full | `rounded-lg` or `rounded-full` |
| チャットバブル | 16px (角1つ小) | `rounded-2xl rounded-tl-sm` |
| プログレスバー | full | `rounded-full` |
| アバター | full | `rounded-full` |

### 4.2 ボーダー

```css
/* 標準ボーダー */
border border-gray-200 dark:border-gray-700

/* ホバー時ボーダー */
hover:border-gray-300 dark:hover:border-gray-600

/* アクティブ/選択時ボーダー */
border-indigo-500 dark:border-indigo-400

/* 強調ボーダー (結論バブル等) */
border-2 border-amber-400 dark:border-amber-500

/* 点線ボーダー (ドロップゾーン) */
border-2 border-dashed border-gray-300 dark:border-gray-600
```

---

## 5. シャドウ

### 5.1 シャドウ体系

| 用途 | クラス | 適用箇所 |
|------|--------|---------|
| カード基本 | `shadow-sm` | セクションカード |
| カードホバー | `shadow-md` | ホバー時 |
| 浮遊要素 | `shadow-lg` | ドロップダウン、トースト |
| モーダル | `shadow-2xl` | モーダルダイアログ |
| ボタン強調 | `shadow-lg shadow-indigo-200 dark:shadow-indigo-900/50` | CTAボタン |
| glow効果 | カスタム (box-shadow) | ホバーカード |

### 5.2 glow 効果

```css
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
```

---

## 6. アニメーション

### 6.1 キーフレーム定義

```css
/* === 基本アニメーション === */

@keyframes fadeIn {
from { opacity: 0; }
to { opacity: 1; }
}

@keyframes slideUp {
from {
opacity: 0;
transform: translateY(8px);
}
to {
opacity: 1;
transform: translateY(0);
}
}

@keyframes slideDown {
from {
opacity: 0;
transform: translateY(-8px);
}
to {
opacity: 1;
transform: translateY(0);
}
}

@keyframes scaleIn {
from {
opacity: 0;
transform: scale(0.95);
}
to {
opacity: 1;
transform: scale(1);
}
}

@keyframes slideInRight {
from {
opacity: 0;
transform: translateX(16px);
}
to {
opacity: 1;
transform: translateX(0);
}
}

@keyframes slideOutRight {
from {
opacity: 1;
transform: translateX(0);
}
to {
opacity: 0;
transform: translateX(16px);
}
}

/* === 特殊アニメーション === */

@keyframes pulseGlow {
0%, 100% {
box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
}
50% {
box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
}
}

@keyframes typing {
0% { opacity: 0.3; }
50% { opacity: 1; }
100% { opacity: 0.3; }
}

@keyframes shimmer {
0% { background-position: -200% 0; }
100% { background-position: 200% 0; }
}

@keyframes countUp {
from { opacity: 0; transform: translateY(10px); }
to { opacity: 1; transform: translateY(0); }
}
```

### 6.2 ユーティリティクラス

```css
/* 基本 */
.animate-fade-in { animation: fadeIn 300ms ease-out both; }
.animate-slide-up { animation: slideUp 400ms ease-out both; }
.animate-slide-down { animation: slideDown 400ms ease-out both; }
.animate-scale-in { animation: scaleIn 200ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.animate-slide-in-right { animation: slideInRight 300ms ease-out both; }
.animate-slide-out-right { animation: slideOutRight 200ms ease-in both; }

/* 特殊 */
.animate-pulse-glow { animation: pulseGlow 2s infinite; }
.animate-shimmer {
background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.4) 50%, transparent 100%);
background-size: 200% 100%;
animation: shimmer 1.5s infinite;
}
.animate-count-up { animation: countUp 500ms ease-out both; }

/* stagger (順次表示) */
.stagger-1 { animation-delay: 100ms; }
.stagger-2 { animation-delay: 200ms; }
.stagger-3 { animation-delay: 300ms; }
.stagger-4 { animation-delay: 400ms; }
.stagger-5 { animation-delay: 500ms; }
.stagger-6 { animation-delay: 600ms; }
.stagger-7 { animation-delay: 700ms; }
.stagger-8 { animation-delay: 800ms; }
```

### 6.3 アニメーション適用ガイド

| シーン | アニメーション | 理由 |
|--------|--------------|------|
| ページ表示 | fade-in | 自然な表出 |
| カード表示 | slide-up + stagger | 順次表示で視線誘導 |
| チャット発言 | slide-up | 下から追加される感覚 |
| ラウンド結論 | scale-in | 特別感、注目を集める |
| トースト表示 | slide-in-right | 右から入って注意喚起 |
| モーダル表示 | scale-in (0.95→1) | 浮かび上がる感覚 |
| ステップ遷移 | fade + slide | スムーズな切り替え |
| エラー強調 | pulse-glow | 赤い点滅で緊急性 |
| 統計数値 | count-up | 数字が上がる動き |
| ロード中 | shimmer | スケルトンのキラキラ |

### 6.4 アニメーション抑制

```css
/* ユーザーがモーション軽減を設定している場合 */
@media (prefers-reduced-motion: reduce) {
*,
*::before,
*::after {
animation-duration: 0.01ms !important;
animation-iteration-count: 1 !important;
transition-duration: 0.01ms !important;
}
}
```

---

## 7. ダークモード

### 7.1 実装方式

```
方式: Tailwind CSS の class 方式
切替: localStorage + OS設定フォールバック
適用: document.documentElement に 'dark' クラスを付与/除去
```

### 7.2 初期化 (白フラッシュ防止)

```html
<!-- <head> 内の先頭に配置 -->
<script>
(function() {
const stored = localStorage.getItem('darkMode');
const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
if (stored === 'true' || (stored === null && prefersDark)) {
document.documentElement.classList.add('dark');
}
})();
</script>
```

### 7.3 トグル実装

```javascript
// web/static/js/dark-mode.js

/**
* ダークモードトグル。
* Alpine.js から呼び出す。
*/
function toggleDarkMode() {
const isDark = document.documentElement.classList.toggle('dark');
localStorage.setItem('darkMode', isDark.toString());
}

/**
* 現在のダークモード状態を返す。
* @returns {boolean}
*/
function isDarkMode() {
return document.documentElement.classList.contains('dark');
}

/**
* OS設定の変更を監視する。
* localStorage に明示設定がない場合のみ追従。
*/
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
const stored = localStorage.getItem('darkMode');
if (stored === null) {
document.documentElement.classList.toggle('dark', e.matches);
}
});
```

### 7.4 カラーマッピング

| 要素 | Light | Dark |
|------|-------|------|
| ページ背景 | `bg-gray-50` | `bg-gray-900` |
| テキスト | `text-gray-900` | `text-gray-100` |
| カード背景 | `bg-white` | `bg-gray-800` |
| カードボーダー | `border-gray-200` | `border-gray-700` |
| 入力背景 | `bg-white` | `bg-gray-800` |
| 入力ボーダー | `border-gray-300` | `border-gray-600` |
| セカンダリテキスト | `text-gray-600` | `text-gray-400` |
| ミュートテキスト | `text-gray-400` | `text-gray-500` |
| ホバー背景 | `hover:bg-gray-50` | `hover:bg-gray-700` |
| コード背景 | `bg-gray-100` | `bg-gray-800` |
| divider | `border-gray-200` | `border-gray-700` |

### 7.5 特殊ダークモード対応

```css
/* 透過背景 (ヘッダー) */
bg-white/80 dark:bg-gray-900/80

/* グラデーション */
bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500
/* → ダークモードでもそのまま使用 (テキストに適用) */

/* 影のダーク対応 */
shadow-lg shadow-indigo-200 dark:shadow-indigo-900/50

/* glow のダーク対応 */
.card-glow:hover {
box-shadow: 0 0 20px rgba(99, 102, 241, 0.2);
}
.dark .card-glow:hover {
box-shadow: 0 0 20px rgba(129, 140, 248, 0.3);
}
```

---

## 8. トランジション

### 8.1 共通トランジション

```css
/* 基本: 色と背景の変化 */
transition-colors duration-200

/* インタラクション: 影とスケール含む */
transition-all duration-200

/* モーダル/パネル: やや長め */
transition ease-out duration-300
```

### 8.2 Alpine.js トランジション

```html
<!-- フェードイン/アウト -->
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0"
x-transition:enter-end="opacity-100"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100"
x-transition:leave-end="opacity-0"

<!-- スケールイン/アウト (モーダル) -->
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0 scale-95"
x-transition:enter-end="opacity-100 scale-100"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100 scale-100"
x-transition:leave-end="opacity-0 scale-95"

<!-- スライドダウン (ドロップダウン) -->
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0 -translate-y-2"
x-transition:enter-end="opacity-100 translate-y-0"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-start="opacity-100 translate-y-0"
x-transition:leave-end="opacity-0 -translate-y-2"
```

---

## 9. スクロールバー

### 9.1 カスタムスクロールバー

```css
/* チャットエリア、長いリストに適用 */
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

/* ダークモード */
.dark .custom-scrollbar::-webkit-scrollbar-thumb {
background: rgba(75, 85, 99, 0.6);
}

.dark .custom-scrollbar::-webkit-scrollbar-thumb:hover {
background: rgba(75, 85, 99, 0.8);
}

/* Firefox */
.custom-scrollbar {
scrollbar-width: thin;
scrollbar-color: rgba(156, 163, 175, 0.4) transparent;
}

.dark .custom-scrollbar {
scrollbar-color: rgba(75, 85, 99, 0.6) transparent;
}
```

---

## 10. フォーカス状態

### 10.1 フォーカスリング

```css
/* キーボードフォーカス時のみ表示 */
.focus-ring:focus-visible {
outline: none;
box-shadow: 0 0 0 2px var(--tw-ring-color, rgba(99, 102, 241, 1));
box-shadow: 0 0 0 2px white, 0 0 0 4px rgba(99, 102, 241, 1);
}

/* ダークモード */
.dark .focus-ring:focus-visible {
box-shadow: 0 0 0 2px rgb(17, 24, 39), 0 0 0 4px rgba(129, 140, 248, 1);
}

/* Tailwind クラス */
focus-visible:outline-none
focus-visible:ring-2
focus-visible:ring-indigo-500
focus-visible:ring-offset-2
dark:focus-visible:ring-offset-gray-900
```

### 10.2 入力フィールドのフォーカス

```css
/* テキスト入力 */
focus:ring-2 focus:ring-indigo-500 focus:border-transparent

/* エラー状態 */
focus:ring-2 focus:ring-red-500 focus:border-transparent
```

---

## 11. レスポンシブユーティリティ

### 11.1 表示切替

```html
<!-- モバイルのみ表示 -->
<div class="md:hidden">...</div>

<!-- デスクトップのみ表示 -->
<div class="hidden md:block">...</div>

<!-- テキスト短縮 (モバイル) -->
<span class="hidden sm:inline">フルテキスト</span>
<span class="sm:hidden">短縮</span>
```

### 11.2 レスポンシブ間隔

```html
<!-- モバイル: 小間隔、デスクトップ: 大間隔 -->
<div class="gap-3 md:gap-6">...</div>
<div class="p-4 md:p-6 lg:p-8">...</div>
<div class="space-y-4 md:space-y-6">...</div>
```

---

## 12. Markdown レンダリングスタイル

### 12.1 prose クラス設定

```css
/* レポート・会話ログ表示用 */
.prose-orchestra {
/* Tailwind Typography プラグイン互換の手動設定 */
max-width: none;
font-size: 0.875rem;
line-height: 1.625;
color: inherit;
}

.prose-orchestra h1 {
font-size: 1.5rem;
font-weight: 700;
margin-top: 2rem;
margin-bottom: 0.75rem;
padding-bottom: 0.5rem;
border-bottom: 1px solid rgba(156, 163, 175, 0.3);
}

.prose-orchestra h2 {
font-size: 1.25rem;
font-weight: 700;
margin-top: 1.5rem;
margin-bottom: 0.5rem;
}

.prose-orchestra h3 {
font-size: 1rem;
font-weight: 600;
margin-top: 1.25rem;
margin-bottom: 0.5rem;
}

.prose-orchestra p {
margin-top: 0.5rem;
margin-bottom: 0.5rem;
}

.prose-orchestra ul,
.prose-orchestra ol {
margin-top: 0.5rem;
margin-bottom: 0.5rem;
padding-left: 1.5rem;
}

.prose-orchestra li {
margin-top: 0.25rem;
margin-bottom: 0.25rem;
}

.prose-orchestra code {
background: rgba(156, 163, 175, 0.15);
padding: 0.125rem 0.375rem;
border-radius: 0.25rem;
font-size: 0.8em;
font-family: ui-monospace, monospace;
}

.prose-orchestra pre {
background: rgba(17, 24, 39, 0.95);
color: #e5e7eb;
padding: 1rem;
border-radius: 0.75rem;
overflow-x: auto;
margin: 1rem 0;
font-size: 0.8rem;
}

.prose-orchestra pre code {
background: none;
padding: 0;
color: inherit;
}

.prose-orchestra table {
width: 100%;
border-collapse: collapse;
margin: 1rem 0;
font-size: 0.8rem;
}

.prose-orchestra th,
.prose-orchestra td {
border: 1px solid rgba(156, 163, 175, 0.3);
padding: 0.5rem 0.75rem;
text-align: left;
}

.prose-orchestra th {
background: rgba(156, 163, 175, 0.1);
font-weight: 600;
}

.prose-orchestra blockquote {
border-left: 3px solid rgba(99, 102, 241, 0.5);
padding-left: 1rem;
margin: 1rem 0;
color: rgba(107, 114, 128, 1);
font-style: italic;
}

.prose-orchestra a {
color: rgba(99, 102, 241, 1);
text-decoration: underline;
}

.prose-orchestra hr {
margin: 1.5rem 0;
border-color: rgba(156, 163, 175, 0.3);
}

/* ダークモード */
.dark .prose-orchestra code {
background: rgba(75, 85, 99, 0.4);
}

.dark .prose-orchestra th {
background: rgba(75, 85, 99, 0.3);
}

.dark .prose-orchestra blockquote {
color: rgba(156, 163, 175, 1);
}

.dark .prose-orchestra a {
color: rgba(129, 140, 248, 1);
}
```

### 12.2 Markdown レンダリングヘルパー

```javascript
// web/static/js/markdown.js

/**
* Markdownテキストをサニタイズ済みHTMLに変換する。
*
* @param {string} md - Markdownテキスト
* @returns {string} サニタイズ済みHTML
*/
function renderMarkdown(md) {
if (!md) return '';

// marked 設定
marked.setOptions({
gfm: true,          // GitHub Flavored Markdown
breaks: false,       // 改行を <br> にしない
headerIds: false,    // ヘッダーIDを付与しない (XSS対策)
mangle: false,       // メールアドレスを難読化しない
});

// Markdown → HTML
const rawHtml = marked.parse(md);

// DOMPurify でサニタイズ
const cleanHtml = DOMPurify.sanitize(rawHtml, {
ALLOWED_TAGS: [
'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
'p', 'br', 'hr',
'ul', 'ol', 'li',
'strong', 'em', 'del', 'code', 'pre',
'blockquote',
'table', 'thead', 'tbody', 'tr', 'th', 'td',
'a', 'img',
'span', 'div',
],
ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class'],
ALLOW_DATA_ATTR: false,
});

return cleanHtml;
}
```

---

## 13. スケルトンローディング

### 13.1 スケルトンクラス

```css
.skeleton {
background: linear-gradient(
90deg,
rgba(156, 163, 175, 0.15) 0%,
rgba(156, 163, 175, 0.25) 50%,
rgba(156, 163, 175, 0.15) 100%
);
background-size: 200% 100%;
animation: shimmer 1.5s infinite;
border-radius: 0.5rem;
}

.dark .skeleton {
background: linear-gradient(
90deg,
rgba(75, 85, 99, 0.3) 0%,
rgba(75, 85, 99, 0.5) 50%,
rgba(75, 85, 99, 0.3) 100%
);
background-size: 200% 100%;
}
```

### 13.2 スケルトン使用例

```html
<!-- セッションカードのスケルトン -->
<template x-if="loading">
<div class="space-y-4">
<template x-for="i in 3" :key="i">
<div class="p-5 rounded-2xl border border-gray-200 dark:border-gray-700">
<div class="flex items-center gap-3 mb-3">
<div class="skeleton w-16 h-5"></div>
<div class="skeleton w-24 h-4"></div>
</div>
<div class="skeleton w-full h-4 mb-2"></div>
<div class="skeleton w-3/4 h-4 mb-3"></div>
<div class="flex gap-4">
<div class="skeleton w-12 h-3"></div>
<div class="skeleton w-12 h-3"></div>
<div class="skeleton w-12 h-3"></div>
</div>
</div>
</template>
</div>
</template>
```

---

## 14. custom.css 完全版

```css
/* ================================================
AI Orchestra — Custom CSS
================================================ */

/* === Animations === */
@keyframes fadeIn {
from { opacity: 0; }
to { opacity: 1; }
}
@keyframes slideUp {
from { opacity: 0; transform: translateY(8px); }
to { opacity: 1; transform: translateY(0); }
}
@keyframes slideDown {
from { opacity: 0; transform: translateY(-8px); }
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
@keyframes slideOutRight {
from { opacity: 1; transform: translateX(0); }
to { opacity: 0; transform: translateX(16px); }
}
@keyframes pulseGlow {
0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
50% { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
}
@keyframes shimmer {
0% { background-position: -200% 0; }
100% { background-position: 200% 0; }
}
@keyframes countUp {
from { opacity: 0; transform: translateY(10px); }
to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in { animation: fadeIn 300ms ease-out both; }
.animate-slide-up { animation: slideUp 400ms ease-out both; }
.animate-slide-down { animation: slideDown 400ms ease-out both; }
.animate-scale-in { animation: scaleIn 200ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.animate-slide-in-right { animation: slideInRight 300ms ease-out both; }
.animate-slide-out-right { animation: slideOutRight 200ms ease-in both; }
.animate-pulse-glow { animation: pulseGlow 2s infinite; }
.animate-count-up { animation: countUp 500ms ease-out both; }

.stagger-1 { animation-delay: 100ms; }
.stagger-2 { animation-delay: 200ms; }
.stagger-3 { animation-delay: 300ms; }
.stagger-4 { animation-delay: 400ms; }
.stagger-5 { animation-delay: 500ms; }
.stagger-6 { animation-delay: 600ms; }
.stagger-7 { animation-delay: 700ms; }
.stagger-8 { animation-delay: 800ms; }

/* === Card Glow === */
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

/* === Scrollbar === */
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb {
background: rgba(156, 163, 175, 0.4);
border-radius: 3px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
background: rgba(156, 163, 175, 0.6);
}
.dark .custom-scrollbar::-webkit-scrollbar-thumb {
background: rgba(75, 85, 99, 0.6);
}
.dark .custom-scrollbar::-webkit-scrollbar-thumb:hover {
background: rgba(75, 85, 99, 0.8);
}
.custom-scrollbar { scrollbar-width: thin; scrollbar-color: rgba(156, 163, 175, 0.4) transparent; }
.dark .custom-scrollbar { scrollbar-color: rgba(75, 85, 99, 0.6) transparent; }

/* === Skeleton === */
.skeleton {
background: linear-gradient(90deg, rgba(156,163,175,0.15) 0%, rgba(156,163,175,0.25) 50%, rgba(156,163,175,0.15) 100%);
background-size: 200% 100%;
animation: shimmer 1.5s infinite;
border-radius: 0.5rem;
}
.dark .skeleton {
background: linear-gradient(90deg, rgba(75,85,99,0.3) 0%, rgba(75,85,99,0.5) 50%, rgba(75,85,99,0.3) 100%);
background-size: 200% 100%;
}

/* === Focus Ring === */
.focus-ring:focus-visible {
outline: none;
box-shadow: 0 0 0 2px white, 0 0 0 4px rgba(99, 102, 241, 1);
}
.dark .focus-ring:focus-visible {
box-shadow: 0 0 0 2px rgb(17, 24, 39), 0 0 0 4px rgba(129, 140, 248, 1);
}

/* === Nav Links === */
.nav-link {
@apply text-sm font-medium text-gray-600 dark:text-gray-300
hover:text-indigo-600 dark:hover:text-indigo-400
transition-colors px-3 py-2 rounded-lg;
}
.nav-link-active {
@apply text-indigo-600 dark:text-indigo-400
bg-indigo-50 dark:bg-indigo-900/20;
}
.mobile-nav-link {
@apply px-4 py-3 rounded-lg text-gray-700 dark:text-gray-200
hover:bg-gray-100 dark:hover:bg-gray-800 transition;
}

/* === Prose (Markdown) === */
.prose-orchestra { max-width: none; font-size: 0.875rem; line-height: 1.625; color: inherit; }
.prose-orchestra h1 { font-size: 1.5rem; font-weight: 700; margin-top: 2rem; margin-bottom: 0.75rem; padding-bottom: 0.5rem; border-bottom: 1px solid rgba(156,163,175,0.3); }
.prose-orchestra h2 { font-size: 1.25rem; font-weight: 700; margin-top: 1.5rem; margin-bottom: 0.5rem; }
.prose-orchestra h3 { font-size: 1rem; font-weight: 600; margin-top: 1.25rem; margin-bottom: 0.5rem; }
.prose-orchestra p { margin-top: 0.5rem; margin-bottom: 0.5rem; }
.prose-orchestra ul, .prose-orchestra ol { margin-top: 0.5rem; margin-bottom: 0.5rem; padding-left: 1.5rem; }
.prose-orchestra li { margin-top: 0.25rem; margin-bottom: 0.25rem; }
.prose-orchestra code { background: rgba(156,163,175,0.15); padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.8em; font-family: ui-monospace, monospace; }
.prose-orchestra pre { background: rgba(17,24,39,0.95); color: #e5e7eb; padding: 1rem; border-radius: 0.75rem; overflow-x: auto; margin: 1rem 0; font-size: 0.8rem; }
.prose-orchestra pre code { background: none; padding: 0; color: inherit; }
.prose-orchestra table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.8rem; }
.prose-orchestra th, .prose-orchestra td { border: 1px solid rgba(156,163,175,0.3); padding: 0.5rem 0.75rem; text-align: left; }
.prose-orchestra th { background: rgba(156,163,175,0.1); font-weight: 600; }
.prose-orchestra blockquote { border-left: 3px solid rgba(99,102,241,0.5); padding-left: 1rem; margin: 1rem 0; color: rgba(107,114,128,1); font-style: italic; }
.prose-orchestra a { color: rgba(99,102,241,1); text-decoration: underline; }
.prose-orchestra hr { margin: 1.5rem 0; border-color: rgba(156,163,175,0.3); }
.dark .prose-orchestra code { background: rgba(75,85,99,0.4); }
.dark .prose-orchestra th { background: rgba(75,85,99,0.3); }
.dark .prose-orchestra blockquote { color: rgba(156,163,175,1); }
.dark .prose-orchestra a { color: rgba(129,140,248,1); }

/* === Motion Reduced === */
@media (prefers-reduced-motion: reduce) {
*, *::before, *::after {
animation-duration: 0.01ms !important;
animation-iteration-count: 1 !important;
transition-duration: 0.01ms !important;
}
}
```

---

## 15. デザイントークンまとめ

```
┌─────────────────────────────────────────────────────────────┐
│  Design Tokens Summary                                      │
├─────────────────────────────────────────────────────────────┤
│  Colors:                                                    │
│    Primary: indigo-600 / indigo-400                         │
│    Surface: white / gray-800                                │
│    Border: gray-200 / gray-700                              │
│    Text: gray-900 / gray-100                                │
│                                                             │
│  Spacing:                                                   │
│    Section gap: 32px (mb-8)                                 │
│    Card gap: 16px (gap-4)                                   │
│    Content gap: 12px (space-y-3)                            │
│                                                             │
│  Radius:                                                    │
│    Card: 16px (rounded-2xl)                                 │
│    Input: 12px (rounded-xl)                                 │
│    Badge: 8px or full                                       │
│                                                             │
│  Shadow:                                                    │
│    Card: shadow-sm                                          │
│    Hover: shadow-md                                         │
│    Float: shadow-lg                                         │
│                                                             │
│  Animation:                                                 │
│    Enter: 200-400ms ease-out                                │
│    Leave: 150-200ms ease-in                                 │
│    Stagger: 100ms increments                                │
│                                                             │
│  Typography:                                                │
│    Title: 2xl-3xl bold                                      │
│    Body: sm (14px)                                          │
│    Meta: xs (12px)                                          │
│    Mono: font-mono (timer, code)                            │
└─────────────────────────────────────────────────────────────┘
