"""``core.follow_up`` モジュールのユニットテスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.api_client import ResilientAPIClient, RetryConfig
from core.exceptions import (
    FileTooLargeError,
    SessionNotFoundError,
    TooManyAttachmentsError,
    UnsupportedFileTypeError,
)
from core.follow_up import (
    AttachmentProcessor,
    FollowUpManager,
    HypothesisManager,
    STATUS_EMOJI,
)
from core.rate_tracker import RateLimitTracker
from tests.mocks.mock_api import MockAPIClient


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _make_session_dir(
    base: Path,
    session_id: str,
    *,
    discussion_data: dict[str, Any] | None = None,
    report_md: str | None = None,
    meta_data: dict[str, Any] | None = None,
) -> Path:
    """テスト用のセッションディレクトリを作成する。"""
    session_dir = base / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    if discussion_data is not None:
        (session_dir / "discussion.json").write_text(
            json.dumps(discussion_data, ensure_ascii=False),
            encoding="utf-8",
        )
    if report_md is not None:
        (session_dir / "report.md").write_text(report_md, encoding="utf-8")
    if meta_data is not None:
        (session_dir / "session_meta.json").write_text(
            json.dumps(meta_data, ensure_ascii=False),
            encoding="utf-8",
        )
    return session_dir


def _basic_discussion(
    final_conclusion: str = "推奨構成: multi-scale kNN",
    rounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if rounds is None:
        rounds = [
            {
                "round": 1,
                "convergence_check": {"reasoning": "問題空間の整理が進んだ"},
            },
            {
                "round": 2,
                "convergence_check": {"reasoning": "穴の指摘で方向転換"},
            },
        ]
    return {
        "session": {"id": "20260620_143052_idea"},
        "planning": {
            "selected_agents": [
                {"role_id": "theorist", "model": "gpt-5.4", "level": "high"},
                {"role_id": "devil", "model": "claude-sonnet-4-5", "level": "medium"},
            ]
        },
        "discussion": {"rounds": rounds, "final_convergence_score": 0.85},
        "evaluation": {},
        "orchestrator_evaluation": {
            "overall_discussion_quality": 4.2,
            "mvp_role_id": "theorist",
            "odsc_achievement": {"detail": "目標達成"},
            "per_agent_feedback": {"theorist": {"orchestrator_feedback": "良かった"}},
        },
        "synthesis": {"final_conclusion": final_conclusion},
    }


_BASIC_REPORT_MD = """\
# 🔬 AI Orchestra 技術検討レポート

## 4. 仮説テーブル

| ID | 仮説 | 状態 | 検証方法 | 備考 |
|---|---|---|---|---|
| H1 | multi-scale が密度不均一に効く | 🔲 未検証 | ablation | 重要 |
| H2 | spectral PE は不要 | ✅ 確認済み | 実験で確認 |  |
| H3 | k=10 で十分 | ❌ 棄却 | 反例あり |  |
| 不正行 | xxx |
| H4 | エッジ部の精度向上 | 🔄 修正 | 修正版を検証 |  |

## 6. 未解決問題

1. k の最適選択基準
- 計算リソース見積もりの精度
2. リアルタイム推論時の安定性

## 7. 参考文献
- (Qi+2017)
"""


@pytest.fixture
def api_client(tmp_path: Path) -> ResilientAPIClient:
    mock = MockAPIClient(responses=[{"content": "圧縮版テキスト 3行"}])
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    return ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )


# ===========================================================================
# FollowUpManager
# ===========================================================================


class TestLoadPreviousSession:
    @pytest.mark.asyncio
    async def test_loads_minimal_session(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        _make_session_dir(
            out_dir,
            "20260620_143052_idea",
            discussion_data=_basic_discussion(),
            report_md=_BASIC_REPORT_MD,
            meta_data={
                "follow_up": {"chain": ["20260620_143052_idea"]}
            },
        )

        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)
        ctx = await manager.load_previous_session("20260620_143052_idea")

        assert ctx.parent_session_id == "20260620_143052_idea"
        assert ctx.previous_conclusion == "推奨構成: multi-scale kNN"
        assert {h["id"] for h in ctx.previous_hypotheses} >= {"H1", "H2", "H3", "H4"}
        assert "k の最適選択基準" in ctx.unresolved_issues
        assert ctx.discussion_summary == "圧縮版テキスト 3行"
        assert len(ctx.previous_agents) == 2
        assert ctx.chain == ["20260620_143052_idea"]
        assert ctx.chain_depth == 1

    @pytest.mark.asyncio
    async def test_appends_to_existing_chain(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        _make_session_dir(
            out_dir,
            "20260625_091200_idea",
            discussion_data=_basic_discussion(),
            report_md=_BASIC_REPORT_MD,
            meta_data={
                "follow_up": {"chain": ["20260620_143052_idea"]}
            },
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)
        ctx = await manager.load_previous_session("20260625_091200_idea")

        assert ctx.chain == ["20260620_143052_idea", "20260625_091200_idea"]
        assert ctx.chain_depth == 2

    @pytest.mark.asyncio
    async def test_missing_session_raises(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)
        with pytest.raises(SessionNotFoundError):
            await manager.load_previous_session("nonexistent")

    @pytest.mark.asyncio
    async def test_session_without_report_md_returns_empty_hypotheses(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        _make_session_dir(
            out_dir,
            "s",
            discussion_data=_basic_discussion(),
            report_md=None,  # report.md なし
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)
        ctx = await manager.load_previous_session("s")

        assert ctx.previous_hypotheses == []
        assert ctx.unresolved_issues == []


class TestExtractConclusion:
    @pytest.mark.asyncio
    async def test_returns_final_conclusion_when_present(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(
            out_dir, "s", discussion_data=_basic_discussion(final_conclusion="結論X")
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)

        assert manager._extract_conclusion(session_dir) == "結論X"

    @pytest.mark.asyncio
    async def test_falls_back_to_odsc_achievement_detail(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        data = _basic_discussion(final_conclusion="")
        # synthesis.final_conclusion を空に
        data["synthesis"]["final_conclusion"] = ""
        session_dir = _make_session_dir(out_dir, "s", discussion_data=data)
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)

        assert manager._extract_conclusion(session_dir) == "目標達成"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(
            out_dir, "s", discussion_data={"synthesis": {}, "orchestrator_evaluation": {}}
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)

        assert manager._extract_conclusion(session_dir) == ""


class TestExtractHypotheses:
    @pytest.mark.asyncio
    async def test_parses_valid_table_rows(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text(_BASIC_REPORT_MD, encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        result = manager._extract_hypotheses(report_path)

        ids = [h["id"] for h in result]
        assert ids == ["H1", "H2", "H3", "H4"]

    @pytest.mark.asyncio
    async def test_parses_status_emoji_mapping(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text(_BASIC_REPORT_MD, encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        statuses = {h["id"]: h["status"] for h in manager._extract_hypotheses(report_path)}
        assert statuses == {
            "H1": "unverified",
            "H2": "confirmed",
            "H3": "rejected",
            "H4": "modified",
        }

    @pytest.mark.asyncio
    async def test_skips_invalid_rows(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        """4 列未満の行や ID 形式が異なる行は無視する。"""
        report_path = tmp_path / "report.md"
        report_path.write_text(_BASIC_REPORT_MD, encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        result = manager._extract_hypotheses(report_path)
        # 「不正行」は ID が "H..." でないため除外、また 4 列ない
        ids = [h["id"] for h in result]
        assert "不正行" not in ids

    @pytest.mark.asyncio
    async def test_empty_when_no_table(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text("# No table here", encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        assert manager._extract_hypotheses(report_path) == []


class TestExtractUnresolved:
    @pytest.mark.asyncio
    async def test_parses_numbered_and_bullet_items(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text(_BASIC_REPORT_MD, encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        issues = manager._extract_unresolved(report_path)

        assert "k の最適選択基準" in issues
        assert "計算リソース見積もりの精度" in issues
        assert "リアルタイム推論時の安定性" in issues

    @pytest.mark.asyncio
    async def test_stops_at_next_section(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text(_BASIC_REPORT_MD, encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        issues = manager._extract_unresolved(report_path)
        # "(Qi+2017)" は 7. 参考文献 の項目なので含まれない
        assert "(Qi+2017)" not in issues

    @pytest.mark.asyncio
    async def test_empty_when_no_section(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        report_path = tmp_path / "report.md"
        report_path.write_text("# 別セクション\n- 何か", encoding="utf-8")
        manager = FollowUpManager(output_dir=tmp_path, api_client=api_client)

        assert manager._extract_unresolved(report_path) == []


class TestCompressDiscussion:
    @pytest.mark.asyncio
    async def test_calls_api_when_client_available(
        self, tmp_path: Path
    ) -> None:
        mock = MockAPIClient(responses=[{"content": "LLM 圧縮テキスト"}])
        tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
        client = ResilientAPIClient(
            base_client=mock,
            rate_tracker=tracker,
            retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
            mode="openai",
        )
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(out_dir, "s", discussion_data=_basic_discussion())
        manager = FollowUpManager(output_dir=out_dir, api_client=client)

        result = await manager._compress_discussion(session_dir)

        assert result == "LLM 圧縮テキスト"
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_falls_back_when_no_api_client(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(out_dir, "s", discussion_data=_basic_discussion())
        manager = FollowUpManager(output_dir=out_dir, api_client=None)

        result = await manager._compress_discussion(session_dir)

        # フォールバック: 各ラウンドの reasoning を連結
        assert "R1:" in result
        assert "問題空間の整理が進んだ" in result
        assert "R2:" in result

    @pytest.mark.asyncio
    async def test_empty_when_no_rounds(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(
            out_dir, "s", discussion_data=_basic_discussion(rounds=[])
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=None)

        assert await manager._compress_discussion(session_dir) == ""


class TestExtractAgentInfo:
    @pytest.mark.asyncio
    async def test_returns_agents_and_orchestrator_evaluation(
        self, tmp_path: Path, api_client: ResilientAPIClient
    ) -> None:
        out_dir = tmp_path / "output"
        session_dir = _make_session_dir(
            out_dir, "s", discussion_data=_basic_discussion()
        )
        manager = FollowUpManager(output_dir=out_dir, api_client=api_client)

        agents, feedback = manager._extract_agent_info(session_dir)

        assert len(agents) == 2
        assert agents[0]["role_id"] == "theorist"
        assert feedback["mvp_role_id"] == "theorist"


# ===========================================================================
# HypothesisManager
# ===========================================================================


class TestHypothesisManagerTransitions:
    @pytest.mark.parametrize(
        ("from_status", "to_status", "expected"),
        [
            ("unverified", "confirmed", True),
            ("unverified", "rejected", True),
            ("unverified", "modified", True),
            ("confirmed", "rejected", False),  # confirmed は変更不可
            ("confirmed", "modified", False),
            ("rejected", "modified", True),
            ("rejected", "confirmed", False),
            ("modified", "confirmed", True),
            ("modified", "rejected", True),
            ("modified", "unverified", False),
        ],
    )
    def test_valid_transitions(
        self, from_status: str, to_status: str, expected: bool
    ) -> None:
        valid = HypothesisManager.VALID_TRANSITIONS[from_status]
        assert (to_status in valid) is expected


class TestApplyUpdates:
    def test_applies_valid_update(self) -> None:
        manager = HypothesisManager()
        hypotheses = [
            {
                "id": "H1",
                "hypothesis": "x",
                "status": "unverified",
                "verification_method": "ablation",
            }
        ]
        updated = manager.apply_updates(
            hypotheses,
            updates={"H1": {"new_status": "confirmed", "note": "実験で確認"}},
            new_hypotheses=[],
        )
        assert updated[0]["status"] == "confirmed"
        assert updated[0]["note"] == "実験で確認"

    def test_ignores_invalid_transition(self) -> None:
        manager = HypothesisManager()
        hypotheses = [
            {
                "id": "H1",
                "hypothesis": "x",
                "status": "confirmed",
                "verification_method": "ablation",
            }
        ]
        updated = manager.apply_updates(
            hypotheses,
            updates={"H1": {"new_status": "rejected"}},
            new_hypotheses=[],
        )
        assert updated[0]["status"] == "confirmed"
        assert updated[0]["_invalid_transition_attempted"] == "rejected"

    def test_appends_new_hypotheses_with_auto_ids(self) -> None:
        manager = HypothesisManager()
        hypotheses = [
            {
                "id": "H3",
                "hypothesis": "x",
                "status": "unverified",
                "verification_method": "",
            }
        ]
        updated = manager.apply_updates(
            hypotheses,
            updates={},
            new_hypotheses=[
                {"hypothesis": "new1"},
                {"hypothesis": "new2"},
            ],
        )
        ids = [h["id"] for h in updated]
        assert ids == ["H3", "H4", "H5"]
        # 新規は unverified
        assert updated[1]["status"] == "unverified"
        assert updated[2]["status"] == "unverified"

    def test_preserves_explicit_new_hypothesis_id(self) -> None:
        manager = HypothesisManager()
        updated = manager.apply_updates(
            hypotheses=[],
            updates={},
            new_hypotheses=[
                {"id": "H10", "hypothesis": "explicit"},
            ],
        )
        assert updated[0]["id"] == "H10"

    def test_empty_inputs(self) -> None:
        manager = HypothesisManager()
        assert manager.apply_updates([], {}, None) == []


class TestGenerateTableMarkdown:
    def test_returns_table_with_emoji(self) -> None:
        manager = HypothesisManager()
        hypotheses = [
            {
                "id": "H1",
                "hypothesis": "multi-scale",
                "status": "unverified",
                "verification_method": "ablation",
                "note": "",
            },
            {
                "id": "H2",
                "hypothesis": "PE 不要",
                "status": "confirmed",
                "verification_method": "実験",
                "note": "良好",
            },
        ]
        md = manager.generate_table_markdown(hypotheses)

        assert "| ID | 仮説 |" in md
        assert STATUS_EMOJI["unverified"] in md
        assert STATUS_EMOJI["confirmed"] in md
        assert "H2" in md
        assert "良好" in md

    def test_empty_returns_placeholder(self) -> None:
        manager = HypothesisManager()
        assert manager.generate_table_markdown([]) == "(仮説なし)"


class TestBuildFocusContext:
    def test_includes_only_focused_hypotheses(self) -> None:
        hypotheses = [
            {
                "id": "H1",
                "hypothesis": "h1",
                "status": "unverified",
                "verification_method": "ab",
            },
            {
                "id": "H2",
                "hypothesis": "h2",
                "status": "confirmed",
                "verification_method": "ex",
            },
        ]
        ctx = HypothesisManager.build_focus_context(hypotheses, ["H1"])

        assert "H1" in ctx
        assert "h1" in ctx
        assert "h2" not in ctx

    def test_empty_when_no_focus_match(self) -> None:
        assert (
            HypothesisManager.build_focus_context(
                [{"id": "H1", "hypothesis": "x", "status": "unverified"}],
                ["H99"],
            )
            == ""
        )


# ===========================================================================
# AttachmentProcessor
# ===========================================================================


class TestAttachmentProcessor:
    def test_processes_valid_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.csv"
        f1.write_text("col1,col2\n1,2", encoding="utf-8")
        f2 = tmp_path / "b.md"
        f2.write_text("# title", encoding="utf-8")
        proc = AttachmentProcessor()

        result = proc.process([f1, f2])

        assert len(result) == 2
        assert result[0]["name"] == "a.csv"
        assert "1,2" in result[0]["content"]
        assert result[1]["name"] == "b.md"

    def test_too_many_files_raises(self, tmp_path: Path) -> None:
        proc = AttachmentProcessor()
        files: list[Path] = []
        for i in range(6):
            p = tmp_path / f"f{i}.txt"
            p.write_text("x", encoding="utf-8")
            files.append(p)

        with pytest.raises(TooManyAttachmentsError):
            proc.process(files)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        proc = AttachmentProcessor()
        with pytest.raises(FileNotFoundError):
            proc.process([tmp_path / "nonexistent.txt"])

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "image.png"
        f.write_text("binary", encoding="utf-8")
        proc = AttachmentProcessor()

        with pytest.raises(UnsupportedFileTypeError):
            proc.process([f])

    def test_too_large_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "huge.txt"
        # MAX_FILE_SIZE = 50_000、それを超える
        f.write_text("a" * 60_000, encoding="utf-8")
        proc = AttachmentProcessor()

        with pytest.raises(FileTooLargeError):
            proc.process([f])

    def test_total_chars_truncates_overflow(self, tmp_path: Path) -> None:
        """合計文字数上限超過は切り詰めて続行する。"""
        f1 = tmp_path / "first.txt"
        f1.write_text("a" * 7000, encoding="utf-8")
        f2 = tmp_path / "second.txt"
        f2.write_text("b" * 5000, encoding="utf-8")
        proc = AttachmentProcessor()

        result = proc.process([f1, f2])

        # 2 つ目は MAX_TOTAL_CHARS=10_000 を超えるため切り詰め
        assert len(result) == 2
        first_content_len = len(result[0]["content"])
        second_content_len = len(result[1]["content"])
        # first は素通り、second は短く切り詰め + 省略マーカー
        assert first_content_len == 7000
        assert second_content_len < 5000
        assert "以降省略" in result[1]["content"]

    def test_max_files_constant_matches_spec(self) -> None:
        assert AttachmentProcessor.MAX_FILES == 5
        assert AttachmentProcessor.MAX_FILE_SIZE == 50_000
        assert AttachmentProcessor.MAX_TOTAL_CHARS == 10_000
        assert ".csv" in AttachmentProcessor.ALLOWED_EXTENSIONS
        assert ".py" in AttachmentProcessor.ALLOWED_EXTENSIONS
        assert ".png" not in AttachmentProcessor.ALLOWED_EXTENSIONS
