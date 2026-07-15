"""テスト用のモック API クライアント。

実 API を呼ばずに ``ResilientAPIClient`` 互換のインターフェースを提供する。
事前に用意したレスポンス列を順番に返し、呼び出し履歴を ``call_log`` に蓄積する。

参照: ``doc/18_roadmap.md`` §18.5.1, ``doc/02_api_specification.md`` §2.4
"""

from __future__ import annotations

from typing import Any


class MockAPIClient:
    """API をモックしてテスト用の固定レスポンスを返す。

    Attributes:
        responses: 事前に登録したレスポンス列。``call`` 呼び出しの度に順番に
            返却される。
        call_log: 呼び出し履歴。各エントリは ``model`` / ``messages`` /
            その他の ``kwargs`` をフラットに含む辞書。
        mode: 接続モード (常に ``"openai"``)。``ResilientAPIClient`` との
            インターフェース互換のために定義している。
    """

    DEFAULT_USAGE = {"input": 100, "output": 50}

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        """モッククライアントを初期化する。

        Args:
            responses: 事前に返したいレスポンス辞書のリスト。``None`` のとき
                は呼び出しごとに自動生成のレスポンスを返す。
        """
        self.responses: list[dict[str, Any]] = list(responses) if responses else []
        self.call_log: list[dict[str, Any]] = []
        self.mode: str = "openai"

    # ------------------------------------------------------------------
    # public API (ResilientAPIClient 互換)
    # ------------------------------------------------------------------

    async def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """呼び出しを記録し、事前設定のレスポンスを返す。

        Args:
            model: モデル名。
            messages: チャットメッセージのリスト。
            **kwargs: 追加パラメータ (``temperature``, ``max_tokens`` など)。
                ``call_log`` にそのまま記録される。

        Returns:
            事前登録のレスポンス辞書。``responses`` を使い切った後は
            ``{"content": "Mock response #N", "usage": {...}}`` を自動生成する。
        """
        index = len(self.call_log)
        self.call_log.append({"model": model, "messages": messages, **kwargs})

        if index < len(self.responses):
            return self.responses[index]
        return {
            "content": f"Mock response #{index}",
            "usage": dict(self.DEFAULT_USAGE),
        }

    @property
    def call_count(self) -> int:
        """これまでに ``call`` が呼ばれた回数。"""
        return len(self.call_log)

    # ------------------------------------------------------------------
    # アサーション・ヘルパー
    # ------------------------------------------------------------------

    def assert_called_with_model(self, model: str) -> None:
        """少なくとも 1 回 ``model`` で呼ばれていることを確認する。

        Args:
            model: 期待するモデル名。

        Raises:
            AssertionError: 一度も該当モデルで呼ばれていない場合。
        """
        models_used = [entry["model"] for entry in self.call_log]
        assert model in models_used, (
            f"Expected at least one call with model={model!r}, "
            f"but got models={models_used!r}"
        )

    def assert_call_count(self, expected: int) -> None:
        """呼び出し回数が ``expected`` と一致することを確認する。

        Args:
            expected: 期待する呼び出し回数。

        Raises:
            AssertionError: 回数が一致しない場合。
        """
        assert self.call_count == expected, (
            f"Expected {expected} call(s), but got {self.call_count}"
        )

    def assert_no_temperature(self) -> None:
        """全ての呼び出しに ``temperature`` が指定されていないことを確認する。

        GPT-5 系・o 系・Claude (extended thinking) など、``temperature`` を
        受け付けないモデルに対して誤って渡していないかを検証するために使う。

        Raises:
            AssertionError: いずれかの呼び出しで ``temperature`` が渡されている場合。
        """
        offenders = [
            i for i, entry in enumerate(self.call_log) if "temperature" in entry
        ]
        assert not offenders, (
            f"temperature must not be set on these calls: {offenders}"
        )

    def assert_no_max_tokens(self) -> None:
        """全ての呼び出しに ``max_tokens`` が指定されていないことを確認する。

        GPT-5 系では ``max_completion_tokens`` を使うため、誤って旧パラメータ
        ``max_tokens`` を渡していないかを検証する。

        Raises:
            AssertionError: いずれかの呼び出しで ``max_tokens`` が渡されている場合。
        """
        offenders = [
            i for i, entry in enumerate(self.call_log) if "max_tokens" in entry
        ]
        assert not offenders, (
            f"max_tokens must not be set on these calls: {offenders}"
        )


__all__ = ["MockAPIClient"]
