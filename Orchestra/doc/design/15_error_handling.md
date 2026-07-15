# 第15章 エラーハンドリングと耐障害設計

---

## 15.1 API エラーの分類

KotoBuddy API で発生しうるエラーを分類し、それぞれの対処方針を定義します。

### エラー分類の全体像

| HTTP Status | 原因 | 頻度 | 影響度 | 対処 |
|---|---|---|---|---|
| 401 | レート制限超過 / キー失効 | 中 | 高 | 停止 or 待機 |
| 404 | モデル未存在 / EOL | 低 | 中 | フォールバック |
| 400 | パラメータ不正 | 低 | 中 | パラメータ修正して再試行 |
| 429 | スロットリング | 中 | 低 | バックオフ後リトライ |
| 500 | サーバー内部エラー | 低 | 中 | リトライ |
| 502/503 | ゲートウェイ / サービス不可 | 低 | 中 | リトライ |
| Timeout | ネットワーク / 応答遅延 | 中 | 中 | リトライ |
| 空応答 | GPT-5 系の既知問題 | 低 | 低 | level下げてリトライ |

---

### 15.1.1 401: レート制限 / キー失効

KotoBuddy API では日次10,000リクエスト超過時に HTTP 401 が返されます。キー失効（有効期限切れ / 管理者による削除）も同じステータスです。

```python
class AuthenticationError(OrchestraAPIError):
"""401エラー: 認証失敗"""

def __init__(self, message: str, is_rate_limit: bool = False):
super().__init__(message)
self.is_rate_limit = is_rate_limit

# 判別ロジック
def classify_401(response) -> AuthenticationError:
"""401の原因を判別"""
body = response.json() if response.content else {}
error_msg = body.get("error", {}).get("message", "").lower()

if "rate limit" in error_msg or "quota" in error_msg:
return AuthenticationError(
"日次リクエスト上限(10,000/day)に達しました。明日0:00にリセットされます。",
is_rate_limit=True
)
else:
return AuthenticationError(
"APIキーが無効です。有効期限切れまたは削除された可能性があります。"
"KotoBuddyポータルでキーの状態を確認してください。",
is_rate_limit=False
)
```

**対処方針**:
- レート制限: セッションを中断。中間結果を保存。
- キー失効: 即時停止。ユーザーにキー確認を促す。

---

### 15.1.2 404: モデル未存在 / EOL

Bedrock 側で EOL となったモデルや、Azure deployment に存在しないモデルを指定した場合に発生します。

```python
class ModelNotFoundError(OrchestraAPIError):
"""404エラー: モデルが見つからない"""

def __init__(self, model: str, message: str):
super().__init__(message)
self.model = model

# 実機で確認された404パターン
KNOWN_EOL_MODELS = {
"claude-3-haiku": "Bedrock側 Legacy扱い",
"claude-3-5-sonnet": "Bedrock側 End-of-Life",
"claude-3-7-sonnet": "Bedrock側 End-of-Life",
"claude-opus-4": "Bedrock側 End-of-Life",
}
```

**対処方針**: フォールバックチェーンで後継モデルに自動切替（15.3参照）。

---

### 15.1.3 500: サーバーエラー

KotoBuddy 基盤側の一時的な障害です。

```python
class ServerError(OrchestraAPIError):
"""500系エラー: サーバー側の問題"""

def __init__(self, status_code: int, message: str):
super().__init__(message)
self.status_code = status_code
self.retryable = status_code in (500, 502, 503)
```

**対処方針**: Exponential Backoff でリトライ（最大3回）。

---

### 15.1.4 タイムアウト

ネットワーク遅延や、高 reasoning_effort での長時間応答で発生します。

```python
class TimeoutError(OrchestraAPIError):
"""タイムアウト: 応答が制限時間内に返らない"""

# モデル別のタイムアウト値
TIMEOUT_MAP = {
"gpt-4.1": 30,         # 30秒
"gpt-4.1-mini": 20,    # 20秒
"gpt-5-mini": 45,      # 45秒
"gpt-5": 60,           # 60秒
"gpt-5.4": 90,         # 90秒（high時は長い）
"claude-sonnet-4-5": 90,  # 拡張思考時は長い
"claude-opus-4-1": 60,
}
```

**対処方針**: リトライ。2回目で失敗したら level を下げてリトライ。

---

## 15.2 リトライ戦略

### 15.2.1 最大リトライ回数

```python
@dataclass
class RetryConfig:
"""リトライ設定"""
max_retries: int = 3            # 最大リトライ回数
base_delay_sec: float = 2.0     # 初回待機時間
max_delay_sec: float = 30.0     # 最大待機時間
backoff_factor: float = 2.0     # 指数バックオフの倍率
retryable_status_codes: set = field(
default_factory=lambda: {429, 500, 502, 503}
)
```

---

### 15.2.2 Exponential Backoff

```python
import asyncio
import time

class RetryHandler:
"""リトライロジック"""

def __init__(self, config: RetryConfig):
self.config = config

async def execute_with_retry(
self,
func,
*args,
**kwargs,
) -> dict:
"""リトライ付きで関数を実行"""

last_error = None

for attempt in range(self.config.max_retries + 1):
try:
return await func(*args, **kwargs)

except ServerError as e:
last_error = e
if not e.retryable:
raise  # リトライ不可能なエラーは即座にraise

if attempt < self.config.max_retries:
delay = self._calculate_delay(attempt)
console.print(
f"[yellow]⚠️ サーバーエラー ({e.status_code})。"
f"{delay:.1f}秒後にリトライ ({attempt+1}/{self.config.max_retries})[/yellow]"
)
await asyncio.sleep(delay)

except TimeoutError as e:
last_error = e
if attempt < self.config.max_retries:
delay = self._calculate_delay(attempt)
console.print(
f"[yellow]⚠️ タイムアウト。{delay:.1f}秒後にリトライ[/yellow]"
)
await asyncio.sleep(delay)

except AuthenticationError:
raise  # 認証エラーはリトライしない

raise MaxRetriesExceededError(
f"最大リトライ回数({self.config.max_retries})を超過: {last_error}"
)

def _calculate_delay(self, attempt: int) -> float:
"""Exponential Backoff の待機時間を計算"""
delay = self.config.base_delay_sec * (self.config.backoff_factor ** attempt)
# ジッター追加（同時リトライの衝突を避ける）
import random
jitter = random.uniform(0, delay * 0.1)
return min(delay + jitter, self.config.max_delay_sec)
```

**リトライ時系列の例**:

```
試行1: 即時実行 → 500エラー
待機: 2.0秒 (base_delay)
試行2: 実行 → 502エラー
待機: 4.0秒 (2.0 × 2^1)
試行3: 実行 → 200 OK ✅
```

---

### 15.2.3 GPT-5 空応答時の level 引き下げリトライ

GPT-5 系で `reasoning_effort=high` + 短い質問の組み合わせで、内部 reasoning に出力 token を使い切り `content=None` (空応答) になることがあります。

```python
class EmptyResponseHandler:
"""GPT-5系の空応答対策"""

LEVEL_DOWNGRADE_ORDER = ["high", "medium", "low", "minimal"]

async def handle_empty_response(
self,
original_params: dict,
api_client: "ResilientAPIClient",
) -> dict:
"""空応答時にlevelを下げてリトライ"""

current_level = original_params.get("reasoning_effort", "medium")
current_idx = self.LEVEL_DOWNGRADE_ORDER.index(current_level)

for downgrade_idx in range(current_idx + 1, len(self.LEVEL_DOWNGRADE_ORDER)):
new_level = self.LEVEL_DOWNGRADE_ORDER[downgrade_idx]
params = {**original_params, "reasoning_effort": new_level}

console.print(
f"[yellow]⚠️ 空応答検知。reasoning_effort を "
f"{current_level}→{new_level} に下げてリトライ[/yellow]"
)

response = await api_client.call_raw(**params)

if response.get("content"):
return response

# 全level試しても空 → エラー
raise EmptyResponseError(
f"全てのlevelで空応答。モデル: {original_params['model']}"
)
```

---

## 15.3 フォールバックチェーン

### 15.3.1 EOL モデル → 後継モデルへの自動切替

```python
# モデルのフォールバックチェーン定義
FALLBACK_CHAIN = {
# EOL モデル → 後継モデル
"claude-3-haiku": "gpt-4.1-mini",
"claude-3-5-sonnet": "claude-sonnet-4",
"claude-3-7-sonnet": "claude-sonnet-4",
"claude-opus-4": "claude-opus-4-1",

# 廃止予定モデル → 推奨後継
"gpt-4o": "gpt-4.1",
"gpt-4o-mini": "gpt-4.1-mini",
}

class FallbackManager:
"""モデルフォールバックの管理"""

def __init__(self):
self.fallback_used: dict[str, str] = {}  # 実行中に使ったフォールバックの記録

def get_fallback(self, model: str) -> str | None:
"""フォールバック先のモデルを取得。なければNone。"""
return FALLBACK_CHAIN.get(model)

async def call_with_fallback(
self,
api_client: "ResilientAPIClient",
model: str,
**kwargs,
) -> dict:
"""フォールバック付きAPI呼出"""

models_to_try = [model]
fallback = self.get_fallback(model)
if fallback:
models_to_try.append(fallback)

last_error = None
for current_model in models_to_try:
try:
response = await api_client.call_raw(model=current_model, **kwargs)

if current_model != model:
# フォールバックが使われた
self.fallback_used[model] = current_model
console.print(
f"[yellow]⚠️ {model} → {current_model} にフォールバック[/yellow]"
)

return response

except ModelNotFoundError as e:
last_error = e
console.print(
f"[yellow]⚠️ {current_model} は利用不可 ({e.message})[/yellow]"
)
continue

except Exception as e:
last_error = e
break  # 404以外のエラーはフォールバックしない

raise OrchestraAPIError(
f"モデル {model} とフォールバック先の全てが失敗: {last_error}"
)
```

---

### 15.3.2 廃止予定モデルの警告表示

```python
DEPRECATION_WARNINGS = {
"gpt-4o": {
"deadline": "2026-09-30",
"successor": "gpt-4.1",
"message": "gpt-4o は 2026/9/30 に廃止予定です。gpt-4.1 への移行を推奨します。"
},
"gpt-4o-mini": {
"deadline": "2026-09-30",
"successor": "gpt-4.1-mini",
"message": "gpt-4o-mini は 2026/9/30 に廃止予定です。gpt-4.1-mini への移行を推奨します。"
},
}

class DeprecationChecker:
"""廃止予定モデルの警告"""

def check_and_warn(self, models_used: list[str]):
"""使用モデルに廃止予定のものが含まれていたら警告"""
for model in models_used:
if model in DEPRECATION_WARNINGS:
warning = DEPRECATION_WARNINGS[model]
console.print(
f"[yellow]⚠️ 廃止予定: {warning['message']}[/yellow]"
)
```

セッション開始時とレポート出力時に警告を表示します。

---

## 15.4 日次リクエスト数の追跡

### 15.4.1 RateLimitTracker の実装

```python
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import json

@dataclass
class RateLimitTracker:
"""日次リクエスト数を追跡。ファイルに永続化。"""

daily_limit: int = 10000
safety_margin: float = 0.9
request_count: int = 0
last_reset: date = field(default_factory=date.today)
persistence_path: Path = field(default_factory=lambda: Path(".orchestra_rate_limit.json"))

def __post_init__(self):
"""起動時に永続化ファイルから復元"""
self._load()

def increment(self, n: int = 1):
"""リクエスト数をインクリメント"""
self._check_reset()
self.request_count += n
self._save()

def remaining(self) -> int:
"""残りリクエスト数"""
self._check_reset()
return self.daily_limit - self.request_count

def can_proceed(self, estimated_requests: int) -> bool:
"""推定リクエスト数を消費しても安全か"""
self._check_reset()
return (self.request_count + estimated_requests) < self.daily_limit * self.safety_margin

def utilization(self) -> float:
"""使用率 (0.0-1.0)"""
self._check_reset()
return self.request_count / self.daily_limit

def _check_reset(self):
"""日付が変わっていればリセット"""
if date.today() != self.last_reset:
self.request_count = 0
self.last_reset = date.today()
self._save()

def _save(self):
"""状態をファイルに永続化"""
data = {
"request_count": self.request_count,
"last_reset": self.last_reset.isoformat(),
}
self.persistence_path.write_text(json.dumps(data), encoding="utf-8")

def _load(self):
"""ファイルから状態を復元"""
if self.persistence_path.exists():
try:
data = json.loads(self.persistence_path.read_text(encoding="utf-8"))
saved_date = date.fromisoformat(data["last_reset"])
if saved_date == date.today():
self.request_count = data["request_count"]
else:
self.request_count = 0
self.last_reset = date.today()
except (json.JSONDecodeError, KeyError, ValueError):
pass  # ファイル破損時は初期値のまま
```

---

### 15.4.2 実行前の残量チェック

```python
class PreExecutionChecker:
"""実行前の各種チェック"""

def __init__(self, rate_tracker: RateLimitTracker):
self.rate_tracker = rate_tracker

def check_and_display(self, estimated_requests: int) -> bool:
"""実行前チェック。問題があればFalseを返す。"""

remaining = self.rate_tracker.remaining()
can_proceed = self.rate_tracker.can_proceed(estimated_requests)

# 表示
console.print(f"📊 予想リクエスト数: [bold]{estimated_requests}[/bold]")
console.print(f"🔑 日次残りリクエスト: [bold]{remaining}[/bold] / {self.rate_tracker.daily_limit}")

if can_proceed:
console.print("[green]✅ 実行可能[/green]")
return True
else:
utilization = self.rate_tracker.utilization()
if utilization >= 1.0:
console.print("[red]❌ 日次リクエスト上限に達しています。明日 0:00 にリセットされます。[/red]")
else:
console.print(
f"[yellow]⚠️ 残りリクエスト({remaining})が推定消費量({estimated_requests})に対して不足する可能性があります。[/yellow]"
)
console.print("[yellow]level を下げるか、参加AI数を減らすことを検討してください。[/yellow]")
return False
```

---

### 15.4.3 90% 到達時の警告

```python
class RuntimeRateWarning:
"""実行中のリクエスト消費監視"""

def __init__(self, rate_tracker: RateLimitTracker):
self.rate_tracker = rate_tracker
self.warned_at_90 = False
self.warned_at_95 = False

def check_after_request(self):
"""各API呼出後にチェック"""
utilization = self.rate_tracker.utilization()

if utilization >= 0.95 and not self.warned_at_95:
console.print(
"[red]🚨 日次リクエストの95%を消費しました。"
"このセッション完了後は新規セッションを控えてください。[/red]"
)
self.warned_at_95 = True

elif utilization >= 0.90 and not self.warned_at_90:
console.print(
"[yellow]⚠️ 日次リクエストの90%を消費しました。"
"残り枯渇に注意してください。[/yellow]"
)
self.warned_at_90 = True
```

---

## 15.5 議論途中のエラー回復

議論の最中にエラーが発生した場合、可能な限りセッションを続行し、最低限の成果物を出力します。

### 15.5.1 1エージェントの失敗時（スキップ / 代替モデル）

```python
class AgentFailureHandler:
"""1体のエージェント発言取得失敗時の対応"""

async def handle(
self,
failed_agent: Agent,
error: Exception,
round_config: RoundConfig,
utterances: list[Utterance],
) -> Utterance | None:
"""エージェント失敗時の回復"""

# 策1: フォールバックモデルで再試行
fallback_model = FALLBACK_CHAIN.get(failed_agent.model)
if fallback_model:
try:
failed_agent.model = fallback_model
utterance = await failed_agent.speak(
self._get_current_context(round_config, utterances)
)
utterance.content = f"[フォールバック: {fallback_model}] " + utterance.content
return utterance
except Exception:
pass  # フォールバックも失敗

# 策2: スキップして記録
console.print(
f"[yellow]⚠️ {failed_agent.display_name} の発言取得に失敗。"
f"このラウンドではスキップします。[/yellow]"
)

# スキップの記録（ログに残す）
skip_utterance = Utterance(
sequence=len(utterances) + 1,
speaker=failed_agent.role_id,
speaker_display=failed_agent.display_name,
type="skip",
content=f"[発言取得失敗: {type(error).__name__}. このラウンドはスキップ]",
model=failed_agent.model,
level=failed_agent.level,
tokens_used={"input": 0, "output": 0},
duration_sec=0,
)

return skip_utterance
```

**影響の最小化**:
- 1体がスキップされても、他の AI の議論は継続
- 収束判定に影響するが、致命的ではない
- 評価時にスキップされたラウンドは考慮から除外

---

### 15.5.2 指揮者の失敗時（再計画）

Phase 1 の計画立案自体が失敗した場合の対応です。

```python
class OrchestratorFailureHandler:
"""指揮者（計画立案）失敗時の対応"""

async def handle(
self,
error: Exception,
user_input: str,
settings: Settings,
) -> OrchestraPlan | None:
"""指揮者失敗時のフォールバック計画"""

# 策1: モデルを変えてリトライ
fallback_models = ["gpt-5", "gpt-4.1", "claude-sonnet-4-5"]
for model in fallback_models:
try:
console.print(f"[yellow]⚠️ 計画立案失敗。{model} で再試行...[/yellow]")
plan = await self.orchestrator.plan(
user_input=user_input,
model=model,
level="medium",  # levelも下げる
time_limit_sec=settings.time_limit_default_sec,
max_agents=3,   # AI数も減らして確実に成功させる
)
return plan
except Exception:
continue

# 策2: デフォルト計画を使用（最終手段）
console.print("[yellow]⚠️ 全モデルで計画立案失敗。デフォルト計画で実行します。[/yellow]")
return self._create_default_plan(user_input, settings)

def _create_default_plan(self, user_input: str, settings: Settings) -> OrchestraPlan:
"""LLMを使わない最小限のデフォルト計画"""
return OrchestraPlan(
odsc=ODSC(
objective=f"「{user_input[:50]}」について多角的に議論する",
deliverable="技術的洞察と次のステップ",
success_criteria="参加者間で方向性の合意が得られること",
convergence_threshold=0.7,
),
selected_agents=[
AgentConfig(role_id="theorist", model="gpt-4.1", level="medium",
reason="default", expected_contribution="理論面の検討"),
AgentConfig(role_id="devil", model="gpt-4.1", level="medium",
reason="default", expected_contribution="穴探し"),
AgentConfig(role_id="experimentalist", model="gpt-4.1", level="medium",
reason="default", expected_contribution="実験面の検討"),
],
discussion_plan=DiscussionPlan(
estimated_rounds=3,
round_config=[
RoundConfig(round=1, phase_name="情報出し", speakers=["theorist", "experimentalist"],
pattern="one_shot", level="medium", time_budget_sec=60, goal="テーマの分解"),
RoundConfig(round=2, phase_name="検証", speakers=["devil", "theorist"],
pattern="ping_pong", level="medium", time_budget_sec=60, goal="穴探し"),
RoundConfig(round=3, phase_name="まとめ", speakers=["theorist", "devil", "experimentalist"],
pattern="one_shot", level="low", time_budget_sec=30, goal="結論"),
],
total_estimated_time_sec=150,
total_estimated_requests=12,
),
private_instructions={},
)
```

---

### 15.5.3 全体失敗時（中間結果の保存）

どうしても回復不可能な致命的エラーが発生した場合でも、それまでの中間結果を保存します。

```python
class GracefulShutdown:
"""致命的エラー時のグレースフル停止"""

def __init__(self, output_dir: Path):
self.output_dir = output_dir

async def save_partial_results(
self,
error: Exception,
plan: OrchestraPlan | None,
discussion_log: DiscussionLog | None,
memory: ConversationMemory | None,
session_id: str,
):
"""中間結果を保存して終了"""

session_dir = self.output_dir / session_id
session_dir.mkdir(parents=True, exist_ok=True)

# 可能な限りのデータを保存
partial_data = {
"_schema_version": "1.0.0",
"_status": "partial_failure",
"_error": {
"type": type(error).__name__,
"message": str(error),
"timestamp": datetime.now().isoformat(),
},
"session": {
"id": session_id,
"status": "failed",
},
}

# 計画が生成済みなら保存
if plan:
partial_data["planning"] = {
"odsc": plan.odsc.__dict__,
"selected_agents": [a.__dict__ for a in plan.selected_agents],
}

# 議論ログが部分的にでもあれば保存
if discussion_log and discussion_log.rounds:
partial_data["discussion"] = {
"completed_rounds": len(discussion_log.rounds),
"rounds": [self._serialize_round(r) for r in discussion_log.rounds],
"score_history": discussion_log.score_history,
}

# メモリのログ保存
if memory:
partial_data["conversation_log"] = memory.full_log

# 保存
output_path = session_dir / "discussion_partial.json"
output_path.write_text(
json.dumps(partial_data, ensure_ascii=False, indent=2),
encoding="utf-8"
)

# session_meta.json も部分的に保存
meta = {
"session_id": session_id,
"status": "failed",
"error": str(error),
"completed_rounds": len(discussion_log.rounds) if discussion_log else 0,
"output_files": {"discussion_partial_json": "discussion_partial.json"},
}
(session_dir / "session_meta.json").write_text(
json.dumps(meta, ensure_ascii=False, indent=2),
encoding="utf-8"
)

console.print(f"\n[red]❌ セッションが失敗しました: {error}[/red]")
console.print(f"[yellow]📁 中間結果を保存しました: {session_dir}[/yellow]")
if discussion_log and discussion_log.rounds:
console.print(
f"[yellow]   完了ラウンド: {len(discussion_log.rounds)}回分の議論が保存されています[/yellow]"
)
```

### 統合: ResilientAPIClient

全てのエラーハンドリングを統合した API クライアントです。

```python
class ResilientAPIClient:
"""耐障害性を備えた API クライアント"""

def __init__(
self,
base_client,
rate_tracker: RateLimitTracker,
retry_config: RetryConfig = RetryConfig(),
fallback_manager: FallbackManager = FallbackManager(),
):
self.client = base_client
self.rate_tracker = rate_tracker
self.retry_handler = RetryHandler(retry_config)
self.fallback_manager = fallback_manager
self.empty_response_handler = EmptyResponseHandler()
self.runtime_warning = RuntimeRateWarning(rate_tracker)
self.mode = detect_mode(os.environ.get("KOTOBUDDY_ENDPOINT", ""))

async def call(self, model: str, messages: list, **kwargs) -> dict:
"""全ての保護機構を含む API 呼び出し"""

# 1. レート制限チェック
if not self.rate_tracker.can_proceed(1):
remaining = self.rate_tracker.remaining()
if remaining <= 0:
raise RateLimitExhaustedError(
"日次リクエスト上限に達しました。"
)

# 2. フォールバック付きでリトライ実行
async def _execute():
return await self.fallback_manager.call_with_fallback(
self, model, messages=messages, **kwargs
)

response = await self.retry_handler.execute_with_retry(_execute)

# 3. 空応答チェック (GPT-5系)
if response.get("content") is None and self._is_gpt5_series(model):
response = await self.empty_response_handler.handle_empty_response(
{"model": model, "messages": messages, **kwargs},
self,
)

# 4. リクエスト数記録 + 警告チェック
self.rate_tracker.increment()
self.runtime_warning.check_after_request()

return response

async def call_raw(self, model: str, messages: list, **kwargs) -> dict:
"""フォールバックなしの素の呼び出し（FallbackManager から呼ばれる）"""

params = self._build_params(model, messages, **kwargs)

try:
response = await self.client.chat.completions.create(**params)
return {
"content": response.choices[0].message.content,
"usage": {
"input": response.usage.prompt_tokens if response.usage else 0,
"output": response.usage.completion_tokens if response.usage else 0,
},
}
except Exception as e:
raise self._classify_error(e, model)
```

---

### 15章まとめ: 耐障害設計の原則

| 原則 | 実現方法 |
|---|---|
| **段階的対応** | リトライ→フォールバック→スキップ→停止 の順で段階的に |
| **議論の継続性** | 1体の失敗が全体を止めない。スキップして続行 |
| **中間結果保存** | 致命的エラーでも完了分の議論ログは必ず保存 |
| **予防的チェック** | 実行前にリクエスト残量を確認。不足なら警告 |
| **自動回復** | EOL モデルは自動フォールバック。空応答はlevel下げ |
| **可観測性** | 全てのエラー・リトライ・フォールバックをログに記録 |

---
