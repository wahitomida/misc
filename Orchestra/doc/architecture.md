# AI Orchestra — アーキテクチャ設計書

> モジュール構成・依存関係・レイヤー構造の全容

---

## 1. レイヤー構造

```
┌─────────────────────────────────────────────────────────┐
│  Interface Layer (入出力)                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ main.py  │  │ serve.py │  │ web/ (FastAPI + UI)  │  │
│  │ (typer)  │  │(uvicorn) │  │                      │  │
│  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘  │
├───────┼──────────────┼───────────────────┼──────────────┤
│  Feature Layer (ユースケース)                            │
│  ┌────┴──────────────┴───────────────────┴───────────┐  │
│  │ features/idea_discussion.py                       │  │
│  │ features/code_review/                             │  │
│  └───────────────────────┬───────────────────────────┘  │
├───────────────────────────┼──────────────────────────────┤
│  Core Layer (ビジネスロジック)                            │
│  ┌───────────────────────┼───────────────────────────┐  │
│  │                       │                           │  │
│  │  orchestrator.py  conductor.py  synthesizer.py    │  │
│  │       │                │              │           │  │
│  │       ├── agent.py ────┤              │           │  │
│  │       │                │              │           │  │
│  │  evaluator.py    memory.py     feedback.py        │  │
│  │       │                │              │           │  │
│  │  role_manager.py  time_keeper.py  follow_up.py    │  │
│  │                                                   │  │
│  └───────────────────────┬───────────────────────────┘  │
├───────────────────────────┼──────────────────────────────┤
│  Infrastructure Layer (外部接続)                          │
│  ┌───────────────────────┼───────────────────────────┐  │
│  │  api_client.py   rate_tracker.py   config_loader  │  │
│  └───────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│  Config Layer (静的定義)                                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │  config/settings.yaml                             │  │
│  │  config/roles/*.yaml (8ファイル)                   │  │
│  │  config/scenarios/*.yaml (3ファイル)               │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 2. モジュール一覧と責務

### 2.1 Interface Layer

| モジュール | 責務 | 依存先 |
|-----------|------|--------|
| `main.py` | CLI エントリポイント (typer) | features/, display/, config_loader |
| `cli_runner.py` | CLI → Feature 構築ブリッジ | features/, core/ |
| `serve.py` | Web UI サーバー起動 (uvicorn) | web/ |
| `web/app.py` | FastAPI アプリケーション定義 | web/routes/, web/deps.py |
| `web/routes/*.py` | HTTPルーティング | features/, core/ |
| `display/*.py` | CLI 表示 (Rich) | core/ の型定義のみ |

### 2.2 Feature Layer

| モジュール | 責務 | 依存先 |
|-----------|------|--------|
| `features/idea_discussion.py` | idea コマンドのフロー制御 | core/ 全体 |
| `features/code_review/` | review コマンドのフロー制御 | core/ 全体 |

### 2.3 Core Layer

| モジュール | 責務 | 依存先 |
|-----------|------|--------|
| `core/orchestrator.py` | Phase 1: 計画立案 | api_client, role_manager, feedback, turn_calculator |
| `core/conductor.py` | Phase 2: 議論進行 | api_client, agent, memory, time_keeper, intervention |
| `core/synthesizer.py` | Phase 3: 統合・評価 | api_client, evaluator, feedback, output_generator |
| `core/agent.py` | AIエージェント (発言・評価) | api_client, memory, role_manager |
| `core/memory.py` | 会話記憶・コンテキスト管理 | api_client |
| `core/evaluator.py` | 自己/他者評価の実行 | api_client |
| `core/feedback.py` | ロール別フィードバック蓄積 | role_manager |
| `core/follow_up.py` | フォローアップ (連続議論) | api_client, output_generator |
| `core/role_manager.py` | ロールYAML読み込み・検証 | (なし) |
| `core/time_keeper.py` | 時間管理 (カウントダウン) | (なし) |
| `core/turn_calculator.py` | ラウンド時間計算・動的調整 | config_loader |
| `core/intervention.py` | 人間介入インターフェース | (なし — ABC) |
| `core/output_generator.py` | ファイル出力 | (なし) |

### 2.4 Infrastructure Layer

| モジュール | 責務 | 依存先 |
|-----------|------|--------|
| `core/api_client.py` | LLM API 呼び出し (リトライ・フォールバック) | rate_tracker, config_loader, exceptions |
| `core/rate_tracker.py` | APIレートリミット追跡・永続化 | (なし) |
| `core/config_loader.py` | 設定ファイル読み込み・環境変数解決 | (なし) |
| `core/exceptions.py` | カスタム例外定義 | (なし) |

---

## 3. 依存関係ルール

### 3.1 依存の方向 (上→下のみ)

```
Interface → Feature → Core → Infrastructure → Config
                                    ↓
                              (外部 API)
```

### 3.2 禁止される依存

| From | To | 理由 |
|------|----|------|
| Core | Interface | コアが表示方法を知るべきでない |
| Core | Feature | Feature がコアを使う (逆はNG) |
| Infrastructure | Core | インフラはコアに依存しない |
| 任意のモジュール | 自身への循環 | 循環import禁止 |

### 3.3 循環回避パターン

```python
# ❌ Bad: orchestrator → feedback → role_manager → orchestrator (循環)

# ✅ Good: インターフェース (Protocol / ABC) で疎結合
# feedback.py は RoleManagerProtocol に依存
# orchestrator.py は FeedbackManagerProtocol に依存
# 具体クラスの注入は features/ で行う
```

---

## 4. データフロー

### 4.1 Idea Discussion の全体フロー

```
User Input (テーマ文字列)
    │
    ▼
┌─ IdeaDiscussion ──────────────────────────────────────┐
│                                                        │
│  ① validate_input(text) → str                         │
│  ② detect_scenario(text) → ScenarioConfig | None      │
│  ③ Orchestrator.plan(text, ...) → OrchestraPlan       │
│       └─ API call (計画生成)                           │
│  ④ confirm_execution(plan) → bool                     │
│  ⑤ Conductor.run_discussion(plan) → DiscussionLog     │
│       └─ 各ラウンドで Agent.speak() × n              │
│           └─ API call (発言生成)                       │
│  ⑥ Synthesizer.synthesize(...) → SynthesisResult      │
│       └─ Evaluator → 各Agent の評価                   │
│       └─ API call (レポート生成)                       │
│  ⑦ OutputGenerator.generate(...) → Path               │
│       └─ ファイル書き出し                              │
│                                                        │
└────────────────────────────────────────────────────────┘
    │
    ▼
Output Directory (7ファイル)
```

### 4.2 Code Review の全体フロー

```
Target Directory Path
    │
    ▼
┌─ CodeReview ───────────────────────────────────────────┐
│                                                        │
│  Phase 1: FolderScanner.scan() → ScanResult            │
│  Phase 2: PartLeaders × 6 並列調査 → findings          │
│  Phase 3: CrossQuestioner.run() → 相互質問結果          │
│  Phase 4: Conductor.run_discussion() → 全体会議ログ     │
│  Phase 5: Synthesizer → レポート + vibe_prompt          │
│                                                        │
└────────────────────────────────────────────────────────┘
    │
    ▼
Output Directory (7ファイル + vibe_coding_prompt.md)
```

---

## 5. 3フェーズエンジンの詳細

```
┌──────────────────────────────────────────────────────────────┐
│                    Phase 1: PLAN (計画)                       │
│                                                              │
│  Orchestrator                                                │
│  ├─ ユーザー入力を分析                                        │
│  ├─ ODSC (目的/成果物/範囲/基準) を定義                       │
│  ├─ 参加AIロールを選定 (2〜8名)                               │
│  ├─ ラウンド計画を立案 (2〜5ラウンド)                         │
│  │   └─ 各ラウンド: フェーズ/パターン/主導者/時間              │
│  ├─ プライベート指示を各AIに作成                              │
│  └─ 時間見積もりを検証                                        │
│                                                              │
│  出力: OrchestraPlan                                         │
├──────────────────────────────────────────────────────────────┤
│                   Phase 2: DISCUSS (議論)                     │
│                                                              │
│  Conductor                                                   │
│  ├─ TimeKeeper で時間監視                                     │
│  ├─ 各ラウンドを順次実行                                      │
│  │   ├─ SpeakingOrder に従い Agent.speak() を呼ぶ            │
│  │   ├─ ConvergenceChecker で収束度を測定                     │
│  │   ├─ RepetitionDetector で堂々巡りを検知                   │
│  │   ├─ AgreementDetector で同意過多を検知                    │
│  │   └─ ラウンド末尾で結論を生成                              │
│  ├─ 時間逼迫時に DynamicPlanAdjuster でプラン修正             │
│  └─ 全ラウンド完走 or 時間切れで終了                          │
│                                                              │
│  出力: DiscussionLog                                         │
├──────────────────────────────────────────────────────────────┤
│                  Phase 3: SYNTHESIZE (統合)                   │
│                                                              │
│  Synthesizer                                                 │
│  ├─ Evaluator で自己評価・他者評価を収集                      │
│  ├─ 指揮者評価 (全体品質、MVP、各AIフィードバック)             │
│  ├─ レポート生成 (仮説・洞察・実験計画)                       │
│  ├─ 全会話ログ整形                                            │
│  ├─ 要約生成                                                  │
│  └─ FeedbackManager にフィードバック蓄積                      │
│                                                              │
│  出力: SynthesisResult → OutputGenerator → ファイル群         │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. Web UI アーキテクチャ

```
┌─ Browser ──────────────────────────────────────────────┐
│                                                        │
│  Alpine.js (状態管理)                                   │
│  ├─ ページコンポーネント (ideaPage, reviewPage, etc.)   │
│  ├─ OrchestraSSE (SSEクライアント)                      │
│  └─ localStorage (入力保存、ダークモード)               │
│                                                        │
└────────────────────┬───────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────┼───────────────────────────────────┐
│  FastAPI Server    │                                   │
│                    │                                   │
│  routes/pages.py ──┤── HTML (Jinja2) レスポンス         │
│  routes/api_*.py ──┤── JSON / SSE レスポンス            │
│                    │                                   │
│  deps.py ──────────┤── 依存注入 (Settings, APIClient)   │
│                                                        │
└────────────────────┬───────────────────────────────────┘
                     │
┌────────────────────┼───────────────────────────────────┐
│  Core Engine       │                                   │
│                    │                                   │
│  SSEInterventionHandler (notify_progress → SSE queue)  │
│  ↕                                                     │
│  features/ → core/ → api_client → LLM API             │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### SSE ストリーミングの仕組み

```python
# Web UIとコアエンジンの接続
async def event_generator(request):
    queue = asyncio.Queue()
    intervention = SSEInterventionHandler(queue)

    # コアエンジンをバックグラウンドで実行
    task = asyncio.create_task(run_orchestra(request, intervention))

    # queue からイベントを取り出してSSEで送信
    while True:
        event = await queue.get()
        yield f"data: {json.dumps(event)}\n\n"
        if event["type"] in ("done", "error"):
            break
```

---

## 7. ファイルツリー (完全版)

```
Orchestra/
├── main.py                     # CLI エントリポイント (typer)
├── cli_runner.py               # CLI → Feature 構築
├── serve.py                    # Web UI 起動 (uvicorn)
├── config/
│   ├── settings.yaml           # 全体設定
│   ├── roles/                  # AIロール定義
│   │   ├── theorist.yaml
│   │   ├── experimentalist.yaml
│   │   ├── implementer.yaml
│   │   ├── literature.yaml
│   │   ├── devil.yaml
│   │   ├── bird_eye.yaml
│   │   ├── code_architect.yaml
│   │   └── code_reviewer.yaml
│   └── scenarios/              # シナリオ定義
│       ├── algorithm_design.yaml
│       ├── experiment_planning.yaml
│       └── paper_discussion.yaml
├── core/                       # コアエンジン
│   ├── __init__.py
│   ├── exceptions.py           # カスタム例外
│   ├── config_loader.py        # 設定読み込み
│   ├── api_client.py           # LLM API クライアント
│   ├── rate_tracker.py         # レートリミット追跡
│   ├── time_keeper.py          # 時間管理
│   ├── turn_calculator.py      # ターン計算
│   ├── role_manager.py         # ロール管理
│   ├── memory.py               # 会話記憶
│   ├── agent.py                # AIエージェント
│   ├── orchestrator.py         # Phase 1: 計画
│   ├── conductor.py            # Phase 2: 議論進行
│   ├── evaluator.py            # 評価実行
│   ├── synthesizer.py          # Phase 3: 統合
│   ├── feedback.py             # フィードバック蓄積
│   ├── follow_up.py            # フォローアップ
│   ├── intervention.py         # 人間介入 (ABC)
│   └── output_generator.py     # ファイル出力
├── features/                   # ユースケース
│   ├── __init__.py
│   ├── idea_discussion.py      # idea コマンド
│   └── code_review/            # review コマンド
│       ├── __init__.py
│       ├── runner.py           # メインフロー
│       ├── scanner.py          # ファイルスキャン
│       ├── chunker.py          # ファイル分割
│       ├── part_leader.py      # パートリーダー割当
│       └── cross_question.py   # 相互質問
├── display/                    # CLI表示 (Rich)
│   ├── __init__.py
│   ├── plan_display.py
│   ├── discussion_display.py
│   ├── progress_display.py
│   └── completion_display.py
├── web/                        # Web UI
│   ├── app.py                  # FastAPI アプリ
│   ├── deps.py                 # 依存注入
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── pages.py            # HTMLルーティング
│   │   ├── api_idea.py         # idea API
│   │   ├── api_review.py       # review API
│   │   ├── api_sessions.py     # 履歴 API
│   │   └── api_roles.py        # ロール API
│   ├── templates/
│   │   ├── base.html
│   │   ├── partials/
│   │   │   ├── header.html
│   │   │   ├── toast.html
│   │   │   ├── modal.html
│   │   │   └── step_indicator.html
│   │   ├── pages/
│   │   │   ├── home.html
│   │   │   ├── idea.html
│   │   │   ├── review.html
│   │   │   ├── history.html
│   │   │   ├── replay.html
│   │   │   └── roles.html
│   │   └── components/
│   │       ├── chat_bubble.html
│   │       ├── plan_card.html
│   │       ├── timer.html
│   │       └── evaluation.html
│   └── static/
│       ├── css/
│       │   └── custom.css
│       └── js/
│           ├── app.js
│           ├── sse.js
│           ├── toast.js
│           └── dark-mode.js
├── tests/
│   ├── unit/
│   │   ├── test_config_loader.py
│   │   ├── test_api_client.py
│   │   ├── test_rate_tracker.py
│   │   ├── test_time_keeper.py
│   │   ├── test_turn_calculator.py
│   │   ├── test_role_manager.py
│   │   ├── test_memory.py
│   │   ├── test_agent.py
│   │   ├── test_orchestrator.py
│   │   ├── test_conductor.py
│   │   ├── test_evaluator.py
│   │   ├── test_synthesizer.py
│   │   ├── test_feedback.py
│   │   ├── test_follow_up.py
│   │   └── test_output_generator.py
│   ├── integration/
│   │   ├── test_idea_discussion.py
│   │   └── test_code_review.py
│   └── mocks/
│       └── mock_api.py
├── output/                     # セッション出力先
├── doc/                        # 設計書 (18章)
├── docs/                       # Copilot 参照ドキュメント
│   ├── architecture.md         # ← このファイル
│   ├── patterns.md
│   ├── api-reference.md
│   ├── data-models.md
│   ├── task-breakdown.md
│   ├── test-strategy.md
│   ├── prompts-catalog.md
│   ├── web-ui-spec.md
│   └── web-ui-prompts.md
└── requirements.txt
```

---

## 8. 技術スタック詳細

| カテゴリ | 技術 | バージョン | 用途 |
|---------|------|-----------|------|
| 言語 | Python | 3.10+ | 全体 |
| LLM SDK | openai | latest | AsyncOpenAI / AsyncAzureOpenAI |
| CLI | typer | 0.9+ | コマンドライン |
| CLI表示 | rich | 13+ | プログレスバー、テーブル |
| Web | FastAPI | 0.100+ | REST + SSE |
| テンプレート | Jinja2 | 3.1+ | HTML生成 |
| ASGI | uvicorn | 0.23+ | サーバー |
| フロントエンド | Alpine.js | 3.x (CDN) | 状態管理 |
| CSS | Tailwind CSS | 3.x (CDN) | スタイリング |
| Markdown | marked | 5.x (CDN) | レンダリング |
| テスト | pytest | 7+ | ユニット/統合 |
| テスト (async) | pytest-asyncio | 0.21+ | 非同期テスト |
| YAML | PyYAML | 6+ | 設定読み込み |

---

## 9. セキュリティ考慮事項

| 項目 | 対策 |
|------|------|
| APIキー | .env ファイルで管理、コードに埋め込まない |
| ファイルアクセス | target_path のパストラバーサル防止 |
| XSS | Markdown表示時に DOMPurify でサニタイズ |
| CORS | 開発時のみ localhost 許可 |
| レートリミット | RateTracker で自主的に制御 |

---

## 10. 将来の拡張ポイント

| 拡張 | 影響モジュール | 設計上の準備 |
|------|--------------|------------|
| 新ロール追加 | config/roles/ + role_manager | YAML追加のみで対応可 |
| 新シナリオ追加 | config/scenarios/ | YAML追加のみで対応可 |
| 新モデル対応 | api_client | FallbackManager のチェーン追加 |
| 人間介入 | intervention.py | ABC を実装するだけ |
| マルチユーザー | web/deps.py | セッションスコープの DI に変更 |
| データベース化 | output_generator | ファイル → DB のアダプタ追加 |
