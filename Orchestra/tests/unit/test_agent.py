"""``core.agent.Agent`` のユニットテスト。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.agent import (
    DEFAULT_MAX_TOKENS_FOR_UTTERANCE,
    DEFAULT_TEMPERATURE,
    MAX_UTTERANCE_CHARS,
    Agent,
    AgentConfig,
)
from core.api_client import ResilientAPIClient, RetryConfig
from core.config_loader import Settings
from core.memory import ConversationMemory
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_ROLE_SYSTEM_PROMPT = (
    "あなたはAI Orchestraの「理論屋」です。\n"
    "\n"
    "{orchestrator_instruction}\n"
    "\n"
    "{feedback_context}\n"
)

_ROLE_DEFINITION = {
    "role_id": "theorist",
    "display_name": "🧮 理論屋",
    "model": "gpt-5.4",
    "system_prompt": _ROLE_SYSTEM_PROMPT,
    "personality": {"traits": ["数式好き"]},
    "expertise": ["数理"],
    "domain_tags": ["machine_learning"],
    "evaluation_criteria": [
        {"name": "c1", "description": "d1"},
        {"name": "c2", "description": "d2"},
        {"name": "c3", "description": "d3"},
    ],
}


def _make_resilient(
    tmp_path: Path,
    responses: list[dict[str, Any]],
    mode: str = "openai",
) -> tuple[ResilientAPIClient, MockAPIClient]:
    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode=mode,
    )
    return client, mock


def _make_agent(
    tmp_path: Path,
    *,
    model: str = "gpt-5.4",
    level: str = "medium",
    mode: str = "openai",
    role_definition: dict[str, Any] | None = None,
    responses: list[dict[str, Any]] | None = None,
) -> tuple[Agent, ResilientAPIClient, MockAPIClient]:
    config = AgentConfig(role_id="theorist", model=model, level=level)
    rd = dict(role_definition or _ROLE_DEFINITION)
    rd["model"] = model
    rd["display_name"] = rd.get("display_name", "🧮 理論屋")

    api_client, mock = _make_resilient(
        tmp_path,
        responses or [{"content": "テスト発言", "usage": {"input": 100, "output": 30}}],
        mode=mode,
    )
    memory = ConversationMemory(api_client=api_client)
    settings = Settings()

    agent = Agent(
        config=config,
        role_definition=rd,
        api_client=api_client,
        memory=memory,
        settings=settings,
    )
    return agent, api_client, mock


# ---------------------------------------------------------------------------
# システムプロンプト
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """``_build_system_prompt`` のプレースホルダ置換と動的追加部分。"""

    def test_unset_placeholders_become_empty(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        prompt = agent._build_system_prompt()
        assert "{orchestrator_instruction}" not in prompt
        assert "{feedback_context}" not in prompt

    def test_private_instruction_is_injected(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        agent.set_private_instruction("計算量を必ず O 記法で明示")

        prompt = agent._build_system_prompt()

        assert "【指揮者からの指示】" in prompt
        assert "計算量を必ず O 記法で明示" in prompt

    def test_feedback_context_is_injected(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        agent.set_feedback_context("代替案の具体性が不足")

        prompt = agent._build_system_prompt()

        assert "【過去のフィードバック（改善を期待しています）】" in prompt
        assert "代替案の具体性が不足" in prompt

    def test_both_placeholders_are_replaced_simultaneously(self, tmp_path: Path) -> None:
        """両方のプレースホルダが正しく連鎖置換される (設計書サンプルのバグ確認)。"""
        agent, _, _ = _make_agent(tmp_path)
        agent.set_private_instruction("INST")
        agent.set_feedback_context("FB")

        prompt = agent._build_system_prompt()

        assert "INST" in prompt
        assert "FB" in prompt

    def test_speaking_rules_appended_at_tail(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        agent.set_speaking_rules("- 50〜150文字\n- 数式OK")

        prompt = agent._build_system_prompt()

        # speaking_rules は prompt 末尾に近い位置に含まれる
        # (さらに末尾には全ロール共通の DIVERSITY_RULE が付与される)
        assert "【発言ルール】\n- 50〜150文字\n- 数式OK" in prompt
        assert prompt.rstrip().endswith(
            "【多様性ルール】\n"
            "- 直前の発言者と同じ出だし・同じ論理展開・同じ結び方を使ってはいけない\n"
            "- あなたの発言が定型化していたら、途中でも書き直す。毎回違う切り口で発言する\n"
            "- 疑似変数 (τ=0.8、ε=0.1、σ、δ 等) や単位の羅列 (bps、+3pt、≤0.5%、24h超過5% 等) を並べない。実際の会議で口頭で自然に言えるレベルの表現に留める"
        )


# ---------------------------------------------------------------------------
# コンテキストメッセージ
# ---------------------------------------------------------------------------


class TestBuildContextMessage:
    """6 層構造の user message が組み立てられる。"""

    def test_includes_objective_and_round_goal(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        msg = agent._build_context_message(
            {"objective": "TEST_OBJ", "round_goal": "GOAL_TEST"}
        )
        assert "TEST_OBJ" in msg
        assert "GOAL_TEST" in msg

    def test_includes_previous_summary_when_present(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        msg = agent._build_context_message(
            {"objective": "o", "round_goal": "g", "previous_summary": "PREV_SUM"}
        )
        assert "PREV_SUM" in msg

    def test_includes_current_round_utterances(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        msg = agent._build_context_message(
            {
                "objective": "o",
                "round_goal": "g",
                "current_round_utterances": [
                    {"speaker_display": "🧮", "content": "hello"},
                    {"speaker_display": "📚", "content": "world"},
                ],
            }
        )
        assert "🧮: hello" in msg
        assert "📚: world" in msg

    def test_includes_additional_instruction(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        msg = agent._build_context_message(
            {"objective": "o", "round_goal": "g"},
            additional_instruction="ADD_INSTR",
        )
        assert "ADD_INSTR" in msg

    def test_includes_last_utterance(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path)
        msg = agent._build_context_message(
            {
                "objective": "o",
                "round_goal": "g",
                "last_utterance": {"speaker_display": "😈", "content": "LAST_UTT"},
            }
        )
        assert "LAST_UTT" in msg


# ---------------------------------------------------------------------------
# _build_api_params dispatch
# ---------------------------------------------------------------------------


class TestBuildApiParamsDispatch:
    """``_build_api_params`` がモデルと level に応じて分岐する。"""

    def test_gpt5_dispatches_to_gpt5_builder(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(tmp_path, model="gpt-5.4", level="medium")
        params = agent._build_api_params("sys", "user")

        # GPT-5 系の特徴: level (reasoning_effort 経由) + verbosity
        assert "level" in params
        assert params["level"] == "medium"
        assert params["verbosity"] == "low"
        # temperature / max_tokens は決して入らない
        assert "temperature" not in params
        assert "max_tokens" not in params

    def test_claude_thinking_dispatches_to_thinking_builder(
        self, tmp_path: Path
    ) -> None:
        agent, _, _ = _make_agent(
            tmp_path, model="claude-sonnet-4-5", level="medium"
        )
        params = agent._build_api_params("sys", "user")

        assert params["level"] == "medium"
        assert params["temperature"] == DEFAULT_TEMPERATURE
        # max_tokens は付けない
        assert "max_tokens" not in params

    def test_claude_thinking_with_minimal_level_uses_standard_builder(
        self, tmp_path: Path
    ) -> None:
        """Claude モデルでも level=minimal/none は標準パラメータに落ちる。"""
        agent, _, _ = _make_agent(
            tmp_path, model="claude-sonnet-4-5", level="minimal"
        )
        params = agent._build_api_params("sys", "user")

        # 標準パラメータの特徴
        assert params["temperature"] == DEFAULT_TEMPERATURE
        assert params["max_tokens"] == DEFAULT_MAX_TOKENS_FOR_UTTERANCE

    def test_standard_model_dispatches_to_standard_builder(
        self, tmp_path: Path
    ) -> None:
        agent, _, _ = _make_agent(tmp_path, model="gpt-4.1", level="medium")
        params = agent._build_api_params("sys", "user")

        assert params["temperature"] == DEFAULT_TEMPERATURE
        assert params["max_tokens"] == DEFAULT_MAX_TOKENS_FOR_UTTERANCE
        assert "level" not in params
        assert "extra_body" not in params


# ---------------------------------------------------------------------------
# GPT-5 系で実 call 後の不変条件 (MockAPIClient で検証)
# ---------------------------------------------------------------------------


class TestGPT5CallInvariant:
    """GPT-5 系の実呼び出しで、temperature/max_tokens が決して送られないこと。"""

    @pytest.mark.asyncio
    async def test_gpt5_never_sends_temperature_or_max_tokens(
        self, tmp_path: Path
    ) -> None:
        agent, _, mock = _make_agent(
            tmp_path,
            model="gpt-5.4",
            level="high",
            mode="openai",
            responses=[{"content": "短い発言です"}],
        )

        await agent.speak(
            round_context={
                "objective": "obj",
                "round_goal": "goal",
                "next_sequence": 1,
            }
        )

        mock.assert_no_temperature()
        mock.assert_no_max_tokens()
        recorded = mock.call_log[0]
        assert recorded["model"] == "gpt-5.4"
        assert recorded["reasoning_effort"] == "high"
        # openai モードでは extra_body 必須
        assert recorded["extra_body"] == {"allowed_openai_params": ["reasoning_effort"]}

    @pytest.mark.asyncio
    async def test_gpt5_azure_mode_omits_extra_body(self, tmp_path: Path) -> None:
        """azure モードでは extra_body を送らない (400 回避)。"""
        agent, _, mock = _make_agent(
            tmp_path,
            model="gpt-5",
            level="medium",
            mode="azure",
            responses=[{"content": "azure"}],
        )

        await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        recorded = mock.call_log[0]
        assert recorded["reasoning_effort"] == "medium"
        assert "extra_body" not in recorded
        mock.assert_no_temperature()
        mock.assert_no_max_tokens()


# ---------------------------------------------------------------------------
# Claude 拡張思考の実呼び出し
# ---------------------------------------------------------------------------


class TestClaudeThinkingCall:
    @pytest.mark.asyncio
    async def test_claude_thinking_sets_budget_tokens(self, tmp_path: Path) -> None:
        agent, _, mock = _make_agent(
            tmp_path,
            model="claude-sonnet-4-5",
            level="medium",
            responses=[{"content": "claude thinking"}],
        )

        await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        recorded = mock.call_log[0]
        assert recorded["model"] == "claude-sonnet-4-5"
        # ResilientAPIClient._build_params が thinking に変換
        assert recorded["extra_body"] == {
            "thinking": {"type": "enabled", "budget_tokens": 8000}
        }


# ---------------------------------------------------------------------------
# 標準モデルの実呼び出し
# ---------------------------------------------------------------------------


class TestStandardModelCall:
    @pytest.mark.asyncio
    async def test_standard_call_sends_temperature_and_max_tokens(
        self, tmp_path: Path
    ) -> None:
        agent, _, mock = _make_agent(
            tmp_path,
            model="gpt-4.1",
            level="low",
            responses=[{"content": "standard"}],
        )

        await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        recorded = mock.call_log[0]
        assert recorded["temperature"] == DEFAULT_TEMPERATURE
        assert recorded["max_tokens"] == DEFAULT_MAX_TOKENS_FOR_UTTERANCE


# ---------------------------------------------------------------------------
# 発言長 3 段防衛: _is_too_long / _request_shorter
# ---------------------------------------------------------------------------


class TestUtteranceLengthDefense:
    """発言長制御の境界と短縮処理。"""

    def test_is_too_long_boundary(self) -> None:
        assert Agent._is_too_long("a" * MAX_UTTERANCE_CHARS) is False
        assert Agent._is_too_long("a" * (MAX_UTTERANCE_CHARS + 1)) is True

    @pytest.mark.asyncio
    async def test_speak_returns_shortened_when_too_long(self, tmp_path: Path) -> None:
        """長い発言は短縮 API 呼び出しで縮められる。"""
        long_content = "あ" * 250  # MAX_UTTERANCE_CHARS = 200 超
        agent, _, mock = _make_agent(
            tmp_path,
            model="gpt-4.1",
            level="medium",
            responses=[
                {"content": long_content},                       # 元の発言
                {"content": "短くまとめた発言"},                  # 短縮 API の応答
            ],
        )

        utt = await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        assert utt.content == "短くまとめた発言"
        # 2 回呼ばれている (本発言 + 短縮)
        mock.assert_call_count(2)
        # 2 回目は短縮モデル (gpt-4.1)
        assert mock.call_log[1]["model"] == "gpt-4.1"

    @pytest.mark.asyncio
    async def test_request_shorter_falls_back_to_truncation_when_still_long(
        self, tmp_path: Path
    ) -> None:
        """短縮 API が長文を返した場合は ``…`` で切り詰める。"""
        long_content = "あ" * 250
        agent, _, _ = _make_agent(
            tmp_path,
            model="gpt-4.1",
            level="medium",
            responses=[
                {"content": long_content},
                {"content": "い" * 300},  # 短縮 API も長い
            ],
        )

        utt = await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        assert len(utt.content) <= MAX_UTTERANCE_CHARS
        assert utt.content.endswith("…")

    @pytest.mark.asyncio
    async def test_speak_passes_through_when_short_enough(
        self, tmp_path: Path
    ) -> None:
        """既定値以下の発言は短縮しない。"""
        agent, _, mock = _make_agent(
            tmp_path,
            model="gpt-4.1",
            responses=[{"content": "短い発言です"}],
        )

        utt = await agent.speak(round_context={"objective": "o", "round_goal": "g"})

        assert utt.content == "短い発言です"
        mock.assert_call_count(1)


# ---------------------------------------------------------------------------
# Utterance のメタデータ
# ---------------------------------------------------------------------------


class TestUtteranceMetadata:
    @pytest.mark.asyncio
    async def test_returned_utterance_has_role_metadata(self, tmp_path: Path) -> None:
        agent, _, _ = _make_agent(
            tmp_path,
            model="gpt-4.1",
            level="low",
            responses=[{"content": "ok", "usage": {"input": 100, "output": 30}}],
        )

        utt = await agent.speak(
            round_context={
                "objective": "o",
                "round_goal": "g",
                "next_sequence": 7,
            }
        )

        assert utt.speaker == "theorist"
        assert utt.speaker_display == "🧮 理論屋"
        assert utt.model == "gpt-4.1"
        assert utt.level == "low"
        assert utt.sequence == 7
        assert utt.tokens_used == {"input": 100, "output": 30}
        assert utt.duration_sec >= 0.0
