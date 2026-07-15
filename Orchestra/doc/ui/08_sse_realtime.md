# AI Orchestra — SSE・リアルタイム通信設計

> Server-Sent Events によるリアルタイム議論配信の全仕様

---

## 1. 概要

### 1.1 通信アーキテクチャ

```
┌─ Browser ──────────────────────────────────────────────────┐
│                                                            │
│  OrchestraSSE クラス                                        │
│  ├─ fetch() で POST SSE を確立                              │
│  ├─ ReadableStream でチャンクを読み取り                      │
│  ├─ SSEパーサーでイベントを分割                             │
│  └─ イベントハンドラに分配                                  │
│                                                            │
└────────────────────────┬───────────────────────────────────┘
│ HTTP POST (streaming response)
│ Content-Type: text/event-stream
┌────────────────────────┼───────────────────────────────────┐
│  FastAPI Server         │                                   │
│                         │                                   │
│  StreamingResponse ─────┘                                   │
│       ↑                                                     │
│  asyncio.Queue (イベントバッファ)                            │
│       ↑                                                     │
│  SSEInterventionHandler.notify_progress()                   │
│       ↑                                                     │
│  Core Engine (Conductor → Agent → API)                      │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 1.2 なぜ SSE か (WebSocket との比較)

| 要件 | SSE | WebSocket |
|------|-----|-----------|
| サーバー→クライアント一方向 | ✅ 最適 | ○ 可能 (オーバースペック) |
| POST body の送信 | ✅ fetch で可能 | ❌ 別途REST必要 |
| 実装の簡素さ | ✅ StreamingResponse | △ 状態管理が複雑 |
| プロキシ対応 | ✅ HTTP/1.1 標準 | △ Upgrade ヘッダー必要 |
| 再接続 | ○ 手動実装 | ✅ 自動 |
| 双方向通信 | ❌ | ✅ |

→ 議論は一方向配信のため、SSE が最適。将来の人間介入はWebSocket追加で対応。

---

## 2. SSE プロトコル仕様

### 2.1 リクエスト

```
POST /api/idea/stream HTTP/1.1
Content-Type: application/json
Accept: text/event-stream

{
"plan": { ... },
"prompt": "...",
"conductor_model": "gpt-4.1",
"synth_model": "gpt-5.4",
"time_limit": 300,
"expertise": "intermediate"
}
```

### 2.2 レスポンスヘッダー

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
Transfer-Encoding: chunked
```

### 2.3 イベント形式

```
data: {"type": "round_start", "round": 1, "config": {...}}\n\n
data: {"type": "utterance", "round": 1, "agent": {...}, "content": "..."}\n\n
data: {"type": "done", "session_id": "...", "statistics": {...}}\n\n
```

**規則:**
- 各イベントは `data: ` プレフィクス + JSON + `\n\n` (空行区切り)
- 1イベント1行 (改行なし)
- JSON は `ensure_ascii=False` (日本語をそのまま)
- イベントIDは使用しない (再接続不要のため)

---

## 3. イベント型一覧

### 3.1 Idea Discussion イベント

| Phase | type | payload | 発生タイミング |
|-------|------|---------|-------------|
| 1 | `planning_start` | `{}` | 計画立案開始 |
| 1 | `planning_complete` | `{plan}` | 計画立案完了 |
| 2 | `round_start` | `{round, config}` | ラウンド開始 |
| 2 | `utterance` | `{round, agent, content, tokens}` | 各AI発言 |
| 2 | `round_conclusion` | `{round, concluder, content}` | ラウンド結論 |
| 2 | `round_end` | `{round, convergence, elapsed_sec}` | ラウンド終了 |
| 2 | `convergence_check` | `{round, score, threshold}` | 収束チェック結果 |
| 2 | `stagnation_detected` | `{round, action}` | 停滞検知 |
| 2 | `agreement_detected` | `{round, direction}` | 同意過多検知 |
| 2 | `time_pressure` | `{remaining_sec, pressure}` | 時間逼迫 |
| 3 | `synthesis_start` | `{}` | 統合開始 |
| 3 | `evaluation_progress` | `{step, agent}` | 評価進捗 |
| 3 | `synthesis_complete` | `{report_preview}` | 統合完了 |
| * | `progress` | `{phase, percent, elapsed_sec, remaining_sec}` | 定期進捗 |
| — | `done` | `{session_id, output_dir, statistics}` | 全完了 |
| — | `error` | `{message, recoverable}` | エラー |

### 3.2 Code Review 追加イベント

| Phase | type | payload | 発生タイミング |
|-------|------|---------|-------------|
| 1 | `scan_start` | `{}` | スキャン開始 |
| 1 | `scan_complete` | `{scan_result}` | スキャン完了 |
| 2 | `investigation_start` | `{aspect, emoji}` | 個別調査開始 |
| 2 | `investigation_progress` | `{aspect, progress}` | 調査進捗 (0-100) |
| 2 | `investigation_finding` | `{aspect, finding}` | 指摘事項発見 |
| 2 | `investigation_complete` | `{aspect, findings_count}` | 調査完了 |
| 3 | `cross_question_start` | `{}` | 相互質問開始 |
| 3 | `cross_question` | `{questioner, target, question, ...}` | 質問 |
| 3 | `cross_answer` | `{answerer, questioner, answer, ...}` | 回答 |
| 3 | `cross_question_complete` | `{}` | 相互質問完了 |
| 4 | `meeting_start` | `{}` | 全体会議開始 |
| 4 | (以降 idea と同じ round_start/utterance 等) | | |

---

## 4. イベント payload 詳細

### 4.1 utterance

```json
{
"type": "utterance",
"round": 1,
"agent": {
"role_id": "theorist",
"emoji": "🧮",
"name": "理論屋"
},
"content": "計算量の観点から見ると、KV-cache圧縮が最も効果的なアプローチです",
"tokens": 150,
"duration_sec": 3.2
}
```

### 4.2 round_start

```json
{
"type": "round_start",
"round": 2,
"config": {
"number": 2,
"phase": "deepen",
"pattern": "ping_pong",
"speakers": ["experimentalist", "devil"],
"leader": "experimentalist",
"topic": "KV-cache圧縮の実験的検証方法",
"estimated_sec": 90,
"level": "standard"
}
}
```

### 4.3 round_conclusion

```json
{
"type": "round_conclusion",
"round": 1,
"concluder": "theorist",
"concluder_emoji": "🧮",
"concluder_name": "理論屋",
"content": "KV-cache圧縮とバッチ最適化の2軸で進めることで合意。次ラウンドで実験設計を詰める"
}
```

### 4.4 progress

```json
{
"type": "progress",
"phase": "discussion",
"percent": 65,
"elapsed_sec": 120.5,
"remaining_sec": 179.5,
"current_round": 2,
"total_rounds": 3
}
```

### 4.5 time_pressure

```json
{
"type": "time_pressure",
"remaining_sec": 28.5,
"pressure": "critical",
"action": "concluding_early"
}
```

### 4.6 done

```json
{
"type": "done",
"session_id": "20260622_133204_idea",
"output_dir": "output/20260622_133204_idea",
"statistics": {
"duration_sec": 272.5,
"utterance_count": 14,
"total_tokens": 2850,
"rounds_completed": 3,
"final_convergence": 0.87,
"mvp": {
"role_id": "theorist",
"emoji": "🧮",
"name": "理論屋"
},
"api_requests": 36,
"fallback_count": 0,
"retry_count": 1
}
}
```

### 4.7 error

```json
{
"type": "error",
"message": "Rate limit exceeded. Daily limit: 10,000 requests.",
"recoverable": false,
"error_type": "RateLimitExhaustedError",
"partial_session_id": "20260622_133204_idea"
}
```

### 4.8 investigation_finding (review)

```json
{
"type": "investigation_finding",
"aspect": "algorithm",
"finding": {
"severity": "critical",
"title": "境界条件チェックが欠落",
"description": "agent.py の speak() メソッドで入力長が0の場合の処理がない",
"file_path": "core/agent.py",
"line_range": [45, 60],
"suggestion": "if not context: raise ValueError('empty context') を追加"
}
}
```

---

## 5. フロントエンド: OrchestraSSE クラス

### 5.1 完全実装

```javascript
/**
* AI Orchestra のSSE接続を管理するクラス。
*
* EventSource は GET のみ対応のため、
* POST SSE は fetch() + ReadableStream で実装する。
*
* @example
* const sse = new OrchestraSSE('/api/idea/stream');
* sse.on('utterance', (data) => addChatBubble(data));
* sse.on('done', (data) => showResults(data));
* sse.on('error', (data) => toast(data.message, 'error'));
* await sse.start({ plan: {...}, prompt: '...' });
*/
class OrchestraSSE {
/**
* @param {string} url - SSEエンドポイントURL
*/
constructor(url) {
this._url = url;
this._handlers = {};
this._controller = null;
this._state = 'idle'; // idle | connecting | streaming | done | error
this._eventCount = 0;
this._startTime = null;
}

/**
* イベントハンドラを登録する。
*
* @param {string} eventType - イベント型 ('utterance', 'done', '*' 等)
* @param {function} handler - コールバック関数 (data) => void
* @returns {OrchestraSSE} メソッドチェーン用
*/
on(eventType, handler) {
if (!this._handlers[eventType]) {
this._handlers[eventType] = [];
}
this._handlers[eventType].push(handler);
return this;
}

/**
* SSE接続を開始する (POST)。
*
* @param {object} body - リクエストボディ (JSON)
* @returns {Promise<void>} ストリーム完了時に resolve
* @throws {Error} ネットワークエラー時
*/
async start(body) {
this._state = 'connecting';
this._startTime = Date.now();
this._controller = new AbortController();

try {
const response = await fetch(this._url, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
'Accept': 'text/event-stream',
},
body: JSON.stringify(body),
signal: this._controller.signal,
});

// HTTPエラーチェック
if (!response.ok) {
const errorText = await response.text();
let errorData;
try {
errorData = JSON.parse(errorText);
} catch {
errorData = { message: errorText || `HTTP ${response.status}` };
}
this._state = 'error';
this._dispatch({
type: 'error',
message: errorData.message || errorData.detail || `HTTP ${response.status}`,
recoverable: response.status >= 500,
});
return;
}

this._state = 'streaming';
await this._readStream(response);

} catch (err) {
if (err.name === 'AbortError') {
// ユーザーによる中断
this._state = 'idle';
return;
}
this._state = 'error';
this._dispatch({
type: 'error',
message: `接続エラー: ${err.message}`,
recoverable: true,
});
}
}

/**
* SSE接続を中断する。
*/
abort() {
if (this._controller) {
this._controller.abort();
this._controller = null;
}
this._state = 'idle';
}

/**
* 接続状態を返す。
* @returns {'idle'|'connecting'|'streaming'|'done'|'error'}
*/
get state() {
return this._state;
}

/**
* 受信イベント数を返す。
* @returns {number}
*/
get eventCount() {
return this._eventCount;
}

/**
* 接続開始からの経過時間(ms)を返す。
* @returns {number|null}
*/
get elapsedMs() {
if (!this._startTime) return null;
return Date.now() - this._startTime;
}

// === Private Methods ===

/**
* ReadableStream からSSEイベントを読み取る。
* @param {Response} response - fetch レスポンス
*/
async _readStream(response) {
const reader = response.body.getReader();
const decoder = new TextDecoder('utf-8');
let buffer = '';

try {
while (true) {
const { done, value } = await reader.read();

if (done) {
// ストリーム終了 (サーバーが閉じた)
if (buffer.trim()) {
this._parseAndDispatch(buffer);
}
if (this._state === 'streaming') {
this._state = 'done';
}
break;
}

// デコード + バッファに追加
buffer += decoder.decode(value, { stream: true });

// イベント分割 (\n\n 区切り)
const events = buffer.split('\n\n');
// 最後の要素は不完全な可能性があるのでバッファに残す
buffer = events.pop() || '';

// 各イベントを処理
for (const eventText of events) {
if (eventText.trim()) {
this._parseAndDispatch(eventText);
}
}
}
} catch (err) {
if (err.name !== 'AbortError') {
this._state = 'error';
this._dispatch({
type: 'error',
message: `ストリーム読み取りエラー: ${err.message}`,
recoverable: false,
});
}
} finally {
reader.releaseLock();
}
}

/**
* SSEテキストをパースしてイベントをディスパッチする。
* @param {string} eventText - "data: {...}" 形式のテキスト
*/
_parseAndDispatch(eventText) {
// 複数行の data: を結合
const lines = eventText.split('\n');
let dataStr = '';

for (const line of lines) {
if (line.startsWith('data: ')) {
dataStr += line.slice(6);
} else if (line.startsWith('data:')) {
dataStr += line.slice(5);
}
// "event:", "id:", "retry:" は無視 (使用しない)
}

if (!dataStr) return;

try {
const data = JSON.parse(dataStr);
this._eventCount++;
this._dispatch(data);

// 終端イベントで状態更新
if (data.type === 'done') {
this._state = 'done';
} else if (data.type === 'error' && !data.recoverable) {
this._state = 'error';
}
} catch (err) {
console.warn('[OrchestraSSE] JSON parse error:', err, dataStr);
}
}

/**
* イベントをハンドラに分配する。
* @param {object} data - パース済みイベントデータ
*/
_dispatch(data) {
// 型別ハンドラ
const handlers = this._handlers[data.type] || [];
for (const handler of handlers) {
try {
handler(data);
} catch (err) {
console.error(`[OrchestraSSE] Handler error (${data.type}):`, err);
}
}

// ワイルドカードハンドラ ('*')
const allHandlers = this._handlers['*'] || [];
for (const handler of allHandlers) {
try {
handler(data);
} catch (err) {
console.error('[OrchestraSSE] Wildcard handler error:', err);
}
}
}
}
```

### 5.2 使用例

```javascript
// Idea 議論
async startDiscussion() {
this.sse = new OrchestraSSE('/api/idea/stream');

// デバッグ用: 全イベントログ
this.sse.on('*', (data) => {
console.log('[SSE]', data.type, data);
});

// Phase 2
this.sse.on('round_start', (data) => {
this.currentRound = data.round;
this.currentPhase = data.config.phase;
this.currentPattern = data.config.pattern;
this.addRoundDivider(data);
});

this.sse.on('utterance', (data) => {
this.isAgentThinking = false;
this.addUtterance(data);
this.updateStats(data);
});

this.sse.on('round_conclusion', (data) => {
this.addConclusion(data);
});

this.sse.on('round_end', (data) => {
this.stats.convergence = data.convergence;
this.resetAgentStatuses();
// 次のラウンドの最初の発言者をthinking表示
this.showNextThinking();
});

// 検知系
this.sse.on('stagnation_detected', () => {
this.addSystemEvent('⚡', '議論の方向転換を指示しました');
});

this.sse.on('agreement_detected', (data) => {
this.addSystemEvent('⚖️', `同意過多検知: 反対意見を要求 (${data.direction})`);
});

// 時間
this.sse.on('progress', (data) => {
this.remainingSec = data.remaining_sec;
this.progressPercent = data.percent;
});

this.sse.on('time_pressure', (data) => {
this.remainingSec = data.remaining_sec;
this.timePressure = data.pressure;
if (data.pressure === 'critical') {
this.addSystemEvent('⏰', '残り時間わずか — 議論を収束します');
}
});

// Phase 3
this.sse.on('synthesis_start', () => {
this.stopTimer();
this.addSystemEvent('📊', '統合・評価フェーズを開始...');
this.isSynthesizing = true;
});

this.sse.on('evaluation_progress', (data) => {
this.synthesisStatus = `${data.step}: ${data.agent}`;
});

// 完了/エラー
this.sse.on('done', async (data) => {
this.stopTimer();
this.isSynthesizing = false;
await this.loadResult(data.session_id);
this.step = 4;
});

this.sse.on('error', (data) => {
this.stopTimer();
this.isSynthesizing = false;
toast(data.message, 'error');
if (!data.recoverable) {
this.handleFatalError(data);
}
});

// 接続開始
await this.sse.start({
plan: this.plan,
prompt: this.prompt,
conductor_model: this.settings.conductorModel,
synth_model: this.settings.synthModel,
time_limit: this.settings.timeLimit,
expertise: this.settings.expertise,
});
}
```

---

## 6. バックエンド: SSE ストリーミング実装

### 6.1 エンドポイント

```python
"""Idea議論のSSEストリーミングエンドポイント。"""

import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class IdeaStreamRequest(BaseModel):
"""SSEストリーミングリクエスト。"""
plan: dict
prompt: str
conductor_model: str = "gpt-4.1"
synth_model: str = "gpt-5.4"
time_limit: int = 300
expertise: str = "intermediate"


@router.post("/api/idea/stream")
async def stream_idea_discussion(request: IdeaStreamRequest):
"""議論をSSEでストリーミングする。"""
return StreamingResponse(
_event_generator(request),
media_type="text/event-stream",
headers={
"Cache-Control": "no-cache",
"Connection": "keep-alive",
"X-Accel-Buffering": "no",  # nginx バッファリング無効化
},
)
```

### 6.2 イベントジェネレータ

```python
async def _event_generator(request: IdeaStreamRequest):
"""SSEイベントを生成する非同期ジェネレータ。"""
queue: asyncio.Queue = asyncio.Queue()
intervention = SSEInterventionHandler(queue)

# コアエンジンをバックグラウンドタスクで実行
task = asyncio.create_task(
_run_orchestra(request, intervention)
)

try:
while True:
try:
# タイムアウト付きでイベントを待つ (keepalive用)
event = await asyncio.wait_for(queue.get(), timeout=30.0)
except asyncio.TimeoutError:
# 30秒イベントなし → keepalive コメント送信
yield ": keepalive\n\n"
continue

# イベントをSSE形式で送信
yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

# 終端イベントでループ終了
if event.get("type") in ("done", "error"):
break

except asyncio.CancelledError:
# クライアント切断
task.cancel()
try:
await task
except asyncio.CancelledError:
pass
except GeneratorExit:
# ジェネレータ終了
task.cancel()
finally:
if not task.done():
task.cancel()
try:
await task
except asyncio.CancelledError:
pass
```

### 6.3 SSEInterventionHandler

```python
"""SSE用のInterventionHandler実装。"""

import asyncio
from core.intervention import InterventionHandler


class SSEInterventionHandler(InterventionHandler):
"""コアエンジンのイベントをSSE queueに送信する。

Conductorの各処理ポイントからnotify_progress()が呼ばれ、
そのイベントをasyncio.Queueに入れる。
event_generatorがqueueからイベントを取り出してSSEとして送信する。
"""

def __init__(self, queue: asyncio.Queue):
self._queue = queue
self._start_time = None

async def notify_progress(self, event: str, data: dict) -> None:
"""進捗イベントをキューに送信する。

Args:
event: イベント型 ("utterance", "round_start" 等)
data: イベントペイロード
"""
await self._queue.put({"type": event, **data})

def check_intervention(self, round_num: int, context: dict) -> str | None:
"""人間介入チェック (Web UIでは常にNone)。

将来: WebSocket経由でユーザーコメントを受け取る。
"""
        return None
```

### 6.4 コアエンジン実行

```python
async def _run_orchestra(
request: IdeaStreamRequest,
intervention: SSEInterventionHandler,
):
"""コアエンジンを実行し、イベントをinterventionに通知する。"""
import time
from core.config_loader import Settings
from core.api_client import ResilientAPIClient
from core.role_manager import RoleManager
from core.memory import ConversationMemory
from core.agent import Agent, AgentConfig
from core.time_keeper import TimeKeeper
from core.conductor import Conductor
from core.synthesizer import Synthesizer
from core.feedback import FeedbackManager
from core.output_generator import OutputGenerator

try:
# 初期化
settings = Settings.load()
api_client = _create_api_client(settings)
role_manager = RoleManager(Path(settings.roles_dir))
feedback_manager = FeedbackManager(Path(settings.roles_dir))

# 計画は既に受け取っている
plan = _reconstruct_plan(request.plan)

# エージェント初期化
agents = {}
for agent_info in plan.agents:
role_id = agent_info if isinstance(agent_info, str) else agent_info["role_id"]
role_def = role_manager.load_role(role_id)
config = plan.agent_configs.get(role_id, AgentConfig(role_id=role_id, model=request.conductor_model))
memory = ConversationMemory(api_client=api_client)
agents[role_id] = Agent(
config=config,
role_definition=role_def,
api_client=api_client,
memory=memory,
settings=settings,
)

# Phase 2: 議論
time_keeper = TimeKeeper(time_limit_sec=request.time_limit)
conductor = Conductor(
api_client=api_client,
agents=agents,
memory=memory,
time_keeper=time_keeper,
intervention=intervention,
settings=settings,
model=request.conductor_model,
)

discussion_log = await conductor.run_discussion(plan.discussion_plan)

# Phase 3: 統合
await intervention.notify_progress("synthesis_start", {})
synthesizer = Synthesizer(
api_client=api_client,
feedback_manager=feedback_manager,
settings=settings,
)
synthesis = await synthesizer.synthesize(
plan=plan,
discussion_log=discussion_log,
memory=memory,
agents=agents,
model=request.synth_model,
expertise=request.expertise,
)

# 出力生成
output_gen = OutputGenerator(output_dir=Path(settings.output_dir))
session_dir = output_gen.generate(
session_type="idea",
plan=plan,
discussion_log=discussion_log,
synthesis=synthesis,
memory=memory,
)

# 完了通知
await intervention.notify_progress("done", {
"session_id": session_dir.name,
"output_dir": str(session_dir),
"statistics": synthesis.meta.get("statistics", {}),
})

except Exception as e:
import traceback
traceback.print_exc()
await intervention.notify_progress("error", {
"message": str(e),
"recoverable": False,
"error_type": type(e).__name__,
})
```

---

## 7. Conductor からの通知ポイント

### 7.1 通知マップ

```python
class Conductor:
"""議論進行管理。intervention.notify_progress() を各所で呼ぶ。"""

async def run_discussion(self, plan):
for round_config in plan.rounds:
# ラウンド開始通知
await self._intervention.notify_progress("round_start", {
"round": round_config.number,
"config": round_config.to_dict(),
})

# ラウンド実行
round_log = await self.run_round(round_config, plan)

# ラウンド終了通知
await self._intervention.notify_progress("round_end", {
"round": round_config.number,
"convergence": round_log.convergence_score,
"elapsed_sec": round_log.duration_sec,
})

async def run_round(self, round_config, plan):
# 各発言後に通知
for utterance in utterances:
await self._intervention.notify_progress("utterance", {
"round": round_config.number,
"agent": {
"role_id": utterance.role_id,
"emoji": utterance.emoji,
"name": utterance.role_name,
},
"content": utterance.content,
"tokens": utterance.tokens,
"duration_sec": utterance.duration_sec,
})

# 結論通知
await self._intervention.notify_progress("round_conclusion", {
"round": round_config.number,
"concluder": conclusion_agent.config.role_id,
"concluder_emoji": conclusion_agent_role["emoji"],
"concluder_name": conclusion_agent_role["name"],
"content": conclusion_text,
})

# 収束チェック通知
await self._intervention.notify_progress("convergence_check", {
"round": round_config.number,
"score": convergence_result.score,
"threshold": self._settings.discussion.convergence_threshold,
})

# 停滞検知通知
if stagnation_result["is_repetitive"]:
await self._intervention.notify_progress("stagnation_detected", {
"round": round_config.number,
"action": "pivot",
"suggestion": stagnation_result["suggestion"],
})

# 時間逼迫通知
if self._time_keeper.pressure in (TimePressure.URGENT, TimePressure.CRITICAL):
await self._intervention.notify_progress("time_pressure", {
"remaining_sec": self._time_keeper.remaining,
"pressure": self._time_keeper.pressure.value,
})
```

### 7.2 定期 progress 通知

```python
# Conductor 内で5秒ごとに progress を送信
async def _send_periodic_progress(self):
"""5秒ごとに進捗を通知するバックグラウンドタスク。"""
while True:
await asyncio.sleep(5)
elapsed = self._time_keeper.elapsed
remaining = self._time_keeper.remaining
total = self._time_keeper._time_limit_sec
percent = min(100, int(elapsed / total * 100))

await self._intervention.notify_progress("progress", {
"phase": "discussion",
"percent": percent,
"elapsed_sec": elapsed,
"remaining_sec": remaining,
"current_round": self._current_round,
"total_rounds": len(self._plan.rounds),
})
```

---

## 8. エラーハンドリング

### 8.1 サーバーサイドエラー

```python
# コアエンジン内でエラーが発生した場合
try:
utterance = await agent.speak(context)
except RateLimitExhaustedError as e:
await intervention.notify_progress("error", {
"message": f"APIレートリミット到達: {e}",
"recoverable": False,
"error_type": "RateLimitExhaustedError",
})
return  # 中断

except TimeoutError as e:
# リトライ可能 → 通知のみで続行
await intervention.notify_progress("error", {
"message": f"タイムアウト (リトライ中): {e}",
"recoverable": True,
"error_type": "TimeoutError",
})
# RetryHandler が内部でリトライ

except Exception as e:
await intervention.notify_progress("error", {
"message": f"予期しないエラー: {e}",
"recoverable": False,
"error_type": type(e).__name__,
})
return  # 中断
```

### 8.2 クライアントサイドエラー

```javascript
// ネットワーク切断
this.sse.on('error', (data) => {
this.stopTimer();

if (data.recoverable) {
// リカバリー可能: トースト表示のみ
toast(data.message, 'warning');
} else {
// リカバリー不可: 中断表示
toast(data.message, 'error');

// 部分結果の保存提案
if (data.partial_session_id) {
this.showPartialResultLink(data.partial_session_id);
} else {
// Step 1 に戻す
setTimeout(() => { this.step = 1; }, 3000);
}
}
});
```

### 8.3 クライアント切断検知

```python
# FastAPI の StreamingResponse はクライアント切断時に GeneratorExit を発生させる
# event_generator の finally ブロックでタスクをキャンセル

# 追加: 定期的な keepalive で切断を早期検知
# 30秒ごとに ": keepalive\n\n" を送信
# → クライアントが読み取らなければパイプ破壊 → GeneratorExit
```

---

## 9. パフォーマンス考慮

### 9.1 バッファリング対策

```python
# nginx がSSEをバッファリングしないよう設定
headers = {
"X-Accel-Buffering": "no",      # nginx
"Cache-Control": "no-cache",     # ブラウザキャッシュ無効
}

# Python側: 即座にflush (StreamingResponse のデフォルト動作)
```

### 9.2 メモリ管理

```python
# asyncio.Queue のサイズ制限
queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

# maxsize到達時: put() がブロック → コアエンジンが自動的に待機
# → クライアントの読み取りが追いつかない場合のバックプレッシャー
```

### 9.3 同時接続制限

```python
# グローバルセマフォで同時SSEセッション数を制限
_active_sessions = asyncio.Semaphore(3)  # 最大3同時セッション

@router.post("/api/idea/stream")
async def stream_idea_discussion(request: IdeaStreamRequest):
if not _active_sessions._value:  # 空きなし
return JSONResponse(
status_code=429,
content={"detail": "同時実行セッション数の上限です。しばらくお待ちください。"}
)

async with _active_sessions:
return StreamingResponse(...)
```

---

## 10. テスト戦略

### 10.1 SSEエンドポイントのテスト

```python
import pytest
from httpx import AsyncClient
from web.app import app


@pytest.mark.asyncio
async def test_idea_stream_returns_sse():
"""SSEストリームが正しく返される。"""
async with AsyncClient(app=app, base_url="http://test") as client:
async with client.stream("POST", "/api/idea/stream", json={
"plan": mock_plan,
"prompt": "test",
}) as response:
assert response.status_code == 200
assert response.headers["content-type"] == "text/event-stream"

events = []
async for line in response.aiter_lines():
if line.startswith("data: "):
event = json.loads(line[6:])
events.append(event)
if event["type"] == "done":
break

assert any(e["type"] == "round_start" for e in events)
assert any(e["type"] == "utterance" for e in events)
assert events[-1]["type"] == "done"
```

### 10.2 OrchestraSSE クラスのテスト (JavaScript)

```javascript
// テスト用モックサーバー (fetch mock)
describe('OrchestraSSE', () => {
it('should parse SSE events correctly', async () => {
// fetch mock: text/event-stream を返す
global.fetch = jest.fn(() => Promise.resolve({
ok: true,
body: new ReadableStream({
start(controller) {
controller.enqueue(
new TextEncoder().encode('data: {"type": "utterance", "content": "test"}\n\n')
);
controller.enqueue(
new TextEncoder().encode('data: {"type": "done"}\n\n')
);
controller.close();
}
})
}));

const sse = new OrchestraSSE('/api/test');
const events = [];
sse.on('*', (data) => events.push(data));
await sse.start({});

expect(events).toHaveLength(2);
expect(events[0].type).toBe('utterance');
expect(events[1].type).toBe('done');
expect(sse.state).toBe('done');
});
});
```

---

## 11. デバッグ支援

### 11.1 ブラウザコンソールログ

```javascript
// 開発時: 全イベントをコンソールに出力
if (window.location.hostname === 'localhost') {
sse.on('*', (data) => {
const color = {
utterance: 'color: #6366f1',
round_start: 'color: #10b981',
done: 'color: #f59e0b; font-weight: bold',
error: 'color: #ef4444; font-weight: bold',
}[data.type] || 'color: #6b7280';

console.log(`%c[SSE ${data.type}]`, color, data);
});
}
```

### 11.2 サーバーサイドログ

```python
import logging
logger = logging.getLogger(__name__)

async def notify_progress(self, event: str, data: dict) -> None:
logger.debug("SSE event: %s %s", event, json.dumps(data, ensure_ascii=False)[:100])
await self._queue.put({"type": event, **data})
```

### 11.3 イベントインスペクター (開発UI)

```html
<!-- 開発時のみ表示: SSEイベントモニター -->
<div x-show="isDev" class="fixed bottom-4 left-4 z-50 max-w-sm max-h-64
overflow-y-auto bg-black/90 text-green-400 text-xs font-mono
rounded-xl p-3 shadow-lg">
<div class="flex justify-between mb-2">
<span>SSE Monitor</span>
<span x-text="'Events: ' + (sse?.eventCount || 0)"></span>
</div>
<template x-for="log in sseLog.slice(-20)" :key="log.id">
<div class="py-0.5 border-b border-gray-800">
<span class="text-gray-500" x-text="log.time"></span>
<span :class="log.color" x-text="log.type"></span>
<span class="text-gray-400 truncate" x-text="log.preview"></span>
</div>
</template>
</div>
