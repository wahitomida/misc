# AI Orchestra — テスト戦略

> テスト方針・モック設計・カバレッジ目標の全容

---

## 1. テスト階層

```
┌─────────────────────────────────────────────────────────┐
│  E2E テスト (tests/e2e/)                                │
│  - 実API使用、全フロー通し                               │
│  - 実行頻度: 手動 / リリース前                           │
│  - 所要時間: 数分                                        │
├─────────────────────────────────────────────────────────┤
│  統合テスト (tests/integration/)                         │
│  - MockAPI使用、Feature全体フロー                        │
│  - 実行頻度: PR ごと                                    │
│  - 所要時間: 数十秒                                      │
├─────────────────────────────────────────────────────────┤
│  ユニットテスト (tests/unit/)                            │
│  - MockAPI使用、1クラス/1メソッド単位                    │
│  - 実行頻度: 毎回 (保存時/コミット前)                    │
│  - 所要時間: 数秒                                        │
└─────────────────────────────────────────────────────────┘
```

| 層 | 目的 | スコープ | API | マーカー |
|----|------|---------|-----|---------|
| ユニット | 個別ロジック検証 | 1クラス/1メソッド | Mock | (なし) |
| 統合 | フロー全体検証 | Feature + Core | Mock | `@pytest.mark.integration` |
| E2E | 実環境動作確認 | CLI/Web → API → 出力 | Real | `@pytest.mark.e2e` |

---

## 2. 実行コマンド

```bash
# ユニットテスト (日常使い)
pytest tests/unit/ -v

# ユニットテスト (高速・簡潔表示)
pytest tests/unit/ -q

# 統合テスト
pytest tests/integration/ -v

# E2Eテスト (実APIキー必要)
pytest tests/e2e/ -v

# 全テスト
pytest

# カバレッジ計測
pytest tests/unit/ --cov=core --cov=features --cov-report=html --cov-report=term

# 特定モジュールのテスト
pytest tests/unit/test_agent.py -v

# 特定テスト関数
pytest tests/unit/test_agent.py::test_speak_returns_utterance -v

# 失敗したテストのみ再実行
pytest --lf

# 変更されたファイルに関連するテストのみ
pytest --co -q  # テスト一覧表示 (実行せず)
```

---

## 3. ディレクトリ構造

```
tests/
├── __init__.py
├── conftest.py              # 共通 fixture
├── unit/
│   ├── __init__.py
│   ├── conftest.py          # ユニットテスト用 fixture
│   ├── test_config_loader.py
│   ├── test_api_client.py
│   ├── test_rate_tracker.py
│   ├── test_time_keeper.py
│   ├── test_turn_calculator.py
│   ├── test_role_manager.py
│   ├── test_memory.py
│   ├── test_agent.py
│   ├── test_orchestrator.py
│   ├── test_conductor.py
│   ├── test_evaluator.py
│   ├── test_synthesizer.py
│   ├── test_feedback.py
│   ├── test_follow_up.py
│   └── test_output_generator.py
├── integration/
│   ├── __init__.py
│   ├── conftest.py          # 統合テスト用 fixture
│   ├── test_idea_discussion.py
│   └── test_code_review.py
├── e2e/
│   ├── __init__.py
│   └── test_full_session.py
├── mocks/
│   ├── __init__.py
│   └── mock_api.py          # MockAPIClient
└── fixtures/
    ├── settings_test.yaml   # テスト用設定
    ├── roles/               # テスト用ロール (最小限)
    │   └── theorist.yaml
    └── sessions/            # テスト用セッション出力
        └── 20260101_000000_idea/
            ├── session_meta.json
            ├── discussion.json
            ├── report.md
            └── summary.txt
```

---

## 4. MockAPIClient 仕様

### 4.1 基本設計

```python
"""テスト用モック API クライアント。

実際のLLM APIを呼ばずに、事前定義されたレスポンスを返す。
呼び出し履歴を記録し、アサーション用メソッドを提供する。
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class MockAPIClient:
    """モック API クライアント。

    Attributes:
        responses: 順番に返すレスポンスリスト。
        call_log: 呼び出し履歴。
        mode: 接続モード (テスト用)。
        default_response: responses が空の場合のデフォルト。
    """
    responses: list[dict] = field(default_factory=list)
    call_log: list[dict] = field(default_factory=list)
    mode: str = "openai"
    default_response: dict = field(default_factory=lambda: {"content": "mock response"})

    @property
    def call_count(self) -> int:
        """呼び出し回数。"""
        return len(self.call_log)

    async def call(self, model: str, messages: list[dict], **kwargs) -> dict:
        """モックAPI呼び出し。

        Args:
            model: モデル名。
            messages: メッセージリスト。
            **kwargs: 追加パラメータ。

        Returns:
            事前定義されたレスポンス。
        """
        self.call_log.append({
            "model": model,
            "messages": messages,
            "kwargs": kwargs,
        })

        if self.responses:
            return self.responses.pop(0)
        return self.default_response.copy()

    async def call_raw(self, model: str, messages: list[dict], **kwargs) -> dict:
        """フォールバックなしのモック呼び出し。call() と同じ動作。"""
        return await self.call(model, messages, **kwargs)

    # === アサーションヘルパー ===

    def assert_called(self) -> None:
        """少なくとも1回呼ばれたことを確認。"""
        assert self.call_count > 0, "API was not called"

    def assert_call_count(self, expected: int) -> None:
        """指定回数呼ばれたことを確認。"""
        assert self.call_count == expected, (
            f"Expected {expected} calls, got {self.call_count}"
        )

    def assert_called_with_model(self, model: str) -> None:
        """指定モデルで呼ばれたことを確認。"""
        models_used = [log["model"] for log in self.call_log]
        assert model in models_used, (
            f"Model {model} not found in calls: {models_used}"
        )

    def assert_no_temperature(self) -> None:
        """temperature が指定されていないことを確認 (GPT-5系テスト用)。"""
        for log in self.call_log:
            assert "temperature" not in log["kwargs"], (
                f"temperature was specified: {log['kwargs']}"
            )

    def assert_no_max_tokens(self) -> None:
        """max_tokens が指定されていないことを確認 (GPT-5系テスト用)。"""
        for log in self.call_log:
            assert "max_tokens" not in log["kwargs"], (
                f"max_tokens was specified: {log['kwargs']}"
            )

    def assert_system_prompt_contains(self, text: str) -> None:
        """system prompt に特定テキストが含まれることを確認。"""
        for log in self.call_log:
            for msg in log["messages"]:
                if msg["role"] == "system" and text in msg["content"]:
                    return
        assert False, f"Text '{text}' not found in any system prompt"

    def get_last_call(self) -> dict:
        """最後の呼び出しを取得。"""
        assert self.call_log, "No calls recorded"
        return self.call_log[-1]

    def reset(self) -> None:
        """呼び出し履歴をリセット。"""
        self.call_log.clear()
```

### 4.2 特殊動作モック

```python
class ErrorMockAPIClient(MockAPIClient):
    """エラーを発生させるモック。"""

    def __init__(self, error: Exception, fail_count: int = 1):
        """
        Args:
            error: 発生させる例外。
            fail_count: 失敗する回数 (その後は正常応答)。
        """
        super().__init__()
        self._error = error
        self._fail_count = fail_count
        self._error_count = 0

    async def call(self, model: str, messages: list[dict], **kwargs) -> dict:
        self.call_log.append({"model": model, "messages": messages, "kwargs": kwargs})
        if self._error_count < self._fail_count:
            self._error_count += 1
            raise self._error
        if self.responses:
            return self.responses.pop(0)
        return self.default_response.copy()


class DelayMockAPIClient(MockAPIClient):
    """遅延を発生させるモック (タイムアウトテスト用)。"""

    def __init__(self, delay_sec: float = 5.0, **kwargs):
        super().__init__(**kwargs)
        self._delay_sec = delay_sec

    async def call(self, model: str, messages: list[dict], **kwargs) -> dict:
        self.call_log.append({"model": model, "messages": messages, "kwargs": kwargs})
        await asyncio.sleep(self._delay_sec)
        if self.responses:
            return self.responses.pop(0)
        return self.default_response.copy()


class SequenceMockAPIClient(MockAPIClient):
    """呼び出し回数に応じて異なる動作をするモック。"""

    def __init__(self, sequence: list[dict | Exception]):
        """
        Args:
            sequence: 各呼び出しで返す値 or 発生させる例外のリスト。
        """
        super().__init__()
        self._sequence = sequence

    async def call(self, model: str, messages: list[dict], **kwargs) -> dict:
        self.call_log.append({"model": model, "messages": messages, "kwargs": kwargs})
        if not self._sequence:
            return self.default_response.copy()
        item = self._sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
```

---

## 5. 共通 Fixture

### 5.1 tests/conftest.py

```python
"""全テスト共通の fixture。"""

import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir() -> Path:
    """テスト用 fixtures ディレクトリ。"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_output(tmp_path) -> Path:
    """テスト用一時出力ディレクトリ。"""
    output = tmp_path / "output"
    output.mkdir()
    return output
```

### 5.2 tests/unit/conftest.py

```python
"""ユニットテスト共通の fixture。"""

import pytest
from pathlib import Path
from tests.mocks.mock_api import MockAPIClient


@pytest.fixture
def mock_api() -> MockAPIClient:
    """基本的なモック API クライアント。"""
    return MockAPIClient()


@pytest.fixture
def mock_api_with_responses() -> callable:
    """レスポンス付きモック API ファクトリ。"""
    def _factory(responses: list[dict]) -> MockAPIClient:
        return MockAPIClient(responses=responses)
    return _factory


@pytest.fixture
def mock_settings(fixtures_dir) -> "Settings":
    """テスト用設定。"""
    from core.config_loader import Settings
    return Settings.load(fixtures_dir)


@pytest.fixture
def mock_role_manager(fixtures_dir) -> "RoleManager":
    """テスト用ロールマネージャー。"""
    from core.role_manager import RoleManager
    return RoleManager(fixtures_dir / "roles")


@pytest.fixture
def sample_utterance() -> "Utterance":
    """サンプル発言。"""
    from core.agent import Utterance
    return Utterance(
        role_id="theorist",
        role_name="理論屋",
        emoji="🧮",
        content="計算量の観点から見ると O(n log n) が最適です",
        round_num=1,
        tokens=150,
        duration_sec=3.2,
    )


@pytest.fixture
def sample_round_config() -> "RoundConfig":
    """サンプルラウンド設定。"""
    from core.orchestrator import RoundConfig
    return RoundConfig(
        number=1,
        phase="diverge",
        pattern="one_shot",
        speakers=["theorist", "experimentalist", "implementer"],
        leader="theorist",
        topic="LLMの推論効率改善アプローチの列挙",
        estimated_sec=60.0,
        level="standard",
    )


@pytest.fixture
def sample_plan(sample_round_config) -> "OrchestraPlan":
    """サンプル議論計画。"""
    from core.orchestrator import OrchestraPlan, ODSC, DiscussionPlan, AgentConfig
    return OrchestraPlan(
        theme="LLMの推論効率を改善する手法",
        odsc=ODSC(
            objective="LLM推論の効率化手法を多角的に検討する",
            deliverables="具体的手法リスト + 実験計画",
            scope="Transformer系モデルの推論時最適化",
            criteria="3つ以上の具体手法が提案され、実験計画がある",
        ),
        agents=["theorist", "experimentalist", "implementer"],
        agent_configs={
            "theorist": AgentConfig(role_id="theorist", model="gpt-4.1"),
            "experimentalist": AgentConfig(role_id="experimentalist", model="gpt-4.1"),
            "implementer": AgentConfig(role_id="implementer", model="gpt-4.1"),
        },
        discussion_plan=DiscussionPlan(
            rounds=[sample_round_config],
            estimated_total_sec=180.0,
            estimated_requests=15,
        ),
    )
```

---

## 6. テストパターン

### 6.1 基本パターン: Arrange / Act / Assert

```python
@pytest.mark.asyncio
async def test_speak_returns_valid_utterance(mock_api):
    """speak() は有効な Utterance を返す。"""
    # Arrange
    mock_api.responses = [{"content": "計算量的に O(n²) が支配的です"}]
    agent = _create_agent(mock_api, role_id="theorist")
    context = {"round_num": 1, "phase": "diverge", "topic": "計算量"}

    # Act
    result = await agent.speak(round_context=context)

    # Assert
    assert isinstance(result, Utterance)
    assert result.role_id == "theorist"
    assert result.content == "計算量的に O(n²) が支配的です"
    assert result.round_num == 1
    assert result.tokens == 0  # モックでは未設定
    mock_api.assert_call_count(1)
    mock_api.assert_called_with_model("gpt-4.1")
```

### 6.2 エラーケースパターン

```python
@pytest.mark.asyncio
async def test_speak_raises_on_rate_limit():
    """speak() はレートリミット時に例外を投げる。"""
    # Arrange
    from core.exceptions import RateLimitExhaustedError
    from tests.mocks.mock_api import ErrorMockAPIClient

    mock_api = ErrorMockAPIClient(
        error=RateLimitExhaustedError("Rate limit exceeded"),
        fail_count=999,
    )
    agent = _create_agent(mock_api, role_id="theorist")

    # Act & Assert
    with pytest.raises(RateLimitExhaustedError):
        await agent.speak(round_context={"round_num": 1, "phase": "diverge"})
```

### 6.3 境界値パターン

```python
class TestTimeKeeper:
    """TimeKeeper のテスト群。"""

    def test_remaining_returns_zero_when_exhausted(self):
        """残り時間0秒の場合 remaining は 0.0 を返す。"""
        # Arrange
        keeper = TimeKeeper(time_limit_sec=0.0)

        # Act & Assert
        assert keeper.remaining == 0.0

    def test_pressure_is_critical_when_almost_no_time(self):
        """残り5%以下の場合 CRITICAL になる。"""
        # Arrange
        keeper = TimeKeeper(time_limit_sec=100.0)
        # 内部的に経過時間を操作 (テスト用)
        keeper._start_time -= 95.0  # 95秒経過

        # Act
        result = keeper.pressure

        # Assert
        assert result == TimePressure.CRITICAL

    def test_can_start_next_round_false_when_insufficient(self):
        """残り時間不足の場合 False を返す。"""
        # Arrange
        keeper = TimeKeeper(time_limit_sec=10.0)
        keeper._start_time -= 9.0  # 残り1秒

        # Act
        result = keeper.can_start_next_round(estimated_round_sec=60.0)

        # Assert
        assert result is False
```

### 6.4 パラメータ化パターン

```python
import pytest


@pytest.mark.parametrize("model,expected_gpt5", [
    ("gpt-5.4", True),
    ("gpt-5.4-mini", True),
    ("o1-preview", True),
    ("o3-mini", True),
    ("o4-mini", True),
    ("gpt-4.1", False),
    ("gpt-4.1-mini", False),
    ("claude-sonnet-4-20250514", False),
])
def test_is_gpt5_series(model: str, expected_gpt5: bool):
    """GPT-5系の判定が正しい。"""
    client = ResilientAPIClient(...)
    assert client._is_gpt5_series(model) == expected_gpt5


@pytest.mark.parametrize("input_text,expected_error", [
    ("", InputTooShortError),
    ("abc", InputTooShortError),      # 4文字 < 5文字
    ("a" * 5001, InputTooLongError),  # 5001文字 > 5000文字
])
def test_validate_input_rejects_invalid(input_text: str, expected_error: type):
    """不正な入力は適切な例外を投げる。"""
    discussion = IdeaDiscussion(...)
    with pytest.raises(expected_error):
        discussion._validate_input(input_text)
```

### 6.5 非同期テストパターン

```python
import pytest
import asyncio


@pytest.mark.asyncio
async def test_concurrent_evaluations(mock_api):
    """複数エージェントの評価を並行実行できる。"""
    # Arrange
    mock_api.responses = [
        {"content": '{"scores": {"論理性": 4, "独自性": 3, "建設性": 4, "簡潔性": 5}}'},
        {"content": '{"scores": {"論理性": 3, "独自性": 4, "建設性": 5, "簡潔性": 4}}'},
        {"content": '{"scores": {"論理性": 5, "独自性": 5, "建設性": 3, "簡潔性": 3}}'},
    ]
    evaluator = Evaluator(api_client=mock_api, settings=mock_settings)
    agents = [agent_1, agent_2, agent_3]

    # Act
    results = await asyncio.gather(*[
        evaluator.request_self_evaluation(agent, discussion_log, plan)
        for agent in agents
    ])

    # Assert
    assert len(results) == 3
    assert mock_api.call_count == 3
```

### 6.6 ファイル出力テストパターン

```python
def test_generate_creates_all_files(tmp_output, sample_plan):
    """generate() は全必要ファイルを作成する。"""
    # Arrange
    generator = OutputGenerator(output_dir=tmp_output)
    synthesis = _create_mock_synthesis()

    # Act
    session_dir = generator.generate(
        session_type="idea",
        plan=sample_plan,
        discussion_log=mock_log,
        synthesis=synthesis,
        memory=mock_memory,
    )

    # Assert
    assert session_dir.exists()
    assert (session_dir / "session_meta.json").exists()
    assert (session_dir / "discussion.json").exists()
    assert (session_dir / "full_conversation.md").exists()
    assert (session_dir / "report.md").exists()
    assert (session_dir / "evaluation.md").exists()
    assert (session_dir / "summary.txt").exists()

    # メタデータの内容確認
    import json
    meta = json.loads((session_dir / "session_meta.json").read_text())
    assert meta["type"] == "idea"
    assert meta["theme"] == sample_plan.theme
```

---

## 7. モジュール別テスト方針

### 7.1 core/config_loader.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_load_from_yaml` | settings.yaml の正常読み込み |
| `test_env_overrides_yaml` | 環境変数による上書き |
| `test_dotenv_loading` | .env ファイルの読み込み |
| `test_missing_yaml_uses_defaults` | YAML なしでデフォルト値 |
| `test_get_timeout_known_model` | 既知モデルのタイムアウト取得 |
| `test_get_timeout_unknown_model` | 未知モデルはデフォルト値 |

### 7.2 core/api_client.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_call_standard_model` | gpt-4.1 で temperature/max_tokens が送られる |
| `test_call_gpt5_no_temperature` | gpt-5.4 で temperature が送られない |
| `test_call_gpt5_no_max_tokens` | gpt-5.4 で max_tokens が送られない |
| `test_call_claude_thinking` | claude に thinking パラメータが送られる |
| `test_retry_on_server_error` | ServerError で指定回数リトライ |
| `test_no_retry_on_auth_error` | AuthenticationError でリトライしない |
| `test_fallback_on_model_not_found` | ModelNotFound でフォールバック |
| `test_empty_response_retry` | 空レスポンスで再送 |
| `test_detect_mode_openai` | 通常URLでopenaiモード |
| `test_detect_mode_azure` | azure URLでazureモード |

### 7.3 core/time_keeper.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_initial_remaining` | 初期状態の残り時間 |
| `test_remaining_decreases` | 時間経過で残り時間減少 |
| `test_pressure_levels` | 各逼迫度レベルの閾値 |
| `test_can_start_next_round_true` | 十分な残り時間 |
| `test_can_start_next_round_false` | 不十分な残り時間 |
| `test_moving_average` | 直近ラウンドの平均計算 |
| `test_moving_average_empty` | ラウンド未完了時のデフォルト |

### 7.4 core/agent.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_speak_returns_utterance` | 正常な発言返却 |
| `test_speak_builds_correct_system_prompt` | system prompt にロール情報含む |
| `test_speak_includes_private_instruction` | 個別指示が反映される |
| `test_speak_includes_feedback_context` | フィードバックが反映される |
| `test_speak_too_long_triggers_shorter` | 長すぎる発言は短縮再要求 |
| `test_speak_gpt5_params` | GPT-5系で正しいパラメータ |
| `test_evaluate_returns_dict` | 評価結果が辞書で返る |

### 7.5 core/orchestrator.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_plan_returns_orchestra_plan` | 正常な計画生成 |
| `test_plan_validates_time_budget` | 時間超過時にラウンド削減 |
| `test_plan_respects_max_agents` | 最大エージェント数の制約 |
| `test_plan_includes_odsc` | ODSC が含まれる |
| `test_plan_with_follow_up` | フォローアップ時の計画 |
| `test_plan_with_scenario` | シナリオ適用時の計画 |

### 7.6 core/conductor.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_run_discussion_completes_all_rounds` | 全ラウンド実行 |
| `test_run_discussion_stops_on_time_limit` | 時間切れで停止 |
| `test_one_shot_pattern` | one_shot パターンの動作 |
| `test_ping_pong_pattern` | ping_pong パターンの動作 |
| `test_free_talk_pattern` | free_talk パターンの動作 |
| `test_convergence_detection` | 収束検知の動作 |
| `test_stagnation_detection` | 停滞検知→方向転換 |
| `test_round_conclusion_by_leader` | リーダーが結論を出す |

### 7.7 core/feedback.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_generate_feedback_context_empty` | 履歴なしで空文字列 |
| `test_generate_feedback_context_with_history` | 履歴ありでコンテキスト生成 |
| `test_update_role_feedback` | フィードバック追加 |
| `test_update_role_feedback_max_history` | 上限超過で古いものを圧縮 |
| `test_should_reinforce_rules_declining` | 下降傾向で True |
| `test_should_reinforce_rules_stable` | 安定で False |
| `test_calculate_trend` | トレンド計算 |

### 7.8 core/follow_up.py

| テストケース | 検証内容 |
|-------------|---------|
| `test_load_previous_session` | セッション読み込み |
| `test_load_nonexistent_session_raises` | 存在しないセッション |
| `test_hypothesis_transitions` | 仮説状態遷移の妥当性 |
| `test_attachment_processing` | ファイル添付処理 |
| `test_attachment_size_limit` | サイズ超過の切り詰め |
| `test_chain_depth_limit` | チェーン深度上限 |

---

## 8. カバレッジ目標

| モジュール | 目標 | 理由 |
|-----------|------|------|
| `core/exceptions.py` | 0% | 定義のみ、テスト不要 |
| `core/config_loader.py` | 80% | I/O依存部分は除外 |
| `core/api_client.py` | 85% | リトライ/フォールバック重要 |
| `core/rate_tracker.py` | 90% | ロジックシンプル |
| `core/time_keeper.py` | 95% | 純粋ロジック |
| `core/turn_calculator.py` | 90% | 計算ロジック |
| `core/role_manager.py` | 90% | ファイル読み込み |
| `core/memory.py` | 80% | 要約はAPI依存 |
| `core/agent.py` | 85% | API呼び出し部分はモック |
| `core/orchestrator.py` | 80% | プロンプト生成は文字列テスト |
| `core/conductor.py` | 75% | 複雑な分岐が多い |
| `core/evaluator.py` | 80% | JSONパース重要 |
| `core/synthesizer.py` | 70% | 多くのAPI呼び出し |
| `core/feedback.py` | 90% | ロジック中心 |
| `core/follow_up.py` | 80% | ファイル操作 |
| `core/output_generator.py` | 85% | ファイル出力 |
| `display/*.py` | 0% | 表示のみ、テスト不要 |
| **全体目標** | **80%** | |

---

## 9. テスト命名規則

```
test_{メソッド名}_{条件}_{期待結果}

# 正常系
test_speak_with_valid_context_returns_utterance
test_load_role_existing_returns_dict
test_remaining_initially_equals_budget

# エラー系
test_speak_when_api_timeout_raises_error
test_load_role_missing_raises_not_found
test_validate_input_too_short_raises

# 境界値
test_can_proceed_at_exact_limit_returns_true
test_utterance_at_max_chars_not_truncated
test_utterance_over_max_chars_triggers_shorter

# 状態変化
test_increment_increases_count
test_record_round_updates_moving_average
test_update_feedback_appends_entry
```

---

## 10. テスト実行時の注意事項

### 10.1 非同期テスト

```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"  # @pytest.mark.asyncio を省略可能にする

# または各テストに明示
@pytest.mark.asyncio
async def test_async_function():
    ...
```

### 10.2 ファイルシステムテスト

```python
# tmp_path fixture を使う（テスト後に自動削除）
def test_output(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    # ... テスト ...
    # tmp_path はテスト終了後に自動削除される
```

### 10.3 環境変数テスト

```python
# monkeypatch を使う
def test_env_loading(monkeypatch):
    monkeypatch.setenv("KOTOBUDDY_API_KEY", "test-key")
    monkeypatch.setenv("KOTOBUDDY_ENDPOINT", "https://test.example.com")

    settings = Settings.load()
    assert settings.api.key == "test-key"
```

### 10.4 時間依存テスト

```python
# time.monotonic をモック化するか、内部状態を直接操作
def test_time_pressure(monkeypatch):
    import time
    start = time.monotonic()

    keeper = TimeKeeper(time_limit_sec=100.0)
    # 直接内部状態を操作してテスト
    keeper._start_time = start - 95.0  # 95秒経過を模擬

    assert keeper.pressure == TimePressure.CRITICAL
```

---

## 11. CI/CD パイプライン想定

```yaml
# .github/workflows/test.yml (参考)
name: Test
on: [push, pull_request]
jobs:
  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/unit/ -v --cov=core --cov-report=xml
      - uses: codecov/codecov-action@v4

  integration-test:
    runs-on: ubuntu-latest
    needs: unit-test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/integration/ -v
```

---

## 12. requirements-dev.txt

```
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
pytest-mock>=3.10
pytest-timeout>=2.1
