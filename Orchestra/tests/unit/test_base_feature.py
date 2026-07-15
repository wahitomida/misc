"""``core.base_feature`` のユニットテスト。

``PhaseKey`` / ``notify_phase`` / ``DiscussionFeatureBase`` の基本動作を検証する。
"""

from __future__ import annotations

from typing import Any

import pytest

from core.base_feature import (
    PHASE_DISPLAY,
    DiscussionFeatureBase,
    PhaseKey,
)


class TestPhaseKey:
    """``PhaseKey`` enum の値定義と網羅性。"""

    def test_all_four_phase_keys_are_defined(self) -> None:
        """input / planning / discussion / result の 4 つが定義される。"""
        values = {key.value for key in PhaseKey}
        assert values == {"input", "planning", "discussion", "result"}

    def test_phase_display_covers_all_keys(self) -> None:
        """``PHASE_DISPLAY`` は全 PhaseKey に対応表示名を持つ。"""
        for key in PhaseKey:
            assert key in PHASE_DISPLAY
            assert PHASE_DISPLAY[key], f"PHASE_DISPLAY[{key}] must not be empty"

    def test_display_names_start_with_phase_number(self) -> None:
        """表示名は 'Phase N: ...' 形式で番号順。"""
        assert PHASE_DISPLAY[PhaseKey.INPUT].startswith("Phase 1")
        assert PHASE_DISPLAY[PhaseKey.PLANNING].startswith("Phase 2")
        assert PHASE_DISPLAY[PhaseKey.DISCUSSION].startswith("Phase 3")
        assert PHASE_DISPLAY[PhaseKey.RESULT].startswith("Phase 4")


class _DummyFeature(DiscussionFeatureBase):
    """テスト用の ``DiscussionFeatureBase`` サブクラス。"""

    def __init__(self) -> None:
        # 実際の依存は不要 (notify_phase のみ検証)
        super().__init__(
            api_client=None,  # type: ignore[arg-type]
            role_manager=None,  # type: ignore[arg-type]
            feedback_manager=None,
            settings=None,  # type: ignore[arg-type]
        )


class TestNotifyPhase:
    """``notify_phase`` は on_phase / on_phase_key の両方を呼ぶ。"""

    def test_notify_phase_calls_both_handlers_when_provided(self) -> None:
        """on_phase と on_phase_key が両方与えられれば両方呼ばれる。"""
        # Arrange
        feature = _DummyFeature()
        received_names: list[str] = []
        received_keys: list[tuple[PhaseKey, str]] = []

        # Act
        feature.notify_phase(
            PhaseKey.DISCUSSION,
            on_phase=lambda name: received_names.append(name),
            on_phase_key=lambda key, name: received_keys.append((key, name)),
        )

        # Assert
        assert received_names == [PHASE_DISPLAY[PhaseKey.DISCUSSION]]
        assert received_keys == [
            (PhaseKey.DISCUSSION, PHASE_DISPLAY[PhaseKey.DISCUSSION])
        ]

    def test_notify_phase_uses_default_display_when_description_omitted(self) -> None:
        """description=None なら PHASE_DISPLAY[key] が使われる。"""
        # Arrange
        feature = _DummyFeature()
        received: list[str] = []

        # Act
        feature.notify_phase(PhaseKey.RESULT, on_phase=received.append)

        # Assert
        assert received == [PHASE_DISPLAY[PhaseKey.RESULT]]

    def test_notify_phase_uses_custom_description_when_provided(self) -> None:
        """description が与えられればそれを優先する。"""
        # Arrange
        feature = _DummyFeature()
        received: list[str] = []

        # Act
        feature.notify_phase(
            PhaseKey.INPUT,
            description="カスタム説明",
            on_phase=received.append,
        )

        # Assert
        assert received == ["カスタム説明"]

    def test_notify_phase_silent_when_no_handlers(self) -> None:
        """handler が None でも例外を出さない。"""
        feature = _DummyFeature()
        # 例外が出なければ OK
        feature.notify_phase(PhaseKey.PLANNING)

    def test_notify_phase_swallows_handler_exception(self) -> None:
        """handler が例外を投げても伝播しない。"""
        # Arrange
        feature = _DummyFeature()
        key_received: list[PhaseKey] = []

        def _raising(name: str) -> None:
            raise RuntimeError("boom")

        # Act — on_phase が失敗しても on_phase_key は呼ばれる
        feature.notify_phase(
            PhaseKey.DISCUSSION,
            on_phase=_raising,
            on_phase_key=lambda key, _n: key_received.append(key),
        )

        # Assert
        assert key_received == [PhaseKey.DISCUSSION]


class TestFeatureAttributes:
    """基底クラスの ``__init__`` が属性を保持する。"""

    def test_init_stores_all_dependencies(self) -> None:
        """4 つの依存 (api_client / role_manager / feedback_manager / settings) が
        属性として保持される。
        """

        # Arrange
        class _Marker:
            pass

        api = _Marker()
        rm = _Marker()
        fb = _Marker()
        st = _Marker()

        # Act
        feature = DiscussionFeatureBase(
            api_client=api,  # type: ignore[arg-type]
            role_manager=rm,  # type: ignore[arg-type]
            feedback_manager=fb,  # type: ignore[arg-type]
            settings=st,  # type: ignore[arg-type]
        )

        # Assert
        assert feature.api_client is api
        assert feature.role_manager is rm
        assert feature.feedback_manager is fb
        assert feature.settings is st
