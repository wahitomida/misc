# AI Orchestra — 機能仕様書 (UI設計用)

> 作成日: 2026-06-22
> 目的: Web UI 構築のための機能・仕様の全容整理

---

## Part 1: AI Orchestra 全機能一覧

### 1. システム概要

AI Orchestra は、複数のAIエージェントが役割ベースで議論・レビューを行うマルチエージェントオーケストレーションシステム。
現在は CLI (typer) で操作しているが、Web UI に移行予定。

---

### 2. コマンド (= UI上の操作モード)

#### 2.1 `idea` — 技術議論 (アイデアブラッシュアップ)

| 項目 | 内容 |
|------|------|
| **目的** | 技術テーマについてAIが多角的に議論し、洞察・仮説・実験計画を導出 |
| **入力** | ユーザーが自由テキストでテーマを入力 |
| **出力** | セッションディレクトリに7ファイル (後述) |

**パラメータ (UIで設定可能にすべきもの):**

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| prompt (テーマ) | — | 必須。議論テーマのテキスト (5〜5000文字) |
| planner_model | `gpt-5.4` | Phase 1 計画立案モデル |
| conductor_model | `gpt-4.1` | Phase 2 進行管理モデル |
| synth_model | `gpt-5.4` | Phase 3 統合モデル |
| time_limit | `300` 秒 | **ユーザーが決める議論時間** |
| max_agents | `5` | 最大参加AI数 (2〜8) |
| expertise | `intermediate` | `beginner` / `intermediate` / `expert` |
| follow_up | `None` | 継続するセッションID |
| attach | `None` | 添付ファイル (複数可) |
| focus_hypothesis | `None` | 重点検証する仮説ID (複数可) |
| output_dir | `./output` | 出力先 |
| no_confirm | `False` | 計画確認をスキップ |

**実行フロー (7ステップ):**

```
① 入力バリデーション + follow-up読み込み
② シナリオ自動検出 (algorithm_design / experiment_planning / paper_discussion)
③ Phase 1: 計画立案 (Orchestrator → ODSC + AI選定 + ラウンド計画)
④ ユーザー確認 (計画を見せて Y/n)
⑤ Phase 2: 議論進行 (Conductor → 時間制限まで全ラウンド完走)
⑥ Phase 3: 統合・評価 (Synthesizer → 自己/他者/指揮者評価 + レポート)
⑦ 出力生成 + フィードバック蓄積
```

---

#### 2.2 `review` — コードレビュー

| 項目 | 内容 |
|------|------|
| **目的** | 研究コードを6観点から多角的にレビューし、修正指示書を生成 |
| **入力** | レビュー対象ディレクトリのパス |
| **出力** | レポート + vibe_coding_prompt.md (AIコーディング向け修正指示書) |

**パラメータ:**

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| target | — | 必須。レビュー対象ディレクトリ |
| planner_model | `gpt-5.4` | 構造判定モデル |
| conductor_model | `gpt-4.1` | 全体会議の指揮者モデル |
| synth_model | `gpt-5.4` | レポート生成モデル |
| time_limit | `600` 秒 | 制限時間 |
| max_agents | `6` | 最大パートリーダー数 |
| focus | `all` | 重点モード (`all/pre_submission/performance/structure/handover/algorithm`) |
| ignore | `None` | 追加ignoreパターン (カンマ区切り) |
| output_dir | `./output` | 出力先 |

**実行フロー (5 Phase):**

```
Phase 1: 構造スキャン (FolderScanner でファイルツリー構築)
Phase 2: 個別調査 (6観点のパートリーダーが並列でコード分析)
Phase 3: 相互質問 (パートリーダー間で質疑応答、max 5往復)
Phase 4: 全体会議 (3ラウンド: 課題報告→深掘り→合意形成)
Phase 5: レポート生成 (report.md + vibe_coding_prompt.md)
```

**6つの観点:**

| 観点 | 担当ロール | 分析対象 |
|------|-----------|---------|
| algorithm | theorist | 数式↔コード対応、境界条件、数値安定性 |
| reproducibility | experimentalist | seed固定、config管理、環境依存 |
| performance | implementer | ボトルネック、メモリ、並列化 |
| structure | code_architect | モジュール分割、DRY、SOLID |
| readability | code_reviewer | 命名、docstring、型ヒント |
| results | experimentalist | 出力妥当性、論文整合、テスト |

---

#### 2.3 `list-roles` — ロール一覧表示

利用可能なAIロールの一覧を表示。詳細モードで性格・統計・弱み等も表示可能。

---

#### 2.4 `history` — セッション履歴一覧

| パラメータ | 説明 |
|-----------|------|
| `--chain` | フォローアップチェーンを表示 |
| `--limit` | 表示件数 (デフォルト10) |
| `--type` | idea / review でフィルタ |

---

#### 2.5 `replay` — 過去セッション再表示

セッションIDを指定して過去の結果を再表示。セクション指定可能:
- `conversation` — 全会話ログ
- `report` — レポート
- `evaluation` — 評価結果
- `summary` — 要約

---

#### 2.6 `role-stats` — ロール別統計

ロール別のパフォーマンス統計 (セッション数、自己評価平均、他者評価平均、トレンド)。

---

### 3. コア機能の詳細

#### 3.1 議論制御の仕組み

| 項目 | 仕様 |
|------|------|
| **時間管理** | ユーザー指定の制限時間を使い切る。収束による早期終了は無効。時間切れのみで終了 |
| **ラウンド数** | 2〜5ラウンド (時間に応じ。細かく切りすぎない) |
| **ラウンド結論** | 各ラウンド末尾で主導者 (speakers[0]) が他者の意見を踏まえて結論を出す |
| **Pivot** | 議論停滞検知時に方向転換指示を生成し次ラウンドに注入 |
| **堂々巡り検知** | 直近4発言の内容重複を検知 → 強制的に新論点へ誘導 |
| **同意しすぎ検知** | 全員が同じ方向に偏っているとき → 反対意見を要求 |

#### 3.2 発言パターン

| パターン | 動作 | 停止条件 |
|---------|------|---------|
| `one_shot` | speakers順に各1回発言 | speakers数で固定 |
| `ping_pong` | 2者が交互に応答 | 3往復 (6発言) |
| `free_talk` | LLMが毎回次発言者を動的決定 | 最大8発言 |

#### 3.3 発言スタイル制御

- 1回の発言: 50〜150文字 (チャットテンポ)
- 論文口調禁止、数式は必要最小限
- 会話トーン: `brainstorming` (デフォルト) / `lab_discussion` / `formal` / `casual` / `debate`
- expertise別に文字数・語彙レベルを調整

#### 3.4 評価システム (Phase 3)

| 評価種別 | 内容 |
|---------|------|
| **自己評価** | 各AI: 4観点×5点満点 + reasoning + 貢献/やり残し |
| **他者評価** | 各AI → 他全員: 5点 + コメント |
| **指揮者評価** | 全体品質 (5点)、MVP選出、各AIへのフィードバック、ODSC達成度判定 |

#### 3.5 フォローアップ (連続議論)

- 前セッションの仮説テーブルを引き継いで深掘り
- 仮説状態: 🔲未検証 / ✅確認 / ❌棄却 / 🔄修正
- 添付ファイル対応 (最大10,000文字/ファイル)
- チェーン深度: 最大10

#### 3.6 フィードバックシステム

- ロールYAMLに最大10件のセッション評価を蓄積
- トレンド判定: improving / declining / stable
- 次回セッション時にsystem promptに改善依頼を注入
- 下降傾向時はルール強化

---

### 4. ロール一覧

| role_id | 表示名 | 絵文字 | 専門 |
|---------|--------|--------|------|
| `theorist` | 理論屋 | 🧮 | 数学的定式化、計算量解析、収束証明 |
| `experimentalist` | 実験屋 | 🔬 | 実験設計、検証計画、再現性 |
| `implementer` | 実装屋 | 🤖 | 実装可能性、性能、並列化 |
| `literature` | 文献屋 | 📚 | 関連研究、引用、先行事例 |
| `devil` | 穴探し | 😈 | 反論、弱点指摘、限界指摘 |
| `bird_eye` | 鳥の目 | 🎯 | 俯瞰、方向修正、全体整合 |
| `code_architect` | 設計リーダー | 📐 | モジュール分割、DRY、SOLID |
| `code_reviewer` | 可読性リーダー | 📝 | 命名、docstring、型ヒント |

---

### 5. 出力ファイル

セッションごとに `output/{YYYYMMDD_HHMMSS}_{type}/` に生成:

| ファイル | 形式 | 内容 |
|---------|------|------|
| `session_meta.json` | JSON | セッションID、日時、パラメータ、統計 |
| `discussion.json` | JSON | 全ラウンドログ (発言/tokens/duration/convergence) |
| `full_conversation.md` | Markdown | 全会話の人間可読な台本 (舞台裏・結論・評価含む) |
| `report.md` | Markdown | 議論結果レポート (insight/仮説/実験計画) |
| `evaluation.md` | Markdown | 自己/他者/指揮者評価の全結果 |
| `summary.txt` | テキスト | 1ページ要約 |
| `vibe_coding_prompt.md` | Markdown | (review のみ) AIコーディング向け修正指示書 |

---

### 6. 設定体系

| カテゴリ | 主要パラメータ |
|---------|--------------|
| **時間** | idea=300s, review=600s, min=60s, max=1800s |
| **エージェント数** | idea_max=5, review_max=6, min=2, max=8 |
| **収束** | threshold=0.85, stagnation_window=3 |
| **会話スタイル** | brainstorming / lab_discussion / formal / casual / debate |
| **発言長** | min=50, max=150, absolute_max=200文字 |
| **API** | daily_limit=10000, retry_max=3, モデル別timeout |
| **フィードバック** | max_history=10, trend_window=3 |

---

### 7. 進捗表示 (Rich Progress)

現在CLI上で Rich の PhaseProgress バーを表示:
- `idea`: 4フェーズ (計画→議論→統合→出力)
- `review`: 5フェーズ (スキャン→調査→相互質問→会議→レポート)

---

### 8. 将来予定 (UI化で実現したいもの)

| 機能 | 詳細 |
|------|------|
| リアルタイム議論表示 | SSE/WebSocketで議論発言をストリーミング表示 |
| 人間介入 | 議論途中でユーザーがコメント・方向修正を投入 |
| ロールカスタマイズ | UIから新ロール追加 (例: 孫正義AI、ベゾスAI) |
| 計画の対話的編集 | Phase 1 の計画をUIで修正してから Phase 2 開始 |
| セッション比較 | 複数セッションの結果を並べて比較 |
| エクスポート | PDF / Notion / Google Docs 出力 |

---

---

## Part 2: exhibit の UI 仕様 (参考実装)

### 1. テクノロジースタック

| レイヤー | 技術 |
|---------|------|
| **Backend** | FastAPI (Python) + Uvicorn |
| **テンプレート** | Jinja2 |
| **フロントエンド** | Alpine.js 3.x (CDN) |
| **CSS** | Tailwind CSS (CDN) |
| **チャート** | Chart.js 4 + D3.js 7 |
| **Markdown** | marked + DOMPurify |
| **リアルタイム** | SSE (Server-Sent Events) |
| **AI** | Vertex AI (Gemini 2.5 Flash) |

---

### 2. ページ構成

| URL | 機能 |
|-----|------|
| `/` | Hero ランディング + モード選択カード |
| `/pre-research` | 事前調査ウィザード (4ステップ) |
| `/post-report` | 事後報告ウィザード (4ステップ) |
| `/analysis` | 分析ダッシュボード (7種チャート) |
| `/history` | 履歴一覧・再開・削除 |

---

### 3. レイアウトパターン

#### 3.1 ベースレイアウト

```
┌────────────────────────────────────────────────────┐
│ [Header] 固定ナビバー (backdrop-blur)              │
│  ロゴ | ナビリンク... | 🌙/☀️ ダークモードトグル   │
├────────────────────────────────────────────────────┤
│                                                    │
│  [Main Content] (max-w-[1440px] mx-auto)          │
│                                                    │
├────────────────────────────────────────────────────┤
│ [Help FAB] 左下固定                                │
│ [Toast Container] 右上固定                         │
└────────────────────────────────────────────────────┘
```

#### 3.2 ウィザードレイアウト

```
┌────────────────────────────────────────────────────┐
│  [Step Indicator] ● 1 ─── ● 2 ─── ● 3 ─── ● 4   │
├────────────────────────────────────────────────────┤
│  ┌──── 2/5幅 ──────────┐ ┌──── 3/5幅 ────────┐   │
│  │  入力フォーム        │ │ プレビュー/結果    │   │
│  │  (アコーディオン)    │ │ (sticky top-20)   │   │
│  └──────────────────────┘ └────────────────────┘   │
└────────────────────────────────────────────────────┘
```

#### 3.3 Hero ページ

```
┌────────────────────────────────────────────────────┐
│        グラデーションテキスト見出し                  │
│        サブ説明文                                   │
│                                                    │
│   ┌── カード ──┐    ┌── カード ──┐                 │
│   │ アイコン    │    │ アイコン    │                 │
│   │ タイトル    │    │ タイトル    │                 │
│   │ 説明       │    │ 説明       │                 │
│   │ → 開始     │    │ → 開始     │                 │
│   └────────────┘    └────────────┘                 │
│                                                    │
│   (stagger animation で順次表示)                    │
└────────────────────────────────────────────────────┘
```

---

### 4. API設計パターン

| パターン | 用途 | 実装 |
|---------|------|------|
| **REST (JSON)** | CRUD操作、軽量リクエスト | `POST /api/xxx` → JSON response |
| **SSE Stream** | 長時間処理の進捗表示 | `POST /api/research` → `text/event-stream` |
| **HTML Template** | ページ描画 | `GET /path` → Jinja2 rendered HTML |

**SSE イベント形式:**
```json
{"type": "start", "index": 0, "company": "企業名", "completed": 0, "total": 5}
{"type": "result", "index": 0, "status": "success", "data": {...}}
{"type": "error", "index": 1, "error": "タイムアウト"}
{"type": "done", "completed": 5, "total": 5, "elapsed_sec": 42.3}
```

---

### 5. フロントエンド設計

#### 5.1 状態管理: Alpine.js

```javascript
// ページごとに独立したコンポーネント関数
function preResearch() {
  return {
    step: 1,            // ステップ番号
    loading: false,     // ローディング状態
    results: [],        // 結果配列
    // ... リアクティブ変数
    async submit() { /* API呼び出し */ },
    restore() { /* localStorage復元 */ }
  }
}
```

#### 5.2 ダークモード

- Tailwind `darkMode: 'class'` 方式
- `localStorage.darkMode` で永続化
- OS設定 fallback 対応
- head 内スクリプトで白フラッシュ防止

#### 5.3 リアルタイム更新 (SSE)

```javascript
const es = new EventSource('/api/research', { method: 'POST', body: data });
es.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch(msg.type) {
    case 'start': this.progress = msg; break;
    case 'result': this.results.push(msg.data); break;
    case 'done': es.close(); break;
  }
};
```

#### 5.4 アニメーション

| 種類 | CSS |
|------|-----|
| フェードイン | `opacity 0→1 + translateY(8px→0)` 300ms |
| スライドアップ | `opacity 0→1 + translateY(16px→0)` 400ms |
| スケールイン | `scale(0→1)` バウンス 200ms |
| 順次表示 | `stagger-{1-5}`: animation-delay 100ms刻み |
| トースト | 右スライドイン/アウト |

---

### 6. UI コンポーネント

| コンポーネント | 仕様 |
|---------------|------|
| **ヘッダー** | 固定、backdrop-blur、ロゴ + ナビ + ダークモード |
| **ステップインジケーター** | 番号 + ラベル + 接続ライン、クリックジャンプ |
| **カード** | `rounded-2xl p-6`、ホバーglow効果 |
| **アコーディオン** | `<details>/<summary>` + chevron回転 |
| **フォーム** | `rounded-xl`、focus ring、タグピル |
| **プログレス** | グラデーションバー + ステータス行 + 経過時間 |
| **トースト** | 右上固定、4色 (success/error/warning/info)、3秒自動消去 |
| **モーダル** | backdrop-blur + ESC閉じ + 背景クリック閉じ |
| **チャート** | Chart.js (棒/ドーナツ/バブル) + D3 (ネットワーク/ワードクラウド) |

---

### 7. データ永続化

| 方式 | 用途 |
|------|------|
| `localStorage` | セッション復元、ダークモード設定 |
| `sessionStorage` | 分析データの一時保存 |
| JSONファイル (`data/users/`) | レポート保存 |

---

### 8. デプロイ

```
serve.bat → uvicorn main:app --host 0.0.0.0 --port 8080
setup_firewall.bat → ポート8080のファイアウォール開放
start.bat → 仮想環境有効化 + サーバー起動
```

---

---

## Part 3: Orchestra UI への示唆

### exhibit から流用すべきパターン

| パターン | 理由 |
|---------|------|
| FastAPI + Jinja2 + Alpine.js | 同じ構成で素早く構築可能 |
| Tailwind CSS (CDN) | デザインの統一・高速開発 |
| SSE で議論発言をストリーミング | 議論のリアルタイム表示に最適 |
| ステップインジケーター | idea/review の多段階フローに適合 |
| ダークモード | ユーザー体験 |
| localStorage 復元 | 入力途中の状態保存 |
| トースト通知 | エラー表示 (進捗バーのみ + エラーのみ出力の方針と一致) |

### Orchestra 固有のUI要件

| 要件 | 詳細 |
|------|------|
| **議論のリアルタイム表示** | 各AI発言がSSEで1件ずつ流れてくるチャットUI |
| **結論の強調表示** | 各ラウンド末の「🎯結論」を視覚的に目立たせる |
| **計画の承認/編集UI** | Phase 1 の計画表示 → 修正 → 確認 → 実行 |
| **タイマー表示** | ユーザー設定の時間制限をカウントダウン表示 |
| **評価ダッシュボード** | ランキング表、MVP、議論品質スコア |
| **セッション履歴** | 過去結果の閲覧 + follow-up開始 |
| **ロールカスタマイズ** | 新ロール追加UI (将来: 有名経営者AIなど) |

---

*以上*
