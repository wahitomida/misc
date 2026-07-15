# 第16章 CLI インターフェース

---

## 16.1 コマンド体系

AI Orchestra は `click` または `typer` ベースの CLI を提供します。メインコマンド `main.py` の下にサブコマンドを配置する構成です。

```
main.py
├── idea        # 機能①: 技術議論
├── review      # 機能②: コードレビュー
├── list-roles  # ロール一覧表示
├── history     # セッション履歴
├── replay      # 過去セッションの再表示
└── role-stats  # ロール別統計
```

---

### 16.1.1 `idea` コマンド

```python
import typer
from pathlib import Path
from typing import Optional

app = typer.Typer(help="🎼 AI Orchestra — 研究者のためのAI議論ツール")

@app.command()
def idea(
prompt: str = typer.Argument(..., help="議論したいテーマ・質問"),
# モデル指定
planner_model: str = typer.Option("gpt-5.4", "--planner-model", help="Phase 1 計画立案モデル"),
conductor_model: str = typer.Option("gpt-4.1", "--conductor-model", help="Phase 2 進行管理モデル"),
synth_model: str = typer.Option("claude-sonnet-4-5", "--synth-model", help="Phase 3 統合モデル"),
# 制御パラメータ
time_limit: int = typer.Option(300, "--time-limit", "-t", help="制限時間（秒）"),
max_agents: int = typer.Option(5, "--max-agents", "-n", help="最大参加AI数"),
expertise: str = typer.Option("intermediate", "--expertise", "-e", help="beginner/intermediate/expert"),
# follow-up
follow_up: Optional[str] = typer.Option(None, "--follow-up", "-f", help="継続するセッションID"),
attach: Optional[list[Path]] = typer.Option(None, "--attach", "-a", help="添付ファイル（複数可）"),
focus_hypothesis: Optional[list[str]] = typer.Option(None, "--focus-hypothesis", help="フォーカスする仮説ID"),
# 出力
output_dir: Path = typer.Option(Path("./output"), "--output-dir", "-o", help="出力ディレクトリ"),
):
"""💡 技術テーマについてAIが多角的に議論し、洞察・仮説・実験計画を導出する"""
...
```

**使用例**:

```bash
# 基本
python main.py idea "点群のGNNで特徴量抽出する設計指針"

# フルオプション
python main.py idea \
--planner-model gpt-5.4 \
--conductor-model gpt-4.1 \
--synth-model claude-sonnet-4-5 \
--time-limit 600 \
--max-agents 6 \
--expertise expert \
"VAEの潜在空間次元数の決め方"

# follow-up
python main.py idea \
--follow-up 20260620_143052_idea \
--attach results.csv \
--focus-hypothesis H1 H3 \
"H1は確認できた。H3は棄却。次は？"
```

---

### 16.1.2 `review` コマンド

```python
@app.command()
def review(
target: Path = typer.Argument(..., help="レビュー対象のディレクトリ"),
# モデル指定
planner_model: str = typer.Option("gpt-5.4", "--planner-model"),
conductor_model: str = typer.Option("gpt-4.1", "--conductor-model"),
synth_model: str = typer.Option("claude-sonnet-4-5", "--synth-model"),
# 制御パラメータ
time_limit: int = typer.Option(600, "--time-limit", "-t", help="制限時間（秒）。デフォルト10分"),
max_agents: int = typer.Option(6, "--max-agents", "-n"),
focus: str = typer.Option("all", "--focus", help="重点モード: all/pre_submission/performance/structure/handover/algorithm"),
ignore: Optional[str] = typer.Option(None, "--ignore", help="追加ignoreパターン（カンマ区切り）"),
# 出力
output_dir: Path = typer.Option(Path("./output"), "--output-dir", "-o"),
):
"""🔬 研究コードを6観点から多角的にレビューし、修正指示書を生成する"""
...
```

**使用例**:

```bash
# 基本
python main.py review ./src/

# 論文投稿前チェック
python main.py review --focus pre_submission ./src/

# 性能改善に特化
python main.py review --focus performance --time-limit 900 ./src/model/

# 特定パターンを除外
python main.py review --ignore "*.test.py,data/" ./src/
```

---

### 16.1.3 `list-roles` コマンド

```python
@app.command("list-roles")
def list_roles(
verbose: bool = typer.Option(False, "--verbose", "-v", help="詳細表示"),
):
"""📋 利用可能なロール一覧を表示"""
...
```

**出力例**:

```
$ python main.py list-roles

📋 利用可能なロール (8個)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 研究議論用:
  🧮 理論屋      (theorist)       gpt-5.4         [ML, 信号処理, 最適化, 数学]
  🔬 実験屋      (experimentalist) gpt-5           [ML, 信号処理, CV, ロボ]
  🤖 実装屋      (implementer)    claude-s4-5     [ML, DL, HPC, CV]
  📚 文献屋      (literature)     gpt-5.4         [ML, CV, NLP, 信号処理]
  😈 穴探し      (devil)          claude-s4-5     [全分野]
  🎯 鳥の目      (bird_eye)       gpt-5.4         [分野横断]

 コードレビュー用:
  📐 設計リーダー  (code_architect) gpt-4.1         [SE, ML]
  📝 可読性リーダー (code_reviewer)  gpt-4.1-mini    [SE]
```

**verbose モード** (`-v`):

```
$ python main.py list-roles -v

🧮 理論屋 (theorist)
  モデル: gpt-5.4 | level: high
  得意: 数理モデリング, 計算量解析, 最適化理論, 収束証明, 情報理論
  分野: machine_learning, signal_processing, optimization, mathematics
  性格: 数式で考える。"なぜそうなるか"の根拠を常に求める。
  弱み: 実装の泥臭い部分や実験の現実的制約を軽視しがち
  統計: 8セッション参加 | 平均4.30/5 | trend: improving
```

---

### 16.1.4 `history` コマンド

```python
@app.command()
def history(
chain: Optional[str] = typer.Option(None, "--chain", "-c", help="指定セッションのチェーンを表示"),
limit: int = typer.Option(10, "--limit", "-l", help="表示件数"),
type_filter: Optional[str] = typer.Option(None, "--type", help="idea/review でフィルタ"),
):
"""📜 過去のセッション一覧を表示"""
...
```

**出力例 (一覧)**:

```
$ python main.py history

📜 セッション履歴 (直近10件)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ID                        Type    時間   品質  収束  テーマ
─────────────────────────────────────────────────────────────────
 20260630_100000_idea      idea    4:12   4.7   0.92  [F#2] GNN最終構成
 20260625_150000_review    review  6:18   4.3   0.85  ./src/ pre_submission
 20260625_091200_idea      idea    3:48   4.3   0.85  [F#1] multi-scale速度
 20260620_143052_idea      idea    3:36   4.5   0.88  点群GNN設計指針
 20260618_101500_idea      idea    4:55   4.1   0.80  VAE潜在次元
 ...

[F#N] = follow-up (chain_depth=N)
```

**出力例 (--chain)**:

```
$ python main.py history --chain 20260620_143052_idea

🔗 Session Chain: 点群GNN特徴量抽出
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📍 20260620_143052_idea [初回] — 設計指針
   結論: multi-scale kNN + 相対位置PE + EdgeConv
   仮説: H1🔲 H2🔲 H3🔲 H4🔲 H5🔲
   参加: 🧮🔬🤖📚😈 | 品質: 4.5/5

   ↓ (5日後)

📍 20260625_091200_idea [follow-up #1] — 速度問題
   結論: 階層的multi-scale
   仮説: H1✅ H2🔲 H3❌ → H3'🔲 H5🔲 H6🔲
   参加: 🧮🤖😈 | 品質: 4.3/5

   ↓ (5日後)

📍 20260630_100000_idea [follow-up #2] — 最終構成
   結論: 論文用実験計画フィックス
   仮説: H1✅ H2✅ H3'✅ H5✅ H6🔲 H8🔲
   参加: 🧮🔬🤖😈📚 | 品質: 4.7/5
```

---

### 16.1.5 `replay` コマンド

```python
@app.command()
def replay(
session_id: str = typer.Argument(..., help="再表示するセッションID"),
section: str = typer.Option("conversation", "--section", "-s",
help="conversation/report/evaluation/summary"),
):
"""🔄 過去セッションの内容を再表示"""
...
```

**使用例**:

```bash
# 会話ログを再表示
python main.py replay 20260620_143052_idea

# レポートのみ
python main.py replay 20260620_143052_idea --section report

# 評価のみ
python main.py replay 20260620_143052_idea --section evaluation
```

---

### 16.1.6 `role-stats` コマンド

```python
@app.command("role-stats")
def role_stats(
role_id: Optional[str] = typer.Argument(None, help="特定ロールの詳細。省略で全ロール"),
):
"""📊 ロール別のパフォーマンス統計を表示"""
...
```

**出力例**:

```
$ python main.py role-stats

📊 ロール別パフォーマンス統計
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 ロール         セッション  自己評価  他者評価  トレンド  強み
─────────────────────────────────────────────────────────────
 🧮 理論屋      8          4.15     4.30     📈 improving  定式化
 🔬 実験屋      6          4.20     4.40     ━━ stable     実験設計
 🤖 実装屋      7          4.00     4.25     📈 improving  ボトルネック特定
 📚 文献屋      5          3.90     4.10     📉 declining  系譜整理
 😈 穴探し      8          4.30     4.50     ━━ stable     反例構築
 🎯 鳥の目      3          4.50     4.60     📈 improving  リフレーミング
```

**特定ロール詳細**:

```
$ python main.py role-stats theorist

📊 🧮 理論屋 (theorist) — 詳細統計
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

総セッション数: 8
平均自己評価: 4.15 / 5.0
平均他者評価: 4.30 / 5.0
トレンド: 📈 improving (+0.35)

Top強み: 定式化の的確さ
Top弱み: 計算量見積もりの精度

直近5セッション:
 2026-06-30 [4.5/5] GNN最終構成 ← 最高スコア
 2026-06-25 [4.5/5] multi-scale速度問題
 2026-06-20 [4.25/5] GNN設計指針
 2026-06-18 [4.0/5] VAE潜在次元
 2026-06-15 [3.8/5] 時系列特徴抽出

改善履歴:
 📈 6/15(3.8) → 6/18(4.0) → 6/20(4.25) → 6/25(4.5) → 6/30(4.5)
```

---

## 16.2 共通オプション一覧

全サブコマンドに共通するオプション:

| オプション | 短縮 | デフォルト | 説明 |
|---|---|---|---|
| `--planner-model` | — | gpt-5.4 | Phase 1 モデル |
| `--conductor-model` | — | gpt-4.1 | Phase 2 進行モデル |
| `--synth-model` | — | claude-sonnet-4-5 | Phase 3 統合モデル |
| `--time-limit` | `-t` | 300 (idea) / 600 (review) | 制限時間（秒） |
| `--max-agents` | `-n` | 5 (idea) / 6 (review) | 最大参加AI数 |
| `--output-dir` | `-o` | ./output | 出力先 |
| `--expertise` | `-e` | intermediate | beginner/intermediate/expert |
| `--verbose` | `-v` | False | 詳細ログ表示 |
| `--quiet` | `-q` | False | 進捗表示を最小化 |
| `--no-confirm` | — | False | 実行確認をスキップ |

---

## 16.3 環境変数の読み込み優先順位

### 16.3.1 CLI 引数 > .env > 環境変数 > デフォルト値

```python
class ConfigLoader:
"""設定の読み込み（優先順位管理）"""

def __init__(self):
self.cli_args = {}
self.env_file = {}
self.env_vars = {}
self.defaults = {}

def load(self, cli_args: dict) -> dict:
"""全ソースからマージして最終設定を返す"""

# 1. デフォルト値（settings.yaml）
config = self._load_defaults()

# 2. 環境変数
config.update(self._load_env_vars())

# 3. .env ファイル（プロジェクトルート）
config.update(self._load_env_file())

# 4. CLI 引数（最優先）
config.update({k: v for k, v in cli_args.items() if v is not None})

return config

def _load_env_file(self) -> dict:
"""プロジェクトルートの .env ファイルを読み込み"""
env_paths = [
Path(".env"),
Path("API/.env"),
]

for env_path in env_paths:
if env_path.exists():
return self._parse_env_file(env_path)
return {}

def _parse_env_file(self, path: Path) -> dict:
"""独自の .env パーサー（python-dotenv 不要）"""
result = {}
for line in path.read_text(encoding="utf-8").splitlines():
line = line.strip()
if not line or line.startswith("#"):
continue
if "=" in line:
key, _, value = line.partition("=")
key = key.strip()
value = value.strip().strip("'\"")
result[key] = value
# 環境変数にもセット（OpenAI SDKが参照するため）
os.environ.setdefault(key, value)
return result

def _load_env_vars(self) -> dict:
"""環境変数からの読み込み"""
mapping = {
"KOTOBUDDY_API_KEY": "api_key",
"KOTOBUDDY_ENDPOINT": "endpoint",
"KOTOBUDDY_MODE": "mode",
"API_VERSION": "api_version",
"HTTP_PROXY": "http_proxy",
"HTTPS_PROXY": "https_proxy",
# 互換用フォールバック
"AZURE_OPENAI_KEY": "api_key",
"AZURE_OPENAI_ENDPOINT": "endpoint",
}

result = {}
for env_name, config_key in mapping.items():
value = os.environ.get(env_name)
if value and config_key not in result:
result[config_key] = value

return result
```

**優先順位の具体例**:

```
設定項目: endpoint

1. CLI引数: --endpoint https://custom.endpoint.com → ✅ これが使われる
2. .env: KOTOBUDDY_ENDPOINT=https://from-env-file.com → (CLIが未指定なら)
3. 環境変数: KOTOBUDDY_ENDPOINT=https://from-env-var.com → (上が未設定なら)
4. 互換: AZURE_OPENAI_ENDPOINT=https://legacy.com → (上が全て未設定なら)
5. デフォルト: settings.yaml の値 → (全て未設定なら)
```

---

## 16.4 進捗バー表示（rich ライブラリ）

### 16.4.1 計画表示テーブル

Phase 1 完了後、実行前にユーザーに計画を提示します。

```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

class PlanDisplay:
"""計画の表示"""

def show(self, plan: OrchestraPlan, rate_tracker: RateLimitTracker):
"""計画を視覚的に表示"""

# ODSC 表示
console.print(Panel(
f"[bold]Objective:[/bold] {plan.odsc.objective}\n"
f"[bold]Deliverable:[/bold] {plan.odsc.deliverable}\n"
f"[bold]Success Criteria:[/bold] {plan.odsc.success_criteria}",
title="🎯 ODSC",
border_style="blue",
))

# 参加AI表示
agents_str = " / ".join(
f"{a.role_id}({a.model})" for a in plan.selected_agents
)
console.print(f"\n🤖 参加AI: {agents_str}")

# ラウンド計画テーブル
table = Table(title="🎼 議論計画", show_header=True, header_style="bold cyan")
table.add_column("Round", style="cyan", width=6)
table.add_column("Phase", style="magenta", width=20)
table.add_column("参加者", style="green", width=20)
table.add_column("Pattern", style="yellow", width=10)
table.add_column("Level", style="red", width=8)
table.add_column("時間", style="white", width=6)

for rc in plan.discussion_plan.round_config:
speakers = ", ".join(rc.speakers)
table.add_row(
str(rc.round),
rc.phase_name,
speakers,
rc.pattern,
rc.level,
f"{rc.time_budget_sec:.0f}s",
)

console.print(table)

# 統計表示
console.print(f"\n📊 予想リクエスト数: [bold]{plan.discussion_plan.total_estimated_requests}[/bold]")
console.print(f"⏱️  予想所要時間: [bold]{plan.discussion_plan.total_estimated_time_sec:.0f}秒[/bold] / {plan.time_limit_sec}秒制限")
console.print(f"🔑 日次残りリクエスト: [bold]{rate_tracker.remaining()}[/bold] / {rate_tracker.daily_limit}")
```

---

### 16.4.2 実行確認プロンプト

```python
def confirm_execution(self, plan: OrchestraPlan, no_confirm: bool = False) -> bool:
"""実行確認"""
if no_confirm:
return True

response = console.input("\n▶ 実行しますか？ [Y/n]: ").strip().lower()
return response in ("", "y", "yes")
```

---

### 16.4.3 リアルタイム発言表示

```python
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

class DiscussionDisplay:
"""議論中のリアルタイム表示"""

EMOJI_MAP = {
"theorist": "🧮",
"experimentalist": "🔬",
"implementer": "🤖",
"literature": "📚",
"devil": "😈",
"bird_eye": "🎯",
"code_architect": "📐",
"code_reviewer": "📝",
"conductor": "🎵",
}

def show_round_start(self, round_config: RoundConfig, time_keeper: TimeKeeper):
"""ラウンド開始表示"""
console.print(
f"\n── [bold]Round {round_config.round}: {round_config.phase_name}[/bold] "
f"── ({round_config.pattern}, level={round_config.level}) "
f"── 残り{time_keeper.remaining:.0f}秒 ──"
)

def show_utterance(self, utterance: Utterance):
"""1発言の表示"""
emoji = self.EMOJI_MAP.get(utterance.speaker, "🤖")
model_short = utterance.model.replace("claude-sonnet-4-5", "claude-s4-5")

# 発言パネル
console.print(Panel(
utterance.content,
title=f"{emoji} {utterance.speaker} ({model_short}, {utterance.duration_sec:.1f}s)",
border_style="blue" if utterance.type == "discussion" else "dim",
width=min(80, console.width - 4),
))

def show_convergence(self, result: ConvergenceResult):
"""収束判定の表示"""
color = "green" if result.score >= 0.8 else "yellow" if result.score >= 0.5 else "red"
console.print(
f"\n[{color}]📈 収束: {result.score:.2f}[/{color}] — {result.reasoning}"
)

def show_orchestrator_memo(self, memo: str):
"""指揮者メモの表示（verbose時のみ）"""
console.print(f"[dim]🎼 [内心] {memo}[/dim]")
```

---

### 16.4.4 経過時間 / 残り時間表示

```python
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TaskID

class TimeDisplay:
"""時間表示の管理"""

def __init__(self, time_limit: float):
self.time_limit = time_limit
self.progress = Progress(
SpinnerColumn(),
TextColumn("[bold blue]{task.description}"),
BarColumn(bar_width=30),
TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
TimeElapsedColumn(),
TextColumn("残り [bold]{task.fields[remaining]}[/bold]s"),
)
self.task_id: TaskID | None = None

def start(self):
"""進捗バー開始"""
self.progress.start()
self.task_id = self.progress.add_task(
"議論進行中",
total=self.time_limit,
remaining=f"{self.time_limit:.0f}",
)

def update(self, elapsed: float, remaining: float):
"""進捗更新"""
if self.task_id is not None:
self.progress.update(
self.task_id,
completed=elapsed,
remaining=f"{remaining:.0f}",
)

def stop(self):
"""進捗バー停止"""
self.progress.stop()
```

**実行中の表示イメージ**:

```
🎼 AI Orchestra v1.0 — 技術議論モード
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⠋ 議論進行中 ████████████░░░░░░░░░░░░░░░░░░ 38% 01:12 残り 192s

── Round 2: 穴探し (ping_pong, level=medium) ── 残り192秒 ──

╭─ 😈 穴探し (claude-s4-5, 12.1s) ────────────────╮
│ ちょっと待って。kNNグラフ構築って密度不均一だっ │
│ たらどうなる？疎な領域でk個取ると物理的に離れた │
│ 点が繋がって意味ないエッジができるよね。       │
╰──────────────────────────────────────────────────╯

╭─ 🧮 理論屋 (gpt-5.4, 8.3s) ─────────────────────╮
│ 良い指摘。manifold仮定が成り立つなら、kNNは測地 │
│ 距離の近似として理論的に正当化できるんだけど、  │
│ manifoldの境界や角ではその仮定が崩れる。       │
╰──────────────────────────────────────────────────╯

📈 収束: 0.55 — kNNの限界は合意。対策の合意はまだ。
```

---

## 16.5 出力の色分けと絵文字

### カラースキーム

```python
COLOR_SCHEME = {
# フェーズ表示
"phase1": "bold cyan",
"phase2": "bold blue",
"phase3": "bold magenta",

# ロール別
"theorist": "bright_blue",
"experimentalist": "bright_green",
"implementer": "bright_yellow",
"literature": "bright_cyan",
"devil": "bright_red",
"bird_eye": "bright_magenta",
"conductor": "dim",

# 状態
"success": "green",
"warning": "yellow",
"error": "red",
"info": "dim",

# 収束度
"convergence_high": "green",    # ≥ 0.8
"convergence_mid": "yellow",   # 0.5-0.8
"convergence_low": "red",      # < 0.5

# 課題の重要度
"critical": "bold red",
"warn": "yellow",
"suggestion": "dim green",
}
```

### 絵文字の使用ルール

| 用途 | 絵文字 | 場面 |
|---|---|---|
| ロール識別 | 🧮🔬🤖📚😈🎯📐📝 | 発言表示、評価 |
| フェーズ | 📋🎵🔮 | Phase 1/2/3 |
| 状態 | ✅❌⚠️🔲 | 仮説テーブル、チェック結果 |
| 統計 | 📊📈📉 | スコア、トレンド |
| アクション | ▶⏸⏹🔄 | 実行確認、一時停止（将来） |
| セッション | 📍🔗 | 履歴、チェーン表示 |
| 時間 | ⏱️⏰ | 時間表示、タイムアウト警告 |
| ファイル | 📄📁💾 | 出力ファイル表示 |

### セッション完了時の表示

```python
def show_completion(self, output_path: Path, statistics: dict):
"""セッション完了表示"""

console.print("\n" + "━" * 50)
console.print("[bold green]✅ セッション完了！[/bold green]")
console.print()
console.print(f"📄 レポート: [link]{output_path / 'report.md'}[/link]")
console.print(f"🎭 会話ログ: [link]{output_path / 'full_conversation.md'}[/link]")
console.print(f"📊 評価:    [link]{output_path / 'evaluation.md'}[/link]")
console.print(f"📋 要約:    [link]{output_path / 'summary.txt'}[/link]")
if (output_path / "vibe_coding_prompt.md").exists():
console.print(f"🤖 修正指示: [link]{output_path / 'vibe_coding_prompt.md'}[/link]")
console.print()
console.print(
f"📈 統計: {statistics['total_requests']} req | "
f"{statistics['total_tokens']:,} tokens | "
f"{statistics['duration_sec']:.0f}秒 | "
f"収束 {statistics['convergence']:.2f}"
)
console.print("━" * 50)
```

**完了時の表示イメージ**:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ セッション完了！

📄 レポート: output/20260620_143052_idea/report.md
🎭 会話ログ: output/20260620_143052_idea/full_conversation.md
📊 評価:    output/20260620_143052_idea/evaluation.md
📋 要約:    output/20260620_143052_idea/summary.txt

📈 統計: 35 req | 121,500 tokens | 216秒 | 収束 0.88
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### 16章まとめ: CLI 設計の原則

| 原則 | 実現方法 |
|---|---|
| **シンプルなデフォルト** | `python main.py idea "テーマ"` だけで動作。オプションは全て省略可 |
| **段階的詳細化** | デフォルト→個別オプション→settings.yaml で段階的にカスタマイズ |
| **視覚的フィードバック** | rich によるカラー表示、絵文字、パネル、テーブルで直感的 |
| **進捗の可視化** | リアルタイムの発言表示 + 進捗バー + 残り時間 |
| **確認後実行** | 計画表示→ユーザー確認→実行の3ステップ（`--no-confirm` でスキップ可） |
| **研究者フレンドリー** | ターミナル慣れした研究者が快適に使える設計 |

---
