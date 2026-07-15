"""``core.conductor.Conductor`` のユニットテスト。

Agent は ``FakeAgent`` で代替し、検知器 (``ConvergenceChecker`` /
``RepetitionDetector`` / ``AgreementDetector``) はモック動作を仕込んだ
``MockAPIClient`` 経由で振る舞いを制御する。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.config_loader import Settings
from core.conductor import (
    EXCESSIVE_AGREEMENT_INSTRUCTION,
    FORCE_NEW_TOPIC_INSTRUCTION,
    NoIntervention,
    PIVOT_PROMPT,
    Conductor,
)
from core.convergence import (
    AgreementDetector,
    ConvergenceChecker,
    RepetitionDetector,
)
from core.data_models import (
    ODSC,
    ConvergenceResult,
    DiscussionPlan,
    OrchestraPlan,
    RepetitionResult,
    RoundConfig,
    RoundLog,
    Utterance,
)
from core.memory import ConversationMemory
from core.rate_tracker import RateLimitTracker
from core.time_keeper import TimeKeeper, TimePressure
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# Fake Agent
# ---------------------------------------------------------------------------


class FakeAgent:
    """Conductor から呼ばれる ``Agent`` インターフェースの最小スタブ。

    ``speak()`` は順次インクリメントしたカウンタを使った発言を返し、追加指示は
    ``received_instructions`` に蓄積する。
    """

    def __init__(self, role_id: str, display_name: str | None = None) -> None:
        self.role_id = role_id
        self.display_name = display_name or role_id
        self.model = "gpt-4.1"
        self.level = "medium"
        self.call_count = 0
        self.received_contexts: list[dict[str, Any]] = []
        self.received_instructions: list[str] = []

    async def speak(
        self,
        round_context: dict[str, Any],
        additional_instruction: str = "",
    ) -> Utterance:
        self.call_count += 1
        self.received_contexts.append(round_context)
        self.received_instructions.append(additional_instruction)
        sequence = int(round_context.get("next_sequence", self.call_count))
        return Utterance(
            sequence=sequence,
            speaker=self.role_id,
            speaker_display=self.display_name,
            type="discussion",
            content=f"{self.role_id}-utt-{self.call_count}",
            model=self.model,
            level=self.level,
            tokens_used={"input": 100, "output": 30},
            duration_sec=0.01,
        )


# ---------------------------------------------------------------------------
# Stub Detectors
# ---------------------------------------------------------------------------


class StubConvergenceChecker:
    """事前に用意した結果を順番に返すスタブ。"""

    def __init__(self, results: list[ConvergenceResult]) -> None:
        self.results = results
        self.score_history: list[float] = []
        self.calls: list[RoundLog] = []
        self._idx = 0

    async def check(
        self,
        round_log: RoundLog,
        plan: OrchestraPlan,
        memory: ConversationMemory | None = None,
    ) -> ConvergenceResult:
        del plan, memory
        self.calls.append(round_log)
        if self._idx < len(self.results):
            result = self.results[self._idx]
        else:
            result = self.results[-1] if self.results else ConvergenceResult(score=0.0)
        self._idx += 1
        self.score_history.append(result.score)
        return result

    def should_terminate(self, result: ConvergenceResult, threshold: float) -> bool:
        return result.score >= threshold or result.recommendation == "conclude"

    def is_stagnating(self, window: int = 3, tolerance: float = 0.05) -> bool:
        if len(self.score_history) < window:
            return False
        recent = self.score_history[-window:]
        return (max(recent) - min(recent)) < tolerance


class StubRepetitionDetector:
    """``check_repetition`` の戻り値を固定するスタブ。"""

    def __init__(self, result: RepetitionResult | None = None) -> None:
        self._result = result or RepetitionResult(is_repeating=False)
        self.call_count = 0

    async def check_repetition(
        self,
        recent_utterances: list[Utterance],
        window: int = 4,
    ) -> RepetitionResult:
        del recent_utterances, window
        self.call_count += 1
        return self._result


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _round_config(
    speakers: list[str],
    pattern: str = "one_shot",
    round_num: int = 1,
) -> RoundConfig:
    return RoundConfig(
        round=round_num,
        phase_name=f"phase{round_num}",
        speakers=speakers,
        pattern=pattern,
        level="medium",
        time_budget_sec=40.0,
        goal=f"goal-{round_num}",
    )


def _plan(rounds: list[RoundConfig]) -> OrchestraPlan:
    return OrchestraPlan(
        odsc=ODSC(
            objective="obj",
            deliverable="del",
            success_criteria="suc",
            convergence_threshold=0.8,
        ),
        discussion_plan=DiscussionPlan(
            estimated_rounds=len(rounds),
            round_config=rounds,
        ),
    )


def _make_resilient(
    tmp_path: Path,
    responses: list[dict[str, Any]] | None = None,
) -> tuple[ResilientAPIClient, MockAPIClient]:
    mock = MockAPIClient(responses=responses or [])
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    return client, mock


def _make_conductor(
    tmp_path: Path,
    agents: dict[str, FakeAgent],
    *,
    convergence_results: list[ConvergenceResult] | None = None,
    repetition_result: RepetitionResult | None = None,
    extra_responses: list[dict[str, Any]] | None = None,
    time_keeper: TimeKeeper | None = None,
) -> tuple[Conductor, MockAPIClient, ConversationMemory, StubConvergenceChecker]:
    """Conductor + 関連ヘルパーを組み立てる。"""
    client, mock = _make_resilient(tmp_path, responses=extra_responses)
    memory = ConversationMemory(api_client=client)
    settings = Settings.load(
        config_dir=Path(__file__).resolve().parents[2] / "config",
        env_file=tmp_path / "missing.env",
    )
    checker = StubConvergenceChecker(
        convergence_results or [ConvergenceResult(score=0.5)]
    )
    repetition = StubRepetitionDetector(repetition_result)
    keeper = time_keeper or TimeKeeper(
        time_limit_sec=600.0, phase3_reserve_sec=25.0, safety_margin=0.9
    )
    conductor = Conductor(
        api_client=client,
        agents=agents,  # type: ignore[arg-type]  # FakeAgent は Agent と同じ API
        memory=memory,
        time_keeper=keeper,
        settings=settings,
        intervention=NoIntervention(),
        convergence_checker=checker,  # type: ignore[arg-type]
        repetition_detector=repetition,  # type: ignore[arg-type]
        agreement_detector=AgreementDetector(client),
        enable_bonus_rounds=False,  # テストの決定的な rounds 数を維持
    )
    return conductor, mock, memory, checker


# ---------------------------------------------------------------------------
# run_round: one_shot
# ---------------------------------------------------------------------------


class TestRunRoundOneShot:
    @pytest.mark.asyncio
    async def test_each_agent_speaks_once_in_order(self, tmp_path: Path) -> None:
        agents = {
            "a": FakeAgent("a"),
            "b": FakeAgent("b"),
            "c": FakeAgent("c"),
        }
        conductor, _, memory, _ = _make_conductor(tmp_path, agents)

        round_log = await conductor.run_round(
            _round_config(["a", "b", "c"], pattern="one_shot"),
            _plan([_round_config(["a", "b", "c"])]),
        )

        assert len(round_log.public_utterances) == 4
        assert [u.speaker for u in round_log.public_utterances] == ["a", "b", "c", "a"]
        # 各 agent は 1 回 + 結論(a) で呼ばれる
        assert agents["a"].call_count == 2
        assert agents["b"].call_count == 1
        assert agents["c"].call_count == 1
        # メモリにも記録される
        assert len(memory.get_round_utterances(1)) == 4

    @pytest.mark.asyncio
    async def test_round_log_includes_convergence_result(
        self, tmp_path: Path
    ) -> None:
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            {"a": FakeAgent("a")},
            convergence_results=[
                ConvergenceResult(score=0.42, recommendation="continue")
            ],
        )

        round_log = await conductor.run_round(
            _round_config(["a"]), _plan([_round_config(["a"])])
        )

        assert round_log.convergence_check is not None
        assert round_log.convergence_check.score == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# run_round: ping_pong
# ---------------------------------------------------------------------------


class TestRunRoundPingPong:
    @pytest.mark.asyncio
    async def test_two_speakers_alternate(self, tmp_path: Path) -> None:
        agents = {
            "theorist": FakeAgent("theorist"),
            "devil": FakeAgent("devil"),
        }
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        round_log = await conductor.run_round(
            _round_config(["theorist", "devil"], pattern="ping_pong"),
            _plan([_round_config(["theorist", "devil"])]),
        )

        # max_exchanges=3 → 6 発言 + 1 結論
        assert len(round_log.public_utterances) == 7
        speakers = [u.speaker for u in round_log.public_utterances]
        # 2 者が交互 + 結論は speakers[0]
        assert set(speakers) == {"theorist", "devil"}
        # 結論前の 6 発言は隣接同士が異なる
        for prev, curr in zip(speakers[:6], speakers[1:6]):
            assert prev != curr


# ---------------------------------------------------------------------------
# run_round: free_talk
# ---------------------------------------------------------------------------


class TestRunRoundFreeTalk:
    @pytest.mark.asyncio
    async def test_free_talk_uses_dynamic_order(self, tmp_path: Path) -> None:
        """DynamicOrder の API 応答に従って次発言者が選ばれる。

        max_utterances=8 の各回で API が "a" または "b" を返すように設定する。
        さらに 4 発言ごとに堂々巡りチェックが入るため、追加で False 応答を仕込む。
        """
        agents = {"a": FakeAgent("a"), "b": FakeAgent("b")}
        # 8 回の next-speaker 応答 (a と b を交互に)
        responses = [
            {"content": "a"},
            {"content": "b"},
            {"content": "a"},
            {"content": "b"},
            {"content": "a"},
            {"content": "b"},
            {"content": "a"},
            {"content": "b"},
        ]
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            extra_responses=responses,
            repetition_result=RepetitionResult(is_repeating=False),
        )

        round_config = _round_config(["a", "b"], pattern="free_talk")
        round_log = await conductor.run_round(
            round_config, _plan([round_config])
        )

        # max_utterances=8 + 1 結論
        assert 1 <= len(round_log.public_utterances) <= 9
        speakers = [u.speaker for u in round_log.public_utterances]
        # 結論前の発言で同じ AI が 3 回以上連続することはない
        discussion_speakers = speakers[:-1]  # 結論を除く
        for i in range(len(discussion_speakers) - 2):
            assert not (discussion_speakers[i] == discussion_speakers[i + 1] == discussion_speakers[i + 2])

    @pytest.mark.asyncio
    async def test_free_talk_injects_repetition_instruction(
        self, tmp_path: Path
    ) -> None:
        """4 発言目以降で堂々巡り検知が発火したら、追加指示が次の発言者に渡る。"""
        agents = {"a": FakeAgent("a"), "b": FakeAgent("b")}
        responses = [{"content": "a"}] * 12  # next-speaker をすべて a 返答
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            extra_responses=responses,
            repetition_result=RepetitionResult(
                is_repeating=True, repeated_topic="kの選び方"
            ),
        )
        round_config = _round_config(["a", "b"], pattern="free_talk")

        await conductor.run_round(round_config, _plan([round_config]))

        # 4 発言目 (index 4 のループ) で堂々巡り指示が渡る
        # FakeAgent は順番に instructions を蓄積
        all_instructions = []
        for ag in agents.values():
            all_instructions.extend(ag.received_instructions)
        repetition_messages = [
            inst for inst in all_instructions if "堂々巡り" in inst
        ]
        assert repetition_messages, "Repetition instruction should be injected"
        assert "kの選び方" in repetition_messages[0]


# ---------------------------------------------------------------------------
# run_discussion: 終了条件
# ---------------------------------------------------------------------------


class TestRunDiscussionTermination:
    @pytest.mark.asyncio
    async def test_runs_all_rounds_when_no_termination(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            convergence_results=[
                ConvergenceResult(score=0.3, recommendation="continue"),
                ConvergenceResult(score=0.4, recommendation="continue"),
                ConvergenceResult(score=0.5, recommendation="continue"),
            ],
        )

        log = await conductor.run_discussion(_plan(rounds))

        assert len(log.rounds) == 3
        assert log.early_termination is None
        assert log.score_history == [0.3, 0.4, 0.5]

    @pytest.mark.asyncio
    async def test_no_convergence_termination_runs_all_rounds(
        self, tmp_path: Path
    ) -> None:
        """収束判定による早期終了は無効化済み。全ラウンド完走する。"""
        agents = {"a": FakeAgent("a")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            convergence_results=[
                ConvergenceResult(score=0.3, recommendation="continue"),
                ConvergenceResult(score=0.9, recommendation="continue"),  # 閾値超えても続行
                ConvergenceResult(score=0.5, recommendation="continue"),
            ],
        )

        log = await conductor.run_discussion(_plan(rounds))

        assert len(log.rounds) == 3
        assert log.early_termination is None
        assert log.final_convergence_score == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_conclude_recommendation_does_not_terminate(
        self, tmp_path: Path
    ) -> None:
        """conclude recommendation でも早期終了しない。"""
        agents = {"a": FakeAgent("a")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            convergence_results=[
                ConvergenceResult(score=0.5, recommendation="conclude"),
                ConvergenceResult(score=0.6, recommendation="continue"),
                ConvergenceResult(score=0.7, recommendation="continue"),
            ],
        )

        log = await conductor.run_discussion(_plan(rounds))

        assert len(log.rounds) == 3
        assert log.early_termination is None


# ---------------------------------------------------------------------------
# _handle_time_pressure / 時間切れ
# ---------------------------------------------------------------------------


class TestHandleTimePressure:
    @pytest.mark.asyncio
    async def test_critical_pressure_terminates_discussion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``time_keeper.force_conclude`` が True なら即座に終了する。"""
        agents = {"a": FakeAgent("a")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]

        # 時間切れの TimeKeeper を仕込む (budget=0)
        keeper = TimeKeeper(time_limit_sec=10.0, phase3_reserve_sec=100.0)
        conductor, _, _, _ = _make_conductor(
            tmp_path, agents, time_keeper=keeper
        )

        log = await conductor.run_discussion(_plan(rounds))

        assert log.early_termination == "time_limit"
        assert log.rounds == []

    def test_relaxed_pressure_returns_continue(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)
        # デフォルトの 600 秒制限 + 開始直後 → RELAXED
        assert conductor._handle_time_pressure(estimated_round_sec=30.0) == "continue"


# ---------------------------------------------------------------------------
# _handle_early_convergence
# ---------------------------------------------------------------------------


class TestHandleEarlyConvergence:
    @pytest.mark.asyncio
    async def test_terminate_when_threshold_met(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        result = ConvergenceResult(score=0.85, recommendation="continue")
        action = await conductor._handle_early_convergence(result, threshold=0.8)
        assert action == "terminate"

    @pytest.mark.asyncio
    async def test_pivot_when_recommendation_is_pivot(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        result = ConvergenceResult(score=0.5, recommendation="pivot")
        action = await conductor._handle_early_convergence(result, threshold=0.8)
        assert action == "pivot"

    @pytest.mark.asyncio
    async def test_pivot_when_stagnating(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, checker = _make_conductor(tmp_path, agents)

        # 履歴を停滞状態にする
        checker.score_history = [0.50, 0.51, 0.52]

        result = ConvergenceResult(score=0.52, recommendation="continue")
        action = await conductor._handle_early_convergence(result, threshold=0.8)
        assert action == "pivot"

    @pytest.mark.asyncio
    async def test_continue_otherwise(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        result = ConvergenceResult(score=0.4, recommendation="continue")
        action = await conductor._handle_early_convergence(result, threshold=0.8)
        assert action == "continue"


# ---------------------------------------------------------------------------
# _handle_stagnation: pivot 指示生成
# ---------------------------------------------------------------------------


class TestHandleStagnation:
    @pytest.mark.asyncio
    async def test_generates_pivot_instruction(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, mock, memory, _ = _make_conductor(
            tmp_path,
            agents,
            extra_responses=[{"content": "別の角度から検討してください"}],
        )

        result = ConvergenceResult(
            score=0.5,
            recommendation="pivot",
            remaining_disagreements=["k の選び方"],
        )
        instruction = await conductor._handle_stagnation(result)

        assert instruction == "別の角度から検討してください"
        # memory にシステムイベントが記録される
        events = [e for e in memory._system_events if "pivot" in e["event"]]
        assert events


class TestPivotInstructionInjection:
    @pytest.mark.asyncio
    async def test_pivot_instruction_injected_into_next_round(
        self, tmp_path: Path
    ) -> None:
        """pivot 後の次ラウンドの最初の発言者に指示が渡る。"""
        agents = {"a": FakeAgent("a"), "b": FakeAgent("b")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]

        # 1 ラウンド目で pivot 推奨 → 2 ラウンド目に指示注入
        conductor, _, _, _ = _make_conductor(
            tmp_path,
            agents,
            convergence_results=[
                ConvergenceResult(score=0.4, recommendation="pivot"),
                ConvergenceResult(score=0.5, recommendation="continue"),
                ConvergenceResult(score=0.6, recommendation="continue"),
            ],
            extra_responses=[{"content": "PIVOT_INSTRUCTION_TEST"}],
        )

        await conductor.run_discussion(_plan(rounds))

        # ラウンド 2 の最初の発言者 (a) に PIVOT_INSTRUCTION_TEST が渡る
        # FakeAgent は呼ばれるたびに instructions を蓄積
        a_instructions = agents["a"].received_instructions
        assert any("PIVOT_INSTRUCTION_TEST" in inst for inst in a_instructions)


# ---------------------------------------------------------------------------
# 不正パターン / フォールバック
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_unknown_pattern_falls_back_to_one_shot(
        self, tmp_path: Path
    ) -> None:
        agents = {"a": FakeAgent("a"), "b": FakeAgent("b")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        round_config = _round_config(["a", "b"], pattern="weird_pattern")
        round_log = await conductor.run_round(
            round_config, _plan([round_config])
        )

        # one_shot 相当 → 各 agent 1 回ずつ + 結論 (speakers[0] = "a")
        assert len(round_log.public_utterances) == 3

    @pytest.mark.asyncio
    async def test_missing_agent_is_skipped(self, tmp_path: Path) -> None:
        """``round_config.speakers`` に未登録の agent_id があってもスキップして続行。"""
        agents = {"a": FakeAgent("a")}  # b は未登録
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        round_config = _round_config(["a", "b"], pattern="one_shot")
        round_log = await conductor.run_round(
            round_config, _plan([round_config])
        )

        # a のみ発言 + 結論 (speakers[0]="a")
        assert len(round_log.public_utterances) == 2
        assert round_log.public_utterances[0].speaker == "a"
        assert round_log.public_utterances[1].speaker == "a"

    @pytest.mark.asyncio
    async def test_empty_plan_returns_empty_log(self, tmp_path: Path) -> None:
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)

        plan = OrchestraPlan(
            odsc=ODSC(
                objective="o",
                deliverable="d",
                success_criteria="s",
                convergence_threshold=0.8,
            ),
            discussion_plan=DiscussionPlan(estimated_rounds=0),
        )

        log = await conductor.run_discussion(plan)

        assert log.rounds == []
        assert log.early_termination is None


# ---------------------------------------------------------------------------
# プロンプト / 定数
# ---------------------------------------------------------------------------


class TestPromptConstants:
    def test_pivot_prompt_has_required_placeholders(self) -> None:
        assert "{recent_scores}" in PIVOT_PROMPT
        assert "{disagreements}" in PIVOT_PROMPT

    def test_force_new_topic_has_repeated_topic_placeholder(self) -> None:
        assert "{repeated_topic}" in FORCE_NEW_TOPIC_INSTRUCTION

    def test_excessive_agreement_is_non_empty(self) -> None:
        assert "あえて反対の立場" in EXCESSIVE_AGREEMENT_INSTRUCTION

    def test_round_conclusion_asks_for_next_topic(self) -> None:
        """非最終ラウンドの結論テンプレートは【次論点】を要求する。"""
        from core.conductor import ROUND_CONCLUSION_INSTRUCTION
        assert "【次論点】" in ROUND_CONCLUSION_INSTRUCTION
        assert "{round_goal}" in ROUND_CONCLUSION_INSTRUCTION

    def test_final_round_conclusion_forbids_next_topic(self) -> None:
        """最終ラウンドの結論テンプレートは【次論点】を書かせない。"""
        from core.conductor import FINAL_ROUND_CONCLUSION_INSTRUCTION
        assert "【最終結論】" in FINAL_ROUND_CONCLUSION_INSTRUCTION
        # 「次論点」の禁止指示が含まれる
        assert "次論点" in FINAL_ROUND_CONCLUSION_INSTRUCTION
        assert "書かない" in FINAL_ROUND_CONCLUSION_INSTRUCTION


class TestFinalRoundConclusion:
    """``is_final_round`` フラグに応じて結論指示テンプレートが切り替わる。"""

    @pytest.mark.asyncio
    async def test_non_final_round_uses_next_topic_template(
        self, tmp_path: Path,
    ) -> None:
        """デフォルト (is_final_round=False) では【次論点】を要求。"""
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)
        rc = _round_config(["a"])

        await conductor.run_round(rc, _plan([rc]), is_final_round=False)

        # 主導者 (a) は 2 回呼ばれる (発言 + 結論)、結論指示に【次論点】を含む
        conclusion_instruction = agents["a"].received_instructions[-1]
        assert "【次論点】" in conclusion_instruction

    @pytest.mark.asyncio
    async def test_final_round_uses_final_template(
        self, tmp_path: Path,
    ) -> None:
        """is_final_round=True では【最終結論】+ 次論点禁止の指示を渡す。"""
        agents = {"a": FakeAgent("a")}
        conductor, _, _, _ = _make_conductor(tmp_path, agents)
        rc = _round_config(["a"])

        await conductor.run_round(rc, _plan([rc]), is_final_round=True)

        conclusion_instruction = agents["a"].received_instructions[-1]
        assert "【最終結論】" in conclusion_instruction
        assert "書かない" in conclusion_instruction

    @pytest.mark.asyncio
    async def test_run_discussion_marks_last_planned_round_as_final(
        self, tmp_path: Path,
    ) -> None:
        """bonus round 無効時、計画の最終ラウンドを is_final=True で実行する。"""
        agents = {"a": FakeAgent("a")}
        rounds = [_round_config(["a"], round_num=i + 1) for i in range(3)]
        conductor, _, _, _ = _make_conductor(
            tmp_path, agents,
            convergence_results=[
                ConvergenceResult(score=0.3, recommendation="continue")
            ] * 3,
        )
        # enable_bonus_rounds=False は _make_conductor のデフォルト

        await conductor.run_discussion(_plan(rounds))

        # 各ラウンドで a は 2 回呼ばれる (発言 + 結論) → 合計 6 回
        assert agents["a"].call_count == 6
        # 最後の呼び出し (=Round 3 結論) には【最終結論】が含まれる
        assert "【最終結論】" in agents["a"].received_instructions[-1]
        # Round 1, 2 の結論には【次論点】が含まれる (呼び出し index 1, 3)
        assert "【次論点】" in agents["a"].received_instructions[1]
        assert "【次論点】" in agents["a"].received_instructions[3]


class TestTimeKeeperIntegration:
    """依頼① 時間管理: TimeKeeper と Conductor の連携。"""

    @pytest.mark.asyncio
    async def test_time_keeper_start_before_phase1_gives_correct_remaining(
        self,
    ) -> None:
        """TimeKeeper 生成 (Phase 1 開始前) → Phase 2 開始時に remaining が
        discussion_budget と一致する (負値を引かない)。
        """
        # Arrange: start_time = 現在時刻 で TimeKeeper 生成
        keeper = TimeKeeper(
            time_limit_sec=180.0,
            phase3_reserve_sec=15.0,
            safety_margin=0.9,
        )
        # budget = 180 * 0.9 - 0 - 15 = 147

        # Act: Phase 1 (計画) が 20 秒経過したとみなす
        # phase1_actual_sec を後から書き込む
        keeper.phase1_actual_sec = 20.0
        # advance 20 秒 (Phase 1 経過をシミュレート)
        import time as _time

        original_time = _time.time
        try:
            _time.time = lambda: original_time() + 20.0  # noqa: E731
            # Phase 2 開始時: elapsed = 20, discussion_elapsed = 0
            # remaining = 147 - 0 = 147
            # budget も 180*0.9 - 20 - 15 = 127 に変わる
            # つまり remaining = 127 - 0 = 127 (負値の -20 は引かれない)
            assert keeper.discussion_budget == pytest.approx(127.0)
            assert keeper.remaining == pytest.approx(127.0)
        finally:
            _time.time = original_time



class TestNoIntervention:
    def test_check_intervention_always_none(self) -> None:
        no_int = NoIntervention()
        assert no_int.check_intervention(1, {}) is None

    def test_notify_progress_is_noop(self) -> None:
        # 呼んでも例外を出さない
        NoIntervention().notify_progress("event", {"k": "v"})
