"""``core.speaking_order`` のユニットテスト。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.data_models import RoundConfig, Utterance
from core.rate_tracker import RateLimitTracker
from core.speaking_order import (
    DialecticOrder,
    DynamicOrder,
    FixedOrder,
    ShuffleOrder,
)
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _round_config(
    speakers: list[str],
    pattern: str = "one_shot",
    level: str = "medium",
) -> RoundConfig:
    return RoundConfig(
        round=1,
        phase_name="P",
        speakers=speakers,
        pattern=pattern,
        level=level,
        time_budget_sec=40.0,
        goal="g",
    )


def _utterance(content: str, speaker: str = "theorist") -> Utterance:
    return Utterance(
        sequence=1,
        speaker=speaker,
        speaker_display=speaker,
        type="discussion",
        content=content,
        model="gpt-4.1",
        level="medium",
    )


# ---------------------------------------------------------------------------
# FixedOrder
# ---------------------------------------------------------------------------


class TestFixedOrder:
    def test_returns_speakers_unchanged(self) -> None:
        order = FixedOrder()
        result = order.get_speaking_order(
            ["a", "b", "c"], _round_config(["a", "b", "c"]), {}
        )
        assert result == ["a", "b", "c"]

    def test_empty_speakers(self) -> None:
        order = FixedOrder()
        assert order.get_speaking_order([], _round_config([]), {}) == []

    def test_returns_copy_not_alias(self) -> None:
        """変更が元の list に影響しない。"""
        speakers = ["a", "b"]
        order = FixedOrder()
        result = order.get_speaking_order(speakers, _round_config(speakers), {})
        result.append("c")
        assert speakers == ["a", "b"]


# ---------------------------------------------------------------------------
# DialecticOrder
# ---------------------------------------------------------------------------


class TestDialecticOrder:
    def test_two_speakers_interleaved(self) -> None:
        order = DialecticOrder(max_exchanges=3)
        result = order.get_speaking_order(
            ["theorist", "devil"], _round_config(["theorist", "devil"]), {}
        )
        # 3 往復: A,B,A,B,A,B (どちらが A になるかは OPPOSITION_MAP 探索順依存)
        assert len(result) == 6
        # 2 者が交互配置されている
        assert set(result) == {"theorist", "devil"}
        # 偶数位置と奇数位置で異なる発言者
        assert result[0] != result[1]
        assert result[0] == result[2] == result[4]
        assert result[1] == result[3] == result[5]

    def test_finds_best_opposition_pair_from_many_speakers(self) -> None:
        """OPPOSITION_MAP を使って対立度の高い 2 者を抽出する。"""
        order = DialecticOrder(max_exchanges=2)
        # speakers に literature, theorist, devil が含まれる
        # devil の opposites = (theorist, literature) → 最初に見つかる
        result = order.get_speaking_order(
            ["literature", "theorist", "devil"],
            _round_config(["literature", "theorist", "devil"]),
            {},
        )
        # 対立ペアが正しく拾われている (順番は OPPOSITION_MAP の探索順依存)
        unique = set(result)
        assert len(unique) == 2  # 2 者だけが交互に並ぶ

    def test_falls_back_to_first_two_when_no_opposition(self) -> None:
        order = DialecticOrder(max_exchanges=2)
        result = order.get_speaking_order(
            ["alpha", "beta", "gamma"],
            _round_config(["alpha", "beta", "gamma"]),
            {},
        )
        # 対立関係なし → 先頭 2 者
        assert set(result) == {"alpha", "beta"}

    def test_single_speaker_repeats_self(self) -> None:
        order = DialecticOrder(max_exchanges=3)
        result = order.get_speaking_order(
            ["theorist"], _round_config(["theorist"]), {}
        )
        assert result == ["theorist", "theorist", "theorist"]


# ---------------------------------------------------------------------------
# ShuffleOrder
# ---------------------------------------------------------------------------


class TestShuffleOrder:
    def test_returns_all_speakers(self) -> None:
        order = ShuffleOrder(seed=42)
        result = order.get_speaking_order(
            ["a", "b", "c", "d"], _round_config(["a", "b", "c", "d"]), {}
        )
        assert sorted(result) == ["a", "b", "c", "d"]

    def test_seed_makes_result_deterministic(self) -> None:
        first = ShuffleOrder(seed=42).get_speaking_order(
            ["a", "b", "c", "d"], _round_config(["a", "b", "c", "d"]), {}
        )
        second = ShuffleOrder(seed=42).get_speaking_order(
            ["a", "b", "c", "d"], _round_config(["a", "b", "c", "d"]), {}
        )
        assert first == second

    def test_does_not_mutate_input(self) -> None:
        speakers = ["a", "b", "c"]
        ShuffleOrder(seed=1).get_speaking_order(speakers, _round_config(speakers), {})
        assert speakers == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# DynamicOrder
# ---------------------------------------------------------------------------


def _make_client(
    tmp_path: Path, responses: list[dict[str, Any]]
) -> ResilientAPIClient:
    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    return ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )


class TestDynamicOrder:
    @pytest.mark.asyncio
    async def test_returns_first_speaker_when_no_utterances(
        self, tmp_path: Path
    ) -> None:
        """発言履歴がない場合は API を呼ばず先頭を返す。"""
        client = _make_client(tmp_path, [])
        dynamic = DynamicOrder(client)

        result = await dynamic.decide_next_speaker(
            speakers=["a", "b", "c"],
            utterances=[],
            utterance_counts={"a": 0, "b": 0, "c": 0},
            round_goal="g",
        )
        assert result == "a"

    @pytest.mark.asyncio
    async def test_returns_llm_choice_when_exact_match(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path, [{"content": "devil"}])
        dynamic = DynamicOrder(client)

        result = await dynamic.decide_next_speaker(
            speakers=["theorist", "devil", "literature"],
            utterances=[_utterance("hello")],
            utterance_counts={"theorist": 1, "devil": 0, "literature": 0},
            round_goal="g",
        )
        assert result == "devil"

    @pytest.mark.asyncio
    async def test_returns_substring_match(self, tmp_path: Path) -> None:
        """応答が ``role_id`` を含む文字列でも解決できる。"""
        client = _make_client(tmp_path, [{"content": "次は devil でお願いします"}])
        dynamic = DynamicOrder(client)

        result = await dynamic.decide_next_speaker(
            speakers=["theorist", "devil"],
            utterances=[_utterance("hello")],
            utterance_counts={"theorist": 1, "devil": 0},
            round_goal="g",
        )
        assert result == "devil"

    @pytest.mark.asyncio
    async def test_falls_back_to_least_spoken_on_failure(
        self, tmp_path: Path
    ) -> None:
        """応答がパースできなければ発言数最少の AI を返す。"""
        client = _make_client(tmp_path, [{"content": "完全に無関係"}])
        dynamic = DynamicOrder(client)

        result = await dynamic.decide_next_speaker(
            speakers=["theorist", "devil"],
            utterances=[_utterance("hello")],
            utterance_counts={"theorist": 3, "devil": 1},
            round_goal="g",
        )
        # devil の方が発言数少ない
        assert result == "devil"

    @pytest.mark.asyncio
    async def test_raises_when_speakers_empty(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path, [])
        dynamic = DynamicOrder(client)
        with pytest.raises(ValueError, match="non-empty"):
            await dynamic.decide_next_speaker(
                speakers=[],
                utterances=[],
                utterance_counts={},
                round_goal="g",
            )

    @pytest.mark.asyncio
    async def test_strips_quotes_and_whitespace(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path, [{"content": '"theorist"\n'}])
        dynamic = DynamicOrder(client)

        result = await dynamic.decide_next_speaker(
            speakers=["theorist", "devil"],
            utterances=[_utterance("hi")],
            utterance_counts={"theorist": 0, "devil": 0},
            round_goal="g",
        )
        assert result == "theorist"
