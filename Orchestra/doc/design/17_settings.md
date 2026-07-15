# 第17章 設定ファイル（settings.yaml）

---

AI Orchestra の全設定を `config/settings.yaml` に集約します。コード変更なしで挙動を調整可能にする設計です。

```yaml
# ============================================================
# AI Orchestra — settings.yaml
# ============================================================
# このファイルでシステム全体の挙動を制御します。
# CLI 引数で上書き可能な項目は (CLI上書き可) と表記。
# ============================================================

version: "1.0.0"
```

---

## 17.1 全体設定

### 17.1.1 時間制限

```yaml
# === 時間制限 ===
time_limits:
idea_default_sec: 300          # 機能①のデフォルト制限時間（5分）(CLI上書き可)
review_default_sec: 600        # 機能②のデフォルト制限時間（10分）(CLI上書き可)
min_sec: 60                    # 最小制限時間（これ以下は拒否）
max_sec: 1800                  # 最大制限時間（30分。これ以上は拒否）

# Phase 別の時間予約
phase1_max_sec: 15             # Phase 1 の最大許容時間
phase3_reserve_sec: 25         # Phase 3 用に確保する時間
conductor_overhead_per_round_sec: 3  # 進行管理1回あたりのオーバーヘッド
convergence_check_time_sec: 2  # 収束判定1回あたりの時間
```

---

### 17.1.2 エージェント上限

```yaml
# === エージェント設定 ===
agents:
idea_default_max: 5            # 機能①のデフォルト最大AI数 (CLI上書き可)
review_default_max: 6          # 機能②のデフォルト最大AI数 (CLI上書き可)
min_agents: 2                  # 最小参加AI数
max_agents: 8                  # 最大参加AI数（これ以上は拒否）
```

---

### 17.1.3 収束閾値

```yaml
# === 収束判定 ===
convergence:
default_threshold: 0.8         # デフォルトの収束閾値
min_threshold: 0.5             # 指揮者が設定可能な最小閾値
max_threshold: 0.95            # 指揮者が設定可能な最大閾値
stagnation_window: 3           # 停滞検知のウィンドウ（連続N回スコア変動なし）
stagnation_tolerance: 0.05     # 停滞と判定するスコア変動の閾値
```

---

## 17.2 会話スタイル設定

### 17.2.1 tone（lab_discussion）

```yaml
# === 会話スタイル ===
conversation_style:
tone: "lab_discussion"         # 研究室での議論トーン
# 選択肢: lab_discussion / formal / casual / debate

tone_descriptions:
lab_discussion: "研究室のホワイトボード前の議論。カジュアルだが内容は的確。"
formal: "学会発表のQ&Aのような丁寧さ。敬語ベース。"
casual: "同期との雑談レベル。砕けた表現OK。"
debate: "ディベート形式。明確な主張と反論。"
```

---

### 17.2.2 発言文字数制限

```yaml
# === 発言長制御 ===
utterance_length:
default_min_chars: 50
default_max_chars: 150
absolute_max_chars: 200        # これを超えたら再発言リクエスト
max_tokens_for_utterance: 300  # API の max_tokens 制限（標準モデル用）
verbosity_for_gpt5: "low"     # GPT-5系の発言時 verbosity
```

---

### 17.2.3 ラウンドあたり発言回数

```yaml
# === ラウンド内発言制御 ===
round_utterances:
one_shot_max: null             # one_shot: speakers数で自動決定
ping_pong_max_exchanges: 3    # ping_pong: 最大往復数
free_talk_max_utterances: 8   # free_talk: 最大発言数
free_talk_goal_check_interval: 3  # 何発言ごとに目標達成チェックするか
consecutive_same_speaker_limit: 2  # 同じAIが連続発言できる最大回数
```

---

### 17.2.4 発言ルール

```yaml
# === 発言ルール（全ロール共通で注入） ===
speaking_rules:
common:
- "1回の発言は50〜150文字。短く鋭く。"
- "チャットの会話テンポで。論文口調禁止。"
- "1発言で言いたいことは1つだけ。複数あるなら分けて発言する。"
- "相手の発言を受けてから自分の意見を述べる。"
- "「たしかに」「でもさ」「ちょっと待って」「あ、それいいね」等を自然に使う。"
- "数式はテキスト表現で自然に混ぜる (O(N²), ∑, ∈)"
- "論文引用は (著者+年) で簡潔に"
- "ビジネス的観点（ROI、市場性等）には言及しない"

math_rules:
- "LaTeX記法($...$, \\sum等)は禁止。テキスト表現を使う"
- "例: O(N log N), ∑_i x_i, h ∈ R^d, ∀ε>0"
- "1行30文字以上の数式は避ける。自然言語で説明する"

citation_rules:
- "引用形式: (著者+年) で簡潔に"
- "存在が不確かな論文には必ず [要確認] をつける"
- "知らない場合は「そこは知らない」と正直に言う"
- "架空の論文を作り上げることは最も重大な違反"
```

---

## 17.3 expertise レベル設定

### 17.3.1 beginner

```yaml
expertise_levels:
beginner:
description: "他分野から来た人、学部生。基本概念から説明。"
char_limit_min: 80
char_limit_max: 200
max_tokens: 400
additional_rules:
- "専門用語を使ったら直後に括弧で説明を入れる"
- "例: kNNグラフ（最も近いk個の点を結んだグラフ）"
- "数式は最小限に。直感的な説明を優先する"
- "「要するに」「ざっくり言うと」で要約を入れる"
- "前提知識がない読者を想定して、飛躍なく説明する"
```

---

### 17.3.2 intermediate

```yaml
intermediate:
description: "分野の基礎は知っている修士学生。応用の議論ができる。"
char_limit_min: 50
char_limit_max: 150
max_tokens: 300
additional_rules:
- "基本概念（勾配降下法、CNN、行列演算等）の説明は不要"
- "計算量やオーダーの議論は自然に行う"
- "論文名は出してOKだが、内容の簡単な補足を1文添える"
- "専門的すぎる略語は初出時のみフルスペルを添える"
```

---

### 17.3.3 expert

```yaml
expert:
description: "当該分野の博士学生/ポスドク/研究者。最先端の議論ができる。"
char_limit_min: 30
char_limit_max: 120
max_tokens: 200
additional_rules:
- "説明不要。本質だけ議論する"
- "数式を躊躇なく使う（O記法、Σ、∫、∇等）"
- "未発表の着想レベルの議論もOK"
- "論文のlimitationや再現性の問題にも踏み込む"
- "略語はそのまま使う (WL-test, GCN, PE, FPS等)"

default_expertise: intermediate  # CLI未指定時のデフォルト
```

---

## 17.4 API 制約設定

### 17.4.1 日次リクエスト上限

```yaml
# === API 制約 ===
api:
daily_request_limit: 10000     # 1キーあたりの日次上限
```

---

### 17.4.2 安全マージン

```yaml
safety_margin: 0.9             # 90%で「安全」と判定
warn_threshold: 0.9            # 90%到達で警告
critical_threshold: 0.95       # 95%到達で強い警告
```

---

### 17.4.3 リトライ設定

```yaml
retry:
max_retries: 3               # 最大リトライ回数
base_delay_sec: 2.0          # 初回待機時間
max_delay_sec: 30.0          # 最大待機時間
backoff_factor: 2.0          # 指数バックオフ倍率
retryable_status_codes:      # リトライ対象のHTTPステータス
- 429
- 500
- 502
- 503

# タイムアウト設定（モデル別）
timeouts:
gpt-4.1: 30
gpt-4.1-mini: 20
gpt-5-mini: 45
gpt-5: 60
gpt-5.1: 60
gpt-5.2: 60
gpt-5.4: 90
claude-sonnet-4: 60
claude-sonnet-4-5: 90
claude-opus-4-1: 60
o1: 60
o3-mini: 45
o4-mini: 45
default: 60
```

---

## 17.5 level 別推定時間

```yaml
# === Level 別推定応答時間（秒/1発言） ===
level_time_estimates:
minimal: 3
low: 5
medium: 10
high: 20

# モデル別の補正係数（基準: 1.0 = gpt-5.4）
model_time_multiplier:
gpt-5.4: 1.0
gpt-5: 0.8
gpt-5.1: 0.8
gpt-5.2: 0.8
gpt-5-mini: 0.6
gpt-4.1: 0.5
gpt-4.1-mini: 0.4
claude-sonnet-4-5: 0.9
claude-sonnet-4-5-thinking: 1.2   # 拡張思考有効時
claude-sonnet-4: 0.85
claude-opus-4-1: 1.1
o1: 1.0
o3-mini: 0.7
o4-mini: 0.7
```

---

## 17.6 フィードバック設定

```yaml
# === フィードバック ===
feedback:
enabled: true                  # false にすると YAML 更新しない
history_max: 10                # ロール YAML に保持する最大履歴数
compress_after: 10             # この数を超えたら古いエントリを圧縮
trend_window: 3                # トレンド計算に使う直近セッション数
trend_improving_threshold: 0.3 # この差以上で "improving"
trend_declining_threshold: -0.3 # この差以下で "declining"
inject_in_system_prompt: true  # 次回実行時にフィードバックを注入するか
max_feedback_items_in_prompt: 5 # プロンプトに注入する最大項目数
```

---

## 17.7 フォールバック設定

```yaml
# === フォールバック ===
fallback:
enabled: true                  # フォールバック機能のON/OFF

# EOL/廃止モデルのフォールバック先
chain:
claude-3-haiku: gpt-4.1-mini
claude-3-5-sonnet: claude-sonnet-4
claude-3-7-sonnet: claude-sonnet-4
claude-opus-4: claude-opus-4-1
gpt-4o: gpt-4.1
gpt-4o-mini: gpt-4.1-mini

# 廃止予定モデルの警告
deprecation_warnings:
gpt-4o:
deadline: "2026-09-30"
successor: gpt-4.1
gpt-4o-mini:
deadline: "2026-09-30"
successor: gpt-4.1-mini
```

---

## 17.8 コードレビュー固有設定

### 17.8.1 ignore_patterns

```yaml
# === コードレビュー設定 ===
code_review:
# ファイルスキャン除外パターン
ignore_patterns:
- "*.pyc"
- "__pycache__"
- ".git"
- ".gitignore"
- "node_modules"
- "*.egg-info"
- ".venv"
- "venv"
- "env"
- "wandb/"
- "outputs/"
- "checkpoints/"
- "*.pt"
- "*.pth"
- "*.onnx"
- "*.npy"
- "*.npz"
- "data/"
- "datasets/"
```

---

### 17.8.2 max_file_size

```yaml
# ファイルサイズ制限
max_file_size_bytes: 1048576   # 1MB超のファイルはスキップ
header_lines: 50               # 構造スキャン時に読む行数
max_tokens_per_chunk: 8000     # ファイル分割時の1チャンクあたりtoken上限
```

---

### 17.8.3 パートリーダー構成

```yaml
# パートリーダーの構成
part_leaders:
algorithm:
role_id: theorist
model: gpt-5.4
default_level: high
description: "数式↔コード対応、境界条件、数値安定性"

reproducibility:
role_id: experimentalist
model: gpt-5
default_level: medium
description: "seed固定、config管理、環境依存、バージョン固定"

performance:
role_id: implementer
model: claude-sonnet-4-5
default_level: medium
description: "ボトルネック、メモリ、並列化、I/O"

structure:
role_id: code_architect
model: gpt-4.1
default_level: medium
description: "モジュール分割、DRY、SOLID、テスタビリティ"

readability:
role_id: code_reviewer
model: gpt-4.1-mini
default_level: low
description: "命名、docstring、型ヒント、フォーマット"

results:
role_id: experimentalist
model: gpt-5
default_level: medium
description: "出力妥当性、論文整合、テスト"

# 相互質問の設定
cross_question_max_rounds: 5   # パートリーダー間の質問往復上限
```

---

### 17.8.4 focus_presets

```yaml
# 重点モードのプリセット
# 各数値は「重み」。1.0=標準、2.0=重点、0.3以下=スキップ
focus_presets:
all:
algorithm: 1.0
reproducibility: 1.0
performance: 1.0
structure: 1.0
readability: 1.0
results: 1.0

pre_submission:
algorithm: 1.5
reproducibility: 1.5
results: 1.5
performance: 0.8
structure: 0.5
readability: 0.5

performance:
performance: 2.0
structure: 1.0
algorithm: 0.5
results: 0.5
reproducibility: 0.3
readability: 0.3

structure:
structure: 2.0
readability: 1.5
performance: 0.5
algorithm: 0.3
reproducibility: 0.5
results: 0.3

handover:
readability: 2.0
reproducibility: 1.5
structure: 1.5
algorithm: 0.3
performance: 0.3
results: 0.5

algorithm:
algorithm: 2.0
results: 1.5
performance: 0.5
reproducibility: 0.5
structure: 0.3
readability: 0.3

# コード状態の自動検知 → デフォルトfocusへのマッピング
auto_focus_by_state:
prototype: structure
experimental: all
pre_publication: pre_submission
production: handover
optimization: performance
```

---

## 17.9 出力設定

```yaml
# === 出力設定 ===
output:
dir: "./output"                # デフォルト出力ディレクトリ (CLI上書き可)
log_format: "json"             # discussion.json の形式 (json固定)
report_format: "markdown"      # report.md の形式 (markdown固定)
session_id_format: "{date}_{time}_{type}"  # セッションIDのフォーマット
# {date} = YYYYMMDD, {time} = HHMMSS, {type} = idea/review

# 出力ファイルの生成ON/OFF
generate:
session_meta: true
discussion_json: true
full_conversation_md: true
report_md: true
evaluation_md: true
summary_txt: true
vibe_coding_prompt_md: true    # ②の時のみ有効

# follow-up 設定
follow_up:
max_chain_depth: 10            # チェーンの最大深度
warn_chain_depth: 5            # 警告を出す深度
context_compression_depth: 3   # N代以上前は圧縮サマリのみ引き継ぎ

# === デフォルトモデル設定 ===
models:
planner: "gpt-5.4"
planner_level: "high"
conductor: "gpt-4.1"
conductor_temperature: 0.3
synthesizer: "claude-sonnet-4-5"
synthesizer_thinking_budget: 16000
summary_model: "gpt-4.1"       # 中間要約生成用
summary_temperature: 0.0
next_speaker_model: "gpt-4.1-mini"  # free_talk時の次発言者決定用
```

---

### 設定ファイルの読み込み実装

```python
import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Settings:
"""settings.yaml の構造化表現"""

# 以下、全セクションをネストしたdataclassで表現
time_limits: dict
agents: dict
convergence: dict
conversation_style: dict
utterance_length: dict
round_utterances: dict
speaking_rules: dict
expertise_levels: dict
api: dict
level_time_estimates: dict
model_time_multiplier: dict
feedback: dict
fallback: dict
code_review: dict
output: dict
models: dict

@classmethod
def load(cls, config_dir: Path = Path("config")) -> "Settings":
"""settings.yaml を読み込んで Settings オブジェクトを返す"""
settings_path = config_dir / "settings.yaml"

if not settings_path.exists():
raise FileNotFoundError(f"設定ファイルが見つかりません: {settings_path}")

with open(settings_path, "r", encoding="utf-8") as f:
data = yaml.safe_load(f)

return cls(
time_limits=data.get("time_limits", {}),
agents=data.get("agents", {}),
convergence=data.get("convergence", {}),
conversation_style=data.get("conversation_style", {}),
utterance_length=data.get("utterance_length", {}),
round_utterances=data.get("round_utterances", {}),
speaking_rules=data.get("speaking_rules", {}),
expertise_levels=data.get("expertise_levels", {}),
api=data.get("api", {}),
level_time_estimates=data.get("level_time_estimates", {}),
model_time_multiplier=data.get("model_time_multiplier", {}),
feedback=data.get("feedback", {}),
fallback=data.get("fallback", {}),
code_review=data.get("code_review", {}),
output=data.get("output", {}),
models=data.get("models", {}),
)

def get_timeout(self, model: str) -> int:
"""モデルのタイムアウト値を取得"""
timeouts = self.api.get("retry", {}).get("timeouts", {})
return timeouts.get(model, timeouts.get("default", 60))

def get_level_time(self, level: str, model: str = None) -> float:
"""level×modelの推定時間を取得"""
base = self.level_time_estimates.get(level, 10)
if model:
multiplier = self.model_time_multiplier.get(model, 1.0)
return base * multiplier
return base

def get_expertise_config(self, level: str) -> dict:
"""expertise レベルの設定を取得"""
return self.expertise_levels.get(level, self.expertise_levels.get("intermediate", {}))
```

---

### 17章まとめ: 設定ファイルの設計原則

| 原則 | 実現方法 |
|---|---|
| **一箇所集約** | 全設定を1ファイルに集約。散在しない |
| **コード変更不要** | YAML を編集するだけで挙動を調整可能 |
| **CLI 上書き可** | 重要な項目は CLI 引数で上書き可能（一時的な変更に対応） |
| **安全なデフォルト** | 全項目にデフォルト値あり。settings.yaml がなくても動作 |
| **自己文書化** | 各項目にコメントで説明を付与 |
| **バージョン管理** | `version` フィールドで互換性を追跡 |

---
