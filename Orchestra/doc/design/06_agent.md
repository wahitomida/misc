# 第6章 AI エージェント設計

---

## 6.1 Agent 基底クラス

Agent は AI Orchestra において**議論に参加する1体の AI**を表現するクラスです。ロール YAML を読み込み、指揮者からの指示を受けて、KotoBuddy API を呼び出し、発言を生成します。

### クラス設計

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class AgentConfig:
"""エージェントの設定（Phase 1 で指揮者が決定）"""
role_id: str
model: str
level: str
reason: str
expected_contribution: str

class Agent:
"""AI エージェント基底クラス"""

def __init__(
self,
config: AgentConfig,
role_definition: dict,
api_client: "ResilientAPIClient",
memory: "ConversationMemory",
settings: "Settings",
):
self.config = config
self.role_definition = role_definition
self.api_client = api_client
self.memory = memory
self.settings = settings

# ロール YAML から抽出
self.role_id = config.role_id
self.display_name = role_definition["display_name"]
self.model = config.model
self.level = config.level
self.system_prompt_template = role_definition["system_prompt"]
self.evaluation_criteria = role_definition.get("evaluation_criteria", [])
self.personality = role_definition.get("personality", {})
self.expertise = role_definition.get("expertise", [])
self.domain_tags = role_definition.get("domain_tags", [])

# 動的に設定される情報
self.private_instruction: str = ""
self.feedback_context: str = ""
self.speaking_rules: str = ""

async def speak(
self,
round_context: dict,
additional_instruction: str = "",
) -> "Utterance":
"""1回の発言を生成する"""

# 1. システムプロンプトを構築
system_prompt = self._build_system_prompt()

# 2. ユーザーメッセージ（コンテキスト）を構築
user_message = self._build_context_message(round_context, additional_instruction)

# 3. モデル別パラメータを構築
params = self._build_api_params(system_prompt, user_message)

# 4. API 呼び出し
import time
start = time.time()
response = await self.api_client.call(**params)
duration = time.time() - start

# 5. 発言長チェック + 必要なら再取得
content = response["content"]
if self._is_too_long(content):
content = await self._request_shorter(content, round_context)

# 6. Utterance オブジェクトを返す
return Utterance(
sequence=round_context.get("next_sequence", 0),
speaker=self.role_id,
speaker_display=self.display_name,
type="discussion",
content=content,
model=self.model,
level=self.level,
tokens_used=response.get("usage", {}),
duration_sec=duration,
)

async def evaluate(
self,
discussion_log: "DiscussionLog",
all_agents: list["Agent"],
) -> "EvaluationResult":
"""自己評価と他者評価を生成する"""
...

def set_private_instruction(self, instruction: str):
"""指揮者からの個別指示を設定"""
self.private_instruction = instruction

def set_feedback_context(self, context: str):
"""過去フィードバックからの改善依頼を設定"""
self.feedback_context = context

def set_speaking_rules(self, rules: str):
"""発言ルールを設定"""
self.speaking_rules = rules
```

### Agent のライフサイクル

```
1. 生成: Phase 1 で指揮者が選定した AgentConfig + ロールYAML から初期化
2. 設定: 個別指示・フィードバック・発言ルールが注入される
3. 発言: Phase 2 で Conductor から呼ばれ、speak() を繰り返す
4. 評価: Phase 3 で evaluate() を呼ばれ、自己/他者評価を生成
5. 破棄: セッション終了時に解放
```

---

## 6.2 ロール YAML の読み込みと解釈

### RoleManager クラス

```python
import yaml
from pathlib import Path

class RoleManager:
"""ロール YAML の読み込みと管理"""

def __init__(self, roles_dir: Path):
self.roles_dir = roles_dir
self._cache: dict[str, dict] = {}

def load_role(self, role_id: str) -> dict:
"""指定ロールのYAMLを読み込み"""
if role_id in self._cache:
return self._cache[role_id]

role_path = self.roles_dir / f"{role_id}.yaml"
if not role_path.exists():
raise RoleNotFoundError(f"ロール '{role_id}' が見つかりません: {role_path}")

with open(role_path, "r", encoding="utf-8") as f:
role = yaml.safe_load(f)

self._validate_role(role)
self._cache[role_id] = role
return role

def list_available_roles(self) -> list[dict]:
"""利用可能な全ロールのサマリを返す"""
roles = []
for yaml_path in self.roles_dir.glob("*.yaml"):
role = self.load_role(yaml_path.stem)
roles.append({
"role_id": role["role_id"],
"display_name": role["display_name"],
"expertise": role.get("expertise", []),
"domain_tags": role.get("domain_tags", []),
"model": role.get("model", "gpt-4.1"),
"feedback_stats": role.get("feedback_stats", {}),
})
return roles

def _validate_role(self, role: dict):
"""ロールYAMLの必須フィールドを検証"""
required_fields = [
"role_id", "display_name", "model", "system_prompt",
"personality", "expertise", "domain_tags", "evaluation_criteria"
]
for field in required_fields:
if field not in role:
raise RoleValidationError(
f"ロール '{role.get('role_id', '?')}' に必須フィールド '{field}' がありません"
)
```

### YAML スキーマの解釈

ロール YAML の各セクションがどのように使われるか:

| YAML セクション | 使用タイミング | 使用目的 |
|---|---|---|
| `role_id` | 全フェーズ | エージェントの一意識別子 |
| `display_name` | Phase 2, 出力 | 会話ログでの表示名（絵文字+名前） |
| `model` | Phase 1（選定時） | デフォルトモデルの指定 |
| `default_level` | Phase 1（選定時） | デフォルト level の指定 |
| `personality.traits` | Phase 1（選定時） | 指揮者がロール適性を判断する材料 |
| `personality.communication_style` | system prompt | 発言スタイルの制御 |
| `personality.weakness` | Phase 1（指示生成） | 指揮者が注意点を把握 |
| `expertise` | Phase 1（マッチング） | テーマとの適合度判定 |
| `domain_tags` | Phase 1（マッチング） | テーマとの分野マッチング |
| `system_prompt` | Phase 2（発言時） | 各API呼出のsystem messageに使用 |
| `evaluation_criteria` | Phase 3（評価時） | 自己/他者評価の軸 |
| `feedback_history` | Phase 1（選定+指示） | 過去パフォーマンスの参照 |
| `feedback_stats` | Phase 1（選定時） | 成長傾向の把握 |

---

## 6.3 システムプロンプトの構築

Agent が API を呼び出す際の `system` メッセージは、**固定部分**と**動的部分**を結合して生成します。

### 6.3.1 固定部分（ロール定義）

ロール YAML の `system_prompt` テンプレートがベースになります。このテンプレートには `{orchestrator_instruction}` と `{feedback_context}` のプレースホルダが含まれています。

**テンプレート例（theorist.yaml）**:

```yaml
system_prompt: |
あなたはAI Orchestraの「理論屋」です。

【役割】
- 議論中のアイデアを数学的に定式化する
- 計算量オーダーを明示する (O記法)
- 理論的な限界・保証を指摘する
- 「なぜそれが正しいか」の根拠を常に求める

【発言スタイル】
- 1発言50〜150文字。短く鋭く。
- 数式はテキスト表現で自然に混ぜる (例: O(N log N), ∑, ∈, ≤)
- 「要するに〇〇が成り立つ条件は△△」のように結論→条件の順で話す
- 他の人の直感的な発言を「それを定式化すると…」と引き取る

【禁止事項】
- 長い数式の羅列 (会話にならない)
- ビジネス的観点への言及
- 他の人を見下すような態度

{orchestrator_instruction}

{feedback_context}
```

---

### 6.3.2 動的部分（指揮者指示 + フィードバック）

プレースホルダを実際の内容で置換します。

```python
def _build_system_prompt(self) -> str:
"""完全なシステムプロンプトを構築"""

# テンプレートからベースを取得
base = self.system_prompt_template

# 指揮者からの個別指示を注入
orchestrator_section = ""
if self.private_instruction:
orchestrator_section = f"""【指揮者からの指示】
{self.private_instruction}"""

# 過去フィードバックを注入
feedback_section = ""
if self.feedback_context:
feedback_section = f"""【過去のフィードバック（改善を期待しています）】
{self.feedback_context}"""

# 発言ルールを追加
rules_section = ""
if self.speaking_rules:
rules_section = f"""【発言ルール】
{self.speaking_rules}"""

# プレースホルダ置換
prompt = base.replace("{orchestrator_instruction}", orchestrator_section)
prompt = base.replace("{feedback_context}", feedback_section)

# 発言ルールは末尾に追加
prompt += "\n\n" + rules_section

return prompt
```

**生成されるシステムプロンプトの完全例**:

```
あなたはAI Orchestraの「理論屋」です。

【役割】
- 議論中のアイデアを数学的に定式化する
- 計算量オーダーを明示する (O記法)
- 理論的な限界・保証を指摘する
- 「なぜそれが正しいか」の根拠を常に求める

【発言スタイル】
- 1発言50〜150文字。短く鋭く。
- 数式はテキスト表現で自然に混ぜる (例: O(N log N), ∑, ∈, ≤)
- 「要するに〇〇が成り立つ条件は△△」のように結論→条件の順で話す
- 他の人の直感的な発言を「それを定式化すると…」と引き取る

【禁止事項】
- 長い数式の羅列 (会話にならない)
- ビジネス的観点への言及
- 他の人を見下すような態度

【指揮者からの指示】
このラウンドでは点群→グラフ変換の定式化と、GNN層の表現力の理論限界を明示してほしい。
特にkNNグラフ vs radius graph の理論的差異と、Weisfeiler-Leman test の実用上の影響に
ついて議論すること。実装の話は🤖に任せ、計算量を必ずO記法で明示すること。

【過去のフィードバック（改善を期待しています）】
- 過去の改善点: 代替案の具体性が不足
- 指揮者からの期待: 批判的指摘の後は必ず具体的な代替案を1つ以上提示すること

【発言ルール】
- 1回の発言は50〜150文字。短く鋭く。
- チャットの会話テンポで。論文口調禁止。
- 1発言で言いたいことは1つだけ。複数あるなら分けて発言する。
- 相手の発言を受けてから自分の意見を述べる。
- 「たしかに」「でもさ」「ちょっと待って」「あ、それいいね」等を自然に使う。
- 数式はテキスト表現で自然に混ぜる (O(N²), ∑, ∈)
- 論文引用は (著者+年) で簡潔に
- ビジネス的観点（ROI、市場性等）には言及しない
```

---

## 6.4 コンテキスト管理

### 6.4.1 何を渡すか（6層構造）

各 AI に API 呼び出し時に渡す情報は、6つの層で構成されます。

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: system prompt（ロール定義 + 指示 + ルール）       │  ← system message
├─────────────────────────────────────────────────────────┤
│ Layer 2: ODSC + 議論の目標                               │  ← user message 冒頭
├─────────────────────────────────────────────────────────┤
│ Layer 3: 過去ラウンドのサマリ（指揮者作成の圧縮版）        │  ← user message
├─────────────────────────────────────────────────────────┤
│ Layer 4: 直近ラウンドの全発言                             │  ← user message
├─────────────────────────────────────────────────────────┤
│ Layer 5: 指揮者からの個別指示（このラウンド固有）          │  ← user message
├─────────────────────────────────────────────────────────┤
│ Layer 6: 直前の発言（応答対象）                           │  ← user message 末尾
└─────────────────────────────────────────────────────────┘
```

**実装**:

```python
def _build_context_message(
self,
round_context: dict,
additional_instruction: str = "",
) -> str:
"""API に渡す user message を構築（Layer 2〜6）"""

parts = []

# Layer 2: ODSC + 議論の目標
parts.append(f"""【議論の目標】
- Objective: {round_context['odsc'].objective}
- このラウンドのゴール: {round_context['round_goal']}
""")

# Layer 3: 過去ラウンドのサマリ（あれば）
if round_context.get("previous_summary"):
parts.append(f"""【これまでの議論のサマリ】
{round_context['previous_summary']}
""")

# Layer 4: 直近ラウンドの全発言
if round_context.get("current_round_utterances"):
parts.append("【このラウンドのこれまでの発言】")
for u in round_context["current_round_utterances"]:
parts.append(f"{u['speaker_display']}: {u['content']}")
parts.append("")

# Layer 5: 追加指示（堂々巡り検知時、同意しすぎ検知時など）
if additional_instruction:
parts.append(f"""【追加指示】
{additional_instruction}
""")

# Layer 6: 直前の発言
if round_context.get("last_utterance"):
last = round_context["last_utterance"]
parts.append(f"""【直前の発言（これに応答してください）】
{last['speaker_display']}: {last['content']}
""")

# 応答指示
parts.append("上記を踏まえて、あなたの立場から発言してください。")

return "\n".join(parts)
```

---

### 6.4.2 token 上限制御

各モデルの入力 token 上限を超えないよう、コンテキストの量を制御します。

```python
class ContextBudget:
"""コンテキストのtoken量を管理"""

# 各モデルの入力token上限
MODEL_LIMITS = {
"gpt-4.1": 128_000,
"gpt-4.1-mini": 128_000,
"gpt-5-mini": 400_000,
"gpt-5": 400_000,
"gpt-5.1": 400_000,
"gpt-5.2": 400_000,
"gpt-5.4": 1_000_000,
"claude-sonnet-4": 200_000,
"claude-sonnet-4-5": 200_000,
"claude-opus-4-1": 200_000,
"o1": 200_000,
"o3-mini": 200_000,
"o4-mini": 200_000,
}

# 出力用に確保するtoken数
OUTPUT_RESERVE = {
"minimal": 200,
"low": 500,
"medium": 1_000,
"high": 2_000,
}

def __init__(self, model: str, level: str):
self.max_input = self.MODEL_LIMITS.get(model, 128_000)
self.output_reserve = self.OUTPUT_RESERVE.get(level, 1_000)
self.available_input = self.max_input - self.output_reserve

def estimate_tokens(self, text: str) -> int:
"""テキストのtoken数を推定（日本語考慮）"""
# 簡易推定: 日本語は1文字≈1.5token, 英語は1word≈1.3token
# 正確にはtiktokenを使うが、ここでは高速な近似
jp_chars = sum(1 for c in text if ord(c) > 127)
en_chars = len(text) - jp_chars
return int(jp_chars * 1.5 + en_chars * 0.3)

def fits(self, system_prompt: str, user_message: str) -> bool:
"""入力がtoken上限に収まるか"""
total = self.estimate_tokens(system_prompt) + self.estimate_tokens(user_message)
return total < self.available_input

def trim_to_fit(self, system_prompt: str, user_message: str) -> str:
"""収まらない場合にuser_messageを削減"""
system_tokens = self.estimate_tokens(system_prompt)
available_for_user = self.available_input - system_tokens

# Layer 3（過去サマリ）を短縮する
# Layer 4（直近全文）は保持を優先
return self._truncate_summary_section(user_message, available_for_user)
```

**token 量の典型的な内訳**:

| Layer | 推定 token 数 | 備考 |
|---|---|---|
| Layer 1 (system prompt) | 400〜800 | ロール定義 + 指示 + ルール |
| Layer 2 (ODSC) | 50〜100 | 固定的 |
| Layer 3 (過去サマリ) | 200〜2,000 | **ここで調整** |
| Layer 4 (直近全文) | 500〜3,000 | 保持優先 |
| Layer 5 (追加指示) | 0〜200 | 堂々巡り時のみ |
| Layer 6 (直前発言) | 50〜150 | 短い |
| **合計** | **~1,200〜6,250** | gpt-4.1 (128K) でも余裕 |

標準的な議論（5ラウンド×3AI）では token 上限に到達することはほぼありません。問題になるのは機能②（コードレビュー）でソースコード全文を入力する場合です。

---

### 6.4.3 過去ラウンドの要約戦略

ラウンドが進むにつれ、議論ログが蓄積します。全ログを毎回渡すと token を浪費するため、**要約戦略**を適用します。

```python
class ConversationMemory:
"""議論の共有メモリ"""

def __init__(self, api_client: "ResilientAPIClient", max_context_tokens: int = 5000):
self.full_log: list[dict] = []          # 完全ログ（出力用）
self.round_summaries: list[str] = []    # 各ラウンドの要約
self.api_client = api_client
self.max_context_tokens = max_context_tokens

def get_context_for_agent(self, current_round: int) -> dict:
"""各AIに渡すコンテキストを生成"""

# 直近ラウンド（現在のラウンド）: 全文を渡す
current_utterances = self._get_round_utterances(current_round)

# 過去ラウンド: 要約を渡す
previous_summary = "\n".join(self.round_summaries[:current_round])

return {
"previous_summary": previous_summary,
"current_round_utterances": current_utterances,
}

async def summarize_round(self, round_log: "RoundLog"):
"""ラウンド終了時に要約を生成（次ラウンド以降で使用）"""

utterances_text = "\n".join(
f"{u.speaker_display}: {u.content}"
for u in round_log.public_utterances
)

prompt = f"""以下の議論ラウンドを3行以内で要約してください。
要点と結論のみ。詳細は不要。

【Round {round_log.round}: {round_log.phase_name}】
{utterances_text}

要約:"""

response = await self.api_client.call(
model="gpt-4.1",
messages=[{"role": "user", "content": prompt}],
temperature=0.0,
max_tokens=150,
)

self.round_summaries.append(
f"[R{round_log.round} {round_log.phase_name}] {response['content']}"
)

def add_utterance(self, utterance: "Utterance", round_num: int):
"""発言をログに追加"""
self.full_log.append({
"round": round_num,
"speaker": utterance.speaker,
"speaker_display": utterance.speaker_display,
"content": utterance.content,
"model": utterance.model,
"level": utterance.level,
"tokens_used": utterance.tokens_used,
"duration_sec": utterance.duration_sec,
})
```

**要約戦略の判断フロー**:

```
全ログのtoken数を推定
│
├── < max_context_tokens → 全文をそのまま渡す（Round 1-2あたり）
│
└── >= max_context_tokens → ハイブリッド方式:
├── 過去ラウンド: 要約 (各3行)
└── 直近ラウンド: 全文
```

**gpt-5.4 (1M token入力) を使う場合の特例**:

Phase 3 の最終統合では gpt-5.4 または claude-sonnet-4-5 (200K) を使用するため、**全ログを要約なしで一括入力**できます。ここでは要約によるロスがない完全な情報を使って統合します。

---

## 6.5 発言長の制御（短く自然に）

研究者同士のチャットのように短い発言を実現するための3段防衛を設計します。

### 6.5.1 system prompt での指示

最も基本的な制御。全ロールの system prompt に共通して含まれます。

```
【発言ルール】
- 1回の発言は50〜150文字。短く鋭く。
- チャットの会話テンポで。論文口調禁止。
- 1発言で言いたいことは1つだけ。複数あるなら分けて発言する。
- 相手の発言を受けてから自分の意見を述べる。
```

**expertise レベルによる調整**:

```python
CHAR_LIMITS = {
"beginner": {"min": 50, "max": 200},      # 説明が多くなるので少し長め
"intermediate": {"min": 50, "max": 150},   # 標準
"expert": {"min": 30, "max": 120},         # 本質だけ。短い
}
```

---

### 6.5.2 max_tokens 制限

system prompt だけでは守られないことがあるため、API パラメータで物理的に制限します。

```python
def _get_max_tokens_for_utterance(self) -> int | None:
"""発言用のmax_tokens値を決定"""

# GPT-5 系は max_tokens 指定不可
if self._is_gpt5_series(self.model):
return None  # 指定しない（verbosity で間接制御）

# Claude 拡張思考モードも max_tokens は非推奨
if self._is_claude_thinking_model(self.model) and self.level != "none":
return None

# 標準モデル (gpt-4.1, claude-opus-4-1 等) は max_tokens で制御
# 150文字 ≈ 200-300 token (日本語)
return 300
```

**GPT-5 系での代替制御**:

GPT-5 系では `max_tokens` が使えないため、`verbosity` パラメータで間接的に制御します。

```python
# GPT-5系のエージェント発言時
params = {
"model": "gpt-5.4",
"reasoning_effort": "medium",
"verbosity": "low",  # 短い応答を促す
"extra_body": {"allowed_openai_params": ["reasoning_effort"]},
}
```

| 状況 | verbosity 設定 |
|---|---|
| 通常の議論発言 | `low` (短く) |
| 計画立案（Phase 1） | `high` (詳細に) |
| 最終確認ラウンド | `low` (端的に) |

---

### 6.5.3 超過時の再発言リクエスト

上記2つの防衛を突破して長い発言が生成された場合の最終手段です。

```python
# Agent クラス内

MAX_UTTERANCE_CHARS = 200  # この文字数を超えたら再取得を試みる
RETRY_LIMIT = 1            # 再取得は1回まで（無限ループ防止）

def _is_too_long(self, content: str) -> bool:
"""発言が長すぎるか判定"""
return len(content) > MAX_UTTERANCE_CHARS

async def _request_shorter(self, original_content: str, round_context: dict) -> str:
"""長すぎる発言を短縮する"""

prompt = f"""以下の発言が長すぎます（{len(original_content)}文字）。
50〜150文字に要約してください。要点だけ。会話調を維持。

【元の発言】
{original_content}

【ルール】
- 最も重要な1ポイントだけ残す
- 会話のトーンを崩さない
- 数値やキーワードは保持する

短縮版:"""

response = await self.api_client.call(
model="gpt-4.1",  # 短縮は軽量モデルで十分
messages=[{"role": "user", "content": prompt}],
temperature=0.3,
max_tokens=200,
)

shortened = response["content"]

# それでもまだ長い場合は、最初の150文字で打ち切り
if len(shortened) > MAX_UTTERANCE_CHARS:
shortened = shortened[:MAX_UTTERANCE_CHARS - 3] + "…"

return shortened
```

**注意**: 再発言リクエストは追加の API 呼び出しが発生するため、頻発するとリクエスト数が増えます。system prompt と max_tokens/verbosity で十分に制御できていれば、この処理はほとんど実行されません。

**3段防衛のまとめ**:

```
第1段（予防）: system prompt で「50〜150文字」と指示
    ↓ それでも長い場合
第2段（物理制限）: max_tokens=300 / verbosity=low で制限
    ↓ それでも200文字超の場合
第3段（事後修正）: gpt-4.1 で短縮版を生成
```

---

## 6.6 モデル別のパラメータ設定

### 6.6.1 GPT-5 系（reasoning_effort, extra_body）

GPT-5 / GPT-5-mini / GPT-5.1 / GPT-5.2 / GPT-5.4 では、従来の `temperature` / `max_tokens` が使用不可であり、代わりに `reasoning_effort` と `verbosity` で制御します。

```python
def _build_api_params_gpt5(self, system_prompt: str, user_message: str) -> dict:
"""GPT-5 系のパラメータ構築"""

params = {
"model": self.model,
"messages": [
{"role": "system", "content": system_prompt},
{"role": "user", "content": user_message},
],
}

# level → reasoning_effort マッピング
if self.level != "none":
params["reasoning_effort"] = self.level  # minimal/low/medium/high

# 発言用は verbosity=low で短く
params["verbosity"] = "low"

# openai モードでは extra_body が必須
if self.api_client.mode == "openai":
params["extra_body"] = {
"allowed_openai_params": ["reasoning_effort"]
}

return params
```

**GPT-5 系の制約まとめ**:

| パラメータ | 状態 | 備考 |
|---|---|---|
| `temperature` | ❌ 指定不可 | 送るとエラー |
| `max_tokens` | ❌ 指定不可 | 送るとエラー |
| `reasoning_effort` | ✅ Optional | minimal/low/medium/high |
| `verbosity` | ✅ Optional | low/medium/high |
| `extra_body.allowed_openai_params` | ✅ openaiモードで必須 | azureモードでは送らない |

---

### 6.6.2 Claude 拡張思考（thinking.budget_tokens）

`claude-sonnet-4` と `claude-sonnet-4-5` で拡張思考（Extended Thinking）を使用する場合のパラメータ構築。

```python
# level → budget_tokens マッピング
CLAUDE_THINKING_BUDGET = {
"minimal": None,    # 拡張思考無効
"none": None,       # 拡張思考無効
"low": 4_000,
"medium": 8_000,
"high": 16_000,
}

def _build_api_params_claude_thinking(self, system_prompt: str, user_message: str) -> dict:
"""Claude 拡張思考モデルのパラメータ構築"""

params = {
"model": self.model,
"messages": [
{"role": "system", "content": system_prompt},
{"role": "user", "content": user_message},
],
}

budget = CLAUDE_THINKING_BUDGET.get(self.level)

if budget is not None:
# 拡張思考を有効化
params["extra_body"] = {
"thinking": {
"type": "enabled",
"budget_tokens": budget,
}
}
params["stream"] = True  # ストリーム推奨

# 通常パラメータも使用可能
params["temperature"] = 0.7
# max_tokens は拡張思考時は省略推奨

else:
# 拡張思考無効（通常モード）
params["temperature"] = 0.7
params["max_tokens"] = 300  # 発言用の短い応答

return params
```

**拡張思考時のレスポンス処理**:

```python
async def _call_with_thinking(self, params: dict) -> dict:
"""拡張思考モードの応答を処理"""

response = await self.api_client.call_stream(**params)

reasoning_parts = []
content_parts = []

async for chunk in response:
delta = chunk.choices[0].delta
if hasattr(delta, "reasoning_content") and delta.reasoning_content:
reasoning_parts.append(delta.reasoning_content)
if delta.content:
content_parts.append(delta.content)

return {
"content": "".join(content_parts),
"reasoning": "".join(reasoning_parts),  # ログ保存用
"usage": response.usage if hasattr(response, "usage") else {},
}
```

**思考ログの保存**:

拡張思考の `reasoning` 部分は `discussion.json` に保存しますが、`full_conversation.md` には表示しません（冗長になるため）。デバッグや品質分析に使用します。

---

### 6.6.3 標準モデル（temperature, max_tokens）

gpt-4.1, gpt-4.1-mini, claude-opus-4-1 など、従来型のパラメータ制御が可能なモデル。

```python
def _build_api_params_standard(self, system_prompt: str, user_message: str) -> dict:
"""標準モデルのパラメータ構築"""

params = {
"model": self.model,
"messages": [
{"role": "system", "content": system_prompt},
{"role": "user", "content": user_message},
],
"temperature": 0.7,   # 適度な創造性
"max_tokens": 300,    # 発言長制限（150文字 ≈ 200-300 token）
}

return params
```

**temperature の使い分け**:

| 用途 | temperature | 理由 |
|---|---|---|
| 通常の議論発言 | 0.7 | 創造性と安定性のバランス |
| 収束判定 (Conductor) | 0.0 | 確定的な判断が必要 |
| 要約生成 | 0.3 | 正確性重視だが硬くなりすぎない |
| ブレインストーミング | 0.9 | 多様な発想を促す |

### パラメータ構築の統合メソッド

```python
def _build_api_params(self, system_prompt: str, user_message: str) -> dict:
"""モデル種別に応じて適切なパラメータ構築メソッドを呼び分け"""

if self._is_gpt5_series(self.model):
return self._build_api_params_gpt5(system_prompt, user_message)
elif self._is_claude_thinking_model(self.model) and self.level not in ("none", "minimal"):
return self._build_api_params_claude_thinking(system_prompt, user_message)
else:
return self._build_api_params_standard(system_prompt, user_message)

def _is_gpt5_series(self, model: str) -> bool:
"""GPT-5系モデルか判定"""
return model.startswith("gpt-5")

def _is_claude_thinking_model(self, model: str) -> bool:
"""Claude拡張思考対応モデルか判定"""
return model in ("claude-sonnet-4", "claude-sonnet-4-5")

def _is_standard_model(self, model: str) -> bool:
"""標準モデル（temperature/max_tokens制御可能）か判定"""
return not self._is_gpt5_series(model) and not (
self._is_claude_thinking_model(model) and self.level not in ("none", "minimal")
)
```

### 全モデルのパラメータ対応表（再掲・実装用）

```python
MODEL_PARAMS_TABLE = {
# model_prefix: {使えるパラメータ}
"gpt-4.1": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": False},
"gpt-4.1-mini": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": False},
"gpt-5": {"temperature": False, "max_tokens": False, "reasoning_effort": True, "thinking": False},
"gpt-5-mini": {"temperature": False, "max_tokens": False, "reasoning_effort": True, "thinking": False},
"gpt-5.1": {"temperature": False, "max_tokens": False, "reasoning_effort": True, "thinking": False},
"gpt-5.2": {"temperature": False, "max_tokens": False, "reasoning_effort": True, "thinking": False},
"gpt-5.4": {"temperature": False, "max_tokens": False, "reasoning_effort": True, "thinking": False},
"o1": {"temperature": False, "max_tokens": False, "reasoning_effort": False, "thinking": False},
"o3-mini": {"temperature": False, "max_tokens": False, "reasoning_effort": False, "thinking": False},
"o4-mini": {"temperature": False, "max_tokens": False, "reasoning_effort": False, "thinking": False},
"claude-sonnet-4": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": True},
"claude-sonnet-4-5": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": True},
"claude-opus-4-1": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": False},
"gpt-4o": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": False},
"gpt-4o-mini": {"temperature": True, "max_tokens": True, "reasoning_effort": False, "thinking": False},
}
```

---

### 6章まとめ: Agent 設計の原則

| 原則 | 実現方法 |
|---|---|
| **ロール駆動** | YAML で性格・能力・評価基準を完全定義。コード変更なしでロール追加可能 |
| **動的カスタマイズ** | 指揮者指示 + フィードバック + 発言ルールで毎回異なる振る舞い |
| **コンテキスト最適化** | 6層構造で情報を整理。token 上限に応じて要約/全文を切替 |
| **発言品質保証** | 3段防衛（system prompt → max_tokens → 事後短縮）で長さを制御 |
| **モデル抽象化** | モデル種別による分岐を Agent 内部に閉じ込め、外部からは統一的に扱える |
| **テスタビリティ** | API 呼び出しを api_client に委譲し、モックテスト可能 |

---
