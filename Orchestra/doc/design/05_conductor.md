# 第5章 進行管理（Conductor）設計

---

## 5.1 進行管理の役割

Conductor は Phase 2（議論進行）のリアルタイム制御を担うモジュールです。指揮者（Orchestrator）が作った計画を「実行」する役割であり、オーケストラで言えば**テンポを刻み、各奏者に出番を示す**存在です。

### Conductor が行うこと

```
1. 各ラウンドの開始指示を出す（参加者に目標を伝える）
2. 発言順序を決定し、各AIの発言を取得する
3. 各ラウンド終了時に収束度を判定する
4. 時間を監視し、超過前に対応する
5. 堂々巡りを検知し、議論を前に進める
6. 同意しすぎを検知し、対立を促す
7. 将来的に、人間の介入を受け付ける
```

### Conductor が行わないこと

```
- 計画の策定（それはOrchestratorの仕事）
- 自ら議論に参加すること（発言内容を生成するのはAgentの仕事）
- 最終的な要約・統合（それはSynthesizerの仕事）
```

### 設計上の特徴

Conductor には**軽量・高速なモデル**を割り当てます。Conductor 自身の処理が遅いと議論テンポが崩れるためです。

| Conductor の処理 | モデル | level / temperature | 応答時間目標 |
|---|---|---|---|
| ラウンド開始指示 | gpt-4.1 | temperature=0.3 | <2秒 |
| 次発言者決定 (free_talk) | gpt-4.1 | temperature=0.0 | <1.5秒 |
| 収束判定 | gpt-4.1 | temperature=0.0 | <2秒 |
| 堂々巡り検知 | gpt-4.1 | temperature=0.0 | <1.5秒 |

### 実装クラスの概要

```python
class Conductor:
"""Phase 2: 議論の進行管理を担当"""

def __init__(
self,
api_client: ResilientAPIClient,
agents: dict[str, Agent],
memory: ConversationMemory,
time_keeper: TimeKeeper,
intervention: InterventionHandler,
settings: Settings,
model: str = "gpt-4.1",
):
self.api_client = api_client
self.agents = agents
self.memory = memory
self.time_keeper = time_keeper
self.intervention = intervention
self.settings = settings
self.model = model

def run_discussion(self, plan: OrchestraPlan) -> DiscussionLog:
"""計画に基づいて議論全体を進行する"""
discussion_log = DiscussionLog()

for round_config in plan.discussion_plan.round_config:
# 時間チェック
if not self.time_keeper.can_start_next_round(
self.estimate_round_time(round_config)
):
discussion_log.early_termination = "time_limit"
break

# 介入チェック（将来用）
intervention_input = self.intervention.check_intervention(
round_config.round, self.memory.get_context_summary()
)
if intervention_input:
self.handle_intervention(intervention_input, plan)

# ラウンド実行
round_log = self.run_round(round_config, plan)
discussion_log.rounds.append(round_log)

# 収束判定
if round_log.convergence_check.score >= plan.odsc.convergence_threshold:
discussion_log.early_termination = "converged"
break

return discussion_log
```

---

## 5.2 発言順序の制御

### 5.2.1 fixed（固定順）

計画で指定された `speakers` リストの順番通りに発言を取得します。

**適する場面**:
- one_shot パターン（各AI 1回ずつ情報を出す）
- 最終確認ラウンド（全員が順に結論を述べる）
- 明確な流れが必要な場面（A が提案 → B が批判 → C が折衷案）

**実装**:

```python
class FixedOrder:
"""計画通りの固定順序"""

def get_speaking_order(
self,
speakers: list[str],
round_config: RoundConfig,
context: dict,
) -> list[str]:
return speakers  # そのまま返す
```

**会話ログでの見え方**:

```
💡 創造的発想家: （提案を述べる）
🔍 批判的思考家: （批判する）
🔧 実務家: （折衷案を出す）
```

---

### 5.2.2 dialectic（対立構造）

対立する立場のロールを交互に配置し、弁証法的な議論を促します。

**適する場面**:
- ping_pong パターン（2者の深掘り）
- 明確に対立する視点がある場合
- 議論の深化が目的の場合

**実装**:

```python
class DialecticOrder:
"""対立するロールを交互に配置"""

# ロール間の対立関係マップ
OPPOSITION_MAP = {
"theorist": ["implementer", "experimentalist"],  # 理論 vs 実践
"devil": ["theorist", "literature"],              # 破壊 vs 構築
"bird_eye": ["implementer"],                      # 俯瞰 vs 細部
"creative_thinker": ["devil"],                    # 創造 vs 批判
}

def get_speaking_order(
self,
speakers: list[str],
round_config: RoundConfig,
context: dict,
) -> list[str]:
if len(speakers) != 2:
# 2者でない場合は対立ペアを抽出
pair = self._find_best_opposition_pair(speakers)
return self._interleave(pair, max_exchanges=3)

return self._interleave(speakers, max_exchanges=3)

def _interleave(self, pair: list[str], max_exchanges: int) -> list[str]:
"""A, B, A, B, A, B の順を生成"""
order = []
for i in range(max_exchanges):
order.append(pair[0])
order.append(pair[1])
return order

def _find_best_opposition_pair(self, speakers: list[str]) -> list[str]:
"""speakers の中から最も対立するペアを選ぶ"""
best_pair = speakers[:2]
for s in speakers:
opposites = self.OPPOSITION_MAP.get(s, [])
for opp in opposites:
if opp in speakers:
return [s, opp]
return best_pair
```

**会話ログでの見え方**:

```
🧮 理論屋: kNNグラフはmanifold上の測地距離近似として理論的に自然だよ。
😈 穴探し: でもmanifold仮定が成り立たない箇所は？CADの角とか。
🧮 理論屋: 良い指摘。それはmulti-scaleで対応できると思う。
😈 穴探し: multi-scaleでもkの選び方が恣意的じゃない？適応的に選ぶ根拠は？
🧮 理論屋: うーん、確かに理論的根拠は薄い。ヒューリスティックになる。
😈 穴探し: じゃあそこは実験で決めるしかないね。仮説として残そう。
```

---

### 5.2.3 shuffle（ランダム）

発言順をランダムに決定します。思考の偶発性を活かしたい場合に使います。

**適する場面**:
- ブレインストーミングフェーズ
- 固定順では特定の発言が最後に来ることで影響されるのを防ぎたい場合

**実装**:

```python
import random

class ShuffleOrder:
"""毎ラウンドでランダム順序"""

def __init__(self, seed: int | None = None):
self.rng = random.Random(seed)  # 再現性のためseed指定可能

def get_speaking_order(
self,
speakers: list[str],
round_config: RoundConfig,
context: dict,
) -> list[str]:
shuffled = speakers.copy()
self.rng.shuffle(shuffled)
return shuffled
```

### free_talk での動的順序決定

free_talk パターンでは上記3つの静的戦略ではなく、**Conductor が毎発言ごとに次の発言者を動的に決定**します。

```python
class DynamicOrder:
"""Conductor LLM が文脈に基づいて次発言者を決定"""

def __init__(self, conductor_api: ResilientAPIClient, model: str):
self.api = conductor_api
self.model = model

async def decide_next_speaker(
self,
speakers: list[str],
context: dict,
utterance_count: dict[str, int],
) -> str:
prompt = f"""直前の発言を踏まえて、次に発言すべきAIを選んでください。

【直前の発言】
{context["last_utterance"]["speaker"]}: {context["last_utterance"]["content"]}

【参加AI（発言回数）】
{self._format_speakers_with_counts(speakers, utterance_count)}

【このラウンドの目標】
{context["round_goal"]}

【ルール】
- 直前の発言に最も有効な応答ができるAIを選ぶ
- まだ発言が少ないAIを優先する
- 同じAIが連続3回発言しない
- 目標達成に最も貢献できるAIを選ぶ

出力: role_id のみ（1語）"""

response = await self.api.call(
model=self.model,
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=20,
)
return response["content"].strip()
```

---

## 5.3 収束判定アルゴリズム

### 5.3.1 収束スコア計算プロンプト

各ラウンド終了時に、Conductor は議論の「収束度」を 0.0〜1.0 のスコアで計算します。

**収束判定プロンプト**:

```python
CONVERGENCE_CHECK_PROMPT = """以下の議論ログを分析し、参加者間の合意度を評価してください。

【ODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【このラウンドの目標】
{round_goal}

【直近の議論（このラウンド全文）】
{round_utterances}

【これまでの収束スコア推移】
{previous_scores}

【評価の観点】
1. 参加者間で方向性の合意があるか（全員が同じ結論に向かっているか）
2. 主要な論点について具体的な結論が出ているか
3. 未解決の対立点がどの程度残っているか
4. Success Criteria の達成度はどの程度か

【出力形式 (JSON)】
{{
"score": 0.75,
"reasoning": "合意度の根拠（1-2文）",
"remaining_disagreements": ["未解決の論点1", "論点2"],
"recommendation": "continue"
}}

score の目安:
- 0.0-0.3: 方向性すら定まっていない
- 0.3-0.5: 方向性は見えるが具体的合意なし
- 0.5-0.7: 主要論点の一部で合意、残りは未解決
- 0.7-0.85: おおむね合意、細部のみ未解決
- 0.85-1.0: 完全合意

recommendation:
- "continue": 通常通り次ラウンドへ
- "conclude": 十分な合意が得られた。最終確認ラウンドへ進める
- "pivot": 議論が行き詰まっている。方向転換が必要"""
```

---

### 5.3.2 閾値との比較

```python
class ConvergenceChecker:
"""収束判定ロジック"""

def __init__(self, api_client: ResilientAPIClient, model: str = "gpt-4.1"):
self.api_client = api_client
self.model = model
self.score_history: list[float] = []

async def check(
self,
round_log: RoundLog,
plan: OrchestraPlan,
memory: ConversationMemory,
) -> ConvergenceResult:
"""ラウンド終了時の収束判定"""

prompt = CONVERGENCE_CHECK_PROMPT.format(
objective=plan.odsc.objective,
success_criteria=plan.odsc.success_criteria,
round_goal=round_log.goal,
round_utterances=self._format_utterances(round_log),
previous_scores=self._format_score_history(),
)

response = await self.api_client.call(
model=self.model,
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=200,
)

result = self._parse_json_response(response["content"])
self.score_history.append(result.score)
return result

def should_terminate(self, result: ConvergenceResult, threshold: float) -> bool:
"""議論を終了すべきか判定"""
return result.score >= threshold or result.recommendation == "conclude"

def is_stagnating(self, window: int = 3, tolerance: float = 0.05) -> bool:
"""収束度が停滞しているか（堂々巡りの兆候）"""
if len(self.score_history) < window:
return False
recent = self.score_history[-window:]
return (max(recent) - min(recent)) < tolerance
```

---

### 5.3.3 早期終了 / 続行 / 方向転換の3択

収束判定の `recommendation` に基づいて、Conductor は3つのアクションから選びます。

```python
async def handle_convergence_result(
self,
result: ConvergenceResult,
plan: OrchestraPlan,
current_round: int,
) -> str:
"""収束結果に基づく次のアクション決定"""

# Case 1: 十分に収束 → 早期終了
if self.should_terminate(result, plan.odsc.convergence_threshold):
return "terminate"

# Case 2: 停滞検知 → 方向転換
if self.is_stagnating():
return "pivot"

# Case 3: recommendation が "pivot" → 方向転換
if result.recommendation == "pivot":
return "pivot"

# Case 4: 通常続行
return "continue"
```

**各アクションの処理**:

| アクション | 処理内容 |
|---|---|
| `terminate` | 残りのラウンドをスキップし、Phase 3 へ移行 |
| `continue` | 計画通り次のラウンドを実行 |
| `pivot` | 方向転換プロンプトを生成し、次ラウンドの冒頭で議論の方向を変える |

**方向転換（pivot）の実装**:

```python
async def generate_pivot_instruction(
self,
result: ConvergenceResult,
context: dict,
) -> str:
"""議論が行き詰まった際の方向転換指示を生成"""

prompt = f"""議論が停滞しています。方向転換の指示を生成してください。

【停滞の状況】
- 直近3ラウンドの収束度: {self.score_history[-3:]}
- 未解決の対立点: {result.remaining_disagreements}

【方向転換の方法（いずれかを選択）】
1. 未解決の対立点を「仮に〇〇とする」で暫定合意し、別の論点に移る
2. 抽象度を上げて「そもそも」の問いに立ち返る
3. 具体例を1つ設定し、その例に絞って議論する
4. 対立点を「未解決問題」として残し、解決可能な部分から進める

次のラウンドの冒頭で全AIに伝える指示（100文字以内）:"""

response = await self.api_client.call(
model=self.model,
messages=[{"role": "user", "content": prompt}],
temperature=0.3,
max_tokens=100,
)
return response["content"]
```

---

## 5.4 堂々巡り検知

### 5.4.1 発言類似度チェック

AI 同士が同じ論点を繰り返している場合を検知します。収束判定の `is_stagnating()` とは別に、**発言内容レベル**での重複を検出します。

```python
class RepetitionDetector:
"""堂々巡り（同じ論点の繰り返し）を検知"""

def __init__(self, api_client: ResilientAPIClient, model: str = "gpt-4.1"):
self.api_client = api_client
self.model = model

async def check_repetition(
self,
recent_utterances: list[Utterance],
window: int = 4,
) -> RepetitionResult:
"""直近N発言に繰り返しがあるか判定"""

if len(recent_utterances) < window:
return RepetitionResult(is_repeating=False)

prompt = f"""以下の直近{window}発言を分析し、堂々巡りが起きているか判定してください。

【直近の発言】
{self._format_recent(recent_utterances[-window:])}

【判定基準】
- 同じ論点が2回以上繰り返されている → 堂々巡り
- 新しい情報・視点が追加されず、同じ主張の言い換え → 堂々巡り
- 前の発言を踏まえて深まっている → 堂々巡りではない

【出力形式 (JSON)】
{{
"is_repeating": true/false,
"repeated_topic": "繰り返されている論点（あれば）",
"suggestion": "議論を前に進めるための提案"
}}"""

response = await self.api_client.call(
model=self.model,
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=150,
)
return self._parse_result(response["content"])
```

**検知のタイミング**:
- free_talk パターンでは **4発言ごと** にチェック
- one_shot / ping_pong パターンでは **ラウンド終了時** にチェック（収束判定と同時）

---

### 5.4.2 新論点の強制

堂々巡りが検知された場合、Conductor は次の発言者に「新しい論点を出せ」と指示します。

```python
async def force_new_topic(
self,
detection_result: RepetitionResult,
next_speaker: str,
context: dict,
) -> str:
"""堂々巡り検知後に新論点を強制する追加指示"""

instruction = f"""⚠️ 議論が堂々巡りしています。

【繰り返されている論点】
{detection_result.repeated_topic}

【あなたへの指示】
上記の論点は一旦横に置いてください。代わりに以下のいずれかを行ってください：
1. まったく別の角度から問題を見る
2. 具体的な数値例や反例を出して議論を動かす
3. 「そもそも」の問いに立ち返る
4. この論点を「未解決」として明示し、次に進む

普通に会話するトーンで、50〜150文字で発言してください。"""

return instruction
```

**会話ログでの見え方**:

```
🎼 [堂々巡り検知] 「kの最適値」について3発言同じ主張が繰り返されている
🎼→🔬 別の角度で。具体的な数値で議論を動かして。

🔬 実験屋: そこ机上で決めるの無理じゃない？k=10,20,40で実際にModelNet40回してablationした方が早い。たぶん30分で結果出る。
```

---

## 5.5 時間管理

### 5.5.1 TimeKeeper の実装

```python
import time
from dataclasses import dataclass, field

@dataclass
class TimeKeeper:
"""議論全体の時間管理"""

time_limit_sec: float = 300.0  # デフォルト5分
start_time: float = field(default_factory=time.time)
round_times: list[float] = field(default_factory=list)
phase3_reserve_sec: float = 25.0  # Phase 3 用に確保する時間

@property
def elapsed(self) -> float:
"""経過時間（秒）"""
return time.time() - self.start_time

@property
def remaining(self) -> float:
"""残り時間（秒）。Phase 3 予約分を差し引き"""
return max(0, self.time_limit_sec - self.elapsed - self.phase3_reserve_sec)

@property
def remaining_total(self) -> float:
"""Phase 3 予約を含む残り時間"""
return max(0, self.time_limit_sec - self.elapsed)

def can_start_next_round(self, estimated_round_sec: float) -> bool:
"""次のラウンドを開始して時間内に収まるか"""
return self.remaining > estimated_round_sec * 1.2  # 20%マージン

def record_round_time(self, duration: float):
"""ラウンドの実績時間を記録（以降の推定精度向上に使用）"""
self.round_times.append(duration)

def get_average_round_time(self) -> float:
"""実績ベースの平均ラウンド時間"""
if not self.round_times:
return 30.0  # デフォルト推定
return sum(self.round_times) / len(self.round_times)

def force_conclude(self) -> bool:
"""強制終了すべきか（残り時間ゼロ）"""
return self.remaining <= 0

def time_pressure_level(self) -> str:
"""現在の時間的余裕度"""
ratio = self.remaining / self.time_limit_sec
if ratio > 0.5:
return "relaxed"    # 余裕あり
elif ratio > 0.2:
return "moderate"   # やや急ぎ
elif ratio > 0.05:
return "urgent"     # 急ぎ
else:
return "critical"   # 即時終了
```

---

### 5.5.2 時間超過時の打ち切りロジック

```python
async def handle_time_pressure(
self,
time_keeper: TimeKeeper,
plan: OrchestraPlan,
current_round: int,
) -> TimeAction:
"""時間圧力に応じた対応を決定"""

pressure = time_keeper.time_pressure_level()

if pressure == "critical":
# 即時終了。現在のラウンドの途中でも打ち切る
return TimeAction(
action="force_terminate",
message="⏰ 時間切れ。議論を終了し、ここまでの内容でPhase 3に移行します。"
)

elif pressure == "urgent":
# 残りラウンドを全てスキップし、現ラウンドで終了
return TimeAction(
action="conclude_this_round",
message="⏰ 残り時間わずか。このラウンドで最終確認し、終了します。"
)

elif pressure == "moderate":
# 残りラウンドの level を下げて高速化
remaining_rounds = plan.discussion_plan.round_config[current_round:]
adjusted = self._downgrade_levels(remaining_rounds)
return TimeAction(
action="adjust_plan",
adjusted_rounds=adjusted,
message="⏰ 時間調整。残りラウンドの level を下げて進行します。"
)

else:  # "relaxed"
return TimeAction(action="continue")
```

**打ち切り時の会話ログ表示**:

```
🎼 [時間管理] 残り時間: 28秒 / 制限300秒。pressure=urgent
🎼 [判断] 残りラウンドをスキップ。このラウンドで最終確認して終了。
🎼→全員 時間が迫っています。各自1文で最終結論をお願いします。
```

---

### 5.5.3 ラウンド間の時間調整

各ラウンドの**実績時間**を記録し、以降のラウンドの時間配分を動的に調整します。

```python
class DynamicTimeAdjuster:
"""ラウンド実績に基づく時間調整"""

def adjust_remaining_plan(
self,
plan: DiscussionPlan,
completed_rounds: list[RoundLog],
time_keeper: TimeKeeper,
) -> list[RoundConfig]:
"""完了ラウンドの実績を踏まえて、残りラウンドの計画を調整"""

# 実績 vs 計画の差分を計算
total_overrun = 0.0
for i, completed in enumerate(completed_rounds):
planned_time = plan.round_config[i].time_budget_sec
actual_time = completed.duration_sec
total_overrun += (actual_time - planned_time)

remaining_rounds = plan.round_config[len(completed_rounds):]
remaining_time = time_keeper.remaining

if total_overrun <= 0:
# 予定より早い → 調整不要
return remaining_rounds

# 超過分を残りラウンドに分散して吸収
time_per_round_reduction = total_overrun / max(len(remaining_rounds), 1)

adjusted = []
for rc in remaining_rounds:
new_budget = rc.time_budget_sec - time_per_round_reduction
if new_budget < 15:
# 最低15秒は確保。代わりにlevelを下げる
adjusted.append(replace(rc, time_budget_sec=15, level=self._downgrade(rc.level)))
else:
adjusted.append(replace(rc, time_budget_sec=new_budget))

return adjusted

def _downgrade(self, level: str) -> str:
"""levelを1段階下げる"""
order = ["high", "medium", "low", "minimal"]
idx = order.index(level)
return order[min(idx + 1, len(order) - 1)]
```

**調整の可視化（指揮者メモ）**:

```
🎼 [内心] Round 2 が12秒超過した (実績52秒 vs 計画40秒)
🎼 [内心] 残りRound 3,4 の予算を各6秒ずつ削減: 80→74秒, 30→24秒
🎼 [内心] 全体としてはまだ制限内。問題なし。
```

---

## 5.6 同意しすぎ問題への対策

AI は他の AI の発言に同意しがちです（特に権威あるモデルの発言に対して）。これは議論の深化を阻害します。

### 問題の例

```
❌ こうなると議論が深まらない:
🧮 理論屋: kNNグラフがいいと思う。
🔬 実験屋: たしかに。kNNがよさそうですね。
🤖 実装屋: 同意です。kNNで行きましょう。
😈 穴探し: 私も賛成です。
→ 収束スコア 1.0 だが、何も深まっていない
```

### 対策1: ロール YAML での性格設定

😈 穴探しの system_prompt に「同意から入るな」と明記:

```yaml
# devil.yaml の system_prompt 内:
【重要な行動規範】
- 他者の意見にすぐ同意してはいけない
- まず「ちょっと待って」「でもさ」から入ること
- 同意する場合でも「条件付き同意」にすること
（「〇〇の場合は正しいけど、△△では壊れるよね」）
```

### 対策2: Conductor による同意検知

```python
class AgreementDetector:
"""同意しすぎの検知"""

async def check_excessive_agreement(
self,
recent_utterances: list[Utterance],
window: int = 3,
) -> bool:
"""直近N発言が全て同意的かチェック"""

if len(recent_utterances) < window:
return False

prompt = f"""以下の直近{window}発言を分析してください。

{self._format_utterances(recent_utterances[-window:])}

全員が同じ方向に同意しているだけで、新しい視点や批判が出ていない場合は true を返してください。
出力: true または false のみ"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=10,
)
return response["content"].strip().lower() == "true"
```

### 対策3: 同意検知時の介入

```python
async def handle_excessive_agreement(
self,
speakers: list[str],
context: dict,
) -> str:
"""同意しすぎ検知時の介入指示"""

# 😈 穴探しがいれば優先的に発言させる
devil_agents = [s for s in speakers if "devil" in s]
if devil_agents:
target = devil_agents[0]
else:
# いなければランダムに1体に反論を依頼
target = random.choice(speakers)

instruction = f"""⚠️ 議論が同意に偏っています。

【{target}への追加指示】
全員が同じ方向を向いています。あえて反対の立場から1つ指摘してください。
- この方針のリスクは？
- うまくいかないケースは？
- 見落としている前提は？
- もっと良い方法がないか？

反論が思いつかなくても、「あえて言うなら」の形で1つは出してください。"""

return instruction
```

**会話ログでの見え方**:

```
🎼 [同意検知] 直近3発言が全て同意的。議論の深化不足。
🎼→😈 全員同意してるけど、あえて壊してみて。リスクや見落としはない？

😈 穴探し: ちょっと待って。全員kNNで合意してるけど、点群の密度が不均一な場合にkNNだと物理的に離れた点が繋がる問題、誰も言ってないよね？
```

### 対策4: 計画段階での予防

指揮者が計画段階で以下を盛り込みます:

```
【Round 2の設計意図】
このラウンドでは😈を投入し、Round 1で出た合意を意図的に壊す。
全員が同じ方向を向いている時こそ、前提の検証が重要。
```

---

## 5.7 将来の人間介入ポイント設計

初期版（v1.0）では全自動で議論を進行しますが、将来の介入機能に備えてインターフェースを確保しておきます。

### 介入ハンドラのインターフェース

```python
from abc import ABC, abstractmethod
from typing import Optional

class InterventionHandler(ABC):
"""人間介入のインターフェース"""

@abstractmethod
def check_intervention(self, round_num: int, context: dict) -> Optional[str]:
"""
各ラウンド間で介入をチェック。

Args:
round_num: 現在のラウンド番号
context: 議論の現在状態（要約、収束度等）

Returns:
None: 介入なし（自動続行）
str: 人間からの指示テキスト
"""
pass

@abstractmethod
def notify_progress(self, event: str, data: dict) -> None:
"""進捗イベントの通知（UI更新用）"""
pass
```

### v1.0: NoIntervention（全自動）

```python
class NoIntervention(InterventionHandler):
"""初期版: 介入なし。全て自動進行。"""

def check_intervention(self, round_num: int, context: dict) -> Optional[str]:
return None  # 常に None（介入なし）

def notify_progress(self, event: str, data: dict) -> None:
pass  # CLI表示は別のObserverが担当
```

### 将来版: CLIIntervention（v1.1 想定）

```python
import sys
import select
import threading

class CLIIntervention(InterventionHandler):
"""CLI で途中介入可能なハンドラ"""

def __init__(self, wait_sec: float = 3.0):
self.wait_sec = wait_sec
self.pending_input: Optional[str] = None
self._start_input_listener()

def check_intervention(self, round_num: int, context: dict) -> Optional[str]:
"""ラウンド間で入力を確認"""
console.print(
f"\n[dim]── Round {round_num} 完了 "
f"(収束: {context['convergence']:.2f}) ──[/dim]"
)
console.print(
f"[dim]({self.wait_sec}秒以内にEnter以外を入力で介入 / "
f"Enter or 待機で自動続行)[/dim]"
)

# 一定時間入力を待つ
user_input = self._wait_for_input(self.wait_sec)

if user_input and user_input.strip():
return user_input.strip()
return None

def _wait_for_input(self, timeout: float) -> Optional[str]:
"""タイムアウト付き入力待ち"""
# プラットフォーム依存の実装（Unix: select, Windows: threading）
...
```

### 将来版: WebIntervention（v2.0 想定）

```python
class WebIntervention(InterventionHandler):
"""Web UI からの介入を受け付けるハンドラ"""

def __init__(self, websocket_url: str):
self.ws = WebSocketClient(websocket_url)

def check_intervention(self, round_num: int, context: dict) -> Optional[str]:
"""WebSocket 経由で介入を確認"""
self.ws.send({
"event": "round_complete",
"round": round_num,
"context": context,
"awaiting_input": True,
})
# クライアントからの応答を待つ（タイムアウト付き）
response = self.ws.receive(timeout=10.0)
if response and response.get("intervention"):
return response["intervention"]
return None

def notify_progress(self, event: str, data: dict) -> None:
"""全イベントをWebSocketで配信"""
self.ws.send({"event": event, "data": data})
```

### 介入が発生した場合の処理フロー

```python
# Conductor.run_discussion() 内

# ラウンド間で介入チェック
intervention_input = self.intervention.check_intervention(
round_config.round,
{
"convergence": last_convergence_score,
"summary": self.memory.get_context_summary(),
"remaining_time": self.time_keeper.remaining,
"completed_rounds": len(discussion_log.rounds),
}
)

if intervention_input:
# 人間の指示を指揮者に渡して計画を修正
adjusted_instruction = await self.process_intervention(
intervention_input, plan, current_round
)
# 次のラウンドの冒頭に介入内容を反映
next_round_prefix = f"🎼 [人間からの介入] {adjusted_instruction}"
self.memory.add_system_event(next_round_prefix)
```

### 介入で変更可能な項目

| 介入内容 | Conductor の対応 |
|---|---|
| 「〇〇の方向で考えて」 | 次ラウンドの全AIへの指示に追記 |
| 「△△は無視していい」 | 収束判定の remaining_disagreements から除外 |
| 「もう終わりにして」 | 即座に Phase 3 へ移行 |
| 「もう少し議論して」 | 時間制限を延長（上限あり） |
| 「□□も考慮して」 | 新しい論点として次ラウンドに追加 |
| 「〇〇を呼んで」 | 指定ロールを動的に追加 |

---

### 5章まとめ: Conductor 設計の原則

| 原則 | 実現方法 |
|---|---|
| **軽量・高速** | gpt-4.1 (minimal/temperature=0) で定型処理。議論のテンポを崩さない |
| **状況適応** | 収束度・時間・重複を常に監視し、動的に対応 |
| **議論品質の維持** | 堂々巡り検知・同意しすぎ検知で議論の深化を保証 |
| **時間厳守** | TimeKeeper による継続的監視。超過前に計画を調整 |
| **拡張準備** | InterventionHandler インターフェースで将来の介入に対応 |
| **観測可能性** | 全ての判断（収束判定、堂々巡り、時間調整）をログに記録 |

---
