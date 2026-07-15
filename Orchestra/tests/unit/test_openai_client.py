"""``core.openai_client.AsyncOpenAIClient`` のスモークテスト。

LLM への実通信は行わず、初期化バリデーションと ``_parse_response`` の
構造を検証する。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.exceptions import AuthenticationError, ConfigLoadError
from core.openai_client import (
    DEFAULT_API_VERSION,
    DEFAULT_OPENAI_TIMEOUT_SEC,
    AsyncOpenAIClient,
)


class TestInit:
    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(AuthenticationError):
            AsyncOpenAIClient(api_key="")

    def test_azure_mode_requires_endpoint(self) -> None:
        with pytest.raises(ConfigLoadError):
            AsyncOpenAIClient(api_key="dummy", mode="azure", endpoint=None)

    def test_openai_mode_constructs(self) -> None:
        client = AsyncOpenAIClient(
            api_key="dummy",
            endpoint="https://api.example.com/v1",
            mode="openai",
        )
        assert client.mode == "openai"
        assert client.api_key == "dummy"
        assert client.endpoint == "https://api.example.com/v1"
        assert client.timeout_sec == DEFAULT_OPENAI_TIMEOUT_SEC

    def test_azure_mode_constructs_with_default_version(self) -> None:
        client = AsyncOpenAIClient(
            api_key="dummy",
            endpoint="https://my.openai.azure.com",
            mode="azure",
        )
        assert client.mode == "azure"
        assert client.api_version == DEFAULT_API_VERSION

    def test_custom_timeout_is_stored(self) -> None:
        client = AsyncOpenAIClient(
            api_key="dummy", endpoint="https://x", timeout_sec=15.0
        )
        assert client.timeout_sec == 15.0


class TestParseResponse:
    def test_extracts_content_and_usage(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hello world")
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            ),
        )
        parsed = AsyncOpenAIClient._parse_response(response)
        assert parsed["content"] == "hello world"
        assert parsed["usage"] == {"input": 10, "output": 20, "total": 30}
        assert parsed["raw"] is response

    def test_missing_choices_returns_empty_content(self) -> None:
        response = SimpleNamespace(choices=[], usage=None)
        parsed = AsyncOpenAIClient._parse_response(response)
        assert parsed["content"] == ""
        assert parsed["usage"] == {}

    def test_missing_message_returns_empty_content(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace()], usage=None)
        parsed = AsyncOpenAIClient._parse_response(response)
        assert parsed["content"] == ""

    def test_none_content_returns_empty_string(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None))
            ],
            usage=None,
        )
        parsed = AsyncOpenAIClient._parse_response(response)
        assert parsed["content"] == ""

    def test_partial_usage_fills_zero(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="x"))
            ],
            usage=SimpleNamespace(prompt_tokens=5),
        )
        parsed = AsyncOpenAIClient._parse_response(response)
        assert parsed["usage"] == {"input": 5, "output": 0, "total": 0}


class TestCall:
    @pytest.mark.asyncio
    async def test_call_strips_level_and_delegates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``call`` は ``level`` を除外して下位 ``create`` に渡す。"""
        captured: dict[str, object] = {}

        async def fake_create(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="ok"))
                ],
                usage=SimpleNamespace(
                    prompt_tokens=1, completion_tokens=2, total_tokens=3
                ),
            )

        client = AsyncOpenAIClient(
            api_key="dummy", endpoint="https://x", mode="openai"
        )
        # 内部クライアントを fake に差し替え
        client._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_create)
            )
        )

        result = await client.call(
            model="gpt-4.1",
            messages=[{"role": "user", "content": "hi"}],
            level="medium",  # 除外されるはず
            temperature=0.5,
        )

        assert result["content"] == "ok"
        assert "level" not in captured
        assert captured["model"] == "gpt-4.1"
        assert captured["temperature"] == 0.5
