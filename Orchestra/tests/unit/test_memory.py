"""``core.memory`` のユニットテスト。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.data_models import RoundLog, Utterance
from core.memory import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    ContextBudget,
    ConversationMemory,
)
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _utterance(
    sequence: int = 1,
    speaker: str = "theorist",
    speaker_display: str = "🧮 理論屋",
    content: str = "テスト発言",
    model: str = "gpt-5.4",
    level: str = "medium",
    tokens_used: dict[str, int] | None = None,
    duration_sec: float = 1.0,
) -> Utterance:
    return Utterance(
        sequence=sequence,
        speaker=speaker,
        speaker_display=speaker_display,
        type="discussion",
        content=content,
        model=model,
        level=level,
        tokens_used=tokens_used or {"input": 100, "output": 50},
        duration_sec=duration_sec,
    )


@pytest.fixture
def resilient_client(tmp_path: Path) -> ResilientAPIClient:
    """要約呼び出し用の ResilientAPIClient (MockAPIClient 包み)。"""
    mock = MockAPIClient(responses=[{"content": "要約テスト本文", "usage": {"input": 100, "output": 30}}])
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    return ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )


@pytest.fixture
def memory(resilient_client: ResilientAPIClient) -> ConversationMemory:
    return ConversationMemory(api_client=resilient_client)


# ---------------------------------------------------------------------------
# ContextBudget
# ---------------------------------------------------------------------------


class TestContextBudget:
    """``ContextBudget`` のモデル別・level 別予算計算。"""

    @pytest.mark.parametrize(
        ("model", "expected_limit"),
        [
            ("gpt-4.1", 128_000),
            ("gpt-5.4", 1_000_000),
            ("claude-sonnet-4-5", 200_000),
            ("unknown-model", 128_000),  # default
        ],
    )
    def test_max_input_matches_table(self, model: str, expected_limit: int) -> None:
        budget = ContextBudget(model=model, level="medium")
        assert budget.max_input == expected_limit

    @pytest.mark.parametrize(
        ("level", "expected_reserve"),
        [
            ("minimal", 200),
            ("low", 500),
            ("medium", 1_000),
            ("high", 2_000),
            ("unknown-level", 1_000),
        ],
    )
    def test_output_reserve_matches_table(
        self, level: str, expected_reserve: int
    ) -> None:
        budget = ContextBudget(model="gpt-4.1", level=level)
        assert budget.output_reserve == expected_reserve

    def test_available_input_subtracts_reserve(self) -> None:
        budget = ContextBudget(model="gpt-4.1", level="high")
        assert budget.available_input == 128_000 - 2_000

    def test_estimate_tokens_japanese_vs_english(self) -> None:
        """日本語 1 文字 ≈ 1.5、英語 1 文字 ≈ 0.3 で重みが大きく違う。"""
        budget = ContextBudget(model="gpt-4.1", level="medium")

        jp = budget.estimate_tokens("あいうえお")  # 5 文字
        en = budget.estimate_tokens("hello")        # 5 文字

        # 5 * 1.5 = 7, 5 * 0.3 = 1
        assert jp == 7
        assert en == 1
        assert jp > en

    def test_estimate_tokens_empty_returns_zero(self) -> None:
        budget = ContextBudget(model="gpt-4.1", level="medium")
        assert budget.estimate_tokens("") == 0

    def test_fits_true_when_under_limit(self) -> None:
        budget = ContextBudget(model="gpt-4.1", level="medium")
        assert budget.fits("short", "also short") is True

    def test_fits_false_when_over_limit(self) -> None:
        """小さな予算で長文を入れたら fits=False。"""
        # available_input = 1000 - 200 = 800
        budget = ContextBudget(model="o3-mini", level="minimal")
        budget.max_input = 1000
        budget.available_input = 800

        # 日本語で 1000 文字 → 約 1500 token
        big = "あ" * 1000
        assert budget.fits("system", big) is False

    def test_trim_to_fit_shortens_to_available(self) -> None:
        """``trim_to_fit`` は available_input 内に収まる長さに切り詰める。"""
        budget = ContextBudget(model="gpt-4.1", level="medium")
        budget.max_input = 100
        budget.available_input = 80

        big = "あ" * 100  # ~150 token
        trimmed = budget.trim_to_fit("", big)

        assert budget.fits("", trimmed)


# ---------------------------------------------------------------------------
# add_utterance / ログ集計
# ---------------------------------------------------------------------------


class TestAddUtterance:
    """``add_utterance`` がログとトークン累計を正しく更新する。"""

    def test_add_utterance_appends_to_full_log(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(content="hello"), round_num=1)

        assert len(memory.full_log) == 1
        entry = memory.full_log[0]
        assert entry["round"] == 1
        assert entry["content"] == "hello"
        assert "timestamp" in entry

    def test_add_utterance_groups_by_round(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(sequence=1), round_num=1)
        memory.add_utterance(_utterance(sequence=2), round_num=1)
        memory.add_utterance(_utterance(sequence=1), round_num=2)

        assert len(memory.get_round_utterances(1)) == 2
        assert len(memory.get_round_utterances(2)) == 1

    def test_add_utterance_accumulates_tokens(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(tokens_used={"input": 100, "output": 50}), 1)
        memory.add_utterance(_utterance(tokens_used={"input": 200, "output": 80}), 1)

        assert memory.total_tokens.input == 300
        assert memory.total_tokens.output == 130
        assert memory.total_tokens.total == 430

    def test_add_utterance_increments_request_count(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(), 1)
        memory.add_utterance(_utterance(), 1)

        assert memory.total_requests == 2

    def test_get_last_utterance_returns_none_when_empty(
        self, memory: ConversationMemory
    ) -> None:
        assert memory.get_last_utterance(1) is None

    def test_get_last_utterance_returns_latest(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(sequence=1, content="first"), 1)
        memory.add_utterance(_utterance(sequence=2, content="second"), 1)

        last = memory.get_last_utterance(1)
        assert last is not None
        assert last["content"] == "second"


# ---------------------------------------------------------------------------
# get_context_for_agent
# ---------------------------------------------------------------------------


class TestGetContextForAgent:
    """``get_context_for_agent`` の戻り辞書とハイブリッド戦略。"""

    def test_returns_full_text_when_under_limit(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_utterance(_utterance(sequence=1, content="r1-1"), 1)
        memory.add_utterance(_utterance(sequence=1, content="r2-1"), 2)

        budget = ContextBudget(model="gpt-4.1", level="medium")
        ctx = memory.get_context_for_agent(
            current_round=2,
            agent_role_id="theorist",
            context_budget=budget,
        )

        # 過去 (Round 1) は全文
        assert "r1-1" in ctx["previous_summary"]
        # 現在ラウンドの発言
        assert len(ctx["current_round_utterances"]) == 1
        assert ctx["current_round_utterances"][0]["content"] == "r2-1"

    def test_uses_summary_when_over_limit(self, memory: ConversationMemory) -> None:
        """``max_context_tokens`` を超える場合は ``round_summaries`` を使う。"""
        memory.max_context_tokens = 10  # 強制的に超過させる
        memory.round_summaries.append("[R1] テスト要約")
        memory.add_utterance(_utterance(content="あ" * 200), 1)  # 大きな日本語ログ
        memory.add_utterance(_utterance(content="current"), 2)

        budget = ContextBudget(model="gpt-4.1", level="medium")
        ctx = memory.get_context_for_agent(2, "theorist", budget)

        assert "テスト要約" in ctx["previous_summary"]
        # 全文 ("あ"*200) は入っていない
        assert "あ" * 200 not in ctx["previous_summary"]

    def test_includes_last_utterance(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(sequence=1, content="first"), 2)
        memory.add_utterance(_utterance(sequence=2, content="last"), 2)

        budget = ContextBudget(model="gpt-4.1", level="medium")
        ctx = memory.get_context_for_agent(2, "theorist", budget)

        assert ctx["last_utterance"]["content"] == "last"

    def test_filters_system_events_by_round(self, memory: ConversationMemory) -> None:
        memory.add_system_event("stagnation detected", round_num=1)
        memory.add_system_event("repetition detected", round_num=2)

        budget = ContextBudget(model="gpt-4.1", level="medium")
        ctx = memory.get_context_for_agent(2, "theorist", budget)

        events = ctx["system_events"]
        assert len(events) == 1
        assert events[0]["event"] == "repetition detected"


# ---------------------------------------------------------------------------
# get_full_log_text / get_context_summary
# ---------------------------------------------------------------------------


class TestLogFormatters:
    """テキスト化メソッドの形式。"""

    def test_get_full_log_text_groups_by_round(
        self, memory: ConversationMemory
    ) -> None:
        memory.add_utterance(_utterance(content="r1a"), 1)
        memory.add_utterance(_utterance(content="r1b", speaker_display="📚 文献屋"), 1)
        memory.add_utterance(_utterance(content="r2a"), 2)

        text = memory.get_full_log_text()

        assert "--- Round 1 ---" in text
        assert "--- Round 2 ---" in text
        assert "🧮 理論屋: r1a" in text
        assert "📚 文献屋: r1b" in text

    def test_get_context_summary_uses_round_summaries_when_present(
        self, memory: ConversationMemory
    ) -> None:
        memory.round_summaries.extend(["[R1] s1", "[R2] s2"])
        summary = memory.get_context_summary()
        assert "[R1] s1" in summary
        assert "[R2] s2" in summary

    def test_get_context_summary_falls_back_to_recent_utterances(
        self, memory: ConversationMemory
    ) -> None:
        for i in range(7):
            memory.add_utterance(_utterance(sequence=i, content=f"line-{i}"), 1)
        summary = memory.get_context_summary()
        # 直近 5 件のみ
        assert "line-6" in summary
        assert "line-0" not in summary


# ---------------------------------------------------------------------------
# summarize_round (mock API)
# ---------------------------------------------------------------------------


class TestSummarizeRound:
    """要約生成のフロー。"""

    @pytest.mark.asyncio
    async def test_summarize_round_appends_summary(
        self, memory: ConversationMemory
    ) -> None:
        round_log = RoundLog(
            round=1,
            duration_sec=42.0,
            phase_name="問題の定式化",
            goal="点群→グラフ変換の整理",
            public_utterances=[
                _utterance(speaker_display="🧮 理論屋", content="hello"),
                _utterance(speaker_display="📚 文献屋", content="world"),
            ],
        )

        await memory.summarize_round(round_log)

        assert len(memory.round_summaries) == 1
        assert memory.round_summaries[0].startswith("[R1 問題の定式化]")
        assert "要約テスト本文" in memory.round_summaries[0]

    @pytest.mark.asyncio
    async def test_summarize_round_increments_request_count(
        self, memory: ConversationMemory
    ) -> None:
        round_log = RoundLog(round=1, duration_sec=10.0, public_utterances=[])

        await memory.summarize_round(round_log)

        assert memory.total_requests == 1


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------


class TestExportJson:
    """``export_json`` の構造。"""

    def test_export_json_contains_all_sections(self, memory: ConversationMemory) -> None:
        memory.add_utterance(_utterance(tokens_used={"input": 100, "output": 50}), 1)
        memory.round_summaries.append("[R1] summary")
        memory.add_system_event("test event", 1)

        data = memory.export_json()

        assert "full_log" in data
        assert "round_summaries" in data
        assert "system_events" in data
        assert "statistics" in data
        assert data["statistics"]["total_requests"] == 1
        assert data["statistics"]["total_tokens"]["input"] == 100
        assert data["statistics"]["total_tokens"]["output"] == 50
        assert data["statistics"]["total_tokens"]["total"] == 150

    def test_export_json_returns_copies(self, memory: ConversationMemory) -> None:
        """エクスポートした辞書を変更しても内部状態に影響しない。"""
        memory.add_utterance(_utterance(), 1)
        data = memory.export_json()

        data["full_log"].clear()

        assert len(memory.full_log) == 1


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_max_context_tokens_is_5000(self) -> None:
        assert DEFAULT_MAX_CONTEXT_TOKENS == 5000

    def test_default_summary_model_is_gpt41(
        self, resilient_client: ResilientAPIClient
    ) -> None:
        mem = ConversationMemory(api_client=resilient_client)
        assert mem.summary_model == "gpt-4.1"
