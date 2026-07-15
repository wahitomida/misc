"""Phase 2: 議論の進行管理を担う Conductor。

設計書: ``doc/05_conductor.md`` 全体, ``doc/10_turn_management.md`` §10.4

責務:
    - 各ラウンドの実行 (one_shot / ping_pong / free_talk)
    - 収束判定・堂々巡り検知・同意検知の起動
    - 時間圧力に応じた打ち切り / level 低減
    - 早期収束・停滞に応じた pivot 指示

外部依存 (D-3 以降で詳細化):
    - 介入ハンドラ ``InterventionHandler``: v1.0 は ``NoIntervention``
    - 表示ハンドラ: 任意。``None`` なら logging のみ
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from .convergence import (
    AgreementDetector,
    ConvergenceChecker,
    DEFAULT_AGREEMENT_WINDOW,
    DEFAULT_REPETITION_WINDOW,
    RepetitionDetector,
)
from .data_models import (
    ConvergenceResult,
    DiscussionLog,
    OrchestraPlan,
    RepetitionResult,
    RoundConfig,
    RoundLog,
    Utterance,
)
from .intervention import InterventionHandler, NoIntervention
from .speaking_order import DialecticOrder, DynamicOrder, FixedOrder
from .time_keeper import TimeKeeper, TimePressure
from .turn_calculator import TurnCalculator

if TYPE_CHECKING:
    from .agent import Agent
    from .api_client import ResilientAPIClient
    from .config_loader import Settings
    from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# プロンプト定数と関連 hyperparameter (モジュール分離済み)
# 外部互換のため ``from core.conductor import ROUND_CONCLUSION_INSTRUCTION`` なども
# 引き続き参照可能 (下記 import で再エクスポート)。
# ----------------------------------------------------------------------
from .conductor_prompts import (
    BONUS_ROUND_GOAL_PROMPT,
    BONUS_ROUND_GOAL_TEMPERATURE,
    BONUS_ROUND_GOAL_MAX_TOKENS,
    BONUS_ROUND_PHASE_PREFIX,
    PIVOT_PROMPT,
    PIVOT_PROMPT_TEMPERATURE,
    PIVOT_PROMPT_MAX_TOKENS,
    FORCE_NEW_TOPIC_INSTRUCTION,
    EXCESSIVE_AGREEMENT_INSTRUCTION,
    ROUND_CONCLUSION_INSTRUCTION,
    FINAL_ROUND_CONCLUSION_INSTRUCTION,
    GOAL_COMPLETION_CHECK_PROMPT,
    GOAL_COMPLETION_REQUEST_INSTRUCTION,
    GOAL_COMPLETION_CHECK_MAX_TOKENS,
    GOAL_COMPLETION_CHECK_TEMPERATURE,
    NARROWING_CHECK_PROMPT,
    NARROWING_CHECK_TEMPERATURE,
    NARROWING_CHECK_MAX_TOKENS,
    NARROWING_PIVOT_INSTRUCTION,
)

# Constants (定数のうち、プロンプト以外のものはここに残す)
DEFAULT_CONDUCTOR_MODEL = "gpt-4.1"

# 指揮者 (Conductor) のフロント表示用定数
CONDUCTOR_ROLE_ID = "orchestrator"
CONDUCTOR_EMOJI = "🎼"
CONDUCTOR_NAME = "指揮者"

PING_PONG_DEFAULT_EXCHANGES = 3
FREE_TALK_DEFAULT_MAX = 8
DEFAULT_REPETITION_CHECK_INTERVAL = 3
CONSECUTIVE_SAME_SPEAKER_LIMIT = 2

# Bonus round (全ラウンド完了後に時間が余っている場合の追加ラウンド)
BONUS_ROUND_MIN_REMAINING_SEC = 30.0  # これより上なら bonus round を実行
BONUS_ROUND_MAX_COUNT = 3             # 一セッションでの追加ラウンド上限


# ----------------------------------------------------------------------
# Conductor
# ----------------------------------------------------------------------


class Conductor:
    """議論進行を司る Conductor。

    Attributes:
        api_client: 軽量モデル用 API クライアント。
        agents: ``role_id`` → ``Agent`` のマッピング。
        memory: 共有会話メモリ。
        time_keeper: 時間管理。
        intervention: 介入ハンドラ。
        settings: 全体設定。
        model: Conductor 自身の処理に使うモデル。
        convergence_checker / repetition_detector / agreement_detector:
            検知器群。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        agents: dict[str, "Agent"],
        memory: "ConversationMemory",
        time_keeper: TimeKeeper,
        settings: "Settings",
        intervention: InterventionHandler | None = None,
        model: str = DEFAULT_CONDUCTOR_MODEL,
        convergence_checker: ConvergenceChecker | None = None,
        repetition_detector: RepetitionDetector | None = None,
        agreement_detector: AgreementDetector | None = None,
        turn_calculator: TurnCalculator | None = None,
        enable_bonus_rounds: bool = True,
    ) -> None:
        self.api_client = api_client
        self.agents = agents
        self.memory = memory
        self.time_keeper = time_keeper
        self.intervention = intervention or NoIntervention()
        self.settings = settings
        self.model = model
        # bonus round は本番デフォルト有効。テストや履歴復元時に無効化可能。
        self.enable_bonus_rounds = enable_bonus_rounds

        self.convergence_checker = convergence_checker or ConvergenceChecker(
            api_client, model=model
        )
        self.repetition_detector = repetition_detector or RepetitionDetector(
            api_client, model=model
        )
        self.agreement_detector = agreement_detector or AgreementDetector(
            api_client, model=model
        )
        self.turn_calculator = turn_calculator or TurnCalculator(settings=settings)

        self._pivot_instruction: str = ""  # 次ラウンドに注入する pivot 指示

    # ------------------------------------------------------------------
    # 内部ヘルパー: SSE 進捗通知
    # ------------------------------------------------------------------

    def _notify(self, event: str, data: dict[str, Any] | None = None) -> None:
        """intervention.notify_progress を安全に呼び出す (例外は握りつぶす)。"""
        try:
            self.intervention.notify_progress(event, data or {})
            logger.debug("conductor notify: %s", event)
        except Exception as e:  # noqa: BLE001
            logger.debug("notify_progress(%s) failed: %s", event, e)

    def _agent_display_info(self, role_id: str) -> dict[str, str]:
        """役割 ID から SSE 用の {role_id, emoji, name} を組み立てる。

        Agent.display_name は "🧮 理論屋" のような形式なので分割する。
        指揮者 (``CONDUCTOR_ROLE_ID``) は他のロールとは別のアイコンを使用する。
        """
        if role_id == CONDUCTOR_ROLE_ID:
            return {
                "role_id": CONDUCTOR_ROLE_ID,
                "emoji": CONDUCTOR_EMOJI,
                "name": CONDUCTOR_NAME,
            }
        agent = self.agents.get(role_id)
        if agent is None:
            return {"role_id": role_id, "emoji": "🎭", "name": role_id}
        display = getattr(agent, "display_name", role_id) or role_id
        parts = display.split(None, 1)
        if len(parts) == 2:
            return {"role_id": role_id, "emoji": parts[0], "name": parts[1]}
        return {"role_id": role_id, "emoji": "🎭", "name": display}

    def _utterance_payload(self, u: "Utterance", round_num: int) -> dict[str, Any]:
        """Utterance を SSE utterance イベント用の dict に変換する。"""
        # tokens は {"prompt", "completion", "total"} 形式か整数の可能性
        tokens_dict = getattr(u, "tokens_used", None) or {}
        if isinstance(tokens_dict, dict):
            tokens = int(tokens_dict.get("total") or 0)
        else:
            try:
                tokens = int(tokens_dict)
            except (TypeError, ValueError):
                tokens = 0
        return {
            "agent": self._agent_display_info(getattr(u, "speaker", "")),
            "content": getattr(u, "content", ""),
            "round": round_num,
            "tokens": tokens,
            "duration_sec": float(getattr(u, "duration_sec", 0.0) or 0.0),
        }

    def _build_kickoff_briefing_text(self, plan: OrchestraPlan) -> str:
        """指揮者が議論開始前に述べる計画ブリーフィングを組み立てる。

        Phase 2 で確定した ODSC・参加者・ラウンド構成を読み上げ、
        最後に「では、開始してください」で締める決定論的テキストを返す。
        """
        lines: list[str] = []
        lines.append("それではこれより議論を始めます。まず本セッションの計画を確認します。")
        lines.append("")
        if plan.odsc.objective:
            lines.append(f"【議題 / Objective】{plan.odsc.objective}")
        if plan.odsc.deliverable:
            lines.append(f"【成果物 / Deliverable】{plan.odsc.deliverable}")
        if plan.odsc.success_criteria:
            lines.append(f"【成功基準 / Success Criteria】{plan.odsc.success_criteria}")

        if plan.selected_agents:
            lines.append("")
            lines.append("【参加者と期待】")
            for agent_cfg in plan.selected_agents:
                info = self._agent_display_info(agent_cfg.role_id)
                expectation = (
                    agent_cfg.expected_contribution
                    or agent_cfg.reason
                    or ""
                ).strip()
                suffix = f" — {expectation}" if expectation else ""
                lines.append(f"- {info['emoji']} {info['name']}{suffix}")

        if plan.discussion_plan and plan.discussion_plan.round_config:
            lines.append("")
            lines.append("【ラウンド構成】")
            for rc in plan.discussion_plan.round_config:
                speaker_names = ", ".join(
                    self._agent_display_info(s)["name"] for s in rc.speakers
                ) or "-"
                lines.append(
                    f"- Round {rc.round}: {rc.phase_name} "
                    f"({rc.pattern}, 目安 {int(rc.time_budget_sec)}秒) "
                    f"→ {rc.goal} [発言: {speaker_names}]"
                )
            total_sec = int(plan.discussion_plan.total_estimated_time_sec)
            if total_sec > 0:
                lines.append(f"（推定合計時間: 約 {total_sec} 秒）")

        lines.append("")
        lines.append("以上の計画に沿って進行します。では、開始してください。")
        return "\n".join(lines)

    def _notify_kickoff_briefing(self, plan: OrchestraPlan) -> None:
        """指揮者ブリーフィングを SSE utterance として送信する。"""
        try:
            content = self._build_kickoff_briefing_text(plan)
        except Exception as e:  # noqa: BLE001
            logger.debug("kickoff briefing text build failed: %s", e)
            return
        payload = {
            "agent": {
                "role_id": CONDUCTOR_ROLE_ID,
                "emoji": CONDUCTOR_EMOJI,
                "name": CONDUCTOR_NAME,
            },
            "content": content,
            "round": 0,
            "tokens": 0,
            "duration_sec": 0.0,
        }
        self._notify("utterance", payload)

    # ------------------------------------------------------------------
    # public: run_discussion / run_round
    # ------------------------------------------------------------------

    async def run_discussion(self, plan: OrchestraPlan) -> DiscussionLog:
        """計画に基づいて議論全体を進行する。

        Args:
            plan: ``Orchestrator.plan()`` の出力。

        Returns:
            ``DiscussionLog``。早期終了時は ``early_termination`` が設定される。
        """
        discussion_log = DiscussionLog()
        if plan.discussion_plan is None or not plan.discussion_plan.round_config:
            logger.warning("Plan has no rounds; returning empty DiscussionLog")
            return discussion_log

        threshold = plan.odsc.convergence_threshold

        # SSE: 議論開始を通知 (フロントの progress ハンドラが
        # totalRounds をセットし、タイマー進行年に使う)
        self._notify("progress", {
            "total_rounds": len(plan.discussion_plan.round_config),
            "remaining_sec": float(self.time_keeper.remaining),
        })

        # 指揮者によるキックオフ・ブリーフィング
        # (計画した ODSC / 参加者 / ラウンド構成を先に受講し、
        #  「では、開始してください」で実際のラウンド実行へ移行)
        self._notify_kickoff_briefing(plan)

        for index, round_config in enumerate(plan.discussion_plan.round_config):
            # 時間圧力チェック (ラウンド開始前)
            estimated = self._estimate_round_time(round_config)
            time_action = self._handle_time_pressure(estimated)
            if time_action == "terminate":
                discussion_log.early_termination = "time_limit"
                discussion_log.termination_detail = (
                    f"Round {round_config.round}: 残り{self.time_keeper.remaining:.0f}s, "
                    f"推定{estimated:.0f}s で開始不能"
                )
                break

            # ラウンド実行 (bonus round が有効ならここでは is_final は False。
            # bonus round が無い場合は計画の最後のラウンド = 最終)。
            is_final = (
                (index == len(plan.discussion_plan.round_config) - 1)
                and not self.enable_bonus_rounds
            )
            round_log = await self.run_round(round_config, plan, is_final_round=is_final)
            discussion_log.rounds.append(round_log)
            self.time_keeper.record_round(round_log.duration_sec)

            # 収束判定の結果に基づいて次アクションを決定
            # ※収束による早期終了は無効化済み。時間制限まで議論を継続する。
            #   スコア記録と pivot (方向転換) 指示のみ維持。
            if round_log.convergence_check is not None:
                discussion_log.score_history.append(round_log.convergence_check.score)
                discussion_log.final_convergence_score = round_log.convergence_check.score

                action = await self._handle_early_convergence(
                    round_log.convergence_check, threshold
                )
                if action == "pivot":
                    self._pivot_instruction = await self._handle_stagnation(
                        round_log.convergence_check
                    )

            # 狭まりすぎ検知 (問題1D対策) — 計画上の最終ラウンドでは skip
            # (bonus round は enable フラグと時間残次第で別途起動)
            is_planned_final = (
                index == len(plan.discussion_plan.round_config) - 1
            )
            if not is_planned_final:
                narrowing_pivot = await self._detect_narrowing(round_log, plan)
                if narrowing_pivot:
                    # 既存 pivot と組み合わせて次ラウンドに注入
                    combined = (
                        f"{narrowing_pivot}\n\n{self._pivot_instruction}"
                        if self._pivot_instruction
                        else narrowing_pivot
                    )
                    self._pivot_instruction = combined.strip()

        # 全計画ラウンド完了後、時間が余っていれば bonus round を追加
        # (ユーザーが指定した時間を使い切るためのセーフティネット)
        if self.enable_bonus_rounds:
            await self._run_bonus_rounds_if_time_remains(plan, discussion_log)

        return discussion_log

    async def run_round(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        is_final_round: bool = False,
    ) -> RoundLog:
        """1 ラウンドを実行し、``RoundLog`` を返す。

        Args:
            round_config: ラウンド設定。
            plan: 全体計画。
            is_final_round: このラウンドがセッション最終なら True。
                True の場合はラウンド末尾の結論で「次論点」を含めない。
        """
        round_start = time.time()
        additional_instruction = self._consume_pivot_instruction()

        # 禁止例リストを前ラウンド発言から抽出 (問題2対策)。
        # キャッシュに入り Agent の ``get_context_for_agent`` が取り得るようにする。
        try:
            await self.memory.extract_forbidden_examples(
                round_config.round,
                model=getattr(self, "_default_model", None) or self.convergence_checker.model,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("extract_forbidden_examples failed: %s", e)

        # SSE: ラウンド開始 (フロントが round_divider を描画 + 発言者を thinking に)
        self._notify("round_start", {
            "round": round_config.round,
            "config": {
                "round": round_config.round,
                "phase": round_config.phase_name,
                "pattern": round_config.pattern,
                "speakers": list(round_config.speakers),
                "goal": round_config.goal,
                "topic": round_config.goal,
                "time_budget_sec": round_config.time_budget_sec,
            },
        })

        utterances = await self._dispatch_pattern(
            round_config, plan, additional_instruction
        )

        # ラウンド末尾の結論: 主導者 (speakers[0]) が他者の意見を踏まえて結論を出す
        conclusion = await self._run_round_conclusion(
            round_config, plan, utterances, is_final_round=is_final_round,
        )
        if conclusion is not None:
            utterances.append(conclusion)

        # 問題5対策: goal 達成度チェック + 未達なら leader に補足発言を1回要求
        supplement = await self._check_and_complete_goal(
            round_config, plan, utterances
        )
        if supplement is not None:
            utterances.append(supplement)

        round_log = RoundLog(
            round=round_config.round,
            duration_sec=time.time() - round_start,
            phase_name=round_config.phase_name,
            goal=round_config.goal,
            public_utterances=utterances,
        )

        # 収束判定
        round_log.convergence_check = await self.convergence_checker.check(
            round_log, plan, self.memory
        )

        # SSE: ラウンド完了を通知 (フロントの stats.convergence 更新)
        convergence_score = None
        if round_log.convergence_check is not None:
            convergence_score = round_log.convergence_check.score
            self._notify("convergence_check", {"score": float(convergence_score)})
        self._notify("round_end", {
            "round": round_config.round,
            "elapsed_sec": round_log.duration_sec,
            "convergence": (
                float(convergence_score) if convergence_score is not None else 0.0
            ),
        })

        return round_log

    # ------------------------------------------------------------------
    # ラウンド実装
    # ------------------------------------------------------------------

    async def _run_one_shot(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        additional_instruction: str,
    ) -> list[Utterance]:
        """各 AI が固定順で 1 回ずつ発言する。

        ``additional_instruction`` は pivot / 狭まり採知などのラウンド
        全体に影響する指示を想定しており、全 speaker に同じ内容を渡す。
        (問題 P2-A: 2 人目以降が pivot を無視して元の論点に戻るのを防ぐ)

        speakers が 4 名以上の場合、半数発言後に 1 度だけ中盤 narrowing 判定を
        呼び、狭まっていれば残りの speaker に視野拡大指示を追加注入する
        (問題 P2-B: ラウンド後半で既に狭まっている状況への対処)。
        """
        order = FixedOrder().get_speaking_order(
            round_config.speakers, round_config, context={}
        )
        utterances: list[Utterance] = []
        midround_check_idx = len(order) // 2 if len(order) >= 4 else -1
        midround_pivot_done = False

        for sequence, speaker_id in enumerate(order, start=1):
            # 半数発言後の中盤 narrowing 判定 (1 度だけ)
            if (
                not midround_pivot_done
                and midround_check_idx > 0
                and len(utterances) >= midround_check_idx
            ):
                midround_pivot_done = True
                extra = await self._detect_narrowing_midround(utterances, plan)
                if extra:
                    additional_instruction = (
                        f"{extra}\n\n{additional_instruction}".strip()
                        if additional_instruction
                        else extra
                    )

            agent = self._get_agent(speaker_id)
            if agent is None:
                continue
            context = self._build_round_context(
                round_config, plan, utterances, sequence,
                speaker_role_id=speaker_id,
            )
            utterance = await agent.speak(
                context,
                additional_instruction=additional_instruction,
            )
            utterances.append(utterance)
            self.memory.add_utterance(utterance, round_config.round)
            self._notify("utterance", self._utterance_payload(utterance, round_config.round))
        return utterances

    async def _run_ping_pong(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        additional_instruction: str,
        max_exchanges: int = PING_PONG_DEFAULT_EXCHANGES,
    ) -> list[Utterance]:
        """2 者を ``max_exchanges`` 回交互に応答させる。

        ``additional_instruction`` (pivot 系) は全 speaker に同内容を渡す。
        """
        order = DialecticOrder(max_exchanges=max_exchanges).get_speaking_order(
            round_config.speakers, round_config, context={}
        )
        utterances: list[Utterance] = []
        for sequence, speaker_id in enumerate(order, start=1):
            agent = self._get_agent(speaker_id)
            if agent is None:
                continue
            context = self._build_round_context(
                round_config, plan, utterances, sequence,
                speaker_role_id=speaker_id,
            )
            utterance = await agent.speak(
                context,
                additional_instruction=additional_instruction,
            )
            utterances.append(utterance)
            self.memory.add_utterance(utterance, round_config.round)
            self._notify("utterance", self._utterance_payload(utterance, round_config.round))
        return utterances

    async def _run_free_talk(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        additional_instruction: str,
        max_utterances: int = FREE_TALK_DEFAULT_MAX,
    ) -> list[Utterance]:
        """Conductor が動的に次発言者を決定する。

        ``additional_instruction`` (pivot 系) は base_pivot として全発言に注入する。
        (問題 P2-A: 2 人目以降が pivot を無視するのを防ぐ)
        1 発言ごとに handoff / 堂々巡り検知の追加指示を上乗せする。
        """
        base_pivot = additional_instruction  # ラウンド中は消費しない
        dynamic = DynamicOrder(self.api_client, model=self.model)
        utterances: list[Utterance] = []
        counts: dict[str, int] = {s: 0 for s in round_config.speakers}
        last_speaker: str | None = None
        consecutive_same = 0

        for i in range(max_utterances):
            # 発言毎に時間切れをチェック (free_talk は最大 8 発言と長いため、
            # ラウンド途中で時間超過が起こり得る)。
            if self.time_keeper.force_conclude():
                logger.info(
                    "free_talk: time budget exhausted at utterance %d; stopping",
                    i,
                )
                break

            decision = await dynamic.decide_next_speaker_with_handoff(
                speakers=round_config.speakers,
                utterances=utterances,
                utterance_counts=counts,
                round_goal=round_config.goal,
            )
            next_speaker = decision.role_id
            handoff_for_this = decision.handoff_prompt

            # 同じ AI の連続発言を防ぐ
            if next_speaker == last_speaker:
                consecutive_same += 1
                if consecutive_same >= CONSECUTIVE_SAME_SPEAKER_LIMIT:
                    alternatives = [
                        s for s in round_config.speakers if s != next_speaker
                    ]
                    if alternatives:
                        next_speaker = alternatives[0]
                        handoff_for_this = ""  # 発言者を差し替えたので振りは無効化
                    consecutive_same = 0
            else:
                consecutive_same = 0

            agent = self._get_agent(next_speaker)
            if agent is None:
                continue

            context = self._build_round_context(
                round_config, plan, utterances, sequence=i + 1,
                speaker_role_id=next_speaker,
            )

            # base_pivot を土台に、handoff / 堂々巡り指示を上乗せする
            instruction_parts: list[str] = []

            # 一定間隔で堂々巡りチェック (settings.round_utterances 経由で調整可)
            repetition_interval = self._get_repetition_check_interval()
            repetition_triggered = False
            if i > 0 and i % repetition_interval == 0:
                rep_result = await self.repetition_detector.check_repetition(
                    utterances
                )
                if rep_result.is_repeating:
                    repetition_triggered = True
                    instruction_parts.append(
                        self._build_repetition_instruction(rep_result)
                    )

            # 同意過多チェック (P4: AgreementDetector 有効化)
            # Repetition と同タイミングだが、Repetition が真なら優先して skip
            if (
                not repetition_triggered
                and i > 0
                and i % repetition_interval == 0
            ):
                try:
                    if await self.agreement_detector.check_excessive_agreement(
                        utterances
                    ):
                        instruction_parts.append(EXCESSIVE_AGREEMENT_INSTRUCTION)
                except Exception as e:  # noqa: BLE001
                    logger.debug("agreement detection failed: %s", e)

            # 「振り」文言 (per-utterance)
            if handoff_for_this:
                instruction_parts.append(f"【指揮者からの振り】{handoff_for_this}")

            # base pivot は毎発言に注入 (最下位に置いてラウンド共通の視野を維持)
            if base_pivot:
                instruction_parts.append(base_pivot)

            instruction_for_this = "\n\n".join(instruction_parts)

            utterance = await agent.speak(
                context,
                additional_instruction=instruction_for_this,
            )
            utterances.append(utterance)
            self.memory.add_utterance(utterance, round_config.round)
            self._notify("utterance", self._utterance_payload(utterance, round_config.round))
            counts[next_speaker] = counts.get(next_speaker, 0) + 1
            last_speaker = next_speaker

        return utterances

    # ------------------------------------------------------------------
    # pattern dispatch (one_shot / ping_pong / free_talk)
    # ------------------------------------------------------------------

    async def _dispatch_pattern(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        additional_instruction: str,
    ) -> list[Utterance]:
        """``round_config.pattern`` に応じて対応する ``_run_*`` を呼び出す。

        未知の pattern は ``one_shot`` にフォールバックする。
        """
        handlers = {
            "one_shot": self._run_one_shot,
            "ping_pong": self._run_ping_pong,
            "free_talk": self._run_free_talk,
        }
        handler = handlers.get(round_config.pattern)
        if handler is None:
            logger.warning(
                "Unknown round pattern %r; falling back to one_shot",
                round_config.pattern,
            )
            handler = self._run_one_shot
        return await handler(round_config, plan, additional_instruction)

    # ------------------------------------------------------------------
    # ラウンド末尾の結論
    # ------------------------------------------------------------------

    async def _run_round_conclusion(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        utterances: list[Utterance],
        is_final_round: bool = False,
    ) -> Utterance | None:
        """ラウンド末尾で主導者 (speakers[0]) に結論を出させる。

        他者の意見を踏まえた統合的なまとめを生成する。最終ラウンドでは
        「次論点」を含まないセッション全体の総括にする。

        Args:
            round_config: 現在ラウンドの設定。
            plan: 全体計画。
            utterances: そのラウンドのこれまでの発言。
            is_final_round: セッション最終ラウンドなら True。

        Returns:
            結論発言の ``Utterance``。主導者が解決できない場合は ``None``。
        """
        if not round_config.speakers:
            return None
        leader_id = round_config.speakers[0]
        agent = self._get_agent(leader_id)
        if agent is None:
            return None

        template = (
            FINAL_ROUND_CONCLUSION_INSTRUCTION
            if is_final_round
            else ROUND_CONCLUSION_INSTRUCTION
        )
        instruction = template.format(
            objective=plan.odsc.objective or "(Objective未設定)",
            round_goal=round_config.goal or "(目標未設定)",
        )
        context = self._build_round_context(
            round_config, plan, utterances, sequence=len(utterances) + 1,
            speaker_role_id=leader_id,
        )

        utterance = await agent.speak(
            context,
            additional_instruction=instruction,
        )
        utterance.type = "conclusion"
        self.memory.add_utterance(utterance, round_config.round)

        # SSE: ラウンド結論を通知 (フロントは chatItem type='conclusion' で表示)
        info = self._agent_display_info(leader_id)
        self._notify("round_conclusion", {
            "round": round_config.round,
            "concluder_emoji": info["emoji"],
            "concluder_name": info["name"],
            "content": getattr(utterance, "content", ""),
        })

        return utterance

    # ------------------------------------------------------------------
    # goal 達成度チェック (問題5対策)
    # ------------------------------------------------------------------

    async def _check_and_complete_goal(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        utterances: list[Utterance],
    ) -> "Utterance | None":
        """ラウンド末尾で goal 達成度を判定し、未達なら leader に補足発言を要求する。

        LLM 呼び出しは最大 2 回 (判定 + 補足発言)。goal が空 or 判定不能の場合は
        追加発言なしで即 None を返す。

        Args:
            round_config: 現在ラウンドの設定。
            plan: 全体計画。
            utterances: 結論まで含めたラウンド全発言。

        Returns:
            補足発言の ``Utterance``。未達判定できない or 達成済みなら ``None``。
        """
        goal = (round_config.goal or "").strip()
        if not goal or not utterances or not round_config.speakers:
            return None

        try:
            achieved, missing = await self._check_goal_achievement(goal, utterances)
        except Exception as e:  # noqa: BLE001
            logger.warning("goal completion check failed: %s", e)
            return None

        if achieved:
            return None

        leader_id = round_config.speakers[0]
        agent = self._get_agent(leader_id)
        if agent is None:
            return None

        instruction = GOAL_COMPLETION_REQUEST_INSTRUCTION.format(
            round_goal=goal,
            missing=missing or "(目標の成果物が明示されていません)",
        )
        context = self._build_round_context(
            round_config, plan, utterances, sequence=len(utterances) + 1,
            speaker_role_id=leader_id,
        )
        supplement = await agent.speak(
            context,
            additional_instruction=instruction,
        )
        supplement.type = "goal_completion"
        self.memory.add_utterance(supplement, round_config.round)
        self._notify("utterance", self._utterance_payload(supplement, round_config.round))
        return supplement

    async def _check_goal_achievement(
        self,
        goal: str,
        utterances: list[Utterance],
    ) -> tuple[bool, str]:
        """LLM で goal 達成度を判定し ``(achieved, missing)`` を返す。"""
        text = "\n".join(
            f"{u.speaker_display}: {u.content}" for u in utterances
        )
        prompt = GOAL_COMPLETION_CHECK_PROMPT.format(
            round_goal=goal, utterances_text=text
        )
        response = await self.api_client.call(
            model=self.convergence_checker.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=GOAL_COMPLETION_CHECK_TEMPERATURE,
            max_tokens=GOAL_COMPLETION_CHECK_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        data = self._parse_goal_check_response(content)
        achieved = bool(data.get("achieved", True))  # パース失敗時は達成扱いで安全側
        missing = str(data.get("missing", "")).strip()
        return achieved, missing

    @staticmethod
    def _parse_goal_check_response(content: str) -> dict[str, Any]:
        """goal 判定 LLM 応答を dict に変換。失敗時は空 dict。"""
        import json
        import re

        text = (content or "").strip()
        if not text:
            return {}
        fence = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE
        )
        if fence:
            payload = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            payload = text[start : end + 1] if 0 <= start < end else text
        try:
            data = json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # 次発言者の決定
    # ------------------------------------------------------------------

    async def _decide_next_speaker(
        self,
        dynamic: DynamicOrder,
        speakers: list[str],
        utterances: list[Utterance],
        counts: dict[str, int],
        round_goal: str,
    ) -> str:
        """``DynamicOrder`` 経由で次発言者を決定する。"""
        return await dynamic.decide_next_speaker(
            speakers=speakers,
            utterances=utterances,
            utterance_counts=counts,
            round_goal=round_goal,
        )

    # ------------------------------------------------------------------
    # 時間 / 収束 / 停滞ハンドラ
    # ------------------------------------------------------------------

    def _handle_time_pressure(self, estimated_round_sec: float) -> str:
        """時間圧力に応じて ``"continue"`` / ``"terminate"`` を返す。

        Args:
            estimated_round_sec: 次ラウンドの推定所要秒数。

        Returns:
            ``"terminate"`` なら呼び出し元は議論を打ち切る。
        """
        if self.time_keeper.force_conclude():
            return "terminate"
        pressure = self.time_keeper.pressure
        if pressure == TimePressure.CRITICAL:
            return "terminate"
        if pressure == TimePressure.URGENT and not self.time_keeper.can_start_next_round(
            estimated_round_sec
        ):
            return "terminate"
        return "continue"

    async def _handle_early_convergence(
        self,
        result: ConvergenceResult,
        threshold: float,
    ) -> str:
        """収束判定結果から ``"terminate"`` / ``"pivot"`` / ``"continue"`` を選ぶ。"""
        if self.convergence_checker.should_terminate(result, threshold):
            return "terminate"
        if result.recommendation == "pivot":
            return "pivot"
        if self.convergence_checker.is_stagnating():
            return "pivot"
        return "continue"

    async def _handle_stagnation(self, result: ConvergenceResult) -> str:
        """停滞時に次ラウンドへ注入する pivot 指示を LLM で生成する。"""
        recent_scores = self.convergence_checker.score_history[-3:] or [result.score]
        prompt = PIVOT_PROMPT.format(
            recent_scores=", ".join(f"{s:.2f}" for s in recent_scores),
            disagreements=", ".join(result.remaining_disagreements) or "(なし)",
        )
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=PIVOT_PROMPT_TEMPERATURE,
            max_tokens=PIVOT_PROMPT_MAX_TOKENS,
        )
        instruction = str(response.get("content") or "").strip()
        self.memory.add_system_event(f"pivot指示: {instruction}")
        return instruction

    # ------------------------------------------------------------------
    # 狭まりすぎ検知 (問題1D対策)
    # ------------------------------------------------------------------

    async def _detect_narrowing(
        self,
        round_log: RoundLog,
        plan: OrchestraPlan,
    ) -> str:
        """前ラウンドが単一具体例に閉じていれば視野拡大指示を返す。

        LLM で「1 業務・1 製品・1 シナリオ」への収束を検知する。
        検知したら次ラウンドの ``additional_instruction`` に注入する視野拡大
        テキストを生成して返す。検知しない or 失敗時は空文字を返す
        (呼び出し側は空文字なら pivot 追加しない)。

        Args:
            round_log: 判定対象のラウンド。
            plan: 全体計画 (元テーマ Objective を取り出すため)。

        Returns:
            視野拡大指示の Markdown 文字列。狭まっていなければ空文字。
        """
        if not round_log.public_utterances:
            return ""
        return await self._run_narrowing_check(
            list(round_log.public_utterances), plan
        )

    async def _detect_narrowing_midround(
        self,
        utterances_so_far: list[Utterance],
        plan: OrchestraPlan,
    ) -> str:
        """ラウンド中盤で狭まりを検知する (問題 P2-B 対策)。

        ラウンドの半分の発言者が発言し終えた時点で 1 度だけ呼ばれる想定。
        検知したら残りの発言者に視野拡大指示を注入する。

        Args:
            utterances_so_far: そのラウンドでこれまでに生成された発言。
            plan: 全体計画。

        Returns:
            視野拡大指示。狭まっていない or 検知失敗なら空文字。
        """
        if not utterances_so_far:
            return ""
        return await self._run_narrowing_check(utterances_so_far, plan)

    async def _run_narrowing_check(
        self,
        utterances: list[Utterance],
        plan: OrchestraPlan,
    ) -> str:
        """狭まり判定 LLM 呼び出しと pivot 文字列生成の共通処理。"""
        tail = utterances[-3:]
        utterances_text = "\n".join(
            f"{u.speaker_display}: {u.content}" for u in tail
        )
        prompt = NARROWING_CHECK_PROMPT.format(
            objective=plan.odsc.objective or "",
            utterances_text=utterances_text,
        )
        try:
            response = await self.api_client.call(
                model=self.convergence_checker.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=NARROWING_CHECK_TEMPERATURE,
                max_tokens=NARROWING_CHECK_MAX_TOKENS,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("narrowing detection failed: %s", e)
            return ""

        content = str(response.get("content") or "")
        data = self._parse_narrowing_response(content)
        if not data.get("narrowed"):
            return ""
        focused = str(data.get("focused_topic") or "特定の 1 具体例")
        return NARROWING_PIVOT_INSTRUCTION.format(
            focused_topic=focused,
            objective=plan.odsc.objective or "元のテーマ",
        )

    @staticmethod
    def _parse_narrowing_response(content: str) -> dict[str, Any]:
        """narrowing check LLM 応答を dict に変換する。失敗時は空 dict。"""
        import json
        import re

        text = (content or "").strip()
        if not text:
            return {}
        fence = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE
        )
        if fence:
            payload = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            payload = text[start : end + 1] if 0 <= start < end else text
        try:
            data = json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # 補助
    # ------------------------------------------------------------------

    def _estimate_round_time(self, round_config: RoundConfig) -> float:
        """``TurnCalculator`` を経由してラウンド推定時間を返す。"""
        return self.turn_calculator.calculate_round_time(round_config)

    def _build_round_context(
        self,
        round_config: RoundConfig,
        plan: OrchestraPlan,
        utterances: list[Utterance],
        sequence: int,
        speaker_role_id: str = "",
    ) -> dict[str, Any]:
        """``Agent.speak`` に渡すラウンドコンテキストを組み立てる。

        Args:
            round_config: 現ラウンド設定。
            plan: 全体計画。
            utterances: そのラウンドこれまでの発言。
            sequence: 次発言の連番。
            speaker_role_id: 次発言者の ``role_id``。
                ``own_recent_utterances`` の抽出に使う (P3-B 対策)。
        """
        from .memory import ContextBudget  # 遅延 import で循環回避

        budget = ContextBudget(
            model=getattr(self, "_default_model", DEFAULT_CONDUCTOR_MODEL),
            level=round_config.level,
        )
        ctx = self.memory.get_context_for_agent(
            current_round=round_config.round,
            agent_role_id=speaker_role_id,
            context_budget=budget,
        )
        ctx["odsc"] = plan.odsc
        ctx["round_goal"] = round_config.goal
        ctx["next_sequence"] = sequence
        total_rounds = (
            len(plan.discussion_plan.round_config)
            if plan.discussion_plan
            else 0
        )
        ctx["round_number"] = round_config.round
        ctx["total_rounds"] = total_rounds
        ctx["round_phase_hint"] = self._infer_phase_hint(round_config, total_rounds)
        return ctx

    @staticmethod
    def _infer_phase_hint(round_config: RoundConfig, total_rounds: int) -> str:
        """ラウンド番号と全ラウンド数から、現フェーズのヒントを返す。

        Idea Discussion の推奨フェーズ (PLANNING_PROMPT と一致):
            Phase 1 (Round 1): 各 AI が案を持ち寄る
            Phase 2 (中間 Round): 相互フィードバック
            Phase 3 (最終前 Round): 案の絞り込み
            Phase 4 (最終 Round): 選ばれた案の深掘り
        """
        r = round_config.round
        if r == 1:
            return (
                "Phase 1 (持ち寄り): 各 AI が自分の切り口を 1 つ提示するフェーズ。\n"
                "→ この段階では具体的な数値や実装詳細に踏み込まない。\n"
                "→ 「私は△△という切り口を提案します」形式で、\n"
                "  切り口のタイトルと 1-2 行の簡潔な説明に留める。\n"
                "→ 詳細・MVP・KPI の数値は次ラウンド以降で深掘りする。"
            )
        if total_rounds >= 4 and r == total_rounds:
            return (
                "Phase 4 (深掘り): これまでに選ばれた案について、\n"
                "MVP・実装要素・KPI・リスクを具体的な数値で埋めていくフェーズ。"
            )
        if total_rounds >= 3 and r == total_rounds - 1:
            return (
                "Phase 3 (絞り込み): これまで候補案の中から、\n"
                "最も有望な案を 1 つに絞り込むフェーズ。\n"
                "→ 根拠を明確にし、他の案をなぜ覚えるのかを言化する。"
            )
        return (
            "Phase 2 (相互フィードバック): Phase 1 で出た各案に対し、\n"
            "他 AI が長所 1 つ・懸念 1 つを指攜して案の質を高めるフェーズ。\n"
            "→ この段階ではやだ案を絞らない。全案に対する評価を集める。"
        )

    def _get_agent(self, role_id: str) -> "Agent | None":
        """``role_id`` から ``Agent`` を取得する。見つからなければ警告して None。"""
        agent = self.agents.get(role_id)
        if agent is None:
            logger.warning("Agent %r not registered; skipping utterance", role_id)
        return agent

    def _consume_pivot_instruction(self) -> str:
        """pivot 指示を 1 度だけ消費する (取得後にクリア)。"""
        instruction = self._pivot_instruction
        self._pivot_instruction = ""
        return instruction

    @staticmethod
    def _build_repetition_instruction(result: RepetitionResult) -> str:
        """堂々巡り検知時に渡す追加指示を組み立てる。"""
        return FORCE_NEW_TOPIC_INSTRUCTION.format(
            repeated_topic=result.repeated_topic or "(直近の論点)",
        )

    def _get_repetition_check_interval(self) -> int:
        """settings.round_utterances から堂々巡りチェック間隔を読む。

        未設定なら ``DEFAULT_REPETITION_CHECK_INTERVAL`` を使う。
        """
        round_utterances = getattr(self.settings, "round_utterances", {}) or {}
        try:
            value = int(
                round_utterances.get(
                    "free_talk_repetition_check_interval",
                    DEFAULT_REPETITION_CHECK_INTERVAL,
                )
            )
        except (TypeError, ValueError):
            value = DEFAULT_REPETITION_CHECK_INTERVAL
        return max(1, value)

    # ------------------------------------------------------------------
    # Bonus round (時間余り時の追加ラウンド)
    # ------------------------------------------------------------------

    async def _run_bonus_rounds_if_time_remains(
        self,
        plan: OrchestraPlan,
        discussion_log: DiscussionLog,
    ) -> None:
        """全計画ラウンド完了後、時間が残っていれば bonus round を追加実行する。

        ``BONUS_ROUND_MIN_REMAINING_SEC`` 秒以上残っていれば、LLM に未消化の
        論点を問い、``free_talk`` パターンで追加ラウンドを実行する。
        最大 ``BONUS_ROUND_MAX_COUNT`` 回まで繰り返し、時間を使い切る。
        """
        # ここに入った時点で計画の最終ラウンドが「次論点あり」で終わっている。
        # bonus round が有効ならその「次論点」が使われるので問題なし。
        # bonus round は「次が動くか」を各ループで判定できるので、動かないと
        # 判明した bonus round の 1 つ前が実質最終だが、既に結論生成済み。
        # 妥協として: 各 bonus round が「これが最後かも」判定を事前に行い、
        # そのラウンドは final フラグで実行する。
        for i in range(BONUS_ROUND_MAX_COUNT):
            remaining = self.time_keeper.remaining
            if remaining < BONUS_ROUND_MIN_REMAINING_SEC:
                logger.debug(
                    "Bonus round skipped: remaining=%.1fs < %.1fs",
                    remaining, BONUS_ROUND_MIN_REMAINING_SEC,
                )
                return
            # 時間切れが差し迫っていれば早期抜け出し
            if self.time_keeper.force_conclude():
                logger.info("Bonus round loop: time budget exhausted; stopping")
                return

            next_round_num = (
                max((r.round for r in discussion_log.rounds), default=0) + 1
            )
            try:
                bonus_config = await self._build_bonus_round_config(
                    plan, discussion_log, next_round_num, remaining
                )
            except Exception as e:  # noqa: BLE001 - bonus round 失敗は全体を止めない
                logger.warning("Failed to build bonus round: %s", e)
                return

            estimated = self._estimate_round_time(bonus_config)
            if not self.time_keeper.can_start_next_round(estimated):
                logger.debug(
                    "Bonus round %d: estimated=%.1fs > remaining=%.1fs; stopping",
                    next_round_num, estimated, remaining,
                )
                return

            # 次の bonus round が動くかを事前判定して is_final を決める。
            # 上限に達している / 予想後残時間が不足 なら「これが最終」。
            projected_remaining = remaining - estimated
            is_final_bonus = (
                (i == BONUS_ROUND_MAX_COUNT - 1)
                or (projected_remaining < BONUS_ROUND_MIN_REMAINING_SEC)
            )

            logger.info(
                "Starting bonus round %d (goal=%r, remaining=%.1fs, is_final=%s)",
                next_round_num, bonus_config.goal, remaining, is_final_bonus,
            )
            round_log = await self.run_round(
                bonus_config, plan, is_final_round=is_final_bonus,
            )
            discussion_log.rounds.append(round_log)
            self.time_keeper.record_round(round_log.duration_sec)

            if round_log.convergence_check is not None:
                discussion_log.score_history.append(
                    round_log.convergence_check.score
                )
                discussion_log.final_convergence_score = (
                    round_log.convergence_check.score
                )

    async def _build_bonus_round_config(
        self,
        plan: OrchestraPlan,
        discussion_log: DiscussionLog,
        round_num: int,
        remaining_sec: float,
    ) -> RoundConfig:
        """LLM に未消化の論点を問い、bonus round の ``RoundConfig`` を組み立てる。

        LLM 応答が壊れた場合はデフォルトの goal (「これまでの議論を統合し、
        次に取るべきアクションを 3 つ決める」) で代替する。
        """
        objective = getattr(plan.odsc, "objective", "") if plan.odsc else ""
        previous_goals = "\n".join(
            f"- Round {r.round}: {r.goal}" for r in discussion_log.rounds
        )
        last_score = (
            discussion_log.score_history[-1]
            if discussion_log.score_history else 0.0
        )
        disagreements: list[str] = []
        # 直近の convergence_check から未解決の対立点を取得
        for r in reversed(discussion_log.rounds):
            if r.convergence_check is not None:
                disagreements = list(
                    r.convergence_check.remaining_disagreements or []
                )
                break
        disagreements_text = (
            "\n".join(f"- {d}" for d in disagreements) if disagreements else "(なし)"
        )

        goal = await self._request_bonus_goal(
            objective=objective,
            previous_goals=previous_goals or "(なし)",
            last_score=f"{last_score:.2f}",
            disagreements=disagreements_text,
        )

        # 発言者は plan.selected_agents 全員 (bonus round は全体討議)
        speakers = [a.role_id for a in plan.selected_agents]
        # time_budget は残時間全部 (ただし 60 秒未満にならないよう最小 60)
        time_budget = max(60.0, remaining_sec)

        return RoundConfig(
            round=round_num,
            phase_name=f"{BONUS_ROUND_PHASE_PREFIX}{round_num}",
            speakers=speakers,
            pattern="free_talk",
            level="low",  # 短めに回して発言数を稼ぐ
            time_budget_sec=time_budget,
            goal=goal,
        )

    async def _request_bonus_goal(
        self,
        objective: str,
        previous_goals: str,
        last_score: str,
        disagreements: str,
    ) -> str:
        """LLM に bonus round の goal を生成させる。失敗時はデフォルト値。"""
        default_goal = (
            "これまでの議論を統合し、次に取るべき具体的アクションを 3 つ決める"
        )
        prompt = BONUS_ROUND_GOAL_PROMPT.format(
            objective=objective or "(未指定)",
            previous_goals=previous_goals,
            last_score=last_score,
            disagreements=disagreements,
        )
        try:
            response = await self.api_client.call(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=BONUS_ROUND_GOAL_TEMPERATURE,
                max_tokens=BONUS_ROUND_GOAL_MAX_TOKENS,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Bonus goal LLM call failed: %s", e)
            return default_goal

        raw = str(response.get("content") or "").strip()
        # "goal: <text>" の形を期待
        for line in raw.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("goal:"):
                _, _, value = stripped.partition(":")
                candidate = value.strip()
                if candidate:
                    return candidate
        # フォールバック: 最初の非空行をそのまま
        for line in raw.splitlines():
            if line.strip():
                return line.strip()
        return default_goal


__all__ = [
    "Conductor",
    "InterventionHandler",
    "NoIntervention",
    "PIVOT_PROMPT",
    "FORCE_NEW_TOPIC_INSTRUCTION",
    "EXCESSIVE_AGREEMENT_INSTRUCTION",
    "ROUND_CONCLUSION_INSTRUCTION",
]
