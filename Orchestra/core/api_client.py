"""KotoBuddy API 呼び出しの抽象化層。

責務:
    - モデル種別とモードに応じた API パラメータ構築
    - リトライ (exponential backoff + jitter)
    - EOL モデルの自動フォールバック
    - GPT-5 空応答時の reasoning_effort 引き下げリトライ
    - レート制限カウンタの更新
    - OpenAI SDK 例外の ``OrchestraAPIError`` への分類

設計書:
    - ``doc/02_api_specification.md``: モード、モデル別パラメータ、GPT-5 系の制約
    - ``doc/15_error_handling.md`` §15.1-15.3: エラー分類とリトライ・フォールバック
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .exceptions import (
    AuthenticationError,
    EmptyResponseError,
    MaxRetriesExceededError,
    ModelNotFoundError,
    OrchestraAPIError,
    RateLimitExhaustedError,
    ServerError,
    TimeoutError as OrchestraTimeoutError,
)
from .rate_tracker import RateLimitTracker

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

GPT5_MODEL_PREFIXES = ("gpt-5",)
CLAUDE_THINKING_MODELS = frozenset({
    "claude-sonnet-4",
    "claude-sonnet-4-5",
})

# level → Claude 拡張思考の budget_tokens
CLAUDE_THINKING_BUDGET = {
    "low": 4000,
    "medium": 8000,
    "high": 16000,
}

# GPT-5 空応答時に試す level 順
LEVEL_DOWNGRADE_ORDER = ["high", "medium", "low", "minimal"]

# EOL/廃止モデル → 後継モデル (doc §15.3.1)
FALLBACK_CHAIN: dict[str, str] = {
    "claude-3-haiku": "gpt-4.1-mini",
    "claude-3-5-sonnet": "claude-sonnet-4",
    "claude-3-7-sonnet": "claude-sonnet-4",
    "claude-opus-4": "claude-opus-4-1",
    "gpt-4o": "gpt-4.1",
    "gpt-4o-mini": "gpt-4.1-mini",
}

# レート追跡で「上限超え」と見なすキーワード (response の error.message を見るときに使う)
RATE_LIMIT_KEYWORDS = ("rate limit", "quota", "exceed")

# デフォルトのリトライ対象 HTTP ステータス
DEFAULT_RETRYABLE_STATUS = frozenset({429, 500, 502, 503})


# ----------------------------------------------------------------------
# モード判定
# ----------------------------------------------------------------------


def detect_mode(endpoint: str, explicit_mode: str | None = None) -> str:
    """エンドポイント URL から接続モードを推定する。

    Args:
        endpoint: KotoBuddy のエンドポイント URL。
        explicit_mode: 明示モード ("openai" または "azure")。指定された場合は
            URL を見ずにそのまま採用する。

    Returns:
        ``"openai"`` または ``"azure"``。
    """
    if explicit_mode:
        return explicit_mode
    if not endpoint:
        return "openai"
    if "/openai/direct" in endpoint or "azure-api.net" in endpoint:
        return "azure"
    return "openai"


# ----------------------------------------------------------------------
# RetryConfig / RetryHandler
# ----------------------------------------------------------------------


@dataclass
class RetryConfig:
    """リトライ動作を定義する。

    Attributes:
        max_retries: 最大リトライ回数 (初回試行は含めない)。
        base_delay_sec: 初回バックオフ秒数。
        max_delay_sec: バックオフの最大秒数 (キャップ)。
        backoff_factor: 指数バックオフの底。
        retryable_status_codes: リトライ対象 HTTP ステータスの集合。
    """

    max_retries: int = 3
    base_delay_sec: float = 2.0
    max_delay_sec: float = 30.0
    backoff_factor: float = 2.0
    retryable_status_codes: frozenset[int] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_STATUS
    )


class RetryHandler:
    """``RetryConfig`` に従って非同期関数をリトライ実行する。"""

    def __init__(self, config: RetryConfig) -> None:
        """Args: config: リトライ設定。"""
        self.config = config

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """``func`` をリトライ付きで呼び出す。

        リトライ対象は ``ServerError(retryable=True)`` と
        ``OrchestraTimeoutError``。``AuthenticationError`` や
        ``ModelNotFoundError`` などは即座に伝播する。

        Args:
            func: 呼び出すコルーチン関数。
            *args, **kwargs: ``func`` に渡す引数。

        Returns:
            ``func`` の戻り値。

        Raises:
            MaxRetriesExceededError: 最大リトライを超えても成功しなかった場合。
            OrchestraAPIError: リトライ対象外の API エラー。
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except ServerError as e:
                last_error = e
                if not e.retryable:
                    raise
                if attempt >= self.config.max_retries:
                    break
                delay = self._calculate_delay(attempt)
                logger.warning(
                    "ServerError (%s). Retrying in %.1fs (attempt %d/%d)",
                    e.status_code,
                    delay,
                    attempt + 1,
                    self.config.max_retries,
                )
                await asyncio.sleep(delay)
            except OrchestraTimeoutError as e:
                last_error = e
                if attempt >= self.config.max_retries:
                    break
                delay = self._calculate_delay(attempt)
                logger.warning(
                    "Timeout. Retrying in %.1fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    self.config.max_retries,
                )
                await asyncio.sleep(delay)
            except (AuthenticationError, ModelNotFoundError, RateLimitExhaustedError):
                raise

        raise MaxRetriesExceededError(
            f"Exceeded max_retries={self.config.max_retries}: {last_error}"
        )

    def _calculate_delay(self, attempt: int) -> float:
        """``attempt`` 回目 (0-indexed) のバックオフ秒数を計算する。

        指数バックオフ + 0〜10% のジッターを加算した上で ``max_delay_sec``
        にクリップする。
        """
        base = self.config.base_delay_sec * (self.config.backoff_factor ** attempt)
        jitter = random.uniform(0, base * 0.1)
        return min(base + jitter, self.config.max_delay_sec)


# ----------------------------------------------------------------------
# FallbackManager
# ----------------------------------------------------------------------


class _APIClientLike(Protocol):
    """``FallbackManager.call_with_fallback`` が要求する最低限のインターフェース。"""

    async def call_raw(self, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        ...


class FallbackManager:
    """EOL モデルから後継モデルへの自動切替を管理する。"""

    FALLBACK_CHAIN: dict[str, str] = FALLBACK_CHAIN

    def __init__(self) -> None:
        self.fallback_used: dict[str, str] = {}

    def get_fallback(self, model: str) -> str | None:
        """``model`` の後継モデル名を返す。定義がなければ ``None``。"""
        return self.FALLBACK_CHAIN.get(model)

    async def call_with_fallback(
        self,
        api_client: _APIClientLike,
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """フォールバック付きで ``api_client.call_raw`` を呼ぶ。

        ``ModelNotFoundError`` が発生した場合のみフォールバック先で再試行する。
        他のエラーはそのまま伝播する。

        Args:
            api_client: ``call_raw`` を持つ任意のクライアント。
            model: プライマリモデル名。
            **kwargs: ``call_raw`` に渡される追加引数。

        Returns:
            API レスポンス辞書。

        Raises:
            OrchestraAPIError: プライマリ + フォールバック両方が失敗した場合。
        """
        models_to_try: list[str] = [model]
        fallback = self.get_fallback(model)
        if fallback:
            models_to_try.append(fallback)

        last_error: Exception | None = None
        for current in models_to_try:
            try:
                response = await api_client.call_raw(model=current, **kwargs)
                if current != model:
                    self.fallback_used[model] = current
                    logger.warning("Model fallback used: %s -> %s", model, current)
                return response
            except ModelNotFoundError as e:
                last_error = e
                logger.warning("Model %s not available: %s", current, e)
                continue

        raise OrchestraAPIError(
            f"All fallback candidates failed for {model}: {last_error}"
        )


# ----------------------------------------------------------------------
# EmptyResponseHandler
# ----------------------------------------------------------------------


class EmptyResponseHandler:
    """GPT-5 系の空応答時に reasoning_effort を引き下げて再試行する。"""

    LEVEL_DOWNGRADE_ORDER: list[str] = LEVEL_DOWNGRADE_ORDER

    async def handle_empty_response(
        self,
        original_params: dict[str, Any],
        api_client: _APIClientLike,
    ) -> dict[str, Any]:
        """空応答を受けた呼び出しを level を下げてリトライする。

        Args:
            original_params: 元の呼び出しに使ったパラメータ
                (``model``, ``messages``, ``level`` を含む)。
            api_client: ``call_raw`` を持つクライアント。

        Returns:
            非空のレスポンス辞書。

        Raises:
            EmptyResponseError: ``minimal`` まで下げても空のままだった場合。
        """
        current_level = original_params.get("level", "medium")
        try:
            current_idx = self.LEVEL_DOWNGRADE_ORDER.index(current_level)
        except ValueError:
            current_idx = 0  # 不明な level は high 扱い

        for downgrade_idx in range(current_idx + 1, len(self.LEVEL_DOWNGRADE_ORDER)):
            new_level = self.LEVEL_DOWNGRADE_ORDER[downgrade_idx]
            params = {**original_params, "level": new_level}
            logger.warning(
                "Empty response. Downgrading level %s -> %s and retrying.",
                current_level,
                new_level,
            )
            response = await api_client.call_raw(**params)
            if response.get("content"):
                return response

        raise EmptyResponseError(
            f"Empty response on all levels for model {original_params.get('model')}"
        )


# ----------------------------------------------------------------------
# ResilientAPIClient
# ----------------------------------------------------------------------


class _BaseClientProtocol(Protocol):
    """``ResilientAPIClient`` が利用する base client の契約。

    ``MockAPIClient`` および将来の実 SDK ラッパーが満たすインターフェース。
    """

    async def call(self, **params: Any) -> dict[str, Any]:
        ...


class ResilientAPIClient:
    """耐障害性をもつ API クライアントのファサード。

    - パラメータ構築 (モデル/モード別)
    - レート追跡
    - 例外分類
    - リトライ (``RetryHandler``)
    - フォールバック (``FallbackManager``)
    - 空応答リカバリ (``EmptyResponseHandler``)
    """

    def __init__(
        self,
        base_client: _BaseClientProtocol,
        rate_tracker: RateLimitTracker,
        retry_config: RetryConfig | None = None,
        fallback_manager: FallbackManager | None = None,
        empty_response_handler: EmptyResponseHandler | None = None,
        mode: str | None = None,
        endpoint: str | None = None,
        settings: "Any | None" = None,
    ) -> None:
        """Args:
            base_client: 実際に API を叩く下位クライアント。``MockAPIClient``
                またはそれと同等の ``async call(**params)`` を提供するもの。
            rate_tracker: 日次リクエスト数の追跡。
            retry_config: リトライ設定。``None`` ならデフォルト ``RetryConfig``。
            fallback_manager: フォールバック管理。``None`` なら新規生成。
            empty_response_handler: 空応答ハンドラ。``None`` なら新規生成。
            mode: 接続モード ("openai" | "azure")。未指定なら ``endpoint`` または
                ``base_client.mode`` から自動判定。
            endpoint: ``mode`` の自動判定に使うエンドポイント URL。
            settings: ``Settings`` インスタンス。指定するとモデル別 timeout
                を ``get_timeout(model)`` で解決して per-request に注入する。
        """
        self.base_client = base_client
        self.rate_tracker = rate_tracker
        self.retry_handler = RetryHandler(retry_config or RetryConfig())
        self.fallback_manager = fallback_manager or FallbackManager()
        self.empty_response_handler = empty_response_handler or EmptyResponseHandler()
        self.mode = self._resolve_mode(mode, endpoint, base_client)
        self.settings = settings

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """フォールバック + リトライ + 空応答リカバリ込みで API を呼ぶ。

        Args:
            model: モデル名。
            messages: チャット履歴。
            **kwargs: ``level``, ``temperature``, ``max_tokens``,
                ``verbosity`` などモデル別パラメータ。

        Returns:
            API レスポンス辞書 (``content`` キーを含む)。
        """
        response = await self.fallback_manager.call_with_fallback(
            self, model, messages=messages, **kwargs
        )

        # 空応答の場合は GPT-5 系のみ level 引き下げで再試行
        if self._is_empty_content(response) and self._is_gpt5_series(model):
            response = await self.empty_response_handler.handle_empty_response(
                {"model": model, "messages": messages, **kwargs},
                self,
            )
        return response

    async def call_raw(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """フォールバックなしで単一モデルを叩く (リトライとレート追跡は行う)。"""

        async def _do_call() -> dict[str, Any]:
            params = self._build_params(model, messages, **kwargs)
            self.rate_tracker.increment(1)
            try:
                return await self.base_client.call(**params)
            except Exception as e:  # noqa: BLE001 - 分類して再 raise
                raise self._classify_error(e, model) from e

        return await self.retry_handler.execute_with_retry(_do_call)

    # ------------------------------------------------------------------
    # パラメータ構築
    # ------------------------------------------------------------------

    def _build_params(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """モデル種別 × モードに応じて API パラメータを組み立てる。

        重要な不変条件:
            - GPT-5 系には ``temperature`` / ``max_tokens`` を **絶対に渡さない**
            - ``reasoning_effort`` を付ける場合、``mode == "openai"`` のときのみ
              ``extra_body={"allowed_openai_params": ["reasoning_effort"]}`` を付与
            - ``mode == "azure"`` のときは ``extra_body`` を **付与しない** (400 になる)
            - Claude 拡張思考モデルは ``extra_body.thinking`` のみ付与

        Args:
            model: モデル名。
            messages: チャット履歴。
            **kwargs: ``level`` / ``temperature`` / ``max_tokens`` /
                ``verbosity`` など。

        Returns:
            base_client.call に渡せる辞書。
        """
        params: dict[str, Any] = {"model": model, "messages": messages}
        level = kwargs.get("level")
        verbosity = kwargs.get("verbosity")
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")

        # モデル別 timeout (settings があれば解決)
        request_timeout = self._resolve_request_timeout(model)
        if request_timeout is not None:
            params["timeout"] = request_timeout

        if self._is_gpt5_series(model):
            # GPT-5 系: temperature/max_tokens は絶対送らない
            if level is not None and level != "none":
                params["reasoning_effort"] = level
                if self.mode == "openai":
                    params["extra_body"] = {"allowed_openai_params": ["reasoning_effort"]}
                # azure モードでは extra_body を付けない (400 になる)
            if verbosity is not None:
                params["verbosity"] = verbosity
            return params

        if self._is_claude_thinking(model) and level in CLAUDE_THINKING_BUDGET:
            # Claude 拡張思考: thinking のみ。temperature/max_tokens も一応許容。
            params["extra_body"] = {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": CLAUDE_THINKING_BUDGET[level],
                }
            }
            if temperature is not None:
                params["temperature"] = temperature
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
            return params

        # 標準モデル (gpt-4.1, gpt-4.1-mini, claude-opus-4-1, など)
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        return params

    # ------------------------------------------------------------------
    # モデル判別
    # ------------------------------------------------------------------

    @staticmethod
    def _is_gpt5_series(model: str) -> bool:
        """``gpt-5`` / ``gpt-5-mini`` / ``gpt-5.1`` 等を判定する。

        ``gpt-5o`` のような GPT-4 系誤マッチを避けるため、``gpt-5`` 完全一致または
        ``gpt-5-`` / ``gpt-5.`` で始まるものを GPT-5 系とみなす。
        """
        return model == "gpt-5" or model.startswith("gpt-5-") or model.startswith("gpt-5.")

    def _resolve_request_timeout(self, model: str) -> float | None:
        """``settings`` があればモデル別タイムアウト秒数を返す。なければ ``None``。"""
        if self.settings is None:
            return None
        getter = getattr(self.settings, "get_timeout", None)
        if not callable(getter):
            return None
        try:
            return float(getter(model))
        except Exception:  # noqa: BLE001 - 取得失敗時は None
            return None

    @staticmethod
    def _is_claude_thinking(model: str) -> bool:
        """拡張思考に対応する Claude モデルかを判定する。"""
        return model in CLAUDE_THINKING_MODELS

    @staticmethod
    def _is_empty_content(response: dict[str, Any]) -> bool:
        """レスポンスが空応答かを判定する。"""
        content = response.get("content")
        return content is None or content == ""

    # ------------------------------------------------------------------
    # 例外分類
    # ------------------------------------------------------------------

    def _classify_error(self, exception: BaseException, model: str) -> OrchestraAPIError:
        """OpenAI SDK / 汎用例外を ``OrchestraAPIError`` サブクラスに変換する。

        既に ``OrchestraAPIError`` であればそのまま返す (二重ラップを避ける)。
        SDK 例外は ``status_code`` 属性または ``isinstance`` で分類する。
        """
        if isinstance(exception, OrchestraAPIError):
            return exception

        status = getattr(exception, "status_code", None)

        # SDK 例外型による分類 (import 失敗時は dummy クラスにフォールバック)
        sdk = _openai_exceptions()
        message = str(exception)

        if sdk.AuthenticationError is not None and isinstance(exception, sdk.AuthenticationError):
            is_rate = any(k in message.lower() for k in RATE_LIMIT_KEYWORDS)
            return AuthenticationError(message=message, is_rate_limit=is_rate)
        if sdk.NotFoundError is not None and isinstance(exception, sdk.NotFoundError):
            return ModelNotFoundError(model=model, message=message)
        if sdk.RateLimitError is not None and isinstance(exception, sdk.RateLimitError):
            return RateLimitExhaustedError(message)
        if sdk.APITimeoutError is not None and isinstance(exception, sdk.APITimeoutError):
            return OrchestraTimeoutError(message)
        if sdk.InternalServerError is not None and isinstance(exception, sdk.InternalServerError):
            return ServerError(status_code=status or 500, message=message, retryable=True)

        # HTTP ステータス由来 (汎用)
        if isinstance(status, int):
            if status == 401:
                is_rate = any(k in message.lower() for k in RATE_LIMIT_KEYWORDS)
                return AuthenticationError(message=message, is_rate_limit=is_rate)
            if status == 404:
                return ModelNotFoundError(model=model, message=message)
            if status == 429:
                return RateLimitExhaustedError(message)
            if status in (500, 502, 503):
                return ServerError(status_code=status, message=message, retryable=True)

        if isinstance(exception, asyncio.TimeoutError):
            return OrchestraTimeoutError(str(exception) or "API call timed out")

        return OrchestraAPIError(f"Unclassified API error: {exception!r}")

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_mode(
        mode: str | None,
        endpoint: str | None,
        base_client: Any,
    ) -> str:
        """``mode`` を解決する優先順位: 引数 > endpoint > base_client.mode > openai。"""
        if mode:
            return mode
        if endpoint:
            return detect_mode(endpoint)
        base_mode = getattr(base_client, "mode", None)
        if isinstance(base_mode, str) and base_mode:
            return base_mode
        return "openai"


# ----------------------------------------------------------------------
# OpenAI SDK 例外のレイジィロード
# ----------------------------------------------------------------------


@dataclass
class _SDKExceptionRefs:
    """OpenAI SDK 例外型への参照 (テスト時に差し替えやすくするための間接層)。"""

    AuthenticationError: type[BaseException] | None = None
    NotFoundError: type[BaseException] | None = None
    RateLimitError: type[BaseException] | None = None
    APITimeoutError: type[BaseException] | None = None
    InternalServerError: type[BaseException] | None = None


def _openai_exceptions() -> _SDKExceptionRefs:
    """OpenAI SDK 例外型をまとめて返す。SDK 未インストール時は ``None``。"""
    try:
        import openai as _openai
    except ImportError:
        return _SDKExceptionRefs()

    return _SDKExceptionRefs(
        AuthenticationError=getattr(_openai, "AuthenticationError", None),
        NotFoundError=getattr(_openai, "NotFoundError", None),
        RateLimitError=getattr(_openai, "RateLimitError", None),
        APITimeoutError=getattr(_openai, "APITimeoutError", None),
        InternalServerError=getattr(_openai, "InternalServerError", None),
    )


__all__ = [
    "detect_mode",
    "RetryConfig",
    "RetryHandler",
    "FallbackManager",
    "EmptyResponseHandler",
    "ResilientAPIClient",
    "FALLBACK_CHAIN",
    "LEVEL_DOWNGRADE_ORDER",
    "CLAUDE_THINKING_BUDGET",
]
