# 第4章 指揮者（Orchestrator）設計

---

## 4.1 指揮者の役割定義

指揮者（Orchestrator）は AI Orchestra の**頭脳**です。ユーザーの入力を受け取り、議論全体の「設計図」を作成する Phase 1 の中核モジュールです。

### 指揮者が行うこと

```
1. テーマを分析し、何を議論すべきかを判断する (ODSC策定)
2. どのAIを呼ぶかを決める (参加AI選定)
3. 議論の流れをデザインする (ラウンド構成)
4. 各AIに「何を期待するか」を伝える (個別指示生成)
5. 時間とリソースの制約内に収める (実行可能性検証)
```

### 指揮者が行わないこと

```
- 議論中の発言（それは各AIエージェントの仕事）
- リアルタイムの進行管理（それはConductorの仕事）
- 最終的な統合・要約（それはSynthesizerの仕事）
```

### 実装クラスの概要

```python
class Orchestrator:
"""Phase 1: 議論の計画立案を担当"""

def __init__(
self,
api_client: ResilientAPIClient,
role_manager: RoleManager,
feedback_manager: FeedbackManager,
settings: Settings,
):
self.api_client = api_client
self.role_manager = role_manager
self.feedback_manager = feedback_manager
self.settings = settings

def plan(
self,
user_input: str,
model: str = "gpt-5.4",
level: str = "high",
time_limit_sec: float = 300,
max_agents: int = 5,
follow_up_context: FollowUpContext | None = None,
) -> OrchestraPlan:
"""ユーザー入力から議論計画を生成"""
...
```

---

## 4.2 ODSC 策定ロジック

ODSC（Objective / Deliverable / Success Criteria）は議論の「ゴール定義」です。指揮者はユーザーの入力テーマから ODSC を自動導出します。

### 4.2.1 Objective の自動導出

Objective は「この議論で何を達成するか」を一文で表します。

**導出プロンプトの該当部分**:

```
以下のユーザー入力に対して、技術的議論の目的を設定してください。

【ユーザー入力】
{user_input}

【Objective の要件】
- 「〇〇を多角的に評価/検討/設計する」の形式
- 具体的で検証可能な文言
- ビジネス観点は含めない（技術的観点のみ）
- 1文で完結
```

**導出例**:

| ユーザー入力 | 自動導出される Objective |
|---|---|
| 点群のGNNで特徴量抽出 | 点群データからのGNN特徴量抽出における設計選択肢を技術的に評価する |
| VAEの潜在空間次元数の決め方 | VAEの潜在空間次元数が性能に与える影響を理論・実験両面から分析する |
| 自己教師あり学習で時系列特徴抽出 | ラベルなし時系列データに対する自己教師あり特徴抽出のアプローチを比較検討する |

---

### 4.2.2 Deliverable の形式決定

Deliverable は「議論の成果物として何を出すか」を定義します。テーマの性質に応じて指揮者が形式を選択します。

**形式の選択肢**:

| テーマの性質 | Deliverable 形式 | 含む内容 |
|---|---|---|
| アルゴリズム設計 | 提案手法の骨格 + 実験計画 | 手法概要、疑似コード、比較条件 |
| 手法比較 | 比較表 + 推奨 | 各手法の長短、推奨条件 |
| 問題解決 | 原因分析 + 対策案 | 原因仮説、検証方法、対策の優先順位 |
| 実験計画 | 実験設計書 | 条件、データセット、評価指標、計算リソース |
| 論文議論 | 技術的洞察一覧 | 貢献の整理、限界、発展方向 |

**導出プロンプトの該当部分**:

```
【Deliverable の要件】
- テーマの性質に応じて最適な成果物形式を選択
- 研究者が「次に何をすればいいか」が明確になる形
- 以下から選択またはカスタマイズ:
a) 提案手法の骨格 + 実験計画
b) 比較表 + 推奨
c) 原因分析 + 対策案
d) 実験設計書
e) 技術的洞察一覧 + 未解決問題
```

---

### 4.2.3 Success Criteria と収束閾値

Success Criteria は「議論が成功したかの判定基準」であり、収束閾値はその数値化です。

**Success Criteria の構成要素**:

```python
@dataclass
class ODSC:
objective: str
deliverable: str
success_criteria: str
convergence_threshold: float  # 0.0〜1.0

# success_criteria の例:
# "提案手法のアルゴリズム骨格が合意され、
#  実験で検証すべき仮説が3つ以上明確になっていること"
```

**収束閾値の決定ロジック**:

指揮者はテーマの性質に応じて閾値を調整します。

| テーマの性質 | 推奨閾値 | 理由 |
|---|---|---|
| 明確な問題（バグ修正等） | 0.9 | 正解がほぼ一意。高い合意が求められる |
| 設計選択（複数正解あり） | 0.8 | 完全合意は不要。方向性の合意で十分 |
| 探索的議論（新規アイデア） | 0.7 | 多様な視点を残すことに価値がある |
| ブレインストーミング | 0.6 | 収束よりも発散が重要 |

**導出プロンプトの該当部分**:

```
【Success Criteria の要件】
- 具体的で検証可能な基準を設定
- 収束閾値を 0.0〜1.0 で設定
- テーマが探索的なら閾値は低め (0.6-0.7)
- テーマが明確なら閾値は高め (0.8-0.9)

【出力形式】
"convergence_threshold": 0.8,
"success_criteria": "具体的な成功基準テキスト"
```

---

## 4.3 参加 AI 選定アルゴリズム

### 4.3.1 テーマ × domain_tags マッチング

各ロール YAML には `domain_tags` が定義されています。指揮者はユーザー入力のテーマからキーワードを抽出し、マッチするロールを候補として列挙します。

**ロール YAML の domain_tags 例**:

```yaml
# theorist.yaml
domain_tags:
- machine_learning
- signal_processing
- optimization
- mathematics
- physics_simulation

# experimentalist.yaml
domain_tags:
- machine_learning
- signal_processing
- computer_vision
- robotics
- materials_science

# devil.yaml
domain_tags:
- any  # どの分野でも有効
```

**マッチングロジック**:

```python
def match_roles(theme_keywords: list[str], available_roles: list[Role]) -> list[Role]:
"""テーマキーワードとdomain_tagsのマッチング"""
scored_roles = []
for role in available_roles:
if "any" in role.domain_tags:
# "any" タグを持つロール（穴探し等）は常に候補
score = 0.8
else:
# キーワードとの重複度で計算
overlap = len(set(theme_keywords) & set(role.domain_tags))
score = overlap / max(len(theme_keywords), 1)
scored_roles.append((role, score))

return sorted(scored_roles, key=lambda x: x[1], reverse=True)
```

ただし、この機械的マッチングは**指揮者 LLM の判断の補助**にすぎません。最終的な選定は指揮者が文脈を踏まえて行います。

**指揮者プロンプト内での提示方法**:

```
【利用可能ロール一覧】
以下のロールから、テーマに適した参加者を選んでください。

1. 🧮 理論屋 (theorist)
- 得意: 数理モデリング, 計算量解析, 最適化理論, 収束証明
- 分野: machine_learning, signal_processing, optimization, mathematics
- 過去実績: 直近3回の平均スコア 4.3/5, 強み「定式化の的確さ」

2. 🔬 実験屋 (experimentalist)
- 得意: 実験設計, 統計的仮説検定, 再現性保証, ベンチマーク選定
- 分野: machine_learning, signal_processing, computer_vision, robotics
- 過去実績: 直近3回の平均スコア 4.5/5, 強み「実験設計の妥当性」

3. 🤖 実装屋 (implementer)
...

（全ロール分続く）
```

---

### 4.3.2 過去フィードバックに基づく適性判断

指揮者はロール選定時に、各ロールの `feedback_history` と `feedback_stats` を参照します。

**参照する情報**:

```yaml
# 例: theorist.yaml の feedback_stats
feedback_stats:
total_sessions: 8
avg_self_score: 4.15
avg_peer_score: 4.30
trend: "improving"          # improving / stable / declining
top_strength: "定式化の的確さ"
top_weakness: "代替案の具体性"
recent_topics:
- "点群GNN設計"
- "時系列異常検知"
- "最適化アルゴリズム比較"
```

**適性判断の基準**:

| 判断基準 | 優先/回避 | 理由 |
|---|---|---|
| trend = "improving" | 優先 | フィードバックを活かして成長している |
| trend = "declining" | 回避候補 | 最近の議論で貢献度が下がっている |
| recent_topics にテーマ類似あり | 優先 | 関連する過去議論の蓄積がある |
| avg_peer_score ≥ 4.0 | 優先 | 他者からの評価が高い |
| top_weakness がテーマに致命的 | 回避候補 | 今回のテーマでは弱点が顕在化しやすい |

**指揮者プロンプトでの反映**:

```
【各ロールの過去パフォーマンス】
- 🧮 理論屋: trend=improving, 強み「定式化」, 弱み「代替案の具体性」
→ 前回「代替案を具体的に」とフィードバック済み。今回は改善が期待できる。

- 😈 穴探し: trend=stable, 強み「反例の具体性」, 弱み「否定が先行しすぎる」
→ 今回のテーマでは穴探しが特に重要。ただし「建設的に」と念押しする。
```

---

### 4.3.3 ロール間のバランス（攻め / 守り / 俯瞰）

議論が一方向に偏らないよう、指揮者はロールの「立場」のバランスを意識して選定します。

**立場の分類**:

| 分類 | ロール | 議論における機能 |
|---|---|---|
| **攻め**（提案・拡張） | 🧮 理論屋, 🤖 実装屋, 📚 文献屋 | 新しいアイデア・情報を持ち込む |
| **守り**（検証・批判） | 😈 穴探し, 🔬 実験屋 | 提案の穴を見つけ、地に足をつける |
| **俯瞰**（方向修正） | 🎯 鳥の目 | 議論全体の方向性を確認・修正 |

**バランスルール**:

```
- 参加AI数が3の場合: 攻め1 + 守り1 + (攻めor俯瞰)1
- 参加AI数が4の場合: 攻め2 + 守り1 + 俯瞰1
- 参加AI数が5の場合: 攻め2 + 守り2 + 俯瞰1
- 参加AI数が6の場合: 攻め3 + 守り2 + 俯瞰1
```

**例外**: テーマが「ブレインストーミング」的な場合は攻め比率を上げる。テーマが「既存手法の問題点分析」の場合は守り比率を上げる。

**指揮者プロンプトでの制約**:

```
【選定制約】
- 最低1体は「批判的視点」を持つロールを含めること (😈 or 🔬)
- 全員が同じ方向を向かないこと（同意しすぎ問題の予防）
- 参加AI数は {max_agents} 体以内
```

---

## 4.4 議論計画の生成

### 4.4.1 ラウンド構成の決定

指揮者はテーマの性質に応じて、議論を複数ラウンドに分割します。各ラウンドは独立した目標を持ちます。

**典型的なラウンド構成パターン**:

```
パターンA: 標準的な技術議論 (4-5ラウンド)
R1: 問題の定式化・分解 (🧮📚中心)
R2: 穴探し・前提の検証 (😈🔬中心)
R3: 統合・解決策の構築 (全員)
R4: 実験計画への落とし込み (🔬🤖中心)
R5: 最終確認 (全員, 短い)

パターンB: 手法比較 (3-4ラウンド)
R1: 各手法の特性整理 (📚🧮中心)
R2: 条件別の優劣議論 (全員)
R3: 推奨条件の合意形成 (全員)
R4: 最終確認 (全員, 短い)

パターンC: バグ/問題の原因分析 (3ラウンド)
R1: 現象の整理・仮説列挙 (全員)
R2: 仮説の検証・絞り込み (😈🔬中心)
R3: 対策案の合意 (全員)

パターンD: 探索的ブレインストーミング (5-6ラウンド)
R1: 自由発想 (攻め組中心, free_talk)
R2: 自由発想続き (攻め組中心, free_talk)
R3: 整理・分類 (🎯中心)
R4: 有望アイデアの深掘り (全員)
R5: 穴探し (😈中心)
R6: まとめ (全員, 短い)
```

**指揮者プロンプト**:

```
【ラウンド構成の設計指針】
- 各ラウンドに明確な「目標」を設定すること
- 序盤は「広げる」、中盤は「深める/壊す」、終盤は「収束する」流れ
- ラウンド数は時間制限内に収まる範囲で設定（推定時間を計算すること）
- 各ラウンドの参加者は目標に適したロールを選ぶ
- 全員参加ラウンドは最大2回まで（それ以上は散漫になる）
```

---

### 4.4.2 各ラウンドの level 配分

指揮者は各ラウンドの重要度に応じて `level`（reasoning_effort / thinking budget）を配分します。

**配分戦略**:

```
序盤（問題理解）:     medium — まだ方向が定まらないので中程度で十分
中盤（深掘り/批判）:  high   — 議論の核心。深い思考が必要
終盤（合意形成）:     low    — 結論の確認のみ。速度重視
```

**具体例**（5ラウンドの場合）:

| ラウンド | 目標 | level | 理由 |
|---|---|---|---|
| R1 | 問題の分解 | medium | 幅広く情報を出す段階 |
| R2 | 批判的検証 | medium | 穴を見つけるには中程度で十分 |
| R3 | 統合議論 | **high** | 核心。全視点を統合する深い思考が必要 |
| R4 | 実験計画 | medium | 具体的だが定型的 |
| R5 | 最終確認 | **low** | Yes/No + 残課題のみ |

**level と推定時間の対応**:

| level | GPT-5系の推定応答時間 | Claude(thinking)の推定応答時間 |
|---|---|---|
| minimal | ~3秒 | — (thinking無効) |
| low | ~5秒 | ~5秒 (budget=4000) |
| medium | ~10秒 | ~12秒 (budget=8000) |
| high | ~20秒 | ~22秒 (budget=16000) |

---

### 4.4.3 時間配分計算

指揮者は各ラウンドの時間予算を算出し、全体が時間制限内に収まることを検証します。

**計算ロジック**:

```python
class TurnCalculator:
"""指揮者の時間配分計算を補助"""

LEVEL_TIME_MAP = {
"minimal": 3.0,
"low": 5.0,
"medium": 10.0,
"high": 20.0,
}

CONDUCTOR_OVERHEAD_SEC = 3.0  # 進行管理1回あたりのオーバーヘッド

def calculate_round_time(self, round_config: RoundConfig) -> float:
"""1ラウンドの推定所要時間"""
n_speakers = len(round_config.speakers)
level_time = self.LEVEL_TIME_MAP[round_config.level]

if round_config.pattern == "one_shot":
# 各AI 1発言ずつ
utterance_time = n_speakers * level_time
elif round_config.pattern == "ping_pong":
# 2者が交互に、最大で speakers数×2 発言
utterance_time = n_speakers * 2 * level_time
elif round_config.pattern == "free_talk":
# 最大発言数 × level_time (上限あり)
max_utterances = min(n_speakers * 3, 8)
utterance_time = max_utterances * level_time

return utterance_time + self.CONDUCTOR_OVERHEAD_SEC

def calculate_total_time(self, plan: DiscussionPlan) -> float:
"""計画全体の推定所要時間"""
total = 0
for rc in plan.round_config:
total += self.calculate_round_time(rc)
return total

def fits_in_budget(self, plan: DiscussionPlan, time_limit: float) -> bool:
"""計画が時間制限内に収まるか (10%マージン込み)"""
estimated = self.calculate_total_time(plan)
phase3_overhead = 25.0  # Phase 3 の推定時間
return (estimated + phase3_overhead) < time_limit * 0.9
```

**時間が収まらない場合の調整**:

指揮者は計画が時間制限を超える場合、以下の優先順位で調整します:

```
1. 最終確認ラウンドの level を low → minimal に下げる
2. 各ラウンドの level を1段階ずつ下げる（high→medium, medium→low）
3. ラウンド数を削減する（優先度の低いラウンドを統合）
4. 参加AI数を減らす（最も寄与が低いと判断されるロールを除外）
```

**指揮者プロンプト内の時間制約**:

```
【時間制約】
- 制限時間: {time_limit_sec} 秒
- 各levelの推定時間: minimal=3秒, low=5秒, medium=10秒, high=20秒
- 進行管理オーバーヘッド: 1ラウンドあたり3秒
- Phase 3（統合）の推定時間: 25秒
- 合計が制限時間の90%以内に収まる計画を立てること

もし収まらない場合は:
- ラウンド数を減らす
- level を下げる
- 参加AI数を減らす
いずれかで調整すること。調整した場合はその理由を明記。
```

---

### 4.4.4 発言パターンの選択（one_shot / ping_pong / free_talk）

各ラウンドの「発言の仕方」を制御するパターンです。指揮者がラウンドの目標に応じて選択します。

**パターン定義**:

| パターン | 発言順 | 発言回数 | 適する場面 |
|---|---|---|---|
| `one_shot` | 固定順 (計画通り) | 各AI 1回ずつ | 情報出し、最終確認、報告 |
| `ping_pong` | 2者が交互 | 各2〜3回ずつ | 対立する2者の深掘り、相互質問 |
| `free_talk` | Conductor が動的決定 | 上限あり (max 8発言) | 統合議論、ブレインストーミング |

**各パターンの進行管理**:

```python
# one_shot: 計画順に1回ずつ
async def run_one_shot(self, speakers: list[str], context: dict):
for speaker in speakers:
utterance = await self.get_utterance(speaker, context)
context["log"].append(utterance)

# ping_pong: 2者が交互に応答
async def run_ping_pong(self, speakers: list[str], context: dict, max_exchanges: int = 3):
speaker_a, speaker_b = speakers[0], speakers[1]
for i in range(max_exchanges):
utterance_a = await self.get_utterance(speaker_a, context)
context["log"].append(utterance_a)
utterance_b = await self.get_utterance(speaker_b, context)
context["log"].append(utterance_b)
# 収束チェック（2者間の論点が解消されたか）
if self.mini_convergence_check(context):
break

# free_talk: Conductor が次の発言者を動的に決定
async def run_free_talk(self, speakers: list[str], context: dict, max_utterances: int = 8):
for i in range(max_utterances):
next_speaker = await self.decide_next_speaker(speakers, context)
utterance = await self.get_utterance(next_speaker, context)
context["log"].append(utterance)
# 目標達成チェック
if self.round_goal_achieved(context):
break
```

**free_talk での次発言者決定プロンプト**:

```
直前の発言を踏まえて、次に発言すべきAIを選んでください。

【直前の発言】
{last_utterance}

【参加AI】
{speakers_with_roles}

【このラウンドの目標】
{round_goal}

【判断基準】
- 直前の発言に対して最も有効な応答ができるAI
- まだ発言していないAI を優先
- 同じAIが連続3回発言しないこと

出力: 次の発言者の role_id のみ
```

---

## 4.5 各 AI への個別指示の生成

### 4.5.1 期待する貢献の明文化

指揮者は各 AI に対して「あなたに何を期待しているか」を具体的に伝えます。これにより、AI の発言が散漫にならず、議論に集中した内容になります。

**個別指示の構成要素**:

```python
@dataclass
class PrivateInstruction:
role_id: str
expected_contribution: str    # 何を出してほしいか
focus_points: list[str]       # 特に注意してほしい観点
constraints: list[str]        # やってはいけないこと
context_from_plan: str        # 議論計画上の位置づけ
feedback_reminder: str        # 過去フィードバックからの改善依頼
speaking_rules: str           # 発言形式のルール
```

**指揮者プロンプト（個別指示生成部分）**:

```
各AIに対して、以下の形式で個別指示を生成してください。

【形式】
{
"role_id": "theorist",
"expected_contribution": "このラウンドで〇〇を提供してほしい",
"focus_points": ["特に注意してほしい観点1", "観点2"],
"constraints": ["やってはいけないこと1"],
"context_from_plan": "議論全体の中でのあなたの位置づけ"
}

【生成の指針】
- expected_contribution は具体的かつ検証可能に
- 「良い発言をしてください」のような曖昧な指示は禁止
- 各AIの expertise と weakness を踏まえた指示にすること
```

**生成例**:

```json
{
"theorist": {
"expected_contribution": "点群→グラフ変換の定式化と、GNN層の表現力の理論限界を明示してほしい",
"focus_points": [
"kNNグラフ vs radius graph の理論的差異",
"Weisfeiler-Leman test の実用上の影響"
],
"constraints": [
"実装の話は🤖に任せること",
"計算量を必ずO記法で明示すること"
],
"context_from_plan": "R1で問題の数学的基盤を固める。R3で統合議論に参加。"
},
"devil": {
"expected_contribution": "他のAIの提案に対して、破綻するケースを具体的に示してほしい",
"focus_points": [
"密度不均一データでの動作",
"前提としているmanifold仮定が崩れるケース"
],
"constraints": [
"全否定しない。良い点は認めてから指摘すること",
"穴を指摘したら修復案も1つ添えること"
],
"context_from_plan": "R2で集中的に前提を検証。R3にも参加して統合議論でも遠慮なく指摘。"
}
}
```

---

### 4.5.2 過去フィードバックの反映

指揮者は各ロールの `feedback_history` から直近の改善点を抽出し、個別指示に組み込みます。

**FeedbackManager からの情報取得**:

```python
class FeedbackManager:
def generate_context_from_history(self, role_id: str) -> str:
"""過去のフィードバックから改善依頼テキストを生成"""
role = self.load_role(role_id)
history = role.get("feedback_history", [])

if not history:
return ""

recent = history[-3:]  # 直近3回
context_parts = []

for h in recent:
if h.get("improvements_noted"):
for imp in h["improvements_noted"]:
context_parts.append(f"- 過去の改善点: {imp}")
if h.get("orchestrator_feedback"):
context_parts.append(f"- 指揮者からの期待: {h['orchestrator_feedback']}")

return "\n".join(context_parts[-5:])  # 最大5項目
```

**個別指示への組み込み方**:

```
【あなたへの過去フィードバック（改善を期待しています）】
- 過去の改善点: 中盤以降の批判が弱まる傾向がある
- 過去の改善点: 代替案の具体性が不足
- 指揮者からの期待: 後半ラウンドでも遠慮なく指摘を続けること。批判後は必ず具体的な代替案を添えること。

→ 今回はこの点を意識して発言してください。
```

---

### 4.5.3 発言ルールの付与

全 AI に共通する発言ルールと、ロール固有のルールを組み合わせて付与します。

**共通発言ルール**（全 AI に付与）:

```
【発言ルール（共通）】
- 1回の発言は50〜150文字。短く鋭く。
- チャットの会話テンポで。論文口調禁止。
- 1発言で言いたいことは1つだけ。複数あるなら分けて発言する。
- 相手の発言を受けてから自分の意見を述べる。
- 「たしかに」「でもさ」「ちょっと待って」「あ、それいいね」等を自然に使う。
- 数式はテキスト表現で自然に混ぜる (O(N²), ∑, ∈)
- 論文引用は (著者+年) で簡潔に
- ビジネス的観点（ROI、市場性等）には言及しない
```

**expertise レベル別の追加ルール**:

```python
EXPERTISE_RULES = {
"beginner": [
"専門用語を使ったら直後に括弧で説明を入れる",
"数式は最小限。直感的な説明を優先",
"「要するに」「ざっくり言うと」を多用",
],
"intermediate": [
"基本概念の説明は不要",
"計算量やオーダーの議論は自然に",
"論文名は出してOKだが簡潔に",
],
"expert": [
"説明不要。本質だけ議論",
"数式を躊躇なく使う",
"未発表の着想レベルの議論もOK",
"論文のlimitationや再現性の問題にも踏み込む",
],
}
```

**ロール固有ルールの例**（YAML の system_prompt から）:

```
# 📚 文献屋 固有ルール:
- 存在が不確かな論文には必ず [要確認] をつける
- 知らない分野・手法については「そこは詳しくない」と正直に言う
- arXiv preprint は「(Author+年, arXiv)」と区別する

# 😈 穴探し 固有ルール:
- 全部否定しない。良い点は「それは筋いい、ただし…」と認めてから指摘
- 致命的な穴と些末な穴を区別する
- 修復不可能な穴を見つけたら、代替アプローチを提案する
```

---

## 4.6 指揮者モデルの引数指定

ユーザーは CLI 引数で指揮者（Phase 1）のモデルを指定できます。

### CLI オプション

```bash
python main.py idea \
--planner-model gpt-5.4 \      # Phase 1 のモデル
--conductor-model gpt-4.1 \    # Phase 2 の進行管理モデル
--synth-model claude-sonnet-4-5 \  # Phase 3 のモデル
"テーマ"
```

### デフォルト値

```yaml
# config/settings.yaml
models:
planner: "gpt-5.4"        # Phase 1
planner_level: "high"
conductor: "gpt-4.1"      # Phase 2 進行管理
conductor_temperature: 0.3
synthesizer: "claude-sonnet-4-5"  # Phase 3
synthesizer_thinking_budget: 16000
```

### モデル選定の指針

| 優先事項 | 推奨 planner モデル | 理由 |
|---|---|---|
| 最高品質の計画 | `gpt-5.4` (high) | 1M入力×深い推論 |
| 速度重視 | `gpt-5-mini` (medium) | 計画は軽量でも成立する場合あり |
| 全フェーズ Claude 統一 | `claude-sonnet-4-5` | 一貫した思考スタイル |
| リクエスト節約 | `gpt-4.1` | 1リクエストだけなので大差なし |

### 指揮者プロンプトの全体構造（まとめ）

Phase 1 で指揮者に送るプロンプトの完全構造:

```
[system]
あなたはAI Orchestraの指揮者です。
ユーザーの入力に対して、技術的に深い議論の計画を立ててください。

[user]
【ユーザー入力】
{user_input}

【制約条件】
- 制限時間: {time_limit_sec} 秒
- 参加可能AI数: 最大 {max_agents} 体
- expertise レベル: {expertise}
- 各levelの推定時間: minimal=3秒, low=5秒, medium=10秒, high=20秒
- 進行管理オーバーヘッド: 1ラウンドあたり3秒
- Phase 3 推定時間: 25秒

【利用可能ロール】
{全ロールYAMLのサマリ（名前、得意分野、domain_tags、過去実績）}

【議論の流れの方針】
1. まず問題を定式化する（🧮中心）
2. 先行研究の整理と差分の明確化（📚中心）
3. 提案アプローチの穴を探す（😈中心）
4. 実装フィージビリティの確認（🤖中心）
5. 実験設計への落とし込み（🔬中心）
（上記は参考。テーマに応じてカスタマイズすること）

【重視すること】
- 計算量オーダーの議論
- 前提条件の明示と、それが崩れるケースの検討
- 「なぜそれが理論的に正しいか」の根拠
- 再現可能な実験計画

【重視しないこと】
- ビジネス的観点、市場性、ROI
- 組織論、意思決定者への説明方法

【follow-up情報】(該当する場合のみ)
- 前回セッション: {previous_session_id}
- 前回の結論: {previous_conclusion}
- 前回の仮説テーブル: {previous_hypotheses}
- 前回の未解決問題: {unresolved_issues}
- 今回の新情報: {new_input}

【出力形式 (JSON)】
{
"odsc": {
"objective": "...",
"deliverable": "...",
"success_criteria": "...",
"convergence_threshold": 0.8
},
"selected_agents": [
{
"role_id": "...",
"model": "...",
"level": "...",
"reason": "...",
"expected_contribution": "..."
}
],
"discussion_plan": {
"estimated_rounds": 5,
"round_config": [
{
"round": 1,
"phase_name": "...",
"speakers": ["role_id_1", "role_id_2"],
"pattern": "one_shot",
"level": "medium",
"time_budget_sec": 40,
"goal": "..."
}
],
"total_estimated_time_sec": 190,
"total_estimated_requests": 52
},
"private_instructions": {
"role_id_1": {
"expected_contribution": "...",
"focus_points": ["...", "..."],
"constraints": ["..."],
"context_from_plan": "...",
"feedback_reminder": "..."
}
}
}
```

---

### 4章まとめ: 指揮者設計の原則

| 原則 | 実現方法 |
|---|---|
| **テーマに適応** | ODSC・参加AI・ラウンド構成をテーマごとにカスタム生成 |
| **学習する指揮者** | 過去フィードバックを参照し、選定・指示に反映 |
| **時間制約遵守** | 計算ベースで時間配分を検証し、超過なら計画を調整 |
| **明確な期待** | 各AIに「何を出してほしいか」を具体的に伝える |
| **バランス確保** | 攻め/守り/俯瞰の比率を意識した選定 |
| **柔軟性** | モデル・level・パターンを CLI 引数で上書き可能 |

---
