"""OpenAI / Azure OpenAI の async クライアント薄いラッパー。

``ResilientAPIClient`` の ``base_client`` として渡せる
``async call(**params) -> dict[str, Any]`` インターフェースを提供する。

設計書: ``doc/02_api_specification.md``
"""

from __future__ import annotations

import logging
from typing import Any

from core.exceptions import AuthenticationError, ConfigLoadError

logger = logging.getLogger(__name__)


DEFAULT_OPENAI_TIMEOUT_SEC = 60.0
DEFAULT_API_VERSION = "2024-10-01-preview"
# openai SDK の内部リトライを無効化。リトライは ``ResilientAPIClient``
# 配下の ``RetryHandler`` が一元管理する (二重リトライによる遅延を防ぐ)。
SDK_MAX_RETRIES = 0


class AsyncOpenAIClient:
    """``openai.AsyncOpenAI`` / ``AsyncAzureOpenAI`` の薄いラッパー。

    ``mode == "azure"`` なら ``AsyncAzureOpenAI``、それ以外は ``AsyncOpenAI``。
    ``call(**params)`` は ``params`` をそのまま ``chat.completions.create`` に
    渡し、レスポンスを ``{"content", "usage", "raw"}`` 形式で返す。

    Attributes:
        mode: ``"openai"`` または ``"azure"``。
        api_key: API キー。
        endpoint: API エンドポイント。
        api_version: Azure モードの API バージョン。
        timeout_sec: 1 リクエストのタイムアウト。
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str | None = None,
        mode: str = "openai",
        api_version: str | None = None,
        timeout_sec: float = DEFAULT_OPENAI_TIMEOUT_SEC,
    ) -> None:
        if not api_key:
            raise AuthenticationError("API key is required")

        self.mode = mode
        self.api_key = api_key
        self.endpoint = endpoint
        self.api_version = api_version or DEFAULT_API_VERSION
        self.timeout_sec = float(timeout_sec)
        self._client = self._build_client()

    def _build_client(self) -> Any:
        try:
            from openai import AsyncAzureOpenAI, AsyncOpenAI  # type: ignore
        except ImportError as e:  # pragma: no cover - 環境依存
            raise ConfigLoadError(
                "openai SDK が見つかりません。`pip install openai` を実行してください"
            ) from e

        if self.mode == "azure":
            if not self.endpoint:
                raise ConfigLoadError(
                    "Azure モードでは endpoint が必須です"
                )
            return AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
                timeout=self.timeout_sec,
                max_retries=SDK_MAX_RETRIES,
            )
        # openai モード (KotoBuddy 互換)
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.timeout_sec,
            "max_retries": SDK_MAX_RETRIES,
        }
        if self.endpoint:
            kwargs["base_url"] = self.endpoint
        return AsyncOpenAI(**kwargs)

    # ------------------------------------------------------------------
    # public API (ResilientAPIClient 互換)
    # ------------------------------------------------------------------

    async def call(self, **params: Any) -> dict[str, Any]:
        """``chat.completions.create`` を呼び出して結果を辞書化する。"""
        # ResilientAPIClient が内部で使う管理用キーを除外
        params.pop("level", None)

        response = await self._client.chat.completions.create(**params)
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        try:
            choice = response.choices[0]
            content = choice.message.content or ""
        except (AttributeError, IndexError):
            content = ""

        usage_obj = getattr(response, "usage", None)
        usage: dict[str, int] = {}
        if usage_obj is not None:
            usage = {
                "input": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                "output": int(getattr(usage_obj, "completion_tokens", 0) or 0),
                "total": int(getattr(usage_obj, "total_tokens", 0) or 0),
            }
        return {"content": content, "usage": usage, "raw": response}


__all__ = ["AsyncOpenAIClient", "DEFAULT_OPENAI_TIMEOUT_SEC"]
