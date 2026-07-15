"""``core.intervention`` のユニットテスト。"""

from __future__ import annotations

import pytest

from core.intervention import InterventionHandler, NoIntervention


class TestInterventionHandlerAbstract:
    """``InterventionHandler`` は ABC で、直接インスタンス化できない。"""

    def test_cannot_instantiate_abstract_class(self) -> None:
        with pytest.raises(TypeError, match="abstract"):
            InterventionHandler()  # type: ignore[abstract]

    def test_subclass_without_all_methods_cannot_instantiate(self) -> None:
        """``check_intervention`` のみ実装したサブクラスは不完全。"""

        class Partial(InterventionHandler):
            def check_intervention(self, round_num: int, context: dict) -> str | None:
                return None
            # notify_progress を実装していない

        with pytest.raises(TypeError, match="abstract"):
            Partial()  # type: ignore[abstract]

    def test_complete_subclass_can_instantiate(self) -> None:
        """両メソッドを実装したサブクラスはインスタンス化できる。"""

        class Complete(InterventionHandler):
            def check_intervention(self, round_num: int, context: dict) -> str | None:
                return None

            def notify_progress(self, event: str, data: dict) -> None:
                pass

        handler = Complete()
        assert handler.check_intervention(1, {}) is None


class TestNoIntervention:
    """``NoIntervention`` は ABC の最小実装。"""

    def test_check_intervention_always_none(self) -> None:
        handler = NoIntervention()
        assert handler.check_intervention(1, {}) is None
        assert handler.check_intervention(99, {"any": "data"}) is None

    def test_notify_progress_is_silent(self) -> None:
        """例外を投げずに完了する。"""
        handler = NoIntervention()
        handler.notify_progress("event", {"k": "v"})  # 例外なし
        handler.notify_progress("", {})

    def test_is_intervention_handler_instance(self) -> None:
        assert isinstance(NoIntervention(), InterventionHandler)


class TestExposedViaConductor:
    """``core.conductor`` から再エクスポートされていることを確認 (後方互換)。"""

    def test_conductor_reexports_no_intervention(self) -> None:
        from core.conductor import NoIntervention as ConductorNoIntervention

        assert ConductorNoIntervention is NoIntervention

    def test_conductor_reexports_intervention_handler(self) -> None:
        from core.conductor import InterventionHandler as ConductorIH

        assert ConductorIH is InterventionHandler
