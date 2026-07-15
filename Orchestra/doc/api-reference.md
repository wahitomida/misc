# AI Orchestra — API リファレンス

> LLM API の呼び出し仕様・制約・モデル別挙動の全容

---

## 1. 接続モード

### 1.1 自動検出ロジック

```python
def detect_mode(endpoint: str, explicit_mode: str | None = None) -> str:
    """接続モードを自動検出する。

    Args:
        endpoint: エンドポイントURL。
        explicit_mode: 明示指定 ("openai" / "azure" / None)。

    Returns:
        "openai" または "azure"。
    """
    if explicit_mode:
        return explicit_mode
    if "openai.azure.com" in endpoint or "azure" in endpoint.lower():
        return "azure"
    return "openai"
```

### 1.2 モード別クライアント生成

| モード | SDK クラス | 必要な環境変数 |
|--------|-----------|---------------|
| `openai` | `AsyncOpenAI` | `KOTOBUDDY_API_KEY`, `KOTOBUDDY_ENDPOINT` |
| `azure` | `AsyncAzureOpenAI` | `KOTOBUDDY_API_KEY`, `KOTOBUDDY_ENDPOINT` (+ api_version) |

```python
# openai モード
client = AsyncOpenAI(
    api_key=settings.api.key,
    base_url=settings.api.endpoint,
)

# azure モード
client = AsyncAzureOpenAI(
    api_key=settings.api.key,
    azure_endpoint=settings.api.endpoint,
    api_version="2024-12-01-preview",
)
```

---

## 2. モデル一覧と特性

### 2.1 使用可能モデル

| モデル | 用途 | タイムアウト | 特記事項 |
|--------|------|------------|---------|
| `gpt-5.4` | 計画立案 (Phase 1), 統合 (Phase 3) | 120秒 | 最高品質、高コスト |
| `gpt-4.1` | 議論進行 (Phase 2), 評価 | 90秒 | 標準品質、中コスト |
| `gpt-4.1-mini` | フォールバック、要約 | 60秒 | 軽量、低コスト |
| `gpt-4.1-nano` | 最終フォールバック | 30秒 | 最軽量 |

### 2.2 モデル別パラメータ制約

| モデル | temperature | max_tokens | その他 |
|--------|-------------|------------|--------|
| `gpt-5.4` | **指定禁止** | **指定禁止** | reasoning model のため |
| `gpt-4.1` | 0.7 (議論) / 0.3 (評価) | 1024 | — |
| `gpt-4.1-mini` | 0.7 | 512 | — |
| `gpt-4.1-nano` | 0.7 | 256 | — |

### 2.3 GPT-5 系判定

```python
GPT5_SERIES_PREFIXES = ("gpt-5", "o1", "o3", "o4-mini")

def _is_gpt5_series(self, model: str) -> bool:
    """GPT-5系 (reasoning model) か判定する。

    GPT-5系は temperature / max_tokens を指定できない。
    """
    return any(model.startswith(prefix) for prefix in GPT5_SERIES_PREFIXES)
```

### 2.4 Claude Thinking 系判定

```python
CLAUDE_THINKING_MODELS = ("claude-sonnet-4-20250514",)
CLAUDE_THINKING_BUDGET = 10000

def _is_claude_thinking_model(self, model: str) -> bool:
    """Claude thinking model か判定する。"""
    return model in CLAUDE_THINKING_MODELS
```

---

## 3. API 呼び出し仕様

### 3.1 リクエスト構築

```python
def _build_params(self, model: str, messages: list[dict], **kwargs) -> dict:
    """モデルに応じたAPIパラメータを構築する。"""
    if self._is_gpt5_series(model):
        return self._build_params_gpt5(model, messages, **kwargs)
    elif self._is_claude_thinking_model(model):
        return self._build_params_claude_thinking(model, messages, **kwargs)
    else:
        return self._build_params_standard(model, messages, **kwargs)
```

#### 3.1.1 標準モデル (gpt-4.1 等)

```python
def _build_params_standard(self, model: str, messages: list[dict], **kwargs) -> dict:
    """標準モデルのパラメータ。"""
    return {
        "model": model,
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.7),
        "max_tokens": kwargs.get("max_tokens", 1024),
    }
```

#### 3.1.2 GPT-5 系 (reasoning model)

```python
def _build_params_gpt5(self, model: str, messages: list[dict], **kwargs) -> dict:
    """GPT-5系のパラメータ。temperature/max_tokens を含めない。"""
    return {
        "model": model,
        "messages": messages,
        # temperature, max_tokens は指定しない
    }
```

#### 3.1.3 Claude Thinking 系

```python
def _build_params_claude_thinking(self, model: str, messages: list[dict], **kwargs) -> dict:
    """Claude thinking model のパラメータ。"""
    return {
        "model": model,
        "messages": messages,
        "temperature": 1,  # 必須: 1 固定
        "max_tokens": 16000,
        "thinking": {
            "type": "enabled",
            "budget_tokens": CLAUDE_THINKING_BUDGET,
        },
    }
```

### 3.2 レスポンス形式

```python
# API呼び出し結果の統一形式
@dataclass
class APIResponse:
    """API レスポンス。"""
    content: str                    # 応答テキスト
    model: str                      # 使用されたモデル
    usage: dict[str, int] | None    # {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...}
    finish_reason: str | None       # "stop", "length", etc.
```

### 3.3 呼び出し例

```python
# 基本的な呼び出し
response = await api_client.call(
    model="gpt-4.1",
    messages=[
        {"role": "system", "content": "あなたは理論物理学者です。"},
        {"role": "user", "content": "量子コンピューティングの現状を50文字で。"},
    ],
    temperature=0.7,
    max_tokens=256,
)
print(response["content"])  # "量子コンピューティングは..."

# GPT-5系の呼び出し (temperature/max_tokens 不要)
response = await api_client.call(
    model="gpt-5.4",
    messages=[
        {"role": "user", "content": "議論計画を立案してください。"},
    ],
    # temperature, max_tokens は自動的に除外される
)
```

---

## 4. フォールバックチェーン

### 4.1 チェーン定義

```
gpt-5.4 → gpt-4.1 → gpt-4.1-mini → gpt-4.1-nano
```

### 4.2 フォールバック発動条件

| 条件 | 動作 |
|------|------|
| `ModelNotFoundError` | 次のモデルにフォールバック |
| `ServerError` (retryable) | リトライ → 全失敗後にフォールバック |
| `RateLimitExhaustedError` | フォールバック **しない** (全モデル共通制限) |
| `AuthenticationError` | フォールバック **しない** (認証問題) |
| `TimeoutError` | リトライ → 全失敗後にフォールバック |

### 4.3 フォールバック時のログ

```python
logger.warning(
    "Model %s failed (%s). Falling back to %s.",
    current_model, error_type, fallback_model,
)
```

---

## 5. リトライ戦略

### 5.1 リトライ設定

```python
@dataclass
class RetryConfig:
    """リトライ設定。"""
    max_retries: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 30.0
    jitter_factor: float = 0.5
```

### 5.2 リトライ対象の判定

| 例外型 | リトライ | 理由 |
|--------|---------|------|
| `ServerError` (5xx) | ✅ する | 一時的なサーバー障害 |
| `TimeoutError` | ✅ する | ネットワーク一時障害 |
| `RateLimitExhaustedError` | ❌ しない | 日次上限到達 |
| `AuthenticationError` | ❌ しない | 認証情報の問題 |
| `ModelNotFoundError` | ❌ しない | フォールバックへ |
| `EmptyResponseError` | ✅ する | 再送で解決する場合あり |

### 5.3 バックオフ計算

```
delay = min(base_delay * 2^attempt, max_delay) + random(0, delay * jitter_factor)

attempt 0: 1.0s + jitter → 1.0〜1.5s
attempt 1: 2.0s + jitter → 2.0〜3.0s
attempt 2: 4.0s + jitter → 4.0〜6.0s
```

---

## 6. レートリミット管理

### 6.1 自主制限

```python
@dataclass
class RateLimitTracker:
    """APIレートリミットを追跡する。"""
    daily_limit: int = 10000          # 1日の上限リクエスト数
    safety_margin: float = 0.9        # 90%で警告
    request_count: int = 0            # 本日のリクエスト数
    last_reset: date = field(default_factory=date.today)
    persistence_path: Path = Path("output/.rate_limit.json")
```

### 6.2 セッション開始前チェック

```python
def can_proceed(self, estimated_requests: int) -> bool:
    """セッションに必要なリクエスト数を確保できるか。

    Args:
        estimated_requests: 推定リクエスト数。

    Returns:
        True なら実行可能。
    """
    effective_limit = int(self.daily_limit * self.safety_margin)
    return (self.request_count + estimated_requests) <= effective_limit
```

### 6.3 推定リクエスト数の計算

| 処理 | 推定リクエスト |
|------|--------------|
| Phase 1 計画立案 | 1 |
| Phase 2 各発言 | 1/発言 |
| Phase 2 収束チェック | 1/ラウンド |
| Phase 2 停滞検知 | 0〜1/ラウンド |
| Phase 2 ラウンド要約 | 1/ラウンド |
| Phase 3 自己評価 | エージェント数 |
| Phase 3 他者評価 | エージェント数 |
| Phase 3 指揮者評価 | 1 |
| Phase 3 レポート生成 | 1 |
| Phase 3 要約生成 | 1 |

**典型的な idea セッション (5エージェント, 3ラウンド):**
```
Phase 1: 1
Phase 2: 15発言 + 3収束 + 1停滞 + 3要約 = 22
Phase 3: 5自己 + 5他者 + 1指揮者 + 1レポート + 1要約 = 13
合計: 約36リクエスト
```

---

## 7. 空レスポンス対処

### 7.1 検知と再送

```python
class EmptyResponseHandler:
    """空レスポンスを処理する。"""

    MAX_EMPTY_RETRIES = 2

    async def handle_empty_response(
        self, params: dict, api_client: "ResilientAPIClient"
    ) -> dict:
        """空レスポンスを検知し、再送を試みる。

        戦略:
        1. そのまま再送 (1回目)
        2. "応答を続けてください" を追加して再送 (2回目)
        3. それでも空なら EmptyResponseError を投げる
        """
        for attempt in range(self.MAX_EMPTY_RETRIES):
            if attempt == 1:
                # 2回目: 明示的に応答を要求
                params["messages"] = params["messages"] + [
                    {"role": "user", "content": "応答を続けてください。"}
                ]
            response = await api_client.call_raw(**params)
            if response.get("content", "").strip():
                return response

        raise EmptyResponseError("Empty response after retries")
```

### 7.2 空レスポンスの定義

```python
def _is_empty(content: str | None) -> bool:
    """レスポンスが実質的に空か判定する。"""
    if content is None:
        return True
    stripped = content.strip()
    return len(stripped) == 0 or stripped in ("...", "。", ".", "")
```

---

## 8. エラー分類

### 8.1 例外階層

```
OrchestraError (基底)
├── OrchestraAPIError (API関連の基底)
│   ├── ModelNotFoundError        — model: str
│   ├── AuthenticationError       — is_rate_limit: bool
│   ├── RateLimitExhaustedError
│   ├── EmptyResponseError
│   ├── MaxRetriesExceededError
│   ├── TimeoutError
│   └── ServerError               — status_code: int, retryable: bool
├── RoleNotFoundError
├── RoleValidationError
├── SessionNotFoundError
├── InputTooShortError
├── InputTooLongError
├── ChainTooDeepError
└── ConfigLoadError
```

### 8.2 HTTPステータスからの分類

```python
def _classify_error(self, exception: Exception, model: str) -> OrchestraAPIError:
    """SDK例外を Orchestra 例外に変換する。"""
    if isinstance(exception, openai.AuthenticationError):
        return AuthenticationError("Invalid API key")
    elif isinstance(exception, openai.RateLimitError):
        return RateLimitExhaustedError("Rate limit exceeded")
    elif isinstance(exception, openai.NotFoundError):
        return ModelNotFoundError(model=model)
    elif isinstance(exception, openai.APITimeoutError):
        return TimeoutError(f"Timeout for model {model}")
    elif isinstance(exception, openai.APIStatusError):
        status = exception.status_code
        retryable = status >= 500
        return ServerError(status_code=status, retryable=retryable)
    else:
        return ServerError(status_code=0, retryable=False)
```

---

## 9. タイムアウト設定

### 9.1 モデル別タイムアウト

```yaml
# settings.yaml
api:
  timeout:
    gpt-5.4: 120
    gpt-4.1: 90
    gpt-4.1-mini: 60
    gpt-4.1-nano: 30
    default: 90
```

### 9.2 タイムアウト取得

```python
def get_timeout(self, model: str) -> int:
    """モデル別のタイムアウト秒数を返す。

    Args:
        model: モデル名。

    Returns:
        タイムアウト秒数。
    """
    timeouts = self._raw.get("api", {}).get("timeout", {})
    return timeouts.get(model, timeouts.get("default", 90))
```

---

## 10. Web API エンドポイント一覧

### 10.1 Pages (HTML)

| Method | Path | 説明 |
|--------|------|------|
| GET | `/` | Heroランディングページ |
| GET | `/idea` | Idea議論ページ |
| GET | `/review` | コードレビューページ |
| GET | `/history` | セッション履歴 |
| GET | `/replay/{session_id}` | セッション再表示 |
| GET | `/roles` | ロール一覧 |

### 10.2 REST API (JSON)

| Method | Path | 説明 |
|--------|------|------|
| POST | `/api/idea/plan` | 計画立案 (非ストリーミング) |
| POST | `/api/idea/stream` | 議論実行 (SSE) |
| POST | `/api/review/plan` | レビュー計画 (非ストリーミング) |
| POST | `/api/review/stream` | レビュー実行 (SSE) |
| GET | `/api/sessions` | セッション一覧 |
| GET | `/api/sessions/recent` | 最新セッション (limit指定) |
| GET | `/api/sessions/{id}` | セッション詳細 |
| GET | `/api/sessions/{id}/content` | セッション全コンテンツ |
| GET | `/api/sessions/{id}/download` | ファイルダウンロード |
| DELETE | `/api/sessions/{id}` | セッション削除 |
| GET | `/api/roles` | ロール一覧 |
| GET | `/api/roles/{id}` | ロール詳細 |
| GET | `/api/roles/{id}/stats` | ロール統計 |

### 10.3 SSE イベント仕様

```
POST /api/idea/stream
Content-Type: application/json
Accept: text/event-stream

Response: text/event-stream
```

**イベント形式:**
```
data: {"type": "event_name", ...payload}\n\n
```

**イベント型一覧:**

| type | Phase | payload |
|------|-------|---------|
| `planning_start` | 1 | `{}` |
| `planning_complete` | 1 | `{"plan": {...}}` |
| `round_start` | 2 | `{"round": 1, "config": {...}}` |
| `utterance` | 2 | `{"round": 1, "agent": {...}, "content": "...", "tokens": 150}` |
| `round_conclusion` | 2 | `{"round": 1, "concluder": "theorist", "content": "..."}` |
| `round_end` | 2 | `{"round": 1, "convergence": 0.72, "elapsed_sec": 45.2}` |
| `convergence_check` | 2 | `{"round": 1, "score": 0.72, "threshold": 0.85}` |
| `stagnation_detected` | 2 | `{"round": 2, "action": "pivot"}` |
| `time_pressure` | 2 | `{"remaining_sec": 30, "pressure": "CRITICAL"}` |
| `synthesis_start` | 3 | `{}` |
| `evaluation_progress` | 3 | `{"step": "self_eval", "agent": "theorist"}` |
| `synthesis_complete` | 3 | `{"report_preview": "...first 200 chars..."}` |
| `progress` | * | `{"phase": "discussion", "percent": 65, "elapsed_sec": 120, "remaining_sec": 180}` |
| `done` | — | `{"session_id": "...", "output_dir": "...", "statistics": {...}}` |
| `error` | — | `{"message": "...", "recoverable": false}` |

---

## 11. リクエスト/レスポンス型

### 11.1 Idea Plan

```python
class IdeaPlanRequest(BaseModel):
    """idea計画リクエスト。"""
    prompt: str = Field(..., min_length=5, max_length=5000, description="議論テーマ")
    planner_model: str = Field("gpt-5.4", description="計画立案モデル")
    conductor_model: str = Field("gpt-4.1", description="議論進行モデル")
    synth_model: str = Field("gpt-5.4", description="統合モデル")
    time_limit: int = Field(300, ge=60, le=1800, description="制限時間(秒)")
    max_agents: int = Field(5, ge=2, le=8, description="最大参加AI数")
    expertise: Literal["beginner", "intermediate", "expert"] = Field(
        "intermediate", description="専門レベル"
    )
    follow_up_id: str | None = Field(None, description="フォローアップ元セッションID")
    attached_files: list[str] = Field(default_factory=list, description="添付ファイルパス")


class IdeaPlanResponse(BaseModel):
    """idea計画レスポンス。"""
    plan: dict  # OrchestraPlan のdict表現
    estimated_requests: int
    remaining_quota: int
```

### 11.2 Idea Stream

```python
class IdeaStreamRequest(BaseModel):
    """ideaストリーミングリクエスト。"""
    plan: dict                          # 確認済みの計画
    prompt: str                         # 元テーマ
    conductor_model: str = "gpt-4.1"
    synth_model: str = "gpt-5.4"
    time_limit: int = 300
    expertise: str = "intermediate"
```

### 11.3 Sessions

```python
class SessionListResponse(BaseModel):
    """セッション一覧レスポンス。"""
    sessions: list[SessionSummary]
    total: int
    page: int
    pages: int


class SessionSummary(BaseModel):
    """セッション概要。"""
    id: str
    type: str                   # "idea" or "review"
    theme: str                  # テーマ (truncated)
    date: str                   # ISO 8601
    duration_sec: float | None
    convergence: float | None   # idea のみ
    focus: str | None           # review のみ


class SessionContentResponse(BaseModel):
    """セッション全コンテンツ。"""
    session_id: str
    files: dict[str, str]       # {"report": "# ...", "conversation": "# ...", ...}
    statistics: dict
    hypotheses: list[dict] | None
```

---

## 12. 接続テスト

### 12.1 ヘルスチェック

```python
@router.get("/api/health")
async def health_check():
    """API接続の健全性を確認する。"""
    try:
        api_client = get_api_client()
        response = await api_client.call(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return {
            "status": "ok",
            "mode": api_client.mode,
            "model_available": True,
            "rate_limit_remaining": api_client.rate_tracker.remaining(),
        }
    except OrchestraAPIError as e:
        return {
            "status": "degraded",
            "error": str(e),
            "mode": api_client.mode,
        }
```

---

## 13. 使用量レポート

### 13.1 セッション終了時の統計

```python
@dataclass
class SessionStatistics:
    """セッションの使用量統計。"""
    total_requests: int           # API呼び出し回数
    total_tokens: int             # 総トークン数
    prompt_tokens: int            # 入力トークン
    completion_tokens: int        # 出力トークン
    duration_sec: float           # 所要時間
    model_usage: dict[str, int]   # モデル別リクエスト数
    fallback_count: int           # フォールバック発生回数
    retry_count: int              # リトライ発生回数
    rate_limit_remaining: int     # 残りリクエスト数
```

### 13.2 統計の収集

```python
# api_client 内部でカウント
class ResilientAPIClient:
    def __init__(self, ...):
        self._stats = {
            "total_requests": 0,
            "total_tokens": 0,
            "fallback_count": 0,
            "retry_count": 0,
            "model_usage": defaultdict(int),
        }

    async def call(self, model: str, messages: list[dict], **kwargs) -> dict:
        result = await self._execute(model, messages, **kwargs)
        self._stats["total_requests"] += 1
        self._stats["model_usage"][model] += 1
        if result.get("usage"):
            self._stats["total_tokens"] += result["usage"].get("total_tokens", 0)
        return result

    def get_statistics(self) -> dict:
        """使用量統計を返す。"""
        return dict(self._stats)