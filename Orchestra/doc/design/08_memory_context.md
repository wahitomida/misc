# 第8章 会話メモリとコンテキスト管理

---

## 8.1 会話ログの JSON 構造

AI Orchestra の全ての会話は `discussion.json` に構造化して保存されます。このファイルは**機械処理用**であり、セッションの再現・分析・follow-up に使用します。

### 完全スキーマ

```json
{
"_schema_version": "1.0.0",
"_generated_by": "ai-orchestra v1.0",
"_generated_at": "2026-06-20T14:34:28+09:00",

"session": {
"id": "20260620_143052_idea",
"type": "idea_discussion",
"started_at": "2026-06-20T14:30:52+09:00",
"ended_at": "2026-06-20T14:34:28+09:00",
"duration_sec": 216,
"time_limit_sec": 300,
"user_prompt": "点群データからの特徴量抽出にGNNを適用する際の設計指針",
"expertise": "expert",
"cli_args": {
"planner_model": "gpt-5.4",
"conductor_model": "gpt-4.1",
"synth_model": "claude-sonnet-4-5",
"time_limit": 300,
"max_agents": 5
},
"follow_up": {
"is_follow_up": false,
"parent_session_id": null,
"chain_depth": 0,
"chain": []
}
},

"planning": {
"model": "gpt-5.4",
"level": "high",
"duration_sec": 4.2,
"tokens_used": {"input": 3200, "output": 2800},
"odsc": {
"objective": "...",
"deliverable": "...",
"success_criteria": "...",
"convergence_threshold": 0.8
},
"selected_agents": [
{
"role_id": "theorist",
"model": "gpt-5.4",
"level": "high",
"reason": "...",
"expected_contribution": "..."
}
],
"discussion_plan": {
"estimated_rounds": 5,
"round_config": [],
"total_estimated_time_sec": 190,
"total_estimated_requests": 52
},
"private_instructions": {
"theorist": {
"expected_contribution": "...",
"focus_points": [],
"constraints": [],
"context_from_plan": "...",
"feedback_reminder": "..."
}
}
},

"discussion": {
"rounds": [
{
"round": 1,
"phase_name": "問題の定式化",
"goal": "点群→グラフ変換の数学的定式化と既存手法の整理",
"pattern": "one_shot",
"level": "medium",
"started_at": "2026-06-20T14:31:15+09:00",
"ended_at": "2026-06-20T14:31:58+09:00",
"duration_sec": 43,
"time_budget_sec": 40,
"orchestrator_memo": "Round 1完了。43秒(予算40秒をやや超過、許容範囲)。",
"private_instructions_sent": {
"theorist": {
"instruction": "点群→グラフ変換の定式化と...",
"model": "gpt-4.1",
"tokens_used": {"input": 850, "output": 350},
"duration_sec": 1.8
},
"literature": {
"instruction": "PointNet系との比較軸を...",
"model": "gpt-4.1",
"tokens_used": {"input": 900, "output": 280},
"duration_sec": 1.5
}
},
"conductor_opening": {
"content": "Round 1開始。テーマ: 問題の定式化...",
"model": "gpt-4.1",
"tokens_used": {"input": 600, "output": 120},
"duration_sec": 1.2
},
"public_utterances": [
{
"sequence": 1,
"speaker": "theorist",
"speaker_display": "🧮 理論屋",
"type": "discussion",
"content": "まず整理。点群 P={p_i} ∈ R^{N×3} をグラフ G=(V,E) に変換する時点で...",
"model": "gpt-5.4",
"level": "medium",
"tokens_used": {"input": 2200, "output": 180},
"duration_sec": 8.3,
"reasoning_content": null
},
{
"sequence": 2,
"speaker": "literature",
"speaker_display": "📚 文献屋",
"type": "discussion",
"content": "PointNet (Qi+2017) は点ごとのMLP+max poolで...",
"model": "gpt-5.4",
"level": "medium",
"tokens_used": {"input": 2500, "output": 200},
"duration_sec": 9.1,
"reasoning_content": null
}
],
"convergence_check": {
"prompt_summary": "ラウンド1の議論を分析し合意度を...",
"model": "gpt-4.1",
"tokens_used": {"input": 3500, "output": 150},
"duration_sec": 1.8,
"result": {
"score": 0.35,
"reasoning": "問題空間の整理は進んだが方向性の合意はまだ",
"remaining_disagreements": ["グラフ構築方法の選択", "PEの必要性"],
"recommendation": "continue"
}
},
"repetition_check": null,
"agreement_check": null
}
],
"total_requests": 27,
"total_tokens": {"input": 62700, "output": 16500, "total": 79200},
"final_convergence_score": 0.88,
"early_termination": null,
"score_history": [0.35, 0.55, 0.82, 0.85, 0.88]
},

"evaluation": {
"self_evaluations": {
"theorist": {
"scores": {
"定式化の的確さ": 4,
"理論的根拠の提示": 5,
"計算量の意識": 4,
"議論の深化": 4
},
"avg_score": 4.25,
"reasoning": "...",
"key_contributions": ["...", "..."]
}
},
"peer_evaluations": {
"theorist": {
"evaluators": {
"devil": {"score": 5, "comment": "..."},
"experimentalist": {"score": 4, "comment": "..."}
},
"peer_avg_score": 4.5
}
},
"orchestrator_feedback": {
"overall_discussion_quality": 4.5,
"odsc_achievement": "...",
"per_agent_feedback": {
"theorist": "..."
}
}
},

"synthesis": {
"model": "claude-sonnet-4-5",
"level": "high",
"extended_thinking": {"enabled": true, "budget_tokens": 16000},
"duration_sec": 22.5,
"tokens_used": {"input": 32000, "output": 4500},
"reasoning_content_length": 12000,
"final_conclusion": "..."
},

"statistics": {
"total_requests": 35,
"total_tokens": {"input": 98000, "output": 23500, "total": 121500},
"total_duration_sec": 216,
"time_utilization": 0.72,
"requests_by_phase": {"planning": 1, "discussion": 27, "synthesis": 7},
"requests_by_model": {
"gpt-5.4": 12,
"gpt-4.1": 15,
"claude-sonnet-4-5": 8
}
}
}
```

### 会話タイプの分類

JSON 内で記録される会話は3つのタイプに分類されます:

| タイプ | JSON 内の位置 | 説明 |
|---|---|---|
| Type A: 個別指示 | `rounds[].private_instructions_sent` | 指揮者→AI への非公開指示 |
| Type B: 公開発言 | `rounds[].public_utterances` | AI の議論発言（メインの内容） |
| Type C: 内部判断 | `rounds[].orchestrator_memo`, `convergence_check` | 指揮者の判断・メモ |

---

## 8.2 ConversationMemory クラス設計

### 完全実装

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json

@dataclass
class TokenCount:
input: int = 0
output: int = 0
total: int = 0

class ConversationMemory:
"""議論の共有メモリ。全会話のログ管理とコンテキスト構築を担当。"""

def __init__(
self,
api_client: "ResilientAPIClient",
max_context_tokens: int = 5000,
summary_model: str = "gpt-4.1",
):
self.api_client = api_client
self.max_context_tokens = max_context_tokens
self.summary_model = summary_model

# 完全ログ（出力ファイル用）
self.full_log: list[dict] = []

# ラウンドごとの要約（コンテキスト構築用）
self.round_summaries: list[str] = []

# メタデータ
self.total_tokens = TokenCount()
self.total_requests: int = 0

# ラウンドごとの発言を保持（直近アクセス用）
self._rounds: dict[int, list[dict]] = {}

# システムイベント（堂々巡り検知、時間調整等）
self._system_events: list[dict] = []

def add_utterance(self, utterance: "Utterance", round_num: int):
"""発言をログに追加"""
entry = {
"round": round_num,
"sequence": utterance.sequence,
"speaker": utterance.speaker,
"speaker_display": utterance.speaker_display,
"type": utterance.type,
"content": utterance.content,
"model": utterance.model,
"level": utterance.level,
"tokens_used": {
"input": utterance.tokens_used.get("input", 0),
"output": utterance.tokens_used.get("output", 0),
},
"duration_sec": utterance.duration_sec,
"timestamp": datetime.now().isoformat(),
}

self.full_log.append(entry)

# ラウンド別にも保持
if round_num not in self._rounds:
self._rounds[round_num] = []
self._rounds[round_num].append(entry)

# トークン集計
self.total_tokens.input += entry["tokens_used"]["input"]
self.total_tokens.output += entry["tokens_used"]["output"]
self.total_tokens.total = self.total_tokens.input + self.total_tokens.output
self.total_requests += 1

def add_system_event(self, event: str, round_num: int = -1):
"""システムイベント（堂々巡り検知等）を記録"""
self._system_events.append({
"round": round_num,
"event": event,
"timestamp": datetime.now().isoformat(),
})

def get_round_utterances(self, round_num: int) -> list[dict]:
"""指定ラウンドの全発言を取得"""
return self._rounds.get(round_num, [])

def get_last_utterance(self, round_num: int) -> Optional[dict]:
"""指定ラウンドの最後の発言を取得"""
utterances = self.get_round_utterances(round_num)
return utterances[-1] if utterances else None

def get_context_for_agent(
self,
current_round: int,
agent_role_id: str,
context_budget: "ContextBudget",
) -> dict:
"""各AIに渡すコンテキストを生成（token上限考慮）"""

# 直近ラウンド（現在のラウンド）: 全文
current_utterances = self.get_round_utterances(current_round)

# 過去ラウンド: 全文入るか判定
all_previous = self._get_all_previous_utterances(current_round)
previous_text = self._format_utterances(all_previous)

total_estimate = context_budget.estimate_tokens(previous_text)

if total_estimate < self.max_context_tokens:
# 全文が入る場合: そのまま渡す
previous_summary = previous_text
else:
# 入らない場合: 要約を使う
previous_summary = "\n".join(self.round_summaries[:current_round])

return {
"previous_summary": previous_summary,
"current_round_utterances": current_utterances,
"last_utterance": self.get_last_utterance(current_round),
"system_events": [
e for e in self._system_events if e["round"] == current_round
],
}

def get_full_log_text(self) -> str:
"""全ログをテキスト形式で返す（Phase 3 の統合入力用）"""
lines = []
current_round = -1
for entry in self.full_log:
if entry["round"] != current_round:
current_round = entry["round"]
lines.append(f"\n--- Round {current_round} ---")
lines.append(f"{entry['speaker_display']}: {entry['content']}")
return "\n".join(lines)

def get_context_summary(self) -> str:
"""議論全体の短い要約（介入チェック等で使用）"""
if self.round_summaries:
return "\n".join(self.round_summaries)
# 要約がまだない場合は直近の発言数行
recent = self.full_log[-5:]
return "\n".join(f"{e['speaker_display']}: {e['content'][:50]}..." for e in recent)

async def summarize_round(self, round_log: "RoundLog"):
"""ラウンド終了時に要約を生成"""

utterances_text = "\n".join(
f"{u.speaker_display}: {u.content}"
for u in round_log.public_utterances
)

prompt = f"""以下の議論ラウンドを3行以内で要約してください。
要点・結論・重要な合意/対立のみ。会話調は不要。

【Round {round_log.round}: {round_log.phase_name}】
目標: {round_log.goal}
収束度: {round_log.convergence_check.score}

{utterances_text}

要約（3行以内）:"""

response = await self.api_client.call(
model=self.summary_model,
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=150,
)

summary = f"[R{round_log.round} {round_log.phase_name}] {response['content'].strip()}"
self.round_summaries.append(summary)
self.total_requests += 1

def export_json(self) -> dict:
"""discussion.json 用のデータをエクスポート"""
return {
"full_log": self.full_log,
"round_summaries": self.round_summaries,
"system_events": self._system_events,
"statistics": {
"total_requests": self.total_requests,
"total_tokens": {
"input": self.total_tokens.input,
"output": self.total_tokens.output,
"total": self.total_tokens.total,
},
},
}

def _get_all_previous_utterances(self, current_round: int) -> list[dict]:
"""現在ラウンドより前の全発言を取得"""
return [e for e in self.full_log if e["round"] < current_round]

def _format_utterances(self, utterances: list[dict]) -> str:
"""発言リストをテキスト形式に変換"""
lines = []
for u in utterances:
lines.append(f"{u['speaker_display']}: {u['content']}")
return "\n".join(lines)
```

---

## 8.3 コンテキストウィンドウ戦略

### 8.3.1 全ログが token 上限内の場合

議論の初期（Round 1〜2）や、参加 AI が少ない場合、全ログが token 上限に収まります。この場合は**要約を作らず、全文をそのまま渡します**。

```python
# ConversationMemory.get_context_for_agent() 内の判定

if total_estimate < self.max_context_tokens:
# 全文が入る → 要約ロスなしで最高品質のコンテキスト
previous_summary = previous_text
```

**トークン推定の典型値**:

| 状況 | 推定 token | max_context_tokens (5000) との比較 |
|---|---|---|
| Round 1 完了後 (3AI × 各100文字) | ~600 | ✅ 全文入る |
| Round 2 完了後 (3AI × 各100文字 × 2) | ~1,200 | ✅ 全文入る |
| Round 3 完了後 (5AI × 各120文字 × 3) | ~3,600 | ✅ 全文入る |
| Round 5 完了後 (5AI × 各150文字 × 5) | ~7,500 | ❌ 要約必要 |

**メリット**: 情報ロスなし。全発言をそのまま参照できるため、発言の文脈を正確に理解可能。

---

### 8.3.2 要約 + 直近全文のハイブリッド

token 上限を超える場合、**過去ラウンドは要約、直近ラウンドは全文**のハイブリッド方式を適用します。

```
┌────────────────────────────────────────────────────────┐
│                  Agent に渡すコンテキスト                  │
├────────────────────────────────────────────────────────┤
│                                                         │
│  【過去のサマリ】(各ラウンド3行程度に圧縮)               │
│  [R1 問題の定式化] kNNグラフとradius graphの理論的差異、   │
│  WL-testの限界が議論された。manifold仮定の重要性が指摘。   │
│                                                         │
│  [R2 穴探し] 密度不均一データでkNNが破綻するケースが指摘。 │
│  multi-scale approach が修復案として提案された。           │
│                                                         │
│  [R3 表現力の限界] Positional Encodingの選択肢が整理。     │
│  spectral PEはオフラインのみ、リアルタイムは相対位置PE推奨。│
│                                                         │
│  ───────────────────────────────────────────────────── │
│                                                         │
│  【直近ラウンド (現在のラウンド) 全文】                    │
│  🧮 理論屋: 結論をまとめると、multi-scale kNN + ...       │
│  🔬 実験屋: 比較すべき条件を整理すると...                 │
│  🤖 実装屋: PyGの実装だと...                             │
│  😈 穴探し: ちょっと待って、multi-scaleのk選択は...       │
│                                                         │
└────────────────────────────────────────────────────────┘
```

**要約の品質保証**:

要約は `gpt-4.1` (temperature=0.0) で生成し、以下の品質基準を守ります:

```
要約に含めるべき情報:
✅ 合意された結論
✅ 未解決の対立点
✅ 提案された仮説
✅ 重要な数値（計算量、性能値等）

要約から省いてよい情報:
❌ 会話の流れ（「Aが言って、Bが反論して…」）
❌ 挨拶・同意の相槌
❌ 些末な補足情報
```

---

### 8.3.3 gpt-5.4 (1M token) を活用した全文入力

Phase 3（統合・要約）では `gpt-5.4` または `claude-sonnet-4-5` (200K) を使用します。これらのモデルは入力コンテキストが非常に大きいため、**議論ログ全文を要約なしで一括入力**できます。

```python
class Synthesizer:
"""Phase 3: 統合。全文入力が可能なモデルを使用。"""

async def synthesize(
self,
plan: OrchestraPlan,
discussion_log: DiscussionLog,
memory: ConversationMemory,
model: str = "claude-sonnet-4-5",
) -> SynthesisResult:
# 全ログをテキスト化（要約なし）
full_log_text = memory.get_full_log_text()

# トークン推定
estimated_tokens = self._estimate_tokens(full_log_text)

# 200K token 以内なら全文入力
if estimated_tokens < 180_000:  # 安全マージン
context = full_log_text
else:
# 超える場合（非常に長い議論）: gpt-5.4 (1M) にフォールバック
model = "gpt-5.4"
context = full_log_text  # 1M あれば通常は入る

# 統合レポート生成
...
```

**モデル別の入力戦略**:

| 使用場面 | モデル | 入力上限 | 戦略 |
|---|---|---|---|
| 各AI の発言時 (Phase 2) | 各種 | 128K〜400K | 要約+直近全文 (5K token 目安) |
| 進行管理 (Conductor) | gpt-4.1 | 128K | 直近ラウンドのみ (2K token 目安) |
| 最終統合 (Phase 3) | claude-sonnet-4-5 | 200K | **全文入力** |
| 超長議論の統合 | gpt-5.4 | 1M | **全文入力** |

---

## 8.4 指揮者による中間要約の生成タイミング

### タイミングの決定ロジック

```python
class SummaryScheduler:
"""要約生成のタイミングを管理"""

def __init__(self, max_context_tokens: int = 5000):
self.max_context_tokens = max_context_tokens

def should_summarize(
self,
memory: ConversationMemory,
completed_round: int,
) -> bool:
"""このラウンド完了時に要約を生成すべきか判定"""

# 判定基準1: 次のラウンドで全文がtoken上限を超えそうか
all_utterances = memory._get_all_previous_utterances(completed_round + 1)
all_text = memory._format_utterances(all_utterances)
current_tokens = self._estimate_tokens(all_text)

if current_tokens > self.max_context_tokens * 0.7:
# 70%に達したら要約を開始（余裕を持って）
return True

# 判定基準2: ラウンド数が3以上（蓄積が十分）
if completed_round >= 3 and not memory.round_summaries:
return True

return False
```

### タイミングの典型パターン

```
Round 1 完了: token推定 600  → 要約不要（全文入る）
Round 2 完了: token推定 1200 → 要約不要（全文入る）
Round 3 完了: token推定 3600 → 70%超え → ✅ Round 1,2,3 の要約を生成
Round 4 以降: 新ラウンドのみ追加で要約
```

### 要約生成のコスト

| 処理 | モデル | token 消費 | 所要時間 |
|---|---|---|---|
| 1ラウンドの要約 | gpt-4.1 | ~200 input + ~100 output | ~1.5秒 |
| 5ラウンド一括要約 | gpt-4.1 | ~1000 input + ~500 output | ~3秒 |

要約生成自体は軽量であり、議論のテンポを大きく崩しません。

### 要約のキャッシュと再利用

```python
# 要約は一度生成したら変更しない（イミュータブル）
# 新しいラウンドの要約のみ追加される

class ConversationMemory:
async def ensure_summaries_up_to_date(self, current_round: int):
"""必要な要約が揃っているか確認し、不足分を生成"""
for r in range(len(self.round_summaries), current_round):
round_log = self._get_round_log(r)
if round_log:
await self.summarize_round(round_log)
```

---

## 8.5 follow-up 時のコンテキスト引き継ぎ

### 引き継ぎデータの構造

`--follow-up` で前回セッションを指定した場合、以下のデータが新セッションに引き継がれます:

```python
@dataclass
class FollowUpContext:
"""前回セッションから引き継ぐ情報"""

# 前回のセッション ID
parent_session_id: str

# 前回の結論（report.md の核心部分）
previous_conclusion: str

# 前回の仮説テーブル
previous_hypotheses: list[dict]
# [{"id": "H1", "hypothesis": "...", "status": "unverified", "verification": "..."}]

# 前回の未解決問題
unresolved_issues: list[str]

# 前回の議論要約（指揮者が圧縮した3-5行版）
discussion_summary: str

# 前回の参加者情報
previous_agents: list[dict]

# 前回の評価結果（改善すべき点の参照に）
previous_feedback: dict

# 今回の新情報
new_input: str

# 添付ファイル（実験結果等）
attached_files: list[dict]  # [{"name": "results.csv", "content": "..."}]

# フォーカスする仮説
focus_hypotheses: list[str]  # ["H1", "H3"]

# チェーン情報
chain: list[str]  # 過去のセッションID列
chain_depth: int
```

### 引き継ぎデータの生成

```python
class FollowUpManager:
"""継続議論のコンテキスト管理"""

def __init__(self, output_dir: Path):
self.output_dir = output_dir

def load_previous_session(self, session_id: str) -> FollowUpContext:
"""前回セッションのデータを読み込み、引き継ぎコンテキストを構築"""

session_dir = self.output_dir / session_id
if not session_dir.exists():
raise SessionNotFoundError(f"セッション '{session_id}' が見つかりません")

# discussion.json を読み込み
with open(session_dir / "discussion.json", "r", encoding="utf-8") as f:
data = json.load(f)

# session_meta.json を読み込み
with open(session_dir / "session_meta.json", "r", encoding="utf-8") as f:
meta = json.load(f)

# 結論の抽出
conclusion = data["synthesis"]["final_conclusion"]

# 仮説テーブルの抽出（report.md から解析）
hypotheses = self._extract_hypotheses(session_dir / "report.md")

# 未解決問題の抽出
unresolved = self._extract_unresolved(session_dir / "report.md")

# 議論要約の生成（全ラウンド要約を3-5行にさらに圧縮）
discussion_summary = self._compress_summaries(
data["discussion"]["rounds"]
)

# チェーン情報の構築
chain = meta.get("follow_up", {}).get("chain", [])
chain.append(session_id)

return FollowUpContext(
parent_session_id=session_id,
previous_conclusion=conclusion,
previous_hypotheses=hypotheses,
unresolved_issues=unresolved,
discussion_summary=discussion_summary,
previous_agents=data["planning"]["selected_agents"],
previous_feedback=data["evaluation"]["orchestrator_feedback"],
new_input="",  # 後からセット
attached_files=[],
focus_hypotheses=[],
chain=chain,
chain_depth=len(chain),
)

async def _compress_summaries(self, rounds: list[dict]) -> str:
"""全ラウンドの要約を3-5行に圧縮"""
round_texts = []
for r in rounds:
utterances = r.get("public_utterances", [])
summary = " / ".join(u["content"][:50] for u in utterances[:3])
round_texts.append(f"R{r['round']}: {summary}")

full_text = "\n".join(round_texts)

# さらに圧縮（LLM使用）
prompt = f"""以下の議論の全ラウンド要約を3-5行に圧縮してください。
結論と重要な合意点のみ残してください。

{full_text}

圧縮版（3-5行）:"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=200,
)
return response["content"]
```

### 指揮者プロンプトへの注入

follow-up 時、指揮者のプロンプトに前回情報が追加されます:

```
【follow-up 情報】
これは前回セッション ({parent_session_id}) の継続議論です。

【前回の結論】
{previous_conclusion}

【前回の仮説テーブル】
| ID | 仮説 | 状態 |
| H1 | multi-scale kNNは精度向上する | ✅ 確認済み |
| H2 | 相対位置PEはspectral PEと同等 | 🔲 未検証 |
| H3 | GNNはN>5万でメモリ効率良い | 🔲 未検証 |

【前回の未解決問題】
1. multi-scale統合の最適方法
2. 動的点群への時系列拡張

【前回の議論サマリ（圧縮版）】
{discussion_summary}

【今回の新情報/質問】
{new_input}

【添付データ】
{attached_files_summary}

【フォーカスする仮説】
{focus_hypotheses}

【あなたの判断事項】
1. 前回と同じメンバーを呼ぶか？追加/変更が必要か？
2. 議論の焦点はどこに置くか？
3. 仮説テーブルのどれが更新対象か？
4. 新たな仮説が必要か？
5. 今回の議論の ODSC は何か？
```

### 仮説テーブルの状態遷移

```python
HYPOTHESIS_STATES = {
"unverified": "🔲",   # 未検証
"confirmed": "✅",    # 実験で確認済み
"rejected": "❌",     # 棄却
"modified": "🔄",     # 修正（元仮説を更新）
}

def update_hypothesis_table(
previous: list[dict],
updates: dict,
new_hypotheses: list[dict],
) -> list[dict]:
"""仮説テーブルの状態を更新"""
table = []

for h in previous:
h_id = h["id"]
if h_id in updates:
h["status"] = updates[h_id]["new_status"]
h["note"] = updates[h_id].get("note", "")
table.append(h)

# 新規仮説を追加
for new_h in new_hypotheses:
table.append(new_h)

return table
```

### session_meta.json の follow-up 情報

```json
{
"session_id": "20260625_091200_idea",
"follow_up": {
"is_follow_up": true,
"parent_session_id": "20260620_143052",
"chain_depth": 1,
"chain": ["20260620_143052", "20260625_091200_idea"],
"trigger": "実験結果: multi-scale kNN 精度+2%、推論3倍遅い",
"hypotheses_updated": {
"confirmed": ["H1"],
"rejected": ["H3"],
"new": ["H3_prime", "H5"]
}
}
}
```

### コンテキスト量のバランス

follow-up 時は前回情報 + 今回の議論で token 量が増加します。以下のバランスで管理します:

```
┌─────────────────────────────────────────────┐
│ Agent に渡すコンテキスト (follow-up 時)        │
├─────────────────────────────────────────────┤
│ Layer 1: system prompt         ~600 token   │
│ Layer 2: ODSC                  ~100 token   │
│ Layer 2.5: 前回情報 (圧縮版)   ~500 token   │ ← 追加
│ Layer 3: 過去ラウンドサマリ     ~300 token   │
│ Layer 4: 直近ラウンド全文       ~800 token   │
│ Layer 5: 追加指示              ~100 token   │
│ Layer 6: 直前発言              ~100 token   │
├─────────────────────────────────────────────┤
│ 合計                           ~2,500 token │
└─────────────────────────────────────────────┘
```

前回情報は**指揮者が圧縮した3-5行版**を使うため、token 消費は限定的です。全文が必要な場合は Phase 3 の統合時のみ参照します。

---

### 8章まとめ: メモリ設計の原則

| 原則 | 実現方法 |
|---|---|
| **完全性** | 全会話を JSON に漏れなく記録。後からの再現・分析が可能 |
| **効率性** | token 上限に応じて要約/全文を動的切替。無駄な token 消費を防ぐ |
| **品質保証** | 要約は gpt-4.1 (temperature=0.0) で生成。情報ロスを最小化 |
| **段階的劣化** | 全文→要約+直近全文→要約のみ と段階的にフォールバック |
| **Phase 3 活用** | 最終統合では大コンテキストモデルで全文入力。要約ロスなし |
| **follow-up 対応** | 前回セッションのコア情報を圧縮して引き継ぎ。チェーン管理 |

---
