"""``core.api_client`` モジュールのユニットテスト。

mock API クライアントを差し込み、パラメータ構築・リトライ・フォールバック・
空応答リカバリ・例外分類の各観点を検証する。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from core.api_client import (
    CLAUDE_THINKING_BUDGET,
    FALLBACK_CHAIN,
    EmptyResponseHandler,
    FallbackManager,
    ResilientAPIClient,
    RetryConfig,
    RetryHandler,
    detect_mode,
)
from core.exceptions import (
    AuthenticationError,
    EmptyResponseError,
    MaxRetriesExceededError,
    ModelNotFoundError,
    OrchestraAPIError,
    RateLimitExhaustedError,
    ServerError,
    TimeoutError as OrchestraTimeoutError,
)
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker(tmp_path: Path) -> RateLimitTracker:
    """テスト用の隔離された RateLimitTracker。"""
    return RateLimitTracker(persistence_path=tmp_path / "rate.json")


@pytest.fixture
def fast_retry_config() -> RetryConfig:
    """テストを高速化するための短い待機時間のリトライ設定。"""
    return RetryConfig(
        max_retries=3,
        base_delay_sec=0.001,
        max_delay_sec=0.005,
        backoff_factor=2.0,
    )


def _make_client(
    base: MockAPIClient,
    tracker: RateLimitTracker,
    mode: str = "openai",
    retry_config: RetryConfig | None = None,
) -> ResilientAPIClient:
    return ResilientAPIClient(
        base_client=base,
        rate_tracker=tracker,
        retry_config=retry_config or RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode=mode,
    )


# ---------------------------------------------------------------------------
# detect_mode
# ---------------------------------------------------------------------------


class TestDetectMode:
    """``detect_mode`` の判定ロジック。"""

    def test_explicit_mode_takes_priority(self) -> None:
        """明示モードが指定されれば URL は無視される。"""
        assert detect_mode("https://anything", explicit_mode="azure") == "azure"
        assert detect_mode("https://azure-api.net/openai/direct", explicit_mode="openai") == "openai"

    def test_openai_mode_for_default_kotobuddy_endpoint(self) -> None:
        """KotoBuddy 標準エンドポイントは openai モード。"""
        assert detect_mode("https://api.rdbuddy.rdinx.rd.omron.com/v1") == "openai"

    def test_azure_mode_for_azure_api_net(self) -> None:
        """azure-api.net を含む URL は azure モード。"""
        assert detect_mode("https://api-buddypjjidai.azure-api.net/openai/direct") == "azure"

    def test_azure_mode_for_openai_direct_path(self) -> None:
        """``/openai/direct`` を含む URL は azure モード。"""
        assert detect_mode("https://example.com/openai/direct") == "azure"

    def test_empty_endpoint_defaults_to_openai(self) -> None:
        """空文字 / None はデフォルトで openai。"""
        assert detect_mode("") == "openai"


# ---------------------------------------------------------------------------
# _build_params
# ---------------------------------------------------------------------------


class TestBuildParamsGPT5:
    """GPT-5 系のパラメータ構築の不変条件。"""

    def test_gpt5_strips_temperature_and_max_tokens(self, tracker: RateLimitTracker) -> None:
        """GPT-5 系には temperature/max_tokens を絶対に含めない。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "gpt-5.4",
            [{"role": "user", "content": "hi"}],
            level="high",
            temperature=0.7,
            max_tokens=500,
        )

        assert "temperature" not in params
        assert "max_tokens" not in params

    def test_gpt5_openai_mode_includes_extra_body(self, tracker: RateLimitTracker) -> None:
        """openai モードでは extra_body.allowed_openai_params を付ける。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "gpt-5.4",
            [{"role": "user", "content": "hi"}],
            level="high",
        )

        assert params["reasoning_effort"] == "high"
        assert params["extra_body"] == {"allowed_openai_params": ["reasoning_effort"]}

    def test_gpt5_azure_mode_does_not_include_extra_body(
        self, tracker: RateLimitTracker
    ) -> None:
        """azure モードでは extra_body を付与しない (400 エラー回避)。"""
        client = _make_client(MockAPIClient(), tracker, mode="azure")

        params = client._build_params(
            "gpt-5",
            [{"role": "user", "content": "hi"}],
            level="medium",
        )

        assert params["reasoning_effort"] == "medium"
        assert "extra_body" not in params

    def test_gpt5_with_level_none_skips_reasoning_effort(
        self, tracker: RateLimitTracker
    ) -> None:
        """level=none なら reasoning_effort も送らない。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "gpt-5-mini",
            [{"role": "user", "content": "hi"}],
            level="none",
        )

        assert "reasoning_effort" not in params
        assert "extra_body" not in params

    def test_gpt5_verbosity_is_included_when_specified(self, tracker: RateLimitTracker) -> None:
        """verbosity が指定されたら付与する。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "gpt-5.4",
            [{"role": "user", "content": "hi"}],
            level="medium",
            verbosity="low",
        )

        assert params["verbosity"] == "low"

    @pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini", "gpt-5.1", "gpt-5.2", "gpt-5.4"])
    def test_is_gpt5_series_matches_all_documented_variants(
        self, tracker: RateLimitTracker, model: str
    ) -> None:
        """設計書の全 GPT-5 系モデル名が GPT-5 系と判定される。"""
        assert ResilientAPIClient._is_gpt5_series(model) is True

    @pytest.mark.parametrize("model", ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "claude-sonnet-4-5"])
    def test_is_gpt5_series_rejects_non_gpt5(self, model: str) -> None:
        """GPT-5 以外は False。"""
        assert ResilientAPIClient._is_gpt5_series(model) is False


class TestBuildParamsClaudeThinking:
    """Claude 拡張思考のパラメータ構築。"""

    @pytest.mark.parametrize(
        ("level", "expected_budget"),
        [("low", 4000), ("medium", 8000), ("high", 16000)],
    )
    def test_claude_thinking_sets_budget_tokens(
        self, tracker: RateLimitTracker, level: str, expected_budget: int
    ) -> None:
        """level に応じた budget_tokens を thinking に設定する。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "hi"}],
            level=level,
        )

        assert params["extra_body"] == {
            "thinking": {"type": "enabled", "budget_tokens": expected_budget}
        }
        assert CLAUDE_THINKING_BUDGET[level] == expected_budget

    def test_claude_thinking_with_unsupported_level_skips_thinking(
        self, tracker: RateLimitTracker
    ) -> None:
        """``minimal`` / ``none`` では thinking を付けない。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "claude-sonnet-4-5",
            [{"role": "user", "content": "hi"}],
            level="minimal",
        )

        assert "extra_body" not in params


class TestBuildParamsStandard:
    """標準モデル (gpt-4.1, claude-opus-4-1) のパラメータ構築。"""

    def test_gpt41_accepts_temperature_and_max_tokens(
        self, tracker: RateLimitTracker
    ) -> None:
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params(
            "gpt-4.1",
            [{"role": "user", "content": "hi"}],
            temperature=0.3,
            max_tokens=200,
        )

        assert params["temperature"] == 0.3
        assert params["max_tokens"] == 200
        assert "extra_body" not in params
        assert "reasoning_effort" not in params

    def test_standard_omits_unset_params(self, tracker: RateLimitTracker) -> None:
        """未指定のパラメータは含めない。"""
        client = _make_client(MockAPIClient(), tracker, mode="openai")

        params = client._build_params("gpt-4.1", [{"role": "user", "content": "hi"}])

        assert params.keys() == {"model", "messages"}


# ---------------------------------------------------------------------------
# call / call_raw 経由でのレート追跡 + mock 統合
# ---------------------------------------------------------------------------


class TestCallRaw:
    """``call_raw`` の基本動作。"""

    @pytest.mark.asyncio
    async def test_call_raw_invokes_base_client_with_built_params(
        self, tracker: RateLimitTracker
    ) -> None:
        """build_params 後のパラメータが mock に渡る。"""
        mock = MockAPIClient(responses=[{"content": "ok"}])
        client = _make_client(mock, tracker, mode="openai")

        response = await client.call_raw(
            "gpt-5.4",
            [{"role": "user", "content": "hi"}],
            level="medium",
        )

        assert response == {"content": "ok"}
        mock.assert_call_count(1)
        recorded = mock.call_log[0]
        assert recorded["model"] == "gpt-5.4"
        assert recorded["reasoning_effort"] == "medium"
        assert recorded["extra_body"] == {"allowed_openai_params": ["reasoning_effort"]}
        # GPT-5 系には temperature/max_tokens を渡してはならない
        mock.assert_no_temperature()
        mock.assert_no_max_tokens()

    @pytest.mark.asyncio
    async def test_call_raw_increments_rate_tracker(
        self, tracker: RateLimitTracker
    ) -> None:
        """成功時に rate tracker が +1 される。"""
        mock = MockAPIClient(responses=[{"content": "ok"}])
        client = _make_client(mock, tracker, mode="openai")

        await client.call_raw("gpt-4.1", [{"role": "user", "content": "hi"}])

        assert tracker.request_count == 1


# ---------------------------------------------------------------------------
# RetryHandler
# ---------------------------------------------------------------------------


class TestRetryHandler:
    """``RetryHandler.execute_with_retry`` の挙動。"""

    @pytest.mark.asyncio
    async def test_retries_on_retryable_server_error_then_succeeds(
        self, fast_retry_config: RetryConfig
    ) -> None:
        """retryable=True の ServerError は最大回数までリトライする。"""
        handler = RetryHandler(fast_retry_config)
        calls = {"n": 0}

        async def flaky() -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] < 3:
                raise ServerError(status_code=502, retryable=True)
            return {"content": "ok"}

        result = await handler.execute_with_retry(flaky)

        assert result == {"content": "ok"}
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_when_server_error_is_not_retryable(
        self, fast_retry_config: RetryConfig
    ) -> None:
        """retryable=False の ServerError は即座に raise する。"""
        handler = RetryHandler(fast_retry_config)
        calls = {"n": 0}

        async def fail() -> dict[str, Any]:
            calls["n"] += 1
            raise ServerError(status_code=400, retryable=False)

        with pytest.raises(ServerError):
            await handler.execute_with_retry(fail)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_authentication_error_is_never_retried(
        self, fast_retry_config: RetryConfig
    ) -> None:
        """AuthenticationError は最初の失敗で即停止。"""
        handler = RetryHandler(fast_retry_config)
        calls = {"n": 0}

        async def fail() -> dict[str, Any]:
            calls["n"] += 1
            raise AuthenticationError(is_rate_limit=True)

        with pytest.raises(AuthenticationError):
            await handler.execute_with_retry(fail)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self, fast_retry_config: RetryConfig) -> None:
        """全試行失敗で MaxRetriesExceededError。"""
        handler = RetryHandler(fast_retry_config)

        async def always_timeout() -> dict[str, Any]:
            raise OrchestraTimeoutError("always")

        with pytest.raises(MaxRetriesExceededError):
            await handler.execute_with_retry(always_timeout)

    def test_calculate_delay_grows_exponentially(self, fast_retry_config: RetryConfig) -> None:
        """``_calculate_delay`` は指数的に増えるが ``max_delay_sec`` で頭打ち。"""
        handler = RetryHandler(fast_retry_config)

        d0 = handler._calculate_delay(0)
        d1 = handler._calculate_delay(1)
        d_big = handler._calculate_delay(50)

        assert 0 < d0 <= fast_retry_config.max_delay_sec
        assert d0 <= d1 + 1e-9  # jitter 込みでもおおむね単調
        assert d_big == pytest.approx(fast_retry_config.max_delay_sec, rel=0.2)


# ---------------------------------------------------------------------------
# FallbackManager
# ---------------------------------------------------------------------------


class _CallRawSpy:
    """ModelNotFoundError を制御しつつ call_raw を模倣するスパイ。"""

    def __init__(self, failing_models: set[str]) -> None:
        self.failing_models = failing_models
        self.calls: list[str] = []

    async def call_raw(self, model: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(model)
        if model in self.failing_models:
            raise ModelNotFoundError(model=model, message="not found")
        return {"content": f"ok from {model}", "model": model}


class TestFallbackManager:
    """``FallbackManager.call_with_fallback`` の挙動。"""

    def test_fallback_chain_matches_specification(self) -> None:
        """設計書 §15.3.1 のチェーンが定義されている。"""
        assert FALLBACK_CHAIN["claude-3-haiku"] == "gpt-4.1-mini"
        assert FALLBACK_CHAIN["claude-3-5-sonnet"] == "claude-sonnet-4"
        assert FALLBACK_CHAIN["claude-opus-4"] == "claude-opus-4-1"
        assert FALLBACK_CHAIN["gpt-4o"] == "gpt-4.1"

    def test_get_fallback_returns_none_for_unknown_model(self) -> None:
        """未定義モデルは None を返す。"""
        manager = FallbackManager()
        assert manager.get_fallback("gpt-4.1") is None

    @pytest.mark.asyncio
    async def test_call_with_fallback_succeeds_with_primary(self) -> None:
        """プライマリで成功すればフォールバックは使わない。"""
        spy = _CallRawSpy(failing_models=set())
        manager = FallbackManager()

        result = await manager.call_with_fallback(spy, "gpt-4.1", messages=[])

        assert result["content"] == "ok from gpt-4.1"
        assert spy.calls == ["gpt-4.1"]
        assert manager.fallback_used == {}

    @pytest.mark.asyncio
    async def test_call_with_fallback_uses_successor_on_404(self) -> None:
        """ModelNotFoundError なら後継モデルに切り替える。"""
        spy = _CallRawSpy(failing_models={"claude-opus-4"})
        manager = FallbackManager()

        result = await manager.call_with_fallback(spy, "claude-opus-4", messages=[])

        assert result["model"] == "claude-opus-4-1"
        assert spy.calls == ["claude-opus-4", "claude-opus-4-1"]
        assert manager.fallback_used == {"claude-opus-4": "claude-opus-4-1"}

    @pytest.mark.asyncio
    async def test_call_with_fallback_raises_when_both_fail(self) -> None:
        """両方失敗したら OrchestraAPIError。"""
        spy = _CallRawSpy(failing_models={"claude-opus-4", "claude-opus-4-1"})
        manager = FallbackManager()

        with pytest.raises(OrchestraAPIError):
            await manager.call_with_fallback(spy, "claude-opus-4", messages=[])


# ---------------------------------------------------------------------------
# EmptyResponseHandler
# ---------------------------------------------------------------------------


class _LevelTrackingClient:
    """空応答ハンドラから渡された level を記録するクライアント。"""

    def __init__(self, empty_until: str) -> None:
        """``empty_until`` 以下まで level を下げたら non-empty を返す。

        ``LEVEL_DOWNGRADE_ORDER`` 上の位置で比較する。
        """
        self.calls: list[str] = []
        self.empty_until = empty_until
        self._order = ["high", "medium", "low", "minimal"]

    async def call_raw(self, **params: Any) -> dict[str, Any]:
        level = params.get("level", "medium")
        self.calls.append(level)
        if self._order.index(level) <= self._order.index(self.empty_until):
            return {"content": None}
        return {"content": f"got it at {level}"}


class TestEmptyResponseHandler:
    """空応答時の level 引き下げリトライ。"""

    @pytest.mark.asyncio
    async def test_downgrades_until_non_empty(self) -> None:
        """high → medium で空、low で返ってきたら成功。"""
        spy = _LevelTrackingClient(empty_until="medium")
        handler = EmptyResponseHandler()

        result = await handler.handle_empty_response(
            {"model": "gpt-5.4", "messages": [], "level": "high"},
            spy,
        )

        assert result["content"] == "got it at low"
        # 元の level (high) はハンドラ呼び出し前の試行なのでハンドラ内では呼ばない
        assert spy.calls == ["medium", "low"]

    @pytest.mark.asyncio
    async def test_raises_when_all_levels_empty(self) -> None:
        """全 level で空なら EmptyResponseError。"""
        spy = _LevelTrackingClient(empty_until="minimal")
        handler = EmptyResponseHandler()

        with pytest.raises(EmptyResponseError):
            await handler.handle_empty_response(
                {"model": "gpt-5.4", "messages": [], "level": "high"},
                spy,
            )


# ---------------------------------------------------------------------------
# call (フォールバック + 空応答リカバリの統合)
# ---------------------------------------------------------------------------


class TestResilientCall:
    """``ResilientAPIClient.call`` のエンドツーエンド統合動作。"""

    @pytest.mark.asyncio
    async def test_call_returns_first_response_when_non_empty(
        self, tracker: RateLimitTracker
    ) -> None:
        """初回で content があればそのまま返す。"""
        mock = MockAPIClient(responses=[{"content": "first"}])
        client = _make_client(mock, tracker)

        result = await client.call("gpt-4.1", [{"role": "user", "content": "hi"}])

        assert result == {"content": "first"}
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_call_invokes_empty_recovery_for_gpt5_on_empty(
        self, tracker: RateLimitTracker
    ) -> None:
        """GPT-5 系で空が返ったら EmptyResponseHandler が動く。"""
        mock = MockAPIClient(
            responses=[
                {"content": None},        # 初回: level=high で空
                {"content": "recovered"},  # ハンドラからの level=medium で成功
            ]
        )
        client = _make_client(mock, tracker, mode="openai")

        result = await client.call(
            "gpt-5.4",
            [{"role": "user", "content": "hi"}],
            level="high",
        )

        assert result == {"content": "recovered"}
        assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_call_does_not_run_empty_recovery_for_non_gpt5(
        self, tracker: RateLimitTracker
    ) -> None:
        """GPT-5 以外の空応答ではリカバリを走らせない (そのまま返す)。"""
        mock = MockAPIClient(responses=[{"content": None}])
        client = _make_client(mock, tracker)

        result = await client.call("gpt-4.1", [{"role": "user", "content": "hi"}])

        assert result == {"content": None}
        mock.assert_call_count(1)


# ---------------------------------------------------------------------------
# _classify_error
# ---------------------------------------------------------------------------


class _StatusError(Exception):
    """``status_code`` 属性のみを持つテスト用例外。"""

    def __init__(self, status_code: int, msg: str = "fail") -> None:
        super().__init__(msg)
        self.status_code = status_code


class TestClassifyError:
    """``_classify_error`` の分類ロジック。"""

    @pytest.fixture
    def client(self, tracker: RateLimitTracker) -> ResilientAPIClient:
        return _make_client(MockAPIClient(), tracker)

    def test_orchestra_error_is_passed_through(self, client: ResilientAPIClient) -> None:
        """既に OrchestraAPIError なら二重ラップしない。"""
        original = ServerError(status_code=500)
        assert client._classify_error(original, "gpt-4.1") is original

    def test_401_with_rate_limit_message_marks_is_rate_limit(
        self, client: ResilientAPIClient
    ) -> None:
        """401 + 'rate limit' メッセージで is_rate_limit=True。"""
        exc = _StatusError(401, "rate limit exceeded")

        classified = client._classify_error(exc, "gpt-4.1")

        assert isinstance(classified, AuthenticationError)
        assert classified.is_rate_limit is True

    def test_401_without_rate_limit_message(self, client: ResilientAPIClient) -> None:
        """401 だが rate limit 系メッセージなしなら is_rate_limit=False。"""
        exc = _StatusError(401, "key expired")
        classified = client._classify_error(exc, "gpt-4.1")
        assert isinstance(classified, AuthenticationError)
        assert classified.is_rate_limit is False

    def test_404_becomes_model_not_found(self, client: ResilientAPIClient) -> None:
        exc = _StatusError(404, "deployment not found")
        classified = client._classify_error(exc, "claude-opus-4")
        assert isinstance(classified, ModelNotFoundError)
        assert classified.model == "claude-opus-4"

    def test_429_becomes_rate_limit_exhausted(self, client: ResilientAPIClient) -> None:
        exc = _StatusError(429, "throttled")
        classified = client._classify_error(exc, "gpt-4.1")
        assert isinstance(classified, RateLimitExhaustedError)

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_5xx_becomes_retryable_server_error(
        self, client: ResilientAPIClient, status: int
    ) -> None:
        exc = _StatusError(status)
        classified = client._classify_error(exc, "gpt-4.1")
        assert isinstance(classified, ServerError)
        assert classified.status_code == status
        assert classified.retryable is True

    def test_asyncio_timeout_becomes_orchestra_timeout(
        self, client: ResilientAPIClient
    ) -> None:
        classified = client._classify_error(asyncio.TimeoutError(), "gpt-4.1")
        assert isinstance(classified, OrchestraTimeoutError)

    def test_unknown_error_falls_back_to_generic_api_error(
        self, client: ResilientAPIClient
    ) -> None:
        classified = client._classify_error(RuntimeError("?"), "gpt-4.1")
        assert isinstance(classified, OrchestraAPIError)
        assert not isinstance(classified, ServerError)
