# AI Orchestra — UI 全体設計

> Web UI の技術方針・設計原則・スタック定義・全体構成

---

## 1. 設計思想

### 1.1 コアコンセプト

AI Orchestra の Web UI は「**議論の劇場**」をメタファーとする。
ユーザーは観客席から舞台を眺めるように、AI同士の議論をリアルタイムで観察し、
必要に応じて介入（将来機能）できる。

```
┌─────────────────────────────────────────────────┐
│  🎭 劇場のメタファー                             │
│                                                 │
│  舞台    = チャットエリア (AI同士の議論)          │
│  台本    = 計画 (ODSC + ラウンド構成)            │
│  演出家  = Conductor (進行管理)                  │
│  観客席  = ユーザー (観察 + フォローアップ)       │
│  楽屋裏  = 評価・フィードバック                   │
│  パンフ  = レポート・要約                        │
└─────────────────────────────────────────────────┘
```

### 1.2 設計原則

| # | 原則 | 説明 | 具体例 |
|---|------|------|--------|
| 1 | **サーバーレンダリング優先** | 初回表示は Jinja2 で完結。JS は状態管理とリアルタイム更新のみ | ページ遷移は従来のHTTPリクエスト |
| 2 | **段階的開示** | 情報を必要なときに必要な分だけ見せる | オプション設定はアコーディオンで隠す |
| 3 | **リアルタイム体験** | 議論の臨場感を最大化する | SSEで1発言ずつ流れるチャットUI |
| 4 | **結果へのアクセス最短化** | ユーザーが欲しい情報に最短で到達 | レポートをタブ切替で即表示 |
| 5 | **失敗に寛容** | エラー時に可能な限りデータを救う | 部分結果の保存、再開機能 |
| 6 | **ダークモード標準** | 全ページで light/dark 両対応 | OS設定をデフォルト尊重 |
| 7 | **モバイル対応** | 全ページがモバイルで閲覧可能 | Tailwind のレスポンシブ設計 |
| 8 | **ビルドレス** | npm / webpack 不要。CDN + 静的ファイルのみ | デプロイが `uvicorn` 1コマンド |

---

## 2. 技術スタック

### 2.1 サーバーサイド

| 技術 | バージョン | 役割 | 選定理由 |
|------|-----------|------|---------|
| FastAPI | 0.100+ | Web フレームワーク | async対応、型安全、自動ドキュメント |
| Uvicorn | 0.23+ | ASGI サーバー | 軽量、高速、reload対応 |
| Jinja2 | 3.1+ | テンプレートエンジン | FastAPIネイティブ統合 |
| Python | 3.10+ | サーバー言語 | プロジェクト全体と統一 |

### 2.2 フロントエンド

| 技術 | バージョン | 役割 | 選定理由 |
|------|-----------|------|---------|
| Alpine.js | 3.x (CDN) | 状態管理・リアクティブUI | 軽量(15KB)、学習コスト低、HTMLに宣言的に記述 |
| Tailwind CSS | 3.x (Play CDN) | スタイリング | ユーティリティファースト、ダークモード内蔵 |
| marked.js | 12.x (CDN) | Markdownレンダリング | 高速、拡張可能 |
| DOMPurify | 3.x (CDN) | HTMLサニタイズ | XSS防止の定番 |
| Chart.js | 4.x (CDN) | チャート描画 | 統計表示用、軽量 |

### 2.3 通信

| 方式 | 用途 | 実装 |
|------|------|------|
| REST (JSON) | CRUD操作、軽量リクエスト | `fetch()` → JSON |
| SSE (POST streaming) | 議論のリアルタイム配信 | `fetch()` + `ReadableStream` |
| ファイルDL | レポートダウンロード | `<a href>` / `fetch()` → Blob |

### 2.4 なぜこの構成か

```
✅ ビルドステップ不要 — CDN利用で npm/webpack 不要
✅ Python開発者が即座に理解・修正可能
✅ 超軽量 — Alpine.js ≈ 15KB, 全CDN合計 < 500KB
✅ SSR + SPA のいいとこ取り — 初回は高速SSR、以降は対話的
✅ デプロイ簡素 — uvicorn 1コマンドで起動
✅ Orchestraのコアエンジンと同じPythonプロセス内で動作

❌ 大規模SPAほどのコンポーネント再利用性はない
❌ TypeScriptの型安全性がない
→ プロジェクト規模(10ページ未満)的に十分なトレードオフ
```

---

## 3. ディレクトリ構造

```
web/
├── app.py                      # FastAPI アプリケーション定義
│                               #   - Jinja2テンプレート設定
│                               #   - StaticFilesマウント
│                               #   - ミドルウェア (CORS, エラーハンドラ)
│                               #   - ルーター登録
│
├── deps.py                     # 依存注入
│                               #   - get_settings() → Settings
│                               #   - get_api_client() → ResilientAPIClient
│                               #   - get_role_manager() → RoleManager
│                               #   - get_feedback_manager() → FeedbackManager
│
├── routes/
│   ├── __init__.py
│   ├── pages.py                # HTMLページルーティング
│   │                           #   GET / → home.html
│   │                           #   GET /idea → idea.html
│   │                           #   GET /review → review.html
│   │                           #   GET /history → history.html
│   │                           #   GET /replay/{id} → replay.html
│   │                           #   GET /roles → roles.html
│   │
│   ├── api_idea.py             # Idea API
│   │                           #   POST /api/idea/plan → JSON
│   │                           #   POST /api/idea/stream → SSE
│   │
│   ├── api_review.py           # Review API
│   │                           #   POST /api/review/plan → JSON
│   │                           #   POST /api/review/stream → SSE
│   │
│   ├── api_sessions.py         # Sessions API
│   │                           #   GET /api/sessions → 一覧
│   │                           #   GET /api/sessions/recent → 最新N件
│   │                           #   GET /api/sessions/{id} → 詳細
│   │                           #   GET /api/sessions/{id}/content → 全コンテンツ
│   │                           #   GET /api/sessions/{id}/download → DL
│   │                           #   DELETE /api/sessions/{id} → 削除
│   │
│   └── api_roles.py            # Roles API
│                               #   GET /api/roles → 一覧
│                               #   GET /api/roles/{id} → 詳細
│                               #   GET /api/roles/{id}/stats → 統計
│
├── templates/
│   ├── base.html               # ベースレイアウト
│   │                           #   - <head> (CDN, meta, darkmode初期化)
│   │                           #   - ヘッダー (ナビバー)
│   │                           #   - {% block content %}
│   │                           #   - トーストコンテナ
│   │                           #   - 共通スクリプト
│   │
│   ├── partials/               # 再利用パーシャル ({% include %})
│   │   ├── header.html         # 固定ナビバー (backdrop-blur)
│   │   ├── toast.html          # トースト通知システム
│   │   ├── modal.html          # 汎用モーダルダイアログ
│   │   ├── step_indicator.html # ウィザードステップ表示
│   │   └── loading.html        # ローディングオーバーレイ
│   │
│   ├── pages/                  # ページテンプレート ({% extends "base.html" %})
│   │   ├── home.html           # Hero + モード選択カード
│   │   ├── idea.html           # 4ステップウィザード
│   │   ├── review.html         # 5ステップウィザード
│   │   ├── history.html        # セッション一覧 + フィルタ
│   │   ├── replay.html         # セッション内容表示
│   │   └── roles.html          # ロールカード + 詳細パネル
│   │
│   └── components/             # UIコンポーネント ({% include %})
│       ├── chat_bubble.html    # 議論発言バブル (通常/結論/システム)
│       ├── plan_card.html      # 計画表示 (ODSC + ラウンド)
│       ├── timer.html          # カウントダウン + プログレスバー
│       ├── evaluation.html     # 評価スコア表示
│       ├── hypothesis_table.html # 仮説テーブル (インタラクティブ)
│       ├── file_drop.html      # ファイルドラッグ&ドロップ
│       └── agent_badge.html    # AIエージェントバッジ
│
├── static/
│   ├── css/
│   │   └── custom.css          # カスタムCSS
│   │                           #   - アニメーション定義
│   │                           #   - カードglow効果
│   │                           #   - チャットバブルスタイル
│   │                           #   - Tailwind拡張
│   │
│   └── js/
│       ├── app.js              # 共通ユーティリティ
│       │                       #   - toast(msg, type)
│       │                       #   - formatTime(sec)
│       │                       #   - formatDate(iso)
│       │                       #   - debounce(fn, ms)
│       │                       #   - renderMarkdown(md) → sanitized HTML
│       │
│       ├── sse.js              # OrchestraSSE クラス
│       │                       #   - POST SSEストリーミング
│       │                       #   - イベント分配
│       │                       #   - abort制御
│       │
│       ├── dark-mode.js        # ダークモード
│       │                       #   - 初期化 (白フラッシュ防止)
│       │                       #   - トグル + 永続化
│       │
│       └── markdown.js         # Markdownレンダリング
│                               #   - marked設定 (GFM, tables)
│                               #   - DOMPurifyサニタイズ
│                               #   - コードブロックハイライト
│
└── __init__.py
```

---

## 4. ページマップとユーザーフロー

### 4.1 全体マップ

```
                         ┌──────────┐
                         │  / Home  │
                         └────┬─────┘
                     ┌────────┼────────┐
                     ▼        ▼        ▼
              ┌──────────┐ ┌───────┐ ┌──────────┐
              │ /idea    │ │/review│ │ /history │
              │(4 steps) │ │(5 st) │ │          │
              └────┬─────┘ └───┬───┘ └────┬─────┘
                   │           │          │
                   ▼           ▼          ▼
              結果表示     結果表示   ┌──────────┐
                   │           │    │ /replay  │
                   │           │    │  /{id}   │
                   ▼           ▼    └──────────┘
              ┌───────────────────┐
              │  Follow-up       │
              │  (→ /idea に戻る) │
              └───────────────────┘

              ┌──────────┐
              │  /roles  │ (独立ページ)
              └──────────┘
```

### 4.2 Idea 議論フロー (メインユースケース)

```
Step 1: 入力          Step 2: 計画確認      Step 3: 議論        Step 4: 結果
┌───────────┐        ┌───────────┐        ┌───────────┐      ┌───────────┐
│ テーマ入力  │ ──→   │ ODSC表示   │ ──→   │ リアルタイム│ ──→  │ レポート   │
│ 設定調整   │        │ AI一覧    │        │ チャット   │      │ 評価      │
│            │        │ ラウンド計画│        │ タイマー   │      │ 仮説      │
│ [計画する] │        │ [開始する] │        │ 進捗      │      │ [DL/FU]  │
└───────────┘        └───────────┘        └───────────┘      └───────────┘
     │                     │                    │                   │
     │  POST               │  POST              │  SSE events       │
     │  /api/idea/plan     │  /api/idea/stream  │  (real-time)      │
     ▼                     ▼                    ▼                   ▼
  [Orchestrator]        [Conductor]          [Agent.speak()]    [Synthesizer]
```

---

## 5. 状態管理方針

### 5.1 Alpine.js コンポーネント設計

```javascript
/**
 * 各ページに1つの Alpine コンポーネント関数を定義する。
 * グローバル状態は持たない。ページ間通信は URL パラメータ or localStorage。
 */
function ideaPage() {
  return {
    // === Reactive State ===
    step: 1,                    // 現在のステップ (1-4)
    prompt: '',                 // テーマ入力
    settings: { ... },          // 設定値
    plan: null,                 // Phase 1 結果
    utterances: [],             // 議論発言リスト
    result: null,               // 最終結果

    // === Computed ===
    get isValid() { ... },      // バリデーション
    get progress() { ... },     // 進捗率

    // === Methods ===
    async submitPlan() { ... }, // API呼び出し
    async start() { ... },      // SSE開始

    // === Lifecycle ===
    init() { this.restore(); }, // ページ読み込み時
  };
}
```

### 5.2 状態の保存先

| データ種別 | 保存先 | ライフサイクル |
|-----------|--------|-------------|
| フォーム入力 (テーマ、設定) | `localStorage` | ブラウザ永続 (手動クリアまで) |
| ダークモード | `localStorage` | ブラウザ永続 |
| 議論実行中の状態 | Alpine.js メモリ | ページ表示中のみ |
| セッション結果 | サーバー `output/` | 永続 (ユーザー削除まで) |
| ページ間パラメータ | URL query / hash | 遷移時のみ |

### 5.3 localStorage キー一覧

| キー | 型 | 内容 |
|------|-----|------|
| `darkMode` | `"true"/"false"` | ダークモード設定 |
| `idea_prompt` | `string` | 最後に入力したテーマ |
| `idea_settings` | `JSON string` | 設定値 (モデル、時間制限等) |
| `review_target` | `string` | 最後に指定したパス |
| `review_settings` | `JSON string` | 設定値 |

---

## 6. レスポンシブ設計

### 6.1 ブレークポイント

```
Mobile:  < 768px  (default)
Tablet:  768px+   (md:)
Desktop: 1024px+  (lg:)
Wide:    1280px+  (xl:)
```

### 6.2 レイアウト変化

| コンテンツ | Mobile | Tablet+ | Desktop+ |
|-----------|--------|---------|----------|
| Heroカード | 1列 | 2列 | 2列 (wider) |
| ウィザード | 1列フル | 2列 (2:3) | 2列 (2:3) |
| 議論UI | チャットのみ | サイドバー+チャット | サイドバー+チャット |
| 履歴一覧 | カードリスト | テーブル | テーブル |
| ロール一覧 | 2列 | 4列 | 4列 |

### 6.3 モバイル固有の対応

```
- タッチ: hover効果をtap効果に置換
- スクロール: 議論チャットはネイティブスクロール
- 入力: テキストエリアの高さ自動調整
- ナビ: ハンバーガーメニュー (md未満)
```

---

## 7. パフォーマンス目標

| 指標 | 目標 | 計測 |
|------|------|------|
| First Contentful Paint (FCP) | < 1.5秒 | Lighthouse |
| Time to Interactive (TTI) | < 2.0秒 | Lighthouse |
| SSE 初回発言表示 | < 5秒 (API依存) | 手動 |
| ページ遷移 | < 500ms (体感) | 手動 |
| 合計 JS サイズ | < 100KB (自前JS) | DevTools |
| 合計 CDN サイズ | < 500KB | DevTools |

### 最適化手法

```
- CDNは defer / async で非同期読み込み
- Alpine.js は defer で body末尾に配置
- 画像なし（絵文字で代替）
- CSS: Tailwind Play CDN はJIT的に軽量
- Jinja2テンプレート: サーバーサイドで組み立て済み
```

---

## 8. セキュリティ

| 脅威 | 対策 | 実装箇所 |
|------|------|---------|
| XSS | DOMPurify でMarkdownサニタイズ | `markdown.js` |
| CSRF | Cookie不使用 (APIキーはサーバーのみ) | — |
| パストラバーサル | target_path を正規化 + 許可ディレクトリ内チェック | `api_review.py` |
| APIキー漏洩 | フロントに露出しない。サーバーサイドのみ保持 | `deps.py` |
| 大量リクエスト | RateTracker でAPI呼び出し制限 | `core/rate_tracker.py` |
| SSE接続枯渇 | 同時1セッションのみ許可 | `api_idea.py` |

---

## 9. エラーハンドリング UI方針

### 9.1 エラーの種類と表示方法

| 発生箇所 | 深刻度 | UI表現 |
|---------|--------|--------|
| フォームバリデーション | 低 | インラインエラー (赤テキスト + border-red) |
| API 4xx | 中 | トースト (warning/error) + フォーム修正案内 |
| API 5xx | 高 | トースト (error) + リトライボタン |
| SSE切断 | 高 | バナー表示 + 部分結果の保存ボタン |
| レートリミット | 高 | モーダル (残量表示 + 明日まで待機案内) |
| ページ 404 | — | カスタム 404 ページ (ホームへのリンク) |
| サーバー 500 | — | カスタム 500 ページ (エラーID表示) |

### 9.2 トースト通知仕様

```
位置: 右上固定 (top-4 right-4)
幅: max-w-sm
表示時間: 3秒 (success/info), 5秒 (warning), 手動消去のみ (error)
スタック: 最大3件同時表示
アニメーション: 右からスライドイン → フェードアウト
色:
- success: green-500 border
- info: blue-500 border
- warning: amber-500 border
- error: red-500 border
```

---

## 10. アクセシビリティ

| 項目 | 対応 |
|------|------|
| キーボードナビ | Tab / Shift+Tab でフォーカス移動、Enter で実行 |
| ARIA属性 | role, aria-label, aria-live (トースト/チャット) |
| コントラスト比 | WCAG AA準拠 (4.5:1 以上) |
| スクリーンリーダー | 議論発言に aria-live="polite" |
| フォーカスリング | focus-visible でキーボード操作時のみ表示 |
| 色だけに依存しない | アイコン + テキストで状態を伝える |

---

## 11. 開発ワークフロー

### 11.1 ローカル開発

```bash
# サーバー起動 (ホットリロード)
python serve.py --reload

# ブラウザで開く
open http://localhost:8080

# テンプレート編集 → 自動リロード
# static/ 編集 → ブラウザ手動リロード (or LiveReload拡張)
```

### 11.2 serve.py の仕様

```python
"""Web UI サーバー起動スクリプト。"""
import typer
import uvicorn

app = typer.Typer()

@app.command()
def serve(
    port: int = 8080,
    host: str = "0.0.0.0",
    reload: bool = False,
    debug: bool = False,
):
    """AI Orchestra Web UI を起動する。"""
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="debug" if debug else "info",
    )

if __name__ == "__main__":
    app()
```

### 11.3 環境差分

| 設定 | 開発 | 本番 |
|------|------|------|
| `--reload` | ✅ | ❌ |
| `--debug` | ✅ | ❌ |
| CORS | localhost 許可 | 無効 |
| 静的ファイルキャッシュ | なし | Cache-Control: 1日 |
| エラー詳細表示 | スタックトレース表示 | ユーザーフレンドリーメッセージ |

---

## 12. 将来拡張

| 機能 | 影響範囲 | 技術的準備 |
|------|---------|-----------|
| 人間介入 (議論中にコメント) | SSE → WebSocket 化 | InterventionHandler ABCで抽象化済み |
| マルチユーザー | セッションスコープの DI | deps.py の設計で対応可能 |
| カスタムロール作成UI | roles.html + API追加 | YAML追加で新ロール動作する設計 |
| PDF エクスポート | api_sessions.py 拡張 | レポートMDが整形済み |
| Notion / Google Docs連携 | 新 route 追加 | REST APIで出力取得可能 |
| 多言語対応 (i18n) | テンプレート + JS | Jinja2 i18n拡張で対応 |
| PWA化 | manifest.json + SW | 静的ファイル構成が対応済み |