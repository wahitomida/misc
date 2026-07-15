"""コードレビュー統合フロー: ``CodeReview`` クラス。

Phase 構成 (詳細は ``doc/12_code_review.md`` §12.1):
    Phase 1: 構造スキャン (``_phase1_scan``)
    Phase 2: 個別調査 (``_phase2_investigate``) — ``investigator``
    Phase 3: 相互質問 (``_phase3_cross_question``) — ``CrossQuestioner``
    Phase 4: 全体会議 (``_phase4_meeting``) — ``meeting.run_meeting``
    Phase 5: レポート生成 (``_phase5_report``) — ``report_builder``

``focus`` が ``"auto"`` または ``None`` の場合は
``focus_detector.detect_focus`` で ``ScanResult`` から推定する。

設計書: ``doc/12_code_review.md`` §12.1〜§12.7
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from core.base_feature import (
    DiscussionFeatureBase,
    PhaseHandler,
    PhaseKey,
    PhaseKeyHandler,
)
from core.data_models import DiscussionLog, ScanResult
from core.discussion_common import DEFAULT_EXPERTISE
from features.code_review.assigner import PartLeaderAssigner
from features.code_review.chunker import FileChunker
from features.code_review.constants import FOCUS_PRESETS
from features.code_review.cross_question import CrossQuestioner
from features.code_review.focus_detector import detect_focus, is_auto_focus
from features.code_review.investigator import investigate_one_leader
from features.code_review.phases import (
    run_phase3_cross_question,
    run_phase4_meeting,
    run_phase5_report,
)
from features.code_review.meeting import MeetingResult
from features.code_review.scanner import FolderScanner

if TYPE_CHECKING:
    from core.api_client import ResilientAPIClient
    from core.config_loader import Settings
    from core.feedback import FeedbackManager
    from core.role_manager import RoleManager


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

DEFAULT_FOCUS = "all"
DEFAULT_PLANNER_MODEL = "gpt-5.4"
DEFAULT_CONDUCTOR_MODEL = "gpt-4.1"
DEFAULT_SYNTH_MODEL = "claude-sonnet-4-5"
DEFAULT_TIME_LIMIT_SEC = 600.0
DEFAULT_MAX_AGENTS = 6
DEFAULT_OUTPUT_DIR = Path("./output")


# ----------------------------------------------------------------------
# CodeReview クラス
# ----------------------------------------------------------------------


class CodeReview(DiscussionFeatureBase):
    """機能②: コードレビューの統合フロー。

    4 フェーズ構造 (入力 → 計画 → 議論 → 結果) に従う:

    - Phase 1 (入力): 対象フォルダスキャン + focus 解決 (LLM 不使用)
    - Phase 2 (計画): 6 観点の個別調査 + 相互質問で findings 集約
    - Phase 3 (議論): 全体会議 (パートリーダーによる優先度決定)
    - Phase 4 (結果): 評価 + レポート生成

    Attributes:
        api_client: 共有 API クライアント。
        role_manager: ロール定義の取得元。
        feedback_manager: フィードバック蓄積。
        settings: 全体設定。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        role_manager: "RoleManager",
        feedback_manager: "FeedbackManager | None",
        settings: "Settings",
    ) -> None:
        super().__init__(
            api_client=api_client,
            role_manager=role_manager,
            feedback_manager=feedback_manager,
            settings=settings,
        )

        self._scanner = FolderScanner(settings=settings)
        self._chunker = FileChunker()
        self._assigner = PartLeaderAssigner()
        self._cross_questioner = CrossQuestioner(
            api_client=api_client, settings=settings
        )

    # ------------------------------------------------------------------
    # 全体フロー
    # ------------------------------------------------------------------

    async def run(
        self,
        target_path: Path,
        focus: str | None = DEFAULT_FOCUS,
        planner_model: str = DEFAULT_PLANNER_MODEL,
        conductor_model: str = DEFAULT_CONDUCTOR_MODEL,
        synth_model: str = DEFAULT_SYNTH_MODEL,
        time_limit: float = DEFAULT_TIME_LIMIT_SEC,
        max_agents: int = DEFAULT_MAX_AGENTS,
        expertise: str = DEFAULT_EXPERTISE,
        ignore_patterns: list[str] | None = None,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        on_phase: PhaseHandler | None = None,
        on_phase_key: PhaseKeyHandler | None = None,
    ) -> Path | None:
        """コードレビュー全体フローを 4 フェーズで実行する。

        Args:
            target_path: レビュー対象のフォルダ。
            focus: ``FOCUS_PRESETS`` のキー / ``"auto"`` / ``None`` (auto 推定)。
            planner_model: Phase 1-2 機能判定用モデル。
            conductor_model: Phase 3 全体会議の指揮者モデル。
            synth_model: Phase 4 レポート生成用 (現状テンプレベースで未使用)。
            time_limit: 全フェーズ合計の秒数上限。Phase 3 会議の
                ``TimeKeeper`` に伝樬される。
            max_agents: パートリーダー上限 (現状未使用)。
            expertise: Phase 3 会議の発言口調レベル。
            ignore_patterns: スキャン時の追加 ignore パターン。
            output_dir: レポート出力先。
            on_phase: 下位互換のフェーズ通知 (name のみ)。
            on_phase_key: 新形式のフェーズ通知 (PhaseKey + name)。

        Returns:
            生成セッションディレクトリのパス。スキャン結果が空なら ``None``。
        """
        del max_agents, synth_model  # 将来拡張用 (現状未使用)

        # Phase 1: 入力 — 対象フォルダスキャン + focus 解決
        self.notify_phase(PhaseKey.INPUT, on_phase=on_phase, on_phase_key=on_phase_key)
        scan_result = await self._phase1_scan(
            target_path, planner_model, ignore_patterns
        )
        if scan_result.total_files == 0:
            logger.warning(
                "Scan returned no files for %s; skipping subsequent phases",
                target_path,
            )
            return None
        resolved_focus = await self._resolve_focus(
            focus, scan_result, planner_model
        )

        # Phase 2: 計画 — 個別調査 + 相互質問で findings 集約
        self.notify_phase(PhaseKey.PLANNING, on_phase=on_phase, on_phase_key=on_phase_key)
        findings = await self._phase2_investigate(scan_result, resolved_focus)
        enriched = await self._phase3_cross_question(findings)

        # Phase 3: 議論 — パートリーダーによる全体会議
        self.notify_phase(PhaseKey.DISCUSSION, on_phase=on_phase, on_phase_key=on_phase_key)
        meeting_result = await self._phase4_meeting(
            scan_result, enriched, resolved_focus, conductor_model,
            expertise=expertise,
            time_limit_sec=time_limit,
        )

        # Phase 4: 結果 — 評価 + レポート生成
        self.notify_phase(PhaseKey.RESULT, on_phase=on_phase, on_phase_key=on_phase_key)
        return await self._phase5_report(
            scan_result=scan_result,
            findings=enriched,
            discussion_log=meeting_result.discussion_log,
            focus=resolved_focus,
            output_dir=output_dir,
            agents=meeting_result.agents,
            meeting_plan=meeting_result.plan,
        )

    # ------------------------------------------------------------------
    # Phase 1: 構造スキャン
    # ------------------------------------------------------------------

    async def _phase1_scan(
        self,
        target_path: Path,
        planner_model: str,
        ignore_patterns: list[str] | None,
    ) -> ScanResult:
        """対象フォルダをスキャンして ``ScanResult`` を返す。

        現状の Phase 1 は LLM を呼ばず ``FolderScanner`` のみを使う。
        将来は ``planner_model`` で機能グループ推定を行う。
        """
        del planner_model  # 将来 §12.2.3 のグループ推定で使用
        return await asyncio.to_thread(
            self._scanner.scan,
            target_path,
            ignore_patterns,
        )

    # ------------------------------------------------------------------
    # Phase 2: 個別調査
    # ------------------------------------------------------------------

    async def _phase2_investigate(
        self,
        scan_result: ScanResult,
        focus: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """6 観点のパートリーダーごとに findings を並列収集する。"""
        leaders = self._assigner.assign(scan_result, focus)
        if not leaders:
            return {}

        tasks = [
            investigate_one_leader(
                api_client=self.api_client,
                chunker=self._chunker,
                scan_result=scan_result,
                leader=leader,
            )
            for leader in leaders
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: dict[str, list[dict[str, Any]]] = {}
        for leader, result in zip(leaders, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Investigation failed for concern=%s: %s",
                    leader.concern,
                    result,
                )
                out[leader.concern] = []
            else:
                out[leader.concern] = result
        return out

    # ------------------------------------------------------------------
    # focus 解決
    # ------------------------------------------------------------------

    async def _resolve_focus(
        self,
        focus: str | None,
        scan_result: ScanResult,
        planner_model: str,
    ) -> str:
        if not is_auto_focus(focus):
            assert focus is not None
            return focus
        return await self._auto_detect_focus(scan_result, planner_model)

    async def _auto_detect_focus(
        self,
        scan_result: ScanResult,
        planner_model: str = DEFAULT_PLANNER_MODEL,
    ) -> str:
        """``ScanResult`` から focus を推定する (詳細は ``focus_detector``)。"""
        return await detect_focus(
            api_client=self.api_client,
            scan_result=scan_result,
            planner_model=planner_model,
            valid_focuses=set(FOCUS_PRESETS.keys()),
        )

    # ------------------------------------------------------------------
    # Phase 3-5: 薄い委譲ラッパー (ロジックは ``phases`` モジュールにある)
    # ------------------------------------------------------------------

    async def _phase3_cross_question(
        self,
        findings: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """相互質問を実行して findings を拡充する。"""
        return await run_phase3_cross_question(
            self._cross_questioner, findings
        )

    async def _phase4_meeting(
        self,
        scan_result: ScanResult,
        findings: dict[str, list[dict[str, Any]]],
        focus: str,
        conductor_model: str,
        expertise: str = DEFAULT_EXPERTISE,
        time_limit_sec: float | None = None,
    ) -> "MeetingResult":
        """全体会議を 1 ラウンド実行する。

        ``time_limit_sec`` を指定すると、``run_meeting`` の内部で使用する
        ``TimeKeeper`` の制限時間になる。``None`` なら ``MEETING_TIME_LIMIT_SEC``
        (240 秒) を使用。
        """
        return await run_phase4_meeting(
            api_client=self.api_client,
            role_manager=self.role_manager,
            settings=self.settings,
            scan_result=scan_result,
            findings=findings,
            focus=focus,
            conductor_model=conductor_model,
            expertise=expertise,
            time_limit_sec=time_limit_sec,
        )

    async def _phase5_report(
        self,
        scan_result: ScanResult,
        findings: dict[str, list[dict[str, Any]]],
        discussion_log: DiscussionLog,
        focus: str,
        output_dir: Path,
        agents: dict | None = None,
        meeting_plan: Any | None = None,
    ) -> Path:
        """レポート一式をセッションディレクトリに書き出す。"""
        return await run_phase5_report(
            scan_result=scan_result,
            findings=findings,
            discussion_log=discussion_log,
            focus=focus,
            output_dir=output_dir,
            api_client=self.api_client,
            settings=self.settings,
            agents=agents,
            meeting_plan=meeting_plan,
            feedback_manager=self.feedback_manager,
        )


__all__ = [
    "CodeReview", "DEFAULT_FOCUS", "DEFAULT_PLANNER_MODEL",
    "DEFAULT_CONDUCTOR_MODEL", "DEFAULT_SYNTH_MODEL",
    "DEFAULT_TIME_LIMIT_SEC", "DEFAULT_MAX_AGENTS", "DEFAULT_OUTPUT_DIR",
]
