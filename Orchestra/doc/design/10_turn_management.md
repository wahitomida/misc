# 第10章 ターン管理アルゴリズム

---

## 10.1 ターン数算出ロジック

ターン数（ラウンド数と各ラウンド内の発言回数）は、指揮者が Phase 1 で計画する際に算出します。この算出は**時間制限**と**テーマの複雑度**の両面から決定されます。

### 10.1.1 テーマ複雑度の推定

指揮者はユーザーの入力テーマから「議論に必要な深さ」を推定し、それに基づいてラウンド数を決定します。

**複雑度の分類と目安ラウンド数**:

| 複雑度 | 特徴 | 目安ラウンド数 | 例 |
|---|---|---|---|
| Low | 明確な問いに対する直接的回答 | 2〜3 | 「〇〇のハイパーパラメータの意味は？」 |
| Medium | 複数の選択肢がある設計判断 | 4〜5 | 「点群のGNNでグラフ構築をどうする？」 |
| High | 未解決問題、研究の方向性決定 | 5〜7 | 「ラベルなしデータで自己教師あり学習のフレームワークを設計したい」 |
| Exploratory | 広い探索が必要、ブレインストーミング | 6〜8 | 「次の研究テーマを考えたい」 |

**指揮者プロンプト内の判定指示**:

```
【テーマの複雑度を判定してください】
以下の観点から複雑度を Low / Medium / High / Exploratory で判定し、
それに応じたラウンド数を設定してください。

判定観点:
- 答えが一意に定まるか？ (Yes → Low)
- 比較すべき選択肢の数は？ (2-3個 → Medium, 4個以上 → High)
- 未知の要素があるか？ (ある → High/Exploratory)
- 問題設定自体が曖昧か？ (はい → Exploratory)

ラウンド数の制約:
- 制限時間 {time_limit_sec} 秒から逆算して、実行可能な範囲で設定
- 最小2ラウンド、最大8ラウンド
```

**算出ロジックの実装**:

```python
class TurnCalculator:
"""ターン数と時間配分の算出"""

# 複雑度 → 基本ラウンド数
COMPLEXITY_ROUNDS = {
"low": 3,
"medium": 4,
"high": 5,
"exploratory": 6,
}

# 各levelの推定応答時間（秒/1発言）
LEVEL_TIME_MAP = {
"minimal": 3.0,
"low": 5.0,
"medium": 10.0,
"high": 20.0,
}

# 固定オーバーヘッド
CONDUCTOR_OVERHEAD_PER_ROUND = 3.0  # 進行管理1回あたり
CONVERGENCE_CHECK_TIME = 2.0         # 収束判定1回あたり
PHASE3_RESERVE = 25.0               # Phase 3 用の予約時間

def calculate_optimal_plan(
self,
complexity: str,
num_agents: int,
time_limit_sec: float,
) -> dict:
"""最適なラウンド数と時間配分を算出"""

base_rounds = self.COMPLEXITY_ROUNDS[complexity]
available_time = time_limit_sec - self.PHASE3_RESERVE

# 1ラウンドあたりの推定時間を計算
avg_level_time = self.LEVEL_TIME_MAP["medium"]  # 初期推定はmedium
overhead_per_round = (
self.CONDUCTOR_OVERHEAD_PER_ROUND +
self.CONVERGENCE_CHECK_TIME
)

# 各ラウンドの発言数（one_shot想定）
utterances_per_round = min(num_agents, 3)  # 全員発言しないラウンドもある
time_per_round = (
utterances_per_round * avg_level_time + overhead_per_round
)

# 時間制限内に収まるラウンド数を計算
max_possible_rounds = int(available_time / time_per_round)
actual_rounds = min(base_rounds, max_possible_rounds)
actual_rounds = max(actual_rounds, 2)  # 最低2ラウンド

return {
"rounds": actual_rounds,
"time_per_round": time_per_round,
"total_estimated_time": actual_rounds * time_per_round,
"fits_in_budget": (actual_rounds * time_per_round) < available_time,
}
```

---

### 10.1.2 参加 AI 数との関係

参加 AI 数はラウンドあたりの発言数に直結します。多いほど1ラウンドの時間が長くなるため、ラウンド数を減らす必要が生じます。

**参加AI数とラウンド設計のバランス**:

| 参加AI | 1ラウンドの発言数目安 | 推奨ラウンド数 (5分制限) | 合計発言数 |
|---|---|---|---|
| 3体 | 2〜3 | 5〜6 | 12〜18 |
| 4体 | 2〜3 | 4〜5 | 10〜15 |
| 5体 | 2〜4 | 4〜5 | 10〜20 |
| 6体 | 2〜3 | 3〜4 | 8〜12 |

**重要**: 全員が毎ラウンド発言するわけではありません。指揮者は各ラウンドの目標に応じて**発言する AI を絞り込みます**。

```
Round 1: 問題定式化  → 🧮📚 のみ (2体)
Round 2: 穴探し      → 😈🔬 のみ (2体)
Round 3: 統合議論    → 全員 (5体)
Round 4: 実験計画    → 🔬🤖 のみ (2体)
Round 5: 最終確認    → 全員 (5体, low で短い)
```

---

### 10.1.3 level 別の推定所要時間

各 level での API 応答時間は、モデルと level の組み合わせで変わります。

**実測ベースの推定時間テーブル**:

| level | GPT-5.4 | GPT-5 | GPT-4.1 | Claude-sonnet-4-5 | Claude-sonnet-4-5 (thinking) |
|---|---|---|---|---|---|
| minimal | ~3秒 | ~2.5秒 | ~1.5秒 | ~2秒 | — (thinking無効) |
| low | ~5秒 | ~4秒 | ~2.5秒 | ~4秒 | ~5秒 (budget=4K) |
| medium | ~10秒 | ~8秒 | ~5秒 | ~8秒 | ~12秒 (budget=8K) |
| high | ~20秒 | ~15秒 | ~8秒 | ~15秒 | ~22秒 (budget=16K) |

**設定ファイルでの定義**:

```yaml
# config/settings.yaml
level_time_estimates:
minimal: 3
low: 5
medium: 10
high: 20

# モデル補正係数（基準: gpt-5.4）
model_time_multiplier:
gpt-5.4: 1.0
gpt-5: 0.8
gpt-5-mini: 0.6
gpt-4.1: 0.5
gpt-4.1-mini: 0.4
claude-sonnet-4-5: 0.9
claude-sonnet-4-5-thinking: 1.2
claude-sonnet-4: 0.85
claude-opus-4-1: 1.1
```

**精密な推定時間計算**:

```python
def estimate_utterance_time(self, model: str, level: str) -> float:
"""特定のモデル×levelでの1発言の推定時間"""
base_time = self.LEVEL_TIME_MAP[level]
multiplier = self.settings.model_time_multiplier.get(model, 1.0)
return base_time * multiplier
```

---

## 10.2 時間制限の管理

### 10.2.1 デフォルト5分（設定変更可）

**デフォルト値と設定方法**:

```yaml
# config/settings.yaml
time_limit_default_sec: 300  # 5分
```

```bash
# CLI での上書き
python main.py idea --time-limit 600 "複雑なテーマ"   # 10分
python main.py idea --time-limit 120 "簡単な質問"     # 2分
```

**時間制限の構成要素**:

```
┌──────────── 制限時間 (300秒) ────────────────────────┐
│                                                       │
│  Phase 1    Phase 2 (議論本体)       Phase 3          │
│  [~5秒]    [~245秒]                 [~25秒]          │
│             ↑                        ↑                │
│             議論に使える時間          統合用予約時間     │
│             = 制限 - Phase1 - Phase3                  │
│             = 300 - 5 - 25 = 270秒                   │
│             (さらに10%マージン → 実質243秒)           │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

### 10.2.2 TimeKeeper による残り時間追跡

```python
import time
from dataclasses import dataclass, field
from enum import Enum

class TimePressure(Enum):
RELAXED = "relaxed"      # 残り50%以上
MODERATE = "moderate"    # 残り20-50%
URGENT = "urgent"        # 残り5-20%
CRITICAL = "critical"    # 残り5%未満

@dataclass
class TimeKeeper:
"""議論全体の時間管理"""

time_limit_sec: float = 300.0
phase1_actual_sec: float = 0.0       # Phase 1 の実績時間
phase3_reserve_sec: float = 25.0     # Phase 3 用の予約時間
safety_margin: float = 0.9           # 90% を実効上限とする
start_time: float = field(default_factory=time.time)
round_times: list[float] = field(default_factory=list)

@property
def elapsed(self) -> float:
"""セッション開始からの経過時間"""
return time.time() - self.start_time

@property
def discussion_budget(self) -> float:
"""Phase 2 で使える総時間"""
return (
self.time_limit_sec * self.safety_margin
- self.phase1_actual_sec
- self.phase3_reserve_sec
)

@property
def discussion_elapsed(self) -> float:
"""Phase 2 開始からの経過時間"""
return self.elapsed - self.phase1_actual_sec

@property
def remaining(self) -> float:
"""Phase 2 の残り時間"""
return max(0, self.discussion_budget - self.discussion_elapsed)

@property
def pressure(self) -> TimePressure:
"""現在の時間圧力レベル"""
ratio = self.remaining / self.discussion_budget if self.discussion_budget > 0 else 0
if ratio > 0.5:
return TimePressure.RELAXED
elif ratio > 0.2:
return TimePressure.MODERATE
elif ratio > 0.05:
return TimePressure.URGENT
else:
return TimePressure.CRITICAL

def can_start_next_round(self, estimated_round_sec: float) -> bool:
"""次のラウンドを開始可能か（完了まで時間が足りるか）"""
return self.remaining > estimated_round_sec * 1.2  # 20%マージン

def record_round(self, duration_sec: float):
"""ラウンドの実績時間を記録"""
self.round_times.append(duration_sec)

def get_moving_average(self, window: int = 3) -> float:
"""直近N回の平均ラウンド時間（推定精度向上用）"""
if not self.round_times:
return 30.0  # デフォルト推定
recent = self.round_times[-window:]
return sum(recent) / len(recent)

def estimated_remaining_rounds(self, planned_time_per_round: float) -> int:
"""残り時間で実行可能なラウンド数の推定"""
if planned_time_per_round <= 0:
return 0
# 実績ベースの推定を優先
actual_avg = self.get_moving_average()
effective_time = max(actual_avg, planned_time_per_round)
return int(self.remaining / effective_time)
```

---

### 10.2.3 次ラウンド開始可否の判定

```python
class Conductor:
async def run_discussion(self, plan: OrchestraPlan) -> DiscussionLog:
"""議論全体の進行"""

for i, round_config in enumerate(plan.discussion_plan.round_config):
# === 時間チェック ===
estimated_time = self._estimate_round_time(round_config)

if not self.time_keeper.can_start_next_round(estimated_time):
# 時間不足 → 圧力レベルに応じて対応
action = self._handle_time_shortage(round_config, i)

if action == "terminate":
discussion_log.early_termination = "time_limit"
discussion_log.termination_detail = (
f"Round {round_config.round} 開始前に時間不足を検知。"
f"残り {self.time_keeper.remaining:.0f}秒 < "
f"推定 {estimated_time:.0f}秒"
)
break
elif action == "shorten":
round_config = self._create_shortened_round(round_config)
# shortened round を実行して終了

# === ラウンド実行 ===
round_start = time.time()
round_log = await self.run_round(round_config, plan)
round_duration = time.time() - round_start

self.time_keeper.record_round(round_duration)
discussion_log.rounds.append(round_log)

# ... 収束判定等

def _estimate_round_time(self, round_config: RoundConfig) -> float:
"""ラウンドの推定所要時間"""
n_speakers = len(round_config.speakers)
level_time = self.turn_calculator.LEVEL_TIME_MAP[round_config.level]

if round_config.pattern == "one_shot":
utterance_time = n_speakers * level_time
elif round_config.pattern == "ping_pong":
utterance_time = min(n_speakers * 2, 6) * level_time
elif round_config.pattern == "free_talk":
max_utterances = min(n_speakers * 3, 8)
utterance_time = max_utterances * level_time

overhead = (
self.turn_calculator.CONDUCTOR_OVERHEAD_PER_ROUND +
self.turn_calculator.CONVERGENCE_CHECK_TIME
)

return utterance_time + overhead

def _handle_time_shortage(self, round_config: RoundConfig, round_idx: int) -> str:
"""時間不足時の対応決定"""
pressure = self.time_keeper.pressure

if pressure == TimePressure.CRITICAL:
return "terminate"
elif pressure == TimePressure.URGENT:
# 残りが1ラウンド分はある → 短縮版で最終ラウンド
if self.time_keeper.remaining > 15:
return "shorten"
else:
return "terminate"
else:  # MODERATE
return "shorten"
```

---

## 10.3 動的計画変更

### 10.3.1 時間超過時のラウンド短縮

ラウンドの実績時間が計画を超過した場合、残りのラウンドを動的に短縮します。

```python
class DynamicPlanAdjuster:
"""議論中の動的計画変更"""

def adjust_for_time_overrun(
self,
plan: DiscussionPlan,
completed_rounds: list[RoundLog],
time_keeper: TimeKeeper,
) -> list[RoundConfig]:
"""時間超過を検知し、残りラウンドの計画を調整"""

# 超過量の計算
total_overrun = 0.0
for i, completed in enumerate(completed_rounds):
planned = plan.round_config[i].time_budget_sec
actual = completed.duration_sec
total_overrun += max(0, actual - planned)

if total_overrun <= 5.0:
# 5秒以内の超過は無視
return plan.round_config[len(completed_rounds):]

remaining_configs = plan.round_config[len(completed_rounds):]
remaining_time = time_keeper.remaining

# 戦略1: level を下げて高速化
adjusted = []
for rc in remaining_configs:
new_level = self._downgrade_level_if_needed(rc.level, total_overrun)
new_budget = self._recalculate_budget(rc, new_level, remaining_time, len(remaining_configs))
adjusted.append(RoundConfig(
round=rc.round,
phase_name=rc.phase_name,
speakers=rc.speakers,
pattern=rc.pattern,
level=new_level,
time_budget_sec=new_budget,
goal=rc.goal,
))

return adjusted

def _downgrade_level_if_needed(self, current_level: str, overrun: float) -> str:
"""超過量に応じてlevelを下げる"""
order = ["high", "medium", "low", "minimal"]
current_idx = order.index(current_level)

if overrun > 30:
# 30秒以上超過 → 2段階下げ
return order[min(current_idx + 2, len(order) - 1)]
elif overrun > 15:
# 15秒以上超過 → 1段階下げ
return order[min(current_idx + 1, len(order) - 1)]
else:
return current_level

def _recalculate_budget(
self,
rc: RoundConfig,
new_level: str,
remaining_time: float,
remaining_rounds: int,
) -> float:
"""残り時間を均等に再配分"""
return remaining_time / max(remaining_rounds, 1)
```

**調整の会話ログ表示**:

```
🎼 [時間調整] Round 2 が12秒超過 (実績52秒 vs 計画40秒)
🎼 [計画変更] Round 3: level high→medium に変更 (推定80秒→50秒)
🎼 [計画変更] Round 4: level medium→low に変更 (推定40秒→20秒)
```

---

### 10.3.2 早期収束時のラウンド省略

収束閾値に達した場合、残りの計画ラウンドをスキップします。

```python
class Conductor:
async def handle_early_convergence(
self,
convergence_score: float,
threshold: float,
current_round: int,
plan: OrchestraPlan,
) -> str:
"""早期収束時の処理"""

remaining_rounds = plan.discussion_plan.round_config[current_round:]

if convergence_score >= threshold:
# 閾値達成 → 最終確認ラウンドだけ実行して終了
if self._has_confirmation_round(remaining_rounds):
# 最終確認ラウンドが計画にある → それだけ実行
return "skip_to_confirmation"
else:
# 最終確認ラウンドがない → 即座に終了
return "terminate"

elif convergence_score >= threshold * 0.9:
# 閾値の90%に達している → あと1ラウンドで十分な可能性
return "one_more_round"

return "continue"

async def run_quick_confirmation(self, plan: OrchestraPlan) -> RoundLog:
"""早期収束時の簡易最終確認ラウンド"""

confirmation_config = RoundConfig(
round=99,  # 特殊ラウンド番号
phase_name="最終確認（早期収束）",
speakers=[a.role_id for a in plan.selected_agents],
pattern="one_shot",
level="low",  # 短く
time_budget_sec=20,
goal="結論への同意確認と残課題の明示",
)

return await self.run_round(confirmation_config, plan)
```

**会話ログでの見え方**:

```
🎼 [収束: 0.85] 閾値(0.80)を超えました。残りRound 4,5 をスキップ。
🎼 [判断] 簡易最終確認ラウンドを実行して終了します。

── 最終確認（早期収束）──

🎼→全員 収束しました。各自1文で最終同意と残課題をお願いします。
🧮: OK。残課題はmulti-scaleのk選択の自動化。
😈: OK。耐環境性の実機検証が最優先リスク。
🔬: OK。まずregression test構築から着手。
```

---

### 10.3.3 収束停滞時の計画再立案

収束スコアが3ラウンド連続で改善しない場合、計画を再立案します。

```python
class Conductor:
async def handle_stagnation(
self,
plan: OrchestraPlan,
discussion_log: DiscussionLog,
) -> OrchestraPlan | None:
"""収束停滞時の対応"""

scores = discussion_log.score_history
if len(scores) < 3:
return None

# 直近3ラウンドのスコア変化を確認
recent = scores[-3:]
if max(recent) - min(recent) < 0.05:
# 停滞検知 → 対応策を選択

remaining_time = self.time_keeper.remaining

if remaining_time < 30:
# 時間がない → 強制終了
return None  # Noneは「再立案せず終了」の意味

# 再立案プロンプト
replan = await self._generate_replan(plan, discussion_log, remaining_time)
return replan

return None  # 停滞していない

async def _generate_replan(
self,
original_plan: OrchestraPlan,
discussion_log: DiscussionLog,
remaining_time: float,
) -> OrchestraPlan:
"""停滞時の計画再立案"""

prompt = f"""議論が停滞しています。計画を再立案してください。

【現状】
- 収束スコア推移: {discussion_log.score_history}
- 直近3ラウンドでスコアが改善していません
- 残り時間: {remaining_time:.0f}秒
- 未解決の対立点: {discussion_log.rounds[-1].convergence_check.remaining_disagreements}

【元の計画で残っているラウンド】
{self._format_remaining_plan(original_plan, discussion_log)}

【再立案の方針（以下から選択）】
1. 対立点を「未解決」として残し、合意可能な部分だけまとめる
2. 問題を分割し、合意できる部分から順に処理する
3. 新しい切り口（別のAIの視点）を導入して議論を動かす
4. 抽象度を変える（より具体的に / より抽象的に）

【出力】
残り{remaining_time:.0f}秒で実行可能な修正計画をJSON形式で。
最大2ラウンド以内。"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.3,
max_tokens=500,
)

return self._parse_replan(response["content"])
```

**会話ログでの見え方**:

```
🎼 [停滞検知] 直近3ラウンドでスコア変化なし (0.55→0.57→0.56)
🎼 [計画再立案] 対立点「kの自動選択方法」を未解決として棚上げ。
🎼 [計画再立案] 残り120秒で合意可能な部分（グラフ構築方法+PE選択）をまとめる。

── Round 5 (再立案): 部分合意 ──

🎼→全員 kの選択は実験で決めることとし、それ以外の設計方針を確定させましょう。
```

---

## 10.4 ラウンド内発言回数の制御

### 10.4.1 one_shot パターン

各 AI が**1回ずつ順番に発言**するパターン。最もシンプルで予測可能。

**適する場面**:
- 情報出しフェーズ（各自の知見を順に提示）
- 最終確認ラウンド（全員が結論を述べる）
- 報告フェーズ（コードレビューの各リーダーが結果報告）

**実装**:

```python
async def run_one_shot(
self,
round_config: RoundConfig,
plan: OrchestraPlan,
) -> list[Utterance]:
"""各AIが1回ずつ発言"""

utterances = []

for speaker_id in round_config.speakers:
agent = self.agents[speaker_id]

# コンテキスト構築
context = self._build_round_context(
round_config, plan, utterances
)

# 発言取得
utterance = await agent.speak(context)
utterances.append(utterance)

# メモリに追加
self.memory.add_utterance(utterance, round_config.round)

# CLI に表示
self.progress.show_utterance(utterance)

return utterances
```

**特性**:

| 項目 | 値 |
|---|---|
| 発言回数 | speakers数 × 1 |
| 所要時間 | speakers数 × level_time |
| 予測可能性 | ✅ 完全に予測可能 |
| 相互作用 | △ 後の発言者は前を参照できるが、反論の余地なし |
| API リクエスト | speakers数 |

---

### 10.4.2 ping_pong パターン

**2者が交互に応答**し合うパターン。深い掘り下げに適しています。

**適する場面**:
- 対立する2者の深掘り（🧮 vs 😈 など）
- 相互質問フェーズ（コードレビューでのパートリーダー間質問）
- 特定の論点について2つの視点を戦わせたい時

**実装**:

```python
async def run_ping_pong(
self,
round_config: RoundConfig,
plan: OrchestraPlan,
max_exchanges: int = 3,
) -> list[Utterance]:
"""2者が交互に応答"""

utterances = []
speakers = round_config.speakers[:2]  # 最初の2者

for exchange in range(max_exchanges):
for speaker_id in speakers:
agent = self.agents[speaker_id]

# コンテキスト構築（直前の相手の発言を含む）
context = self._build_round_context(
round_config, plan, utterances
)

utterance = await agent.speak(context)
utterances.append(utterance)
self.memory.add_utterance(utterance, round_config.round)
self.progress.show_utterance(utterance)

# ミニ収束チェック（2者間の論点が解消されたか）
if exchange >= 1:  # 最低2往復は保証
resolved = await self._check_mini_convergence(
utterances[-4:],  # 直近4発言
round_config.goal,
)
if resolved:
break

return utterances

async def _check_mini_convergence(
self,
recent_utterances: list[Utterance],
goal: str,
) -> bool:
"""ping_pong内での論点解消チェック"""

prompt = f"""以下の2者の対話で、論点は解消されましたか？

{self._format_utterances(recent_utterances)}

ラウンドの目標: {goal}

出力: "resolved" または "ongoing" のみ"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=10,
)

return "resolved" in response["content"].lower()
```

**特性**:

| 項目 | 値 |
|---|---|
| 発言回数 | 2 × max_exchanges (最大6) |
| 所要時間 | 発言回数 × level_time |
| 予測可能性 | ○ 上限は予測可能。早期終了あり |
| 相互作用 | ✅ 深い。相手の発言に直接応答 |
| API リクエスト | 4〜6 + ミニ収束チェック1〜2 |

**会話ログでの見え方**:

```
── Round 2: 穴探し (ping_pong: 🧮 vs 😈) ──

🧮: kNNグラフはmanifold上の測地距離近似として理論的に自然だよ。
😈: でもmanifold仮定が成り立たない箇所は？CADの角とかエッジ部分。
🧮: 良い指摘。multi-scale approach で対応できる。k=10,20,40で複数粒度。
😈: multi-scaleでもkの値自体が恣意的。k=10と11で結果変わらない保証は？
🧮: うーん、理論的保証は難しい。感度分析で確認するしかないか。
😈: じゃあそこは実験の仮説として残そう。H4として追加。

🎼 [mini-convergence: resolved] 論点「kNNの理論的正当性」は解消。
```

---

### 10.4.3 free_talk パターン

**Conductor が毎発言ごとに次の発言者を動的に決定**するパターン。最も自然な議論に近いが、予測困難。

**適する場面**:
- 統合議論フェーズ（全視点を組み合わせてアイデアを練る）
- ブレインストーミング
- 複数の論点が絡み合う複雑な議論

**実装**:

```python
async def run_free_talk(
self,
round_config: RoundConfig,
plan: OrchestraPlan,
max_utterances: int = 8,
) -> list[Utterance]:
"""Conductor が動的に次の発言者を決定"""

utterances = []
utterance_counts = {s: 0 for s in round_config.speakers}
consecutive_same = 0
last_speaker = None

for i in range(max_utterances):
# 次の発言者を決定
next_speaker = await self._decide_next_speaker(
round_config.speakers,
utterances,
utterance_counts,
round_config.goal,
)

# 同じ人が連続3回は禁止
if next_speaker == last_speaker:
consecutive_same += 1
if consecutive_same >= 2:
# 別の人を強制選択
alternatives = [s for s in round_config.speakers if s != next_speaker]
next_speaker = alternatives[0] if alternatives else next_speaker
consecutive_same = 0
else:
consecutive_same = 0

agent = self.agents[next_speaker]

# コンテキスト構築
context = self._build_round_context(round_config, plan, utterances)

# 追加指示（堂々巡り検知時など）
additional = ""
if i > 0 and i % 4 == 0:
# 4発言ごとに堂々巡りチェック
repetition = await self.repetition_detector.check_repetition(utterances)
if repetition.is_repeating:
additional = await self._generate_new_topic_instruction(repetition, next_speaker)

utterance = await agent.speak(context, additional_instruction=additional)
utterances.append(utterance)
self.memory.add_utterance(utterance, round_config.round)
self.progress.show_utterance(utterance)

utterance_counts[next_speaker] = utterance_counts.get(next_speaker, 0) + 1
last_speaker = next_speaker

# ラウンド目標達成チェック（3発言ごと）
if i >= 2 and (i + 1) % 3 == 0:
goal_achieved = await self._check_round_goal(
utterances, round_config.goal
)
if goal_achieved:
break

# 時間チェック
if not self.time_keeper.can_start_next_round(
self.turn_calculator.LEVEL_TIME_MAP[round_config.level]
):
break

return utterances

async def _decide_next_speaker(
self,
speakers: list[str],
utterances: list[Utterance],
utterance_counts: dict[str, int],
goal: str,
) -> str:
"""次の発言者を動的に決定"""

if not utterances:
# 最初の発言者はランダム or 計画の最初
return speakers[0]

last = utterances[-1]

prompt = f"""次に発言すべきAIを選んでください。

【直前の発言】
{last.speaker_display}: {last.content}

【参加AI (発言回数)】
{self._format_speaker_counts(speakers, utterance_counts)}

【このラウンドの目標】
{goal}

【判断基準】
- 直前の発言に最も有効な応答ができるAI
- 発言回数が少ないAIを優先
- 同じAIが連続しない（直前と異なるAIを選ぶ）
- 目標達成に最も貢献できるAI

出力: role_id のみ（1語）"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=20,
)

selected = response["content"].strip().lower()

# バリデーション
if selected not in speakers:
# パースに失敗したら発言数最少のAIを選択
min_count = min(utterance_counts.values())
selected = [s for s, c in utterance_counts.items() if c == min_count][0]

return selected

async def _check_round_goal(self, utterances: list[Utterance], goal: str) -> bool:
"""ラウンド目標が達成されたか判定"""

prompt = f"""以下の議論で、ラウンドの目標は達成されましたか？

【目標】
{goal}

【議論】
{self._format_utterances(utterances[-5:])}

出力: "achieved" または "not_yet" のみ"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=10,
)

return "achieved" in response["content"].lower()
```

**特性**:

| 項目 | 値 |
|---|---|
| 発言回数 | 可変 (上限 max_utterances=8) |
| 所要時間 | 可変 (level_time × 発言数 + 判定コスト) |
| 予測可能性 | △ 上限のみ予測可能。実際は早期終了しうる |
| 相互作用 | ✅ 最も自然。動的に最適な応答者を選択 |
| API リクエスト | max_utterances + 判定2〜4回 |

**追加コスト**: 次発言者決定に毎回1リクエスト消費。ラウンド目標チェックに2〜3リクエスト。

**コスト対策**: 次発言者決定を `gpt-4.1-mini` (最軽量) に変更することで追加コストを最小化。

```python
# 次発言者決定は最軽量モデルで十分
response = await self.api_client.call(
model="gpt-4.1-mini",  # 最速・最安
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=20,
)
```

---

### 3パターンの比較まとめ

| 観点 | one_shot | ping_pong | free_talk |
|---|---|---|---|
| 発言数（3AI,5分） | 3〜5 | 4〜6 | 5〜8 |
| 時間の予測性 | ✅ 正確 | ○ やや変動 | △ 変動大 |
| 議論の深さ | △ 浅い | ✅ 深い（2者間） | ○ 中程度（広く） |
| API リクエスト効率 | ✅ 最小 | ○ やや多い | △ 最多（判定含む） |
| 適する Phase | 情報出し、確認 | 対立点の深掘り | 統合議論 |
| Conductor の負荷 | 低 | 中 | 高 |

**指揮者の典型的な組み合わせ**:

```
Round 1 (情報出し):    one_shot (全員1回ずつ)
Round 2 (深掘り):      ping_pong (🧮 vs 😈)
Round 3 (統合):        free_talk (全員で自由討論)
Round 4 (実験計画):    one_shot (🔬🤖 が報告)
Round 5 (最終確認):    one_shot (全員1文ずつ, level=low)
```

---

### 10章まとめ: ターン管理の原則

| 原則 | 実現方法 |
|---|---|
| **時間厳守** | TimeKeeper が全フェーズを通じて残り時間を追跡。20%マージン確保 |
| **動的適応** | 実績時間ベースで計画を動的調整。超過時は level を下げる |
| **早期終了** | 収束閾値達成で即座に Phase 3 へ。無駄なラウンドを省略 |
| **停滞対応** | 3ラウンド連続停滞で計画再立案。棚上げ戦略を適用 |
| **パターン選択** | テーマと目標に応じて one_shot/ping_pong/free_talk を使い分け |
| **コスト意識** | free_talk の追加リクエストは軽量モデル(gpt-4.1-mini)に委譲 |

---
