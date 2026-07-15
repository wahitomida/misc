# AI Orchestra — 実装パターン集

> コード実装時に繰り返し使用するパターンとその具体例

---

## 1. 依存注入パターン

### 1.1 コンストラクタ注入（基本形）

```python
class Conductor:
    """議論進行を管理する。

    Attributes:
        api_client: LLM APIクライアント。
        agents: 参加エージェント辞書。
        memory: 会話記憶。
        time_keeper: 時間管理。
        intervention: 人間介入ハンドラ。
        settings: 全体設定。
    """

    def __init__(
        self,
        api_client: ResilientAPIClient,
        agents: dict[str, Agent],
        memory: ConversationMemory,
        time_keeper: TimeKeeper,
        intervention: InterventionHandler,
        settings: Settings,
        model: str,
    ):
        self._api_client = api_client
        self._agents = agents
        self._memory = memory
        self._time_keeper = time_keeper
        self._intervention = intervention
        self._settings = settings
        self._model = model
```

### 1.2 Feature層での組み立て

```python
class IdeaDiscussion:
    """idea コマンドのフロー制御。"""

    async def run(self, user_input: str, **kwargs) -> Path:
        # 依存オブジェクトを組み立てる（ここが唯一の組み立て場所）
        settings = Settings.load()
        api_client = self._build_api_client(settings)
        role_manager = RoleManager(settings.roles_dir)
        feedback_manager = FeedbackManager(settings.roles_dir)

        # Phase 1
        orchestrator = Orchestrator(
            api_client=api_client,
            role_manager=role_manager,
            feedback_manager=feedback_manager,
            settings=settings,
        )
        plan = await orchestrator.plan(user_input, **kwargs)

        # Phase 2
        agents = self._initialize_agents(plan, api_client, role_manager, settings)
        memory = ConversationMemory(api_client=api_client)
        time_keeper = TimeKeeper(time_limit_sec=kwargs["time_limit"])
        conductor = Conductor(
            api_client=api_client,
            agents=agents,
            memory=memory,
            time_keeper=time_keeper,
            intervention=kwargs.get("intervention", NoIntervention()),
            settings=settings,
            model=kwargs["conductor_model"],
        )
        discussion_log = await conductor.run_discussion(plan)

        # Phase 3 ...
```

---

## 2. ABC + 実装分離パターン

### 2.1 InterventionHandler（人間介入）

```python
from abc import ABC, abstractmethod


class InterventionHandler(ABC):
    """人間介入のインターフェース。"""

    @abstractmethod
    def check_intervention(self, round_num: int, context: dict) -> str | None:
        """介入メッセージがあれば返す。なければ None。"""

    @abstractmethod
    async def notify_progress(self, event: str, data: dict) -> None:
        """進捗イベントを通知する。"""


class NoIntervention(InterventionHandler):
    """介入なし（CLI通常実行用）。"""

    def check_intervention(self, round_num: int, context: dict) -> str | None:
        return None

    async def notify_progress(self, event: str, data: dict) -> None:
        pass


class SSEInterventionHandler(InterventionHandler):
    """SSEストリーミング用（Web UI用）。"""

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue

    def check_intervention(self, round_num: int, context: dict) -> str | None:
        return None  # 将来: WebSocket で人間介入を受け取る

    async def notify_progress(self, event: str, data: dict) -> None:
        await self._queue.put({"type": event, **data})
```

### 2.2 使い分け

```python
# CLI実行時
intervention = NoIntervention()

# Web UI実行時
queue = asyncio.Queue()
intervention = SSEInterventionHandler(queue)

# どちらも同じ Conductor に渡せる
conductor = Conductor(..., intervention=intervention, ...)
```

---

## 3. リトライ + フォールバックパターン

### 3.1 指数バックオフ + ジッター

```python
import asyncio
import random

MAX_RETRIES = 3
BASE_DELAY_SEC = 1.0
MAX_DELAY_SEC = 30.0


class RetryHandler:
    """リトライロジックを管理する。"""

    def __init__(self, max_retries: int = MAX_RETRIES):
        self._max_retries = max_retries

    async def execute_with_retry(self, func, *args, **kwargs):
        """リトライ付きで関数を実行する。

        Args:
            func: 実行する非同期関数。

        Returns:
            関数の戻り値。

        Raises:
            MaxRetriesExceededError: 最大リトライ回数超過。
        """
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except RateLimitExhaustedError:
                raise  # リトライしない
            except (ServerError, TimeoutError) as e:
                last_error = e
                if attempt < self._max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        "Retry %d/%d after %.1fs: %s",
                        attempt + 1, self._max_retries, delay, e,
                    )
                    await asyncio.sleep(delay)

        raise MaxRetriesExceededError(
            f"Failed after {self._max_retries} retries: {last_error}"
        )

    def _calculate_delay(self, attempt: int) -> float:
        """指数バックオフ + ジッターで待機時間を計算する。"""
        delay = min(BASE_DELAY_SEC * (2 ** attempt), MAX_DELAY_SEC)
        jitter = random.uniform(0, delay * 0.5)
        return delay + jitter
```

### 3.2 モデルフォールバック

```python
FALLBACK_CHAIN: dict[str, str] = {
    "gpt-5.4": "gpt-4.1",
    "gpt-4.1": "gpt-4.1-mini",
    "gpt-4.1-mini": "gpt-4.1-nano",
}


class FallbackManager:
    """モデルフォールバックを管理する。"""

    async def call_with_fallback(
        self, api_client: "ResilientAPIClient", model: str, **kwargs
    ) -> dict:
        """フォールバックチェーンに沿ってAPIを呼ぶ。"""
        current_model = model
        while current_model:
            try:
                return await api_client.call_raw(model=current_model, **kwargs)
            except ModelNotFoundError:
                next_model = FALLBACK_CHAIN.get(current_model)
                if next_model:
                    logger.warning(
                        "Model %s not found, falling back to %s",
                        current_model, next_model,
                    )
                    current_model = next_model
                else:
                    raise
        raise ModelNotFoundError(f"No fallback available for {model}")
```

---

## 4. SSEストリーミングパターン

### 4.1 バックエンド（FastAPI）

```python
from fastapi.responses import StreamingResponse


@router.post("/api/idea/stream")
async def stream_discussion(request: IdeaStreamRequest):
    """SSEで議論の進捗をストリーミングする。"""
    return StreamingResponse(
        _event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_generator(request: IdeaStreamRequest):
    """SSEイベントを生成するジェネレータ。"""
    queue: asyncio.Queue = asyncio.Queue()
    intervention = SSEInterventionHandler(queue)

    task = asyncio.create_task(_run_orchestra(request, intervention))

    try:
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["type"] in ("done", "error"):
                break
    except asyncio.CancelledError:
        task.cancel()
    finally:
        if not task.done():
            task.cancel()
```

### 4.2 フロントエンド（JavaScript）

```javascript
class OrchestraSSE {
    constructor(url) {
        this._url = url;
        this._handlers = {};
        this._controller = null;
        this._state = 'idle';
    }

    on(eventType, handler) {
        if (!this._handlers[eventType]) {
            this._handlers[eventType] = [];
        }
        this._handlers[eventType].push(handler);
    }

    async start(body) {
        this._state = 'connecting';
        this._controller = new AbortController();

        try {
            const response = await fetch(this._url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: this._controller.signal,
            });

            this._state = 'streaming';
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        this._dispatch(data);
                        if (data.type === 'done' || data.type === 'error') {
                            this._state = data.type === 'done' ? 'done' : 'error';
                            return;
                        }
                    }
                }
            }
        } catch (err) {
            if (err.name !== 'AbortError') {
                this._state = 'error';
                this._dispatch({ type: 'error', message: err.message, recoverable: false });
            }
        }
    }

    abort() {
        if (this._controller) {
            this._controller.abort();
            this._state = 'idle';
        }
    }

    get state() { return this._state; }

    _dispatch(data) {
        const handlers = this._handlers[data.type] || [];
        for (const handler of handlers) {
            handler(data);
        }
        // '*' ハンドラ（全イベント受信）
        const allHandlers = this._handlers['*'] || [];
        for (const handler of allHandlers) {
            handler(data);
        }
    }
}
```

---

## 5. 時間管理パターン

### 5.1 TimeKeeper（残り時間ベースの制御）

```python
import time
from enum import Enum


class TimePressure(Enum):
    """時間逼迫度。"""
    RELAXED = "relaxed"      # 余裕あり (残り > 60%)
    MODERATE = "moderate"    # 普通 (残り 30-60%)
    URGENT = "urgent"        # 逼迫 (残り 10-30%)
    CRITICAL = "critical"    # 危機的 (残り < 10%)


PRESSURE_THRESHOLDS: dict[TimePressure, float] = {
    TimePressure.RELAXED: 0.6,
    TimePressure.MODERATE: 0.3,
    TimePressure.URGENT: 0.1,
    TimePressure.CRITICAL: 0.0,
}


class TimeKeeper:
    """議論の時間管理を行う。"""

    def __init__(self, time_limit_sec: float, phase1_actual_sec: float = 0.0):
        self._time_limit_sec = time_limit_sec
        self._phase1_actual_sec = phase1_actual_sec
        self._phase3_reserve_sec = time_limit_sec * 0.15
        self._start_time = time.monotonic()
        self._round_times: list[float] = []

    @property
    def remaining(self) -> float:
        """議論フェーズの残り時間（秒）。"""
        budget = self._time_limit_sec - self._phase1_actual_sec - self._phase3_reserve_sec
        elapsed = time.monotonic() - self._start_time
        return max(0.0, budget - elapsed)

    @property
    def pressure(self) -> TimePressure:
        """現在の時間逼迫度。"""
        ratio = self.remaining / self._discussion_budget
        if ratio > 0.6:
            return TimePressure.RELAXED
        elif ratio > 0.3:
            return TimePressure.MODERATE
        elif ratio > 0.1:
            return TimePressure.URGENT
        else:
            return TimePressure.CRITICAL

    def can_start_next_round(self, estimated_round_sec: float) -> bool:
        """次のラウンドを開始できるか判定する。"""
        safety_margin = 1.2  # 20% バッファ
        return self.remaining >= estimated_round_sec * safety_margin

    def record_round(self, duration_sec: float) -> None:
        """ラウンドの実績時間を記録する。"""
        self._round_times.append(duration_sec)

    def get_moving_average(self, window: int = 3) -> float:
        """直近ラウンドの平均所要時間を返す。"""
        if not self._round_times:
            return 60.0  # デフォルト推定
        recent = self._round_times[-window:]
        return sum(recent) / len(recent)

    @property
    def _discussion_budget(self) -> float:
        return self._time_limit_sec - self._phase1_actual_sec - self._phase3_reserve_sec
```

### 5.2 Conductor での使用

```python
async def run_discussion(self, plan: DiscussionPlan) -> DiscussionLog:
    """全ラウンドを実行する。"""
    rounds_log: list[RoundLog] = []

    for round_config in plan.rounds:
        # 時間チェック
        estimated = self._estimate_round_time(round_config)
        if not self._time_keeper.can_start_next_round(estimated):
            logger.info("Time budget exhausted. Concluding discussion.")
            break

        # 時間逼迫通知
        pressure = self._time_keeper.pressure
        if pressure in (TimePressure.URGENT, TimePressure.CRITICAL):
            await self._intervention.notify_progress("time_pressure", {
                "remaining_sec": self._time_keeper.remaining,
                "pressure": pressure.value,
            })

        # ラウンド実行
        start = time.monotonic()
        round_log = await self.run_round(round_config, plan)
        duration = time.monotonic() - start

        self._time_keeper.record_round(duration)
        rounds_log.append(round_log)

    return DiscussionLog(rounds=rounds_log)
```

---

## 6. コンテキスト管理パターン

### 6.1 メモリ + バジェット制御

```python
class ConversationMemory:
    """会話記憶を管理する。"""

    def get_context_for_agent(
        self,
        current_round: int,
        agent_role_id: str,
        context_budget: int,
    ) -> dict:
        """エージェントに渡すコンテキストを構築する。

        優先順位:
        1. 現ラウンドの全発言（必須）
        2. 前ラウンドの結論（高優先）
        3. ラウンド要約（中優先）
        4. 古いラウンドの要約（低優先 — バジェット内で）

        Args:
            current_round: 現在のラウンド番号。
            agent_role_id: エージェントのロールID。
            context_budget: トークン上限。

        Returns:
            コンテキスト辞書 (system_context, round_context, 等)。
        """
        context_parts: list[str] = []
        remaining_budget = context_budget

        # 1. 現ラウンドの発言
        current_utterances = self.get_round_utterances(current_round)
        current_text = self._format_utterances(current_utterances)
        remaining_budget -= self._estimate_tokens(current_text)
        context_parts.append(current_text)

        # 2. 前ラウンドの結論
        if current_round > 1:
            prev_conclusion = self._get_round_conclusion(current_round - 1)
            if prev_conclusion and remaining_budget > 100:
                remaining_budget -= self._estimate_tokens(prev_conclusion)
                context_parts.insert(0, f"【前ラウンド結論】{prev_conclusion}")

        # 3. ラウンド要約（バジェット内）
        for summary in reversed(self.round_summaries[:-1]):
            tokens = self._estimate_tokens(summary)
            if remaining_budget - tokens < 0:
                break
            remaining_budget -= tokens
            context_parts.insert(0, summary)

        return {
            "round_context": "\n\n".join(context_parts),
            "total_tokens_used": context_budget - remaining_budget,
        }
```

---

## 7. 評価パターン

### 7.1 構造化プロンプト → JSON パース

```python
SELF_EVALUATION_PROMPT = """\
あなたは {role_name} として議論に参加しました。
以下の議論ログを振り返り、自己評価をJSON形式で出力してください。

## 議論ログ
{discussion_log}

## 出力形式 (JSON)
{{
  "scores": {{
    "論理性": <1-5>,
    "独自性": <1-5>,
    "建設性": <1-5>,
    "簡潔性": <1-5>
  }},
  "reasoning": "<評価理由 (50文字以内)>",
  "contribution": "<最大の貢献 (50文字以内)>",
  "unfinished": "<やり残し (50文字以内)>"
}}
"""


class Evaluator:
    """評価を実行する。"""

    async def request_self_evaluation(
        self, agent: Agent, discussion_log: DiscussionLog, plan: OrchestraPlan
    ) -> dict:
        """自己評価を要求する。"""
        prompt = SELF_EVALUATION_PROMPT.format(
            role_name=agent.config.role_name,
            discussion_log=self._format_log(discussion_log),
        )
        response = await self._api_client.call(
            model=self._settings.eval_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._parse_evaluation_response(response["content"])

    def _parse_evaluation_response(self, content: str) -> dict:
        """評価レスポンスをパースする。

        JSON部分を抽出してパースする。
        コードブロックで囲まれている場合も対応。
        """
        # ```json ... ``` を除去
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # ```json 行を除去
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse evaluation: %s", e)
            return self._default_evaluation()
```

---

## 8. ファイル出力パターン

### 8.1 セッションディレクトリ生成

```python
from datetime import datetime
from pathlib import Path

SESSION_ID_FORMAT = "%Y%m%d_%H%M%S"


class OutputGenerator:
    """セッション出力を生成する。"""

    def __init__(self, output_dir: Path):
        self._output_dir = output_dir

    def generate(
        self,
        session_type: str,
        plan: "OrchestraPlan",
        discussion_log: "DiscussionLog",
        synthesis: "SynthesisResult",
        memory: "ConversationMemory",
    ) -> Path:
        """全出力ファイルを生成する。

        Returns:
            セッションディレクトリのパス。
        """
        session_id = self._generate_session_id(session_type)
        session_dir = self._output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        self._write_session_meta(session_dir, synthesis.meta)
        self._write_discussion_json(session_dir, plan, discussion_log)
        self._write_full_conversation(session_dir, synthesis.full_conversation)
        self._write_report(session_dir, synthesis.report)
        self._write_evaluation(session_dir, synthesis.evaluation_md)
        self._write_summary(session_dir, synthesis.summary)

        if synthesis.vibe_prompt:
            self._write_vibe_prompt(session_dir, synthesis.vibe_prompt)

        return session_dir

    def _generate_session_id(self, session_type: str) -> str:
        """セッションIDを生成する。形式: YYYYMMDD_HHMMSS_type"""
        timestamp = datetime.now().strftime(SESSION_ID_FORMAT)
        return f"{timestamp}_{session_type}"

    def _write_session_meta(self, session_dir: Path, meta: dict) -> None:
        """session_meta.json を書き出す。"""
        path = session_dir / "session_meta.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
```

---

## 9. 設定読み込みパターン

### 9.1 YAML + 環境変数 + デフォルト値

```python
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class APISettings:
    """API関連設定。"""
    key: str = ""
    endpoint: str = ""
    mode: str = ""  # "openai" or "azure"、空なら自動検出


@dataclass
class Settings:
    """全体設定。"""
    api: APISettings = field(default_factory=APISettings)
    time_limit_default: int = 300
    max_agents_default: int = 5

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "Settings":
        """設定を読み込む。

        優先順位: CLI引数 > .env > 環境変数 > settings.yaml
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"

        # 1. settings.yaml 読み込み
        yaml_path = config_dir / "settings.yaml"
        raw = {}
        if yaml_path.exists():
            raw = yaml.safe_load(yaml_path.read_text()) or {}

        # 2. .env 読み込み
        env_vars = cls._load_dotenv()

        # 3. 環境変数で上書き
        api_key = env_vars.get("KOTOBUDDY_API_KEY", os.environ.get("KOTOBUDDY_API_KEY", ""))
        api_endpoint = env_vars.get("KOTOBUDDY_ENDPOINT", os.environ.get("KOTOBUDDY_ENDPOINT", ""))

        return cls(
            api=APISettings(key=api_key, endpoint=api_endpoint),
            time_limit_default=raw.get("defaults", {}).get("time_limit", 300),
            max_agents_default=raw.get("defaults", {}).get("max_agents", 5),
        )
```

---

## 10. ロール定義パターン

### 10.1 YAML構造 → Agent生成

```yaml
# config/roles/theorist.yaml
id: theorist
name: 理論屋
emoji: "🧮"
specialty: "数学的定式化、計算量解析、収束証明"
personality: "厳密・論理的。数式で語りたがる"
weaknesses: "実装コストを軽視しがち"
speaking_rules:
  - "主張には必ず計算量や証明の根拠を添える"
  - "他者の直感的主張を数式で再解釈する"
  - "実装不可能な理論に走りすぎない"
system_prompt_template: |
  あなたは「理論屋」です。{specialty}
  性格: {personality}
  
  発言ルール:
  {speaking_rules}
  
  弱み (自覚して改善に努めること): {weaknesses}
feedback_history: []
```

### 10.2 RoleManager でのロード

```python
class RoleManager:
    """ロールYAMLを読み込み・検証する。"""

    REQUIRED_FIELDS = frozenset({"id", "name", "emoji", "specialty", "system_prompt_template"})

    def __init__(self, roles_dir: Path):
        self._roles_dir = roles_dir
        self._cache: dict[str, dict] = {}

    def load_role(self, role_id: str) -> dict:
        """ロール定義を読み込む。

        Args:
            role_id: ロールID (例: "theorist")

        Returns:
            ロール定義辞書。

        Raises:
            RoleNotFoundError: ロールファイルが存在しない。
            RoleValidationError: 必須フィールドが不足。
        """
        if role_id in self._cache:
            return self._cache[role_id]

        path = self._roles_dir / f"{role_id}.yaml"
        if not path.exists():
            raise RoleNotFoundError(f"Role not found: {role_id}")

        role = yaml.safe_load(path.read_text())
        self._validate_role(role)
        self._cache[role_id] = role
        return role

    def _validate_role(self, role: dict) -> None:
        """必須フィールドの存在を検証する。"""
        missing = self.REQUIRED_FIELDS - set(role.keys())
        if missing:
            raise RoleValidationError(f"Missing fields: {missing}")
```

---

## 11. 収束・停滞検知パターン

### 11.1 収束チェック

```python
CONVERGENCE_CHECK_PROMPT = """\
以下の議論ログを読み、議論の収束度を0.0〜1.0で評価してください。

収束度の基準:
- 0.0〜0.3: 発散中（新しい論点が次々出ている）
- 0.3〜0.6: 議論中（論点が絞られつつある）
- 0.6〜0.8: 収束傾向（合意形成に向かっている）
- 0.8〜1.0: 収束済み（主要合意が形成された）

## 議論ログ
{round_log}

## 出力 (JSON)
{{"score": <0.0-1.0>, "reason": "<理由 30文字以内>"}}
"""


class ConvergenceChecker:
    """議論の収束度を判定する。"""

    def __init__(self, api_client: "ResilientAPIClient", model: str):
        self._api_client = api_client
        self._model = model
        self._history: list[float] = []

    async def check(self, round_log: "RoundLog") -> "ConvergenceResult":
        """現ラウンドの収束度を計算する。"""
        prompt = CONVERGENCE_CHECK_PROMPT.format(
            round_log=self._format_round(round_log)
        )
        response = await self._api_client.call(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response["content"])
        self._history.append(result["score"])
        return ConvergenceResult(score=result["score"], reason=result["reason"])

    def is_stagnating(self, window: int = 3, tolerance: float = 0.05) -> bool:
        """直近のスコア変動が小さすぎるか判定する。"""
        if len(self._history) < window:
            return False
        recent = self._history[-window:]
        return max(recent) - min(recent) < tolerance
```

### 11.2 堂々巡り検知

```python
class RepetitionDetector:
    """発言の繰り返しを検知する。"""

    DETECTION_PROMPT = """\
以下の直近{window}発言が内容的に繰り返しになっていないか判定してください。

{utterances}

出力 (JSON):
{{"is_repetitive": <true/false>, "suggestion": "<新しい論点の提案 (50文字以内)>"}}
"""

    async def check_repetition(
        self, recent_utterances: list["Utterance"], window: int = 4
    ) -> dict:
        """直近発言の繰り返しを検知する。"""
        if len(recent_utterances) < window:
            return {"is_repetitive": False, "suggestion": ""}

        target = recent_utterances[-window:]
        prompt = self.DETECTION_PROMPT.format(
            window=window,
            utterances=self._format_utterances(target),
        )
        response = await self._api_client.call(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response["content"])
```

---

## 12. Alpine.js 状態管理パターン

### 12.1 ページコンポーネント関数

```javascript
/**
 * Idea議論ページの状態管理。
 * Alpine.js の x-data にバインドする。
 */
function ideaPage() {
    return {
        // === State ===
        step: 1,
        prompt: '',
        timeLimit: 300,
        maxAgents: 5,
        expertise: 'intermediate',
        plan: null,
        planLoading: false,
        utterances: [],
        currentRound: 0,
        remainingSec: 0,
        sessionResult: null,
        sse: null,

        // === Computed (getter) ===
        get isPromptValid() {
            return this.prompt.length >= 5 && this.prompt.length <= 5000;
        },

        get timeLimitFormatted() {
            const min = Math.floor(this.timeLimit / 60);
            const sec = this.timeLimit % 60;
            return `${min}:${sec.toString().padStart(2, '0')}`;
        },

        // === Actions ===
        async submitPlan() {
            this.planLoading = true;
            try {
                const res = await fetch('/api/idea/plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: this.prompt, /* ... */ }),
                });
                this.plan = await res.json();
                this.step = 2;
            } catch (err) {
                toast(err.message, 'error');
            } finally {
                this.planLoading = false;
            }
        },

        async startDiscussion() {
            this.step = 3;
            this.sse = new OrchestraSSE('/api/idea/stream');
            this.sse.on('utterance', (data) => this.addUtterance(data));
            this.sse.on('done', (data) => { this.sessionResult = data; this.step = 4; });
            this.sse.on('error', (data) => toast(data.message, 'error'));
            await this.sse.start({ plan: this.plan, prompt: this.prompt });
        },

        addUtterance(data) {
            this.utterances.push(data);
            this.$nextTick(() => this.scrollToBottom());
        },

        scrollToBottom() {
            const el = this.$refs.chatContainer;
            if (el) el.scrollTop = el.scrollHeight;
        },

        // === Lifecycle ===
        init() {
            this.restoreFromStorage();
        },

        saveToStorage() {
            localStorage.setItem('idea_prompt', this.prompt);
            localStorage.setItem('idea_timeLimit', this.timeLimit);
        },

        restoreFromStorage() {
            this.prompt = localStorage.getItem('idea_prompt') || '';
            this.timeLimit = parseInt(localStorage.getItem('idea_timeLimit') || '300');
        },
    };
}
```

### 12.2 ダークモードパターン

```javascript
// <head> 内に配置（白フラッシュ防止）
(function() {
    const stored = localStorage.getItem('darkMode');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'true' || (stored === null && prefersDark)) {
        document.documentElement.classList.add('dark');
    }
})();

// Alpine.js コンポーネント
function darkModeToggle() {
    return {
        isDark: document.documentElement.classList.contains('dark'),
        toggle() {
            this.isDark = !this.isDark;
            document.documentElement.classList.toggle('dark', this.isDark);
            localStorage.setItem('darkMode', this.isDark);
        },
    };
}
```

---

## 13. エラーハンドリングの層構造

```
Layer 1: api_client.py
├── ネットワークエラー → ServerError (retryable)
├── 認証エラー → AuthenticationError
├── レートリミット → RateLimitExhaustedError
├── タイムアウト → TimeoutError
└── 空レスポンス → EmptyResponseError

Layer 2: agent.py
├── API呼び出し失敗をキャッチ
├── リトライ可能ならリトライ (RetryHandler経由)
└── 不可能なら上位に再送出

Layer 3: conductor.py
├── Agent失敗 → 該当ラウンドのスキップ or 短縮
├── 時間切れ → 強制終了
└── 重大エラー → PartialResult を保存して終了

Layer 4: features/idea_discussion.py
├── Phase全体のエラーハンドリング
├── 部分結果の保存
└── ユーザーへのエラー報告

Layer 5: main.py / web/routes/
├── ユーザーフレンドリーなエラー表示
└── リカバリー提案 (再実行/設定変更)
```

---

## 14. テストでのモック注入パターン

```python
import pytest
from tests.mocks.mock_api import MockAPIClient


@pytest.fixture
def mock_api():
    """モックAPIクライアントを提供する。"""
    return MockAPIClient(responses=[
        {"content": '{"score": 0.75, "reason": "議論が深まっている"}'},
        {"content": '{"score": 0.85, "reason": "合意形成に近い"}'},
    ])


@pytest.fixture
def agent(mock_api):
    """テスト用エージェントを提供する。"""
    role = {"id": "theorist", "name": "理論屋", "emoji": "🧮", "specialty": "...", "system_prompt_template": "..."}
    config = AgentConfig(role_id="theorist", model="gpt-4.1", level="standard")
    memory = ConversationMemory(api_client=mock_api)
    return Agent(config=config, role_definition=role, api_client=mock_api, memory=memory, settings=mock_settings())


@pytest.mark.asyncio
async def test_speak_returns_utterance(agent, mock_api):
    """speak() は Utterance を返す。"""
    mock_api.responses = [{"content": "計算量的に見ると O(n log n) が最適です"}]

    result = await agent.speak(round_context={"round_num": 1, "phase": "diverge"})

    assert isinstance(result, Utterance)
    assert result.content == "計算量的に見ると O(n log n) が最適です"
    assert result.role_id == "theorist"
    assert mock_api.call_count == 1