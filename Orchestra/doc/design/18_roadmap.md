9# 第18章 プロジェクト構造と実装ロードマップ

---

## 18.1 ディレクトリ構成（確定版）

```
ai-orchestra/
├── main.py                          # CLI エントリポイント (typer)
├── requirements.txt                 # 依存ライブラリ
├── requirements-dev.txt             # 開発用依存（テスト、lint等）
├── pyproject.toml                   # プロジェクトメタデータ
├── .env.example                     # 環境変数テンプレート
├── .gitignore
├── README.md
│
├── config/
│   ├── settings.yaml                # 全体設定（第17章で定義）
│   │
│   ├── roles/                       # ロール定義 YAML (8種)
│   │   ├── theorist.yaml            # 🧮 理論屋
│   │   ├── experimentalist.yaml     # 🔬 実験屋
│   │   ├── implementer.yaml         # 🤖 実装屋
│   │   ├── literature.yaml          # 📚 文献屋
│   │   ├── devil.yaml               # 😈 穴探し
│   │   ├── bird_eye.yaml            # 🎯 鳥の目
│   │   ├── code_architect.yaml      # 📐 設計リーダー
│   │   └── code_reviewer.yaml       # 📝 可読性リーダー
│   │
│   └── scenarios/                   # シナリオテンプレート
│       ├── algorithm_design.yaml
│       ├── experiment_planning.yaml
│       └── paper_discussion.yaml
│
├── core/
│   ├── __init__.py
│   ├── api_client.py                # KotoBuddy API ラッパー（リトライ・フォールバック・モード切替）
│   ├── rate_tracker.py              # 日次リクエスト数の追跡・永続化
│   ├── orchestrator.py              # Phase 1: 計画立案
│   ├── conductor.py                 # Phase 2: 議論進行管理
│   ├── synthesizer.py               # Phase 3: 統合・要約・レポート生成
│   ├── agent.py                     # AI エージェント基底クラス
│   ├── memory.py                    # 会話ログ JSON 管理・コンテキスト構築
│   ├── evaluator.py                 # 自己/他者評価ロジック
│   ├── feedback.py                  # YAML フィードバック蓄積・読出
│   ├── follow_up.py                 # 継続議論のコンテキスト管理
│   ├── time_keeper.py               # 時間管理（残り時間追跡・ラウンド判定）
│   ├── turn_calculator.py           # ターン数・時間配分の算出補助
│   ├── intervention.py              # 介入ハンドラ（将来拡張用インターフェース）
│   ├── role_manager.py              # ロール YAML の読込・管理・バリデーション
│   ├── config_loader.py             # 設定読込（.env / 環境変数 / settings.yaml 統合）
│   ├── output_generator.py          # 出力ファイル群の生成
│   └── exceptions.py                # カスタム例外定義
│
├── features/
│   ├── __init__.py
│   ├── idea_discussion.py           # 機能①: 技術議論の統合フロー
│   └── code_review.py               # 機能②: コードレビューの統合フロー
│
├── display/
│   ├── __init__.py
│   ├── plan_display.py              # 計画表示テーブル
│   ├── discussion_display.py        # リアルタイム発言表示
│   ├── progress_display.py          # 進捗バー・時間表示
│   └── completion_display.py        # 完了表示
│
├── output/                          # 実行結果（.gitignore推奨）
│   └── {timestamp}_{type}/
│       ├── session_meta.json
│       ├── discussion.json
│       ├── full_conversation.md
│       ├── report.md
│       ├── evaluation.md
│       ├── summary.txt
│       └── vibe_coding_prompt.md    # ②のみ
│
└── tests/
├── __init__.py
├── conftest.py                  # pytest 共通フィクスチャ
├── mocks/
│   ├── __init__.py
│   └── mock_api.py              # API モック
├── unit/
│   ├── test_api_client.py
│   ├── test_rate_tracker.py
│   ├── test_time_keeper.py
│   ├── test_turn_calculator.py
│   ├── test_memory.py
│   ├── test_agent.py
│   ├── test_feedback.py
│   ├── test_follow_up.py
│   ├── test_role_manager.py
│   └── test_config_loader.py
├── integration/
│   ├── test_orchestrator.py
│   ├── test_conductor.py
│   ├── test_synthesizer.py
│   └── test_output_generator.py
└── e2e/
├── test_idea_mini.py        # ミニ議論 E2E
└── test_review_mini.py      # ミニレビュー E2E
```

---

## 18.2 モジュール一覧と責務

### 18.2.1 core/ 配下

| モジュール | 責務 | 主な依存先 | 行数目安 |
|---|---|---|---|
| `api_client.py` | KotoBuddy API呼出の抽象化。リトライ・フォールバック・モード切替・空応答対策を統合 | openai SDK, requests | 300 |
| `rate_tracker.py` | 日次リクエスト数の追跡・ファイル永続化・残量チェック | なし | 80 |
| `orchestrator.py` | Phase 1: ODSC策定、AI選定、議論計画生成 | api_client, role_manager, feedback | 250 |
| `conductor.py` | Phase 2: ラウンド進行、発言順制御、収束判定、堂々巡り検知、時間管理 | api_client, agent, memory, time_keeper | 400 |
| `synthesizer.py` | Phase 3: 評価統合、最終レポート生成、フィードバック更新 | api_client, evaluator, feedback | 300 |
| `agent.py` | AIエージェント。ロールYAML解釈、プロンプト構築、API呼出、発言長制御 | api_client, memory | 250 |
| `memory.py` | 会話ログのJSON管理、コンテキスト構築、中間要約生成 | api_client | 200 |
| `evaluator.py` | 自己/他者評価のプロンプト生成・結果パース | api_client | 150 |
| `feedback.py` | YAML読書き、feedback_history追記、stats再計算、プロンプト注入テキスト生成 | PyYAML | 200 |
| `follow_up.py` | 前回セッション読込、コンテキスト圧縮、仮説テーブル管理、チェーン管理 | api_client | 250 |
| `time_keeper.py` | 残り時間追跡、圧力レベル判定、ラウンド開始可否判定 | なし | 80 |
| `turn_calculator.py` | ターン数・時間配分の算出、時間超過時の調整 | なし | 100 |
| `intervention.py` | 介入ハンドラのABC + NoIntervention実装 | なし | 50 |
| `role_manager.py` | ロールYAMLの読込・キャッシュ・バリデーション・一覧取得 | PyYAML | 100 |
| `config_loader.py` | .env / 環境変数 / settings.yaml の統合読込、優先順位管理 | PyYAML | 100 |
| `output_generator.py` | 全出力ファイル（JSON, Markdown, txt）の生成・書出 | なし | 300 |
| `exceptions.py` | カスタム例外の定義 | なし | 50 |

---

### 18.2.2 features/ 配下

| モジュール | 責務 | 主な依存先 | 行数目安 |
|---|---|---|---|
| `idea_discussion.py` | 機能①の統合フロー。入力バリデーション→Phase 1→2→3→出力 | core/ 全般 | 200 |
| `code_review.py` | 機能②の統合フロー。5フェーズ（スキャン→調査→質問→会議→レポート） | core/ 全般 | 400 |

---

### 18.2.3 config/ 配下

| ファイル | 役割 |
|---|---|
| `settings.yaml` | 全体設定（第17章で完全定義） |
| `roles/*.yaml` | ロール定義（第7章で完全定義） |
| `scenarios/*.yaml` | シナリオテンプレート（第11章で定義） |

---

## 18.3 依存ライブラリ（requirements.txt）

```
# === Core ===
openai>=1.30.0           # KotoBuddy API (OpenAI SDK v1系)
requests>=2.31.0         # 大容量リクエスト対応 (SHA-256ヘッダ)
pyyaml>=6.0              # ロールYAML / settings.yaml
typer>=0.9.0             # CLI フレームワーク
rich>=13.0.0             # ターミナル表示（テーブル、パネル、進捗バー、カラー）

# === Utilities ===
python-json-logger>=2.0  # 構造化ログ出力

# === Optional (大規模ファイル解析) ===
# tiktoken>=0.5.0        # 正確なtoken数推定（入れなくても簡易推定で動作）
```

**requirements-dev.txt**:

```
# === テスト ===
pytest>=7.0.0
pytest-asyncio>=0.21.0   # async テスト対応
pytest-cov>=4.0.0        # カバレッジ
pytest-mock>=3.10.0      # モック

# === コード品質 ===
ruff>=0.1.0              # リンター + フォーマッター
mypy>=1.5.0              # 型チェック
```

---

## 18.4 実装ロードマップ

### 18.4.1 Week 1: 基盤レイヤー

**目標**: API に繋がり、設定を読み、最小限の CLI が動く状態。

```
Day 1-2: 設定・接続基盤
├── config_loader.py        (.env + 環境変数 + settings.yaml 統合)
├── settings.yaml           (全設定の初期版)
├── exceptions.py           (カスタム例外定義)
└── .env.example            (環境変数テンプレート)

Day 3-4: API クライアント
├── api_client.py           (openai/azureモード自動判定, リトライ, フォールバック)
├── rate_tracker.py         (日次追跡 + 永続化)
└── tests/unit/test_api_client.py, test_rate_tracker.py

Day 5: 時間管理 + CLI スケルトン
├── time_keeper.py          (残り時間追跡)
├── turn_calculator.py      (推定時間計算)
├── main.py                 (typer スケルトン: idea/review/list-roles)
└── tests/unit/test_time_keeper.py, test_turn_calculator.py

マイルストーン: `python main.py idea "hello"` で API に接続し応答を得る
```

---

### 18.4.2 Week 2: 機能① コアロジック

**目標**: 3体の AI で最小限の議論が回る状態。

```
Day 1-2: エージェント + メモリ
├── role_manager.py         (YAML読込 + バリデーション)
├── agent.py                (ロール読込, プロンプト構築, API呼出, 発言長制御)
├── memory.py               (ログ管理, コンテキスト構築, 中間要約)
├── roles/theorist.yaml     (最初のロール)
├── roles/devil.yaml
├── roles/experimentalist.yaml
└── tests/unit/test_agent.py, test_memory.py, test_role_manager.py

Day 3-4: 指揮者 + 進行管理
├── orchestrator.py         (ODSC策定, AI選定, 計画生成)
├── conductor.py            (ラウンド進行, 収束判定, 発言パターン)
└── tests/unit/test_orchestrator.py (モックAPI)

Day 5: 統合フロー
├── features/idea_discussion.py  (Phase 1→2→3 の統合)
├── display/plan_display.py      (計画表示)
├── display/discussion_display.py (発言表示)
└── 手動テスト: 3体で「Hello World」的なミニ議論を実機実行

マイルストーン: `python main.py idea "GNNの設計"` で3体が議論し結果が表示される
```

---

### 18.4.3 Week 3: 機能① 仕上げ + 機能② 着手

**目標**: 機能①が完全動作。機能②のPhase 1-2 が動く。

```
Day 1-2: Phase 3（統合・評価）+ 出力
├── evaluator.py            (自己/他者評価)
├── synthesizer.py          (最終レポート, 全会話台本)
├── feedback.py             (YAML蓄積)
├── output_generator.py     (全ファイル生成)
├── roles/ 残り3ロール追加  (implementer, literature, bird_eye)
└── scenarios/*.yaml         (3シナリオ作成)

Day 3: follow-up + 仕上げ
├── follow_up.py            (前回読込, コンテキスト圧縮, 仮説管理)
├── intervention.py         (NoIntervention 実装)
├── display/completion_display.py
└── 統合テスト: 5体フル議論 + follow-up テスト

Day 4-5: 機能② 着手
├── features/code_review.py  (Phase 1: スキャン + Phase 2: 個別調査)
├── roles/code_architect.yaml
├── roles/code_reviewer.yaml
└── tests/integration/test_code_review_scan.py

マイルストーン: 機能①の全出力ファイルが正しく生成される
機能②のPhase 1-2 が小規模フォルダで動作する
```

---

### 18.4.4 Week 4: 機能② 仕上げ + テスト + ドキュメント

**目標**: 全機能が動作し、テスト・ドキュメントが整備された状態。

```
Day 1-2: 機能② Phase 3-5
├── code_review.py 拡張    (Phase 3: 相互質問, Phase 4: 全体会議, Phase 5: レポート)
├── vibe_coding_prompt 生成ロジック
└── 統合テスト: 実際の研究コードフォルダでレビュー実行

Day 3: CLI完成 + ユーティリティ
├── main.py 完成            (history, replay, role-stats コマンド)
├── display/progress_display.py (進捗バー最終調整)
└── エラーハンドリング統合テスト

Day 4: テスト
├── tests/e2e/test_idea_mini.py  (実機E2Eテスト)
├── tests/e2e/test_review_mini.py
├── カバレッジ確認 (目標: core/ 80%以上)
└── エッジケーステスト (タイムアウト, 空応答, EOLモデル)

Day 5: ドキュメント + リリース
├── README.md               (クイックスタートガイド)
├── 設計書の最終整合確認
└── 初回リリース (v1.0.0)

マイルストーン: 全コマンドが動作。テストが通る。ドキュメント完備。
```

---

## 18.5 テスト戦略

### 18.5.1 ユニットテスト（モック API）

API を呼ばずにロジックの正しさを検証します。

```python
# tests/mocks/mock_api.py
class MockAPIClient:
"""APIをモックしてテスト用の固定レスポンスを返す"""

def __init__(self, responses: list[dict] | None = None):
self.responses = responses or []
self.call_log: list[dict] = []
self._call_count = 0

async def call(self, model: str, messages: list, **kwargs) -> dict:
"""呼び出しを記録し、事前設定のレスポンスを返す"""
self.call_log.append({"model": model, "messages": messages, **kwargs})

if self._call_count < len(self.responses):
response = self.responses[self._call_count]
else:
response = {"content": f"Mock response #{self._call_count}", "usage": {"input": 100, "output": 50}}

self._call_count += 1
return response

# tests/unit/test_time_keeper.py
import pytest
from core.time_keeper import TimeKeeper, TimePressure

class TestTimeKeeper:
def test_remaining_decreases(self):
tk = TimeKeeper(time_limit_sec=100)
tk.start_time = tk.start_time - 30  # 30秒経過を模擬
assert 65 < tk.remaining < 75  # phase3_reserve考慮

def test_pressure_levels(self):
tk = TimeKeeper(time_limit_sec=100)
tk.start_time = tk.start_time - 10
assert tk.pressure == TimePressure.RELAXED

tk.start_time = tk.start_time - 60
assert tk.pressure == TimePressure.MODERATE

def test_can_start_next_round(self):
tk = TimeKeeper(time_limit_sec=100)
tk.start_time = tk.start_time - 90  # 残り10秒
assert tk.can_start_next_round(5) == True  # 5秒のラウンドはOK
assert tk.can_start_next_round(20) == False  # 20秒は不可
```

---

### 18.5.2 統合テスト（KotoBuddy 実機）

実際の API に接続して動作確認します。CI では社内 LAN が必要なためローカル実行。

```python
# tests/integration/test_orchestrator.py
import pytest
from core.orchestrator import Orchestrator

@pytest.mark.integration  # pytest -m integration で実行
class TestOrchestratorIntegration:
"""実機APIを使った統合テスト"""

@pytest.fixture
def orchestrator(self, real_api_client, role_manager, feedback_manager, settings):
return Orchestrator(real_api_client, role_manager, feedback_manager, settings)

async def test_plan_generation(self, orchestrator):
"""計画が正常に生成されるか"""
plan = await orchestrator.plan(
user_input="テスト: 簡単なアルゴリズム設計の議論",
model="gpt-4.1",  # 高速なモデルでテスト
level="low",       # 低levelで高速
time_limit_sec=60,
max_agents=3,
)

assert plan.odsc.objective
assert len(plan.selected_agents) <= 3
assert plan.discussion_plan.estimated_rounds >= 2
assert plan.discussion_plan.total_estimated_time_sec < 60
```

---

### 18.5.3 E2E テスト（ミニ議論の実行）

最小構成（2体、2ラウンド、60秒制限）で全フロー（Phase 1→2→3→出力）を通すテスト。

```python
# tests/e2e/test_idea_mini.py
import pytest
from pathlib import Path
from features.idea_discussion import IdeaDiscussion

@pytest.mark.e2e  # pytest -m e2e で実行
class TestIdeaMini:
"""最小構成でのE2Eテスト"""

async def test_full_flow(self, real_api_client, tmp_path):
"""最小議論の全フローが通るか"""
discussion = IdeaDiscussion(
real_api_client, role_manager, feedback_manager, settings
)

output_path = await discussion.run(
user_input="テスト議論: 1+1=2 の証明方法",
planner_model="gpt-4.1",      # 高速
conductor_model="gpt-4.1-mini",
synth_model="gpt-4.1",        # 拡張思考なしで高速
time_limit=60,
max_agents=2,
expertise="expert",
output_dir=tmp_path,
)

# 全出力ファイルの存在確認
assert (output_path / "session_meta.json").exists()
assert (output_path / "discussion.json").exists()
assert (output_path / "full_conversation.md").exists()
assert (output_path / "report.md").exists()
assert (output_path / "evaluation.md").exists()
assert (output_path / "summary.txt").exists()

# session_meta の基本構造確認
import json
meta = json.loads((output_path / "session_meta.json").read_text())
assert meta["status"] == "completed"
assert meta["total_rounds"] >= 2
assert 0 <= meta["final_convergence"] <= 1.0
```

### テスト実行コマンド

```bash
# ユニットテストのみ（API不要、高速）
pytest tests/unit/ -v

# 統合テスト（API必要、社内LAN）
pytest tests/integration/ -v -m integration

# E2Eテスト（API必要、数分かかる）
pytest tests/e2e/ -v -m e2e

# 全テスト + カバレッジ
pytest --cov=core --cov=features --cov-report=html

# 特定テストのみ
pytest tests/unit/test_time_keeper.py -v
```

---

## 18.6 最初に実装すべきモジュールの優先順位

依存関係を踏まえた実装順序:

```
優先度1（他の全てが依存）:
1. exceptions.py        ← 全モジュールが使う例外定義
2. config_loader.py     ← 設定読込。全モジュールが参照
3. settings.yaml        ← 設定ファイル本体

優先度2（コア基盤）:
4. api_client.py        ← API呼出の抽象化。agent, orchestrator等が依存
5. rate_tracker.py      ← api_clientが使用

優先度3（時間管理）:
6. time_keeper.py       ← conductorが使用
7. turn_calculator.py   ← orchestratorが使用

優先度4（エージェント基盤）:
8. role_manager.py      ← ロールYAMLの読込
9. agent.py             ← API呼出+プロンプト構築
10. memory.py            ← 会話ログ管理

優先度5（3フェーズ）:
11. orchestrator.py      ← Phase 1
12. conductor.py         ← Phase 2
13. evaluator.py         ← Phase 3 の前半
14. synthesizer.py       ← Phase 3 の後半

優先度6（統合+出力）:
15. output_generator.py  ← ファイル生成
16. feedback.py          ← YAML更新
17. features/idea_discussion.py  ← 機能①統合

優先度7（追加機能）:
18. follow_up.py         ← 継続議論
19. features/code_review.py  ← 機能②
20. display/*.py         ← CLI表示
```

**最初のPR（Pull Request）** に含めるべきファイル:

```
PR #1: 基盤レイヤー
├── config_loader.py
├── exceptions.py
├── api_client.py
├── rate_tracker.py
├── time_keeper.py
├── turn_calculator.py
├── config/settings.yaml
├── .env.example
├── main.py (スケルトン)
├── requirements.txt
└── tests/unit/ (上記のテスト)
```

---

## 18.7 将来拡張の展望

### 18.7.1 人間介入機能

**v1.1 で実装予定**。

```python
# 現在: NoIntervention (全自動)
# v1.1: CLIIntervention (ラウンド間で入力待ち)

class CLIIntervention(InterventionHandler):
"""ラウンド間で3秒待ち、入力があれば介入として処理"""

def check_intervention(self, round_num, context):
console.print("[dim](Enter: 続行 / テキスト入力: 介入)[/dim]")
user_input = self._wait_for_input(timeout=3.0)
if user_input:
return user_input
return None
```

**介入で可能なこと**:
- 「〇〇の方向で考えて」→ 次ラウンドの指示に追加
- 「もう終わりにして」→ Phase 3 へ即移行
- 「△△も考慮して」→ 新論点として追加
- 「□□を呼んで」→ 動的にロール追加

---

### 18.7.2 Web UI（Streamlit / Gradio）

**v2.0 で検討**。

```python
# WebIntervention ハンドラ + Streamlit フロントエンド

# バックエンド: 議論エンジンをWebSocket経由で接続
# フロントエンド: リアルタイムで発言が流れるチャット風UI
# 介入: テキストボックスから任意のタイミングで指示
```

**UI のモックアップイメージ**:

```
┌──────────────────────────────────────────────┐
│ 🎼 AI Orchestra — Session: 20260620_143052   │
├──────────────────────────────────────────────┤
│                                              │
│ [Round 2: 穴探し] 収束: 0.55 | 残り: 192s    │
│                                              │
│ 🧮: manifold仮定が崩れる箇所では...          │
│ 😈: ちょっと待って、密度不均一で...           │
│ 🧮: multi-scaleで対応できるはず...           │
│                                              │
│ ─────────────────────────────────────────── │
│ [介入入力] > ここにテキストを入力して介入...   │
│                                              │
├──────────────────────────────────────────────┤
│ [計画] [ログ] [評価] [レポート]               │
└──────────────────────────────────────────────┘
```

---

### 18.7.3 セッション検索・知見 DB

**v2.1 で検討**。

```python
# session_meta.json のタグとテキスト検索
# SQLite or JSON ベースの軽量DB

class SessionSearch:
"""過去セッションの検索"""

def search(self, query: str, tags: list[str] = None) -> list[dict]:
"""テーマ・タグ・結論でのフルテキスト検索"""
...

def find_related(self, session_id: str) -> list[dict]:
"""関連セッション（類似テーマ）の提示"""
...
```

**活用シーン**:
- 「前にGNNの話した時のセッションどれだっけ？」
- 「この手法について過去に議論したことある？」
- 新セッション開始時に「関連する過去の議論があります」と提示

---

### 18.7.4 A/B テスト（AI 編成比較）

**v2.2 で検討**。

```bash
# 同じテーマで異なるAI編成で議論し、結果を比較
python main.py idea --ab-test \
--config-a "agents=theorist,devil,experimentalist" \
--config-b "agents=theorist,implementer,bird_eye" \
"テーマ"
```

**出力**: 2セッションの結果を横並びで比較するレポート。
- どちらの編成がより深い洞察を得られたか
- 収束速度の差
- 評価スコアの差

---

### 18.7.5 外部ツール呼び出し（Web 検索、計算実行）

**v3.0 で検討**。

```python
class ToolCallHandler:
"""議論中に外部ツールを呼び出す"""

tools = {
"arxiv_search": ArxivSearchTool(),     # 論文検索
"python_exec": PythonExecutor(),        # 計算実行
"wolfram": WolframAlphaTool(),          # 数学計算
}

async def handle_tool_request(self, tool_name: str, params: dict) -> str:
"""ツール呼出しの実行"""
...
```

**活用シーン**:
- 📚 文献屋が議論中に「確認してみよう」→ arxiv 検索
- 🧮 理論屋が「この計算量を計算すると…」→ Python 実行
- 🔬 実験屋が「このデータの統計量は…」→ 添付データの計算

---

### 18.7.6 音声出力（ポッドキャスト化）

**v3.1 で検討**。

```bash
# 議論ログをTTSで音声化
python main.py replay 20260620_143052_idea --audio --output podcast.mp3
```

**実装イメージ**:
- 各ロールに異なる声質を割当
- `full_conversation.md` をスクリプトとして音声合成
- 指揮者のメモは「ナレーション」として挿入
- BGM（オーケストラ風）を追加

**活用シーン**:
- 通勤中に議論の振り返り
- チーム内での知見共有（聞き流しで理解）
- 研究室のゼミ発表の代替

---

### 拡張ロードマップまとめ

| バージョン | 内容 | 時期目安 |
|---|---|---|
| v1.0 | 本設計書の全機能 | Week 4 完了時 |
| v1.1 | CLI 介入機能 | +2週間 |
| v2.0 | Web UI (Streamlit) | +1-2ヶ月 |
| v2.1 | セッション検索 DB | +2-3ヶ月 |
| v2.2 | A/B テスト | +3ヶ月 |
| v3.0 | 外部ツール連携 | +4-6ヶ月 |
| v3.1 | 音声出力 | +6ヶ月以降 |

---

### 18章まとめ: プロジェクト構造の設計原則

| 原則 | 実現方法 |
|---|---|
| **関心の分離** | core/(エンジン) / features/(統合フロー) / display/(表示) / config/(設定) を明確に分離 |
| **依存方向の制御** | features → core → 外部ライブラリ の一方向。循環依存なし |
| **テスタビリティ** | API はモック可能な設計。ユニットテストが API なしで実行可能 |
| **段階的構築** | 基盤→コア→機能→UI の順で構築。各段階で動作確認可能 |
| **拡張準備** | InterventionHandler, ToolCallHandler 等のインターフェースで将来に備える |
| **最小依存** | 依存ライブラリは5個のみ(openai, requests, pyyaml, typer, rich) |

---
