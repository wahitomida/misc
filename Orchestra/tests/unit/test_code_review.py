"""``features.code_review`` のスキャン系ユニットテスト (F-2 前半)。

LLM を呼ばないクラスのみを対象:
    - ``FolderScanner``
    - ``FileChunker``
    - ``PartLeaderAssigner``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.config_loader import Settings
from core.data_models import DiscussionLog, PartLeaderConfig, ScanResult
from features.code_review import (
    CONCERN_TO_MODEL,
    CONCERN_TO_ROLE,
    DEFAULT_HEADER_LINES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    FOCUS_PRESETS,
    FileChunker,
    FolderScanner,
    PartLeaderAssigner,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_sample_project(root: Path) -> None:
    """テスト用の小さなプロジェクトを ``root`` に作る。"""
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text(
        '"""エントリポイント。"""\n'
        "from . import utils\n\n"
        "def run():\n"
        "    return utils.add(1, 2)\n",
        encoding="utf-8",
    )
    (root / "src" / "utils.py").write_text(
        '"""ユーティリティ。"""\n'
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text(
        "def test_run():\n    assert True\n",
        encoding="utf-8",
    )
    # 除外されるべきファイル
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "main.cpython-313.pyc").write_text(
        "binary-ish", encoding="utf-8"
    )
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _make_sample_project(root)
    return root


def _settings(tmp_path: Path) -> Settings:
    """同梱の settings.yaml を読み込んだ Settings (.env なし)。"""
    return Settings.load(
        config_dir=Path(__file__).resolve().parents[2] / "config",
        env_file=tmp_path / "missing.env",
    )


# ===========================================================================
# FolderScanner
# ===========================================================================


class TestFolderScannerInit:
    def test_uses_defaults_when_no_settings(self) -> None:
        scanner = FolderScanner(settings=None)
        assert scanner.max_file_size == DEFAULT_MAX_FILE_SIZE_BYTES
        assert scanner.header_lines == DEFAULT_HEADER_LINES
        assert "*.pyc" in scanner.ignore_patterns

    def test_reads_from_settings(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        scanner = FolderScanner(settings=settings)
        # 同梱の settings.yaml は max_file_size_bytes = 1048576, header_lines = 50
        assert scanner.max_file_size == 1_048_576
        assert scanner.header_lines == 50


class TestFolderScannerScan:
    def test_basic_scan_lists_source_files(self, sample_project: Path) -> None:
        scanner = FolderScanner(settings=None)
        result = scanner.scan(sample_project)

        assert isinstance(result, ScanResult)
        paths = sorted(f["path"] for f in result.file_tree)
        # __pycache__/*.pyc と .git/ は除外される
        for path in paths:
            assert ".git" not in path
            assert "__pycache__" not in path
            assert not path.endswith(".pyc")
        assert "src/main.py" in paths
        assert "src/utils.py" in paths
        assert "tests/test_main.py" in paths

    def test_total_counts(self, sample_project: Path) -> None:
        scanner = FolderScanner(settings=None)
        result = scanner.scan(sample_project)

        assert result.total_files == 3
        assert result.total_lines > 0

    def test_each_file_has_header_and_size(self, sample_project: Path) -> None:
        scanner = FolderScanner(settings=None)
        result = scanner.scan(sample_project)

        for f in result.file_details:
            assert f["size_bytes"] > 0
            assert isinstance(f["lines"], int)
            assert "header" in f

    def test_extra_ignores_are_respected(self, sample_project: Path) -> None:
        scanner = FolderScanner(settings=None)
        result = scanner.scan(sample_project, extra_ignores=["tests/*"])

        paths = [f["path"] for f in result.file_tree]
        assert all("tests/" not in p for p in paths)

    def test_oversized_file_is_marked_skipped(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        small = root / "small.py"
        small.write_text("a = 1\n", encoding="utf-8")
        big = root / "big.py"
        big.write_text("x = '" + "y" * 200 + "'\n", encoding="utf-8")

        scanner = FolderScanner(settings=None)
        scanner.max_file_size = 50  # 強制的に小さく
        result = scanner.scan(root)

        skipped_paths = [f["path"] for f in result.skipped_files]
        assert "big.py" in skipped_paths
        # details には skipped ファイルは含まれない
        detail_paths = [f["path"] for f in result.file_details]
        assert "big.py" not in detail_paths
        assert "small.py" in detail_paths

    def test_header_lines_limit(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        (root / "big.py").write_text(
            "\n".join(f"line {i}" for i in range(100)) + "\n",
            encoding="utf-8",
        )

        scanner = FolderScanner(settings=None)
        scanner.header_lines = 5
        result = scanner.scan(root)

        header = result.file_details[0]["header"]
        # 最初の 5 行のみ
        assert "line 0" in header
        assert "line 4" in header
        assert "line 5" not in header

    def test_nonexistent_target_returns_empty(self, tmp_path: Path) -> None:
        scanner = FolderScanner(settings=None)
        result = scanner.scan(tmp_path / "does_not_exist")

        assert result.total_files == 0
        assert result.file_tree == []

    def test_empty_directory_returns_empty_scan(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        scanner = FolderScanner(settings=None)
        result = scanner.scan(root)

        assert result.total_files == 0
        assert result.file_details == []


class TestFolderScannerInternal:
    def test_count_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("a\nb\nc\n", encoding="utf-8")
        scanner = FolderScanner(settings=None)
        assert scanner._count_lines(f) == 3

    def test_count_lines_returns_zero_on_error(self, tmp_path: Path) -> None:
        scanner = FolderScanner(settings=None)
        assert scanner._count_lines(tmp_path / "missing.txt") == 0

    def test_read_header_handles_missing_file(self, tmp_path: Path) -> None:
        scanner = FolderScanner(settings=None)
        assert scanner._read_header(tmp_path / "missing.py") == ""


# ===========================================================================
# FileChunker
# ===========================================================================


class TestFileChunkerEmpty:
    def test_empty_content_returns_single_chunk(self) -> None:
        chunker = FileChunker()
        chunks = chunker.chunk_file("", "src/empty.py")
        assert len(chunks) == 1
        assert chunks[0]["content"] == ""


class TestFileChunkerAST:
    def test_splits_functions_and_classes(self) -> None:
        content = (
            "def foo():\n    return 1\n\n"
            "class Bar:\n    def __init__(self):\n        self.x = 1\n\n"
            "async def baz():\n    return 2\n"
        )
        chunker = FileChunker()
        chunks = chunker.chunk_file(content, "src/sample.py")

        kinds = {c["type"] for c in chunks}
        # FunctionDef / ClassDef / AsyncFunctionDef すべて存在
        assert "FunctionDef" in kinds
        assert "ClassDef" in kinds
        assert "AsyncFunctionDef" in kinds
        names = {c.get("name") for c in chunks}
        assert {"foo", "Bar", "baz"}.issubset(names)

    def test_syntax_error_falls_back_to_line_split(self) -> None:
        # Python 構文として壊れているコード
        bad = "def foo(:\n    return 1\n"
        chunker = FileChunker()
        chunks = chunker.chunk_file(bad, "src/broken.py")
        # フォールバック → 行ベース
        assert all(c["type"] == "lines" for c in chunks)
        assert chunks[0]["content"] != ""

    def test_module_level_only_returns_single_chunk(self) -> None:
        """関数もクラスも無いモジュールはファイル全体を 1 チャンク。"""
        content = "x = 1\ny = 2\nz = x + y\n"
        chunker = FileChunker()
        chunks = chunker.chunk_file(content, "src/constants.py")

        assert len(chunks) == 1
        assert chunks[0]["type"] == "module"

    def test_large_function_is_split_into_sub_chunks(self) -> None:
        """巨大な関数は ``max_tokens`` を超えると行ベースで細分化される。"""
        body = "\n".join(f"    x = '{ 'a' * 200 }'  # line {i}" for i in range(200))
        content = f"def huge():\n{body}\n"
        # max_tokens を小さくしてサブ分割を強制発火
        chunker = FileChunker(max_tokens_per_chunk=100)
        chunks = chunker.chunk_file(content, "src/huge.py")

        # 複数の "lines" チャンクに細分化されている
        assert len(chunks) >= 2
        assert all(c["type"] == "lines" for c in chunks)
        # 親情報が付加されている
        assert any(c.get("parent_name") == "huge" for c in chunks)


class TestFileChunkerLines:
    def test_non_python_file_uses_line_split(self) -> None:
        content = "\n".join(f"line{i}" for i in range(450))
        chunker = FileChunker()
        chunks = chunker.chunk_file(content, "data/sample.txt")

        assert all(c["type"] == "lines" for c in chunks)
        assert all(c["file"] == "data/sample.txt" for c in chunks)
        # 200 行ずつなので 3 チャンク (450 / 200)
        assert len(chunks) == 3
        # 行番号情報
        assert chunks[0]["lines"].startswith("L1-")
        assert "L201-" in chunks[1]["lines"]

    def test_line_chunks_cover_all_lines(self) -> None:
        content = "\n".join(str(i) for i in range(10))
        chunker = FileChunker()
        chunks = chunker.chunk_file(content, "x.txt")

        reconstructed = "\n".join(c["content"] for c in chunks)
        assert reconstructed == content


# ===========================================================================
# PartLeaderAssigner
# ===========================================================================


def _scan_result(paths: list[str]) -> ScanResult:
    """テスト用 ScanResult ビルダー。"""
    details = [
        {"path": p, "size_bytes": 100, "extension": Path(p).suffix, "lines": 10}
        for p in paths
    ]
    return ScanResult(
        target_path=Path("/tmp/dummy"),
        file_tree=details,
        file_details=details,
        total_files=len(paths),
        total_lines=10 * len(paths),
    )


class TestPartLeaderAssignerConstants:
    def test_focus_presets_keys(self) -> None:
        assert set(FOCUS_PRESETS.keys()) == {
            "all",
            "pre_submission",
            "performance",
            "structure",
            "handover",
            "algorithm",
        }

    def test_concern_to_role_complete(self) -> None:
        expected_concerns = {
            "algorithm",
            "reproducibility",
            "performance",
            "structure",
            "readability",
            "results",
        }
        assert set(CONCERN_TO_ROLE.keys()) == expected_concerns
        assert set(CONCERN_TO_MODEL.keys()) == expected_concerns


class TestPartLeaderAssignerAssign:
    def test_assign_all_focus_yields_six_leaders(self) -> None:
        scan = _scan_result(["src/main.py", "src/utils.py"])
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="all")

        assert len(leaders) == 6
        concerns = {l.concern for l in leaders}
        assert concerns == {
            "algorithm",
            "reproducibility",
            "performance",
            "structure",
            "readability",
            "results",
        }
        # 全員 weight=1.0 → level=medium
        assert all(l.level == "medium" for l in leaders)

    def test_assign_performance_focus_skips_low_weight(self) -> None:
        scan = _scan_result(["src/main.py"])
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="performance")

        concerns = {l.concern for l in leaders}
        # weight < 0.3 (reproducibility, readability は 0.3) → 含まれる
        # weight 0.3 はスキップ閾値ぴったり (strict <) なので含まれる
        # 含まれないのは weight < 0.3 のみ
        assert "performance" in concerns
        assert "structure" in concerns
        # weight=0.3 のものはギリギリ含まれる
        assert "reproducibility" in concerns
        assert "readability" in concerns

    def test_assign_uses_correct_role_and_model_mapping(self) -> None:
        scan = _scan_result(["src/main.py"])
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="all")
        by_concern = {l.concern: l for l in leaders}

        assert by_concern["algorithm"].role_id == "theorist"
        assert by_concern["algorithm"].model == "gpt-5.4"
        assert by_concern["structure"].role_id == "code_architect"
        assert by_concern["structure"].model == "gpt-4.1"
        assert by_concern["readability"].role_id == "code_reviewer"
        assert by_concern["readability"].model == "gpt-4.1-mini"

    def test_unknown_focus_falls_back_to_all(self) -> None:
        scan = _scan_result(["src/main.py"])
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="unknown_focus_xyz")

        # all と同じ 6 リーダー
        assert len(leaders) == 6

    def test_high_weight_assigns_all_files(self) -> None:
        scan = _scan_result(["src/main.py", "src/utils.py", "tests/test_main.py"])
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="all")
        # weight=1.0 (>=1.0) → 全ファイル
        for leader in leaders:
            assert set(leader.assigned_files) == set(
                ["src/main.py", "src/utils.py", "tests/test_main.py"]
            )

    def test_low_weight_excludes_minor_files(self) -> None:
        """weight < 1.0 のリーダーには主要ファイルのみ。"""
        scan = _scan_result(
            ["src/main.py", "tests/test_main.py", "src/__init__.py"]
        )
        assigner = PartLeaderAssigner()

        leaders = assigner.assign(scan, focus="performance")
        # readability の weight=0.3 → 主要ファイルのみ (test_/__init__ 除外)
        readability = next(l for l in leaders if l.concern == "readability")
        assert "src/main.py" in readability.assigned_files
        assert all(
            "tests/" not in p and "__init__.py" not in p
            for p in readability.assigned_files
        )


class TestPartLeaderAssignerWeightToLevel:
    @pytest.mark.parametrize(
        ("weight", "expected"),
        [
            (2.0, "high"),
            (1.5, "high"),
            (1.49, "medium"),
            (1.0, "medium"),
            (0.99, "low"),
            (0.5, "low"),
            (0.3, "low"),
        ],
    )
    def test_thresholds(self, weight: float, expected: str) -> None:
        assert PartLeaderAssigner._weight_to_level(weight) == expected


# ===========================================================================
# INVESTIGATION_PROMPTS / CROSS_QUESTION_PAIRS
# ===========================================================================


class TestInvestigationPrompts:
    """``INVESTIGATION_PROMPTS`` の構造検証 (LLM 呼び出しなし)。"""

    def test_has_six_concerns(self) -> None:
        from features.code_review import INVESTIGATION_PROMPTS

        assert set(INVESTIGATION_PROMPTS.keys()) == {
            "algorithm",
            "reproducibility",
            "performance",
            "structure",
            "readability",
            "results",
        }

    def test_each_prompt_contains_file_content_placeholder(self) -> None:
        from features.code_review import INVESTIGATION_PROMPTS

        for concern, prompt in INVESTIGATION_PROMPTS.items():
            assert "{file_content}" in prompt, (
                f"{concern} prompt missing {{file_content}}"
            )

    def test_prompt_can_be_formatted(self) -> None:
        """``str.format`` で実体を入れられること (escape のミスがない)。"""
        from features.code_review import INVESTIGATION_PROMPTS

        for concern, prompt in INVESTIGATION_PROMPTS.items():
            formatted = prompt.format(file_content="x = 1\n")
            assert "x = 1" in formatted


class TestCrossQuestionPairs:
    """``CROSS_QUESTION_PAIRS`` 定義の妥当性。"""

    def test_has_nine_pairs(self) -> None:
        from features.code_review import CROSS_QUESTION_PAIRS

        assert len(CROSS_QUESTION_PAIRS) == 9

    def test_each_pair_has_three_strings(self) -> None:
        from features.code_review import CROSS_QUESTION_PAIRS

        for pair in CROSS_QUESTION_PAIRS:
            assert len(pair) == 3
            assert all(isinstance(s, str) and s for s in pair)

    def test_concerns_are_valid(self) -> None:
        """asker/answerer が ``CONCERN_TO_ROLE`` のキーに含まれる。"""
        from features.code_review import CROSS_QUESTION_PAIRS

        valid = set(CONCERN_TO_ROLE.keys())
        for asker, answerer, _hint in CROSS_QUESTION_PAIRS:
            assert asker in valid, f"unknown asker concern: {asker}"
            assert answerer in valid, f"unknown answerer concern: {answerer}"


# ===========================================================================
# CrossQuestioner
# ===========================================================================


def _make_cross_questioner(
    tmp_path: Path,
    responses: list[dict[str, Any]],
    *,
    max_rounds: int | None = None,
):
    """テスト用 CrossQuestioner を組み立てる。"""
    from core.api_client import ResilientAPIClient, RetryConfig
    from core.rate_tracker import RateLimitTracker
    from features.code_review import CrossQuestioner
    from tests.mocks.mock_api import MockAPIClient

    mock = MockAPIClient(responses=responses)
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )

    settings = _settings(tmp_path)
    if max_rounds is not None:
        settings.code_review["cross_question_max_rounds"] = max_rounds

    return CrossQuestioner(api_client=client, settings=settings), mock


def _sample_finding(concern: str, severity: str = "warning") -> dict[str, Any]:
    return {
        "severity": severity,
        "file": f"src/{concern}.py",
        "line": "L10-20",
        "title": f"{concern} の所見",
        "problem": "(problem)",
        "fix_suggestion": "(fix)",
    }


class TestCrossQuestionerInit:
    def test_reads_max_rounds_from_settings(self, tmp_path: Path) -> None:
        from features.code_review import CrossQuestioner

        questioner, _ = _make_cross_questioner(tmp_path, responses=[])
        assert isinstance(questioner, CrossQuestioner)
        # 同梱の settings.yaml では cross_question_max_rounds = 5
        assert questioner.max_rounds == 5

    def test_max_rounds_can_be_overridden(self, tmp_path: Path) -> None:
        questioner, _ = _make_cross_questioner(
            tmp_path, responses=[], max_rounds=2
        )
        assert questioner.max_rounds == 2


class TestSelectRelevantPairs:
    def test_returns_pairs_with_both_sides_findings(self, tmp_path: Path) -> None:
        questioner, _ = _make_cross_questioner(tmp_path, responses=[])
        findings = {
            "algorithm": [_sample_finding("algorithm")],
            "results": [_sample_finding("results")],
            "performance": [_sample_finding("performance")],
        }
        pairs = questioner._select_relevant_pairs(findings)

        # 全ペアが両 concern とも findings あり
        for asker, answerer, _hint in pairs:
            assert findings.get(asker)
            assert findings.get(answerer)

        # 少なくとも 1 つのペア (algorithm <-> results 双方向) は採用される
        asker_set = {asker for asker, _, _ in pairs}
        assert "algorithm" in asker_set
        assert "results" in asker_set

    def test_skips_pairs_with_missing_findings(self, tmp_path: Path) -> None:
        """片方しか findings がないペアは選ばれない。"""
        questioner, _ = _make_cross_questioner(tmp_path, responses=[])
        findings = {"algorithm": [_sample_finding("algorithm")]}
        pairs = questioner._select_relevant_pairs(findings)
        assert pairs == []

    def test_max_rounds_limit_is_applied(self, tmp_path: Path) -> None:
        questioner, _ = _make_cross_questioner(
            tmp_path, responses=[], max_rounds=2
        )
        # 6 concern 全てに findings → 9 候補ペア全部が relevant
        findings = {
            concern: [_sample_finding(concern)]
            for concern in CONCERN_TO_ROLE.keys()
        }
        pairs = questioner._select_relevant_pairs(findings)
        assert len(pairs) == 2


class TestGenerateQuestion:
    @pytest.mark.asyncio
    async def test_returns_llm_text(self, tmp_path: Path) -> None:
        questioner, mock = _make_cross_questioner(
            tmp_path,
            responses=[{"content": "正規化の有無で出力はどう変わりますか？"}],
        )
        question = await questioner._generate_question(
            asker="algorithm",
            answerer="results",
            asker_findings=[_sample_finding("algorithm")],
            answerer_findings=[_sample_finding("results")],
            hint="正規化のテスト",
        )
        assert question == "正規化の有無で出力はどう変わりますか？"
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self, tmp_path: Path) -> None:
        questioner, _ = _make_cross_questioner(
            tmp_path, responses=[{"content": ""}]
        )
        question = await questioner._generate_question(
            asker="algorithm",
            answerer="results",
            asker_findings=[],
            answerer_findings=[],
            hint="(hint)",
        )
        assert question == ""


class TestGetAnswer:
    @pytest.mark.asyncio
    async def test_returns_llm_text(self, tmp_path: Path) -> None:
        questioner, mock = _make_cross_questioner(
            tmp_path, responses=[{"content": "テストで確認済みです"}]
        )
        answer = await questioner._get_answer(
            answerer="results",
            question="テストはありますか？",
            context=[_sample_finding("results")],
        )
        assert answer == "テストで確認済みです"
        mock.assert_call_count(1)


class TestCrossQuestionerRun:
    @pytest.mark.asyncio
    async def test_enriches_findings_with_info_entries(
        self, tmp_path: Path
    ) -> None:
        # 1 ペアのみに findings → relevant_pairs は 1 件
        # (algorithm, results) のみ
        findings = {
            "algorithm": [_sample_finding("algorithm")],
            "results": [_sample_finding("results")],
        }
        # 質問 → 回答 → 質問 → 回答 (algorithm→results と results→algorithm)
        responses = [
            {"content": "正規化の有無を確認する質問"},  # q1
            {"content": "テスト済みです"},  # a1
            {"content": "差分の原因を確認する質問"},  # q2
            {"content": "そこは確認が必要"},  # a2
        ]
        questioner, _ = _make_cross_questioner(tmp_path, responses=responses)
        leaders: list[Any] = []

        enriched = await questioner.run(findings, leaders)

        # 元 findings は破壊されない
        assert findings["algorithm"][0]["title"] == "algorithm の所見"
        # asker_concern に info エントリが追加される
        algo_info = [
            f for f in enriched["algorithm"] if f.get("severity") == "info"
        ]
        results_info = [
            f for f in enriched["results"] if f.get("severity") == "info"
        ]
        assert len(algo_info) >= 1
        assert "question" in algo_info[0]
        assert "answer" in algo_info[0]
        assert algo_info[0]["source"].startswith("cross_question_")

    @pytest.mark.asyncio
    async def test_skip_question_marker_drops_pair(self, tmp_path: Path) -> None:
        """LLM が「特になし」を返したペアは追加されない。"""
        findings = {
            "algorithm": [_sample_finding("algorithm")],
            "results": [_sample_finding("results")],
        }
        responses = [
            {"content": "特になし"},  # q1: skip
            {"content": "差分の原因を確認"},  # q2
            {"content": "確認が必要"},  # a2
        ]
        questioner, _ = _make_cross_questioner(tmp_path, responses=responses)

        enriched = await questioner.run(findings, leaders=[])

        # algorithm はスキップ、results 側のみ info 追加
        algo_info = [
            f for f in enriched["algorithm"] if f.get("severity") == "info"
        ]
        results_info = [
            f for f in enriched["results"] if f.get("severity") == "info"
        ]
        assert algo_info == []
        assert len(results_info) == 1

    @pytest.mark.asyncio
    async def test_empty_findings_returns_empty_enriched(
        self, tmp_path: Path
    ) -> None:
        questioner, mock = _make_cross_questioner(tmp_path, responses=[])

        enriched = await questioner.run({}, leaders=[])

        assert enriched == {}
        # 1 度も API は呼ばれない
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_does_not_mutate_input_findings(self, tmp_path: Path) -> None:
        findings = {
            "algorithm": [_sample_finding("algorithm")],
            "results": [_sample_finding("results")],
        }
        responses = [
            {"content": "質問1"},
            {"content": "回答1"},
            {"content": "質問2"},
            {"content": "回答2"},
        ]
        questioner, _ = _make_cross_questioner(tmp_path, responses=responses)
        original_lens = {k: len(v) for k, v in findings.items()}

        await questioner.run(findings, leaders=[])

        # 入力辞書のリスト長は不変
        for k, length in original_lens.items():
            assert len(findings[k]) == length

    @pytest.mark.asyncio
    async def test_format_findings_with_empty_list(self) -> None:
        """``_format_findings`` は空リストでも安全 (LLM 呼び出しなし)。"""
        from features.code_review import CrossQuestioner

        assert CrossQuestioner._format_findings([]) == "(所見なし)"

    @pytest.mark.asyncio
    async def test_format_findings_truncates_long_list(self) -> None:
        from features.code_review import CrossQuestioner

        many = [_sample_finding("performance") for _ in range(8)]
        formatted = CrossQuestioner._format_findings(many)
        assert "他 3 件" in formatted

    @pytest.mark.asyncio
    async def test_is_skip_detects_japanese_markers(self) -> None:
        from features.code_review import CrossQuestioner

        assert CrossQuestioner._is_skip("特になし") is True
        assert CrossQuestioner._is_skip("質問は特になしです") is True
        assert CrossQuestioner._is_skip("skip") is True
        assert CrossQuestioner._is_skip("正規化はどうしてますか？") is False


# ===========================================================================
# CodeReview (F-2c: Phase 1-2 統合)
# ===========================================================================


def _make_code_review(
    tmp_path: Path,
    responses: list[dict[str, Any]] | None = None,
):
    """テスト用 CodeReview インスタンスを組み立てる (mock LLM 付き)。"""
    from core.api_client import ResilientAPIClient, RetryConfig
    from core.feedback import FeedbackManager
    from core.rate_tracker import RateLimitTracker
    from core.role_manager import RoleManager
    from features.code_review import CodeReview
    from tests.mocks.mock_api import MockAPIClient

    mock = MockAPIClient(responses=responses or [])
    tracker = RateLimitTracker(persistence_path=tmp_path / "rate.json")
    client = ResilientAPIClient(
        base_client=mock,
        rate_tracker=tracker,
        retry_config=RetryConfig(base_delay_sec=0.001, max_delay_sec=0.005),
        mode="openai",
    )
    settings = _settings(tmp_path)
    role_manager = RoleManager(
        roles_dir=Path(__file__).resolve().parents[2] / "config" / "roles"
    )
    feedback_manager = FeedbackManager(
        roles_dir=Path(__file__).resolve().parents[2] / "config" / "roles"
    )
    code_review = CodeReview(
        api_client=client,
        role_manager=role_manager,
        feedback_manager=feedback_manager,
        settings=settings,
    )
    return code_review, mock


def _findings_json(concern: str) -> str:
    """``_parse_findings`` でパース可能な JSON 文字列を作る。"""
    return (
        '{"findings": [{"severity": "warning", "file": "src/main.py", '
        f'"line": "L1-2", "title": "{concern} issue", '
        '"problem": "p", "fix_suggestion": "f", "impact": "i"}]}'
    )


class TestCodeReviewInit:
    def test_constructs_internal_helpers(self, tmp_path: Path) -> None:
        from features.code_review.assigner import PartLeaderAssigner
        from features.code_review.chunker import FileChunker
        from features.code_review.scanner import FolderScanner

        cr, _ = _make_code_review(tmp_path)

        assert isinstance(cr._scanner, FolderScanner)
        assert isinstance(cr._chunker, FileChunker)
        assert isinstance(cr._assigner, PartLeaderAssigner)
        assert cr.settings is not None
        assert cr.role_manager is not None
        assert cr.feedback_manager is not None


class TestCodeReviewPhase1Scan:
    @pytest.mark.asyncio
    async def test_phase1_returns_scan_result(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(tmp_path)

        result = await cr._phase1_scan(
            target_path=sample_project,
            planner_model="gpt-5.4",
            ignore_patterns=None,
        )

        assert isinstance(result, ScanResult)
        assert result.total_files == 3
        # Phase 1 は LLM を呼ばない
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_phase1_respects_extra_ignore_patterns(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(tmp_path)

        result = await cr._phase1_scan(
            target_path=sample_project,
            planner_model="gpt-5.4",
            ignore_patterns=["tests/*"],
        )

        paths = [f["path"] for f in result.file_tree]
        assert all("tests/" not in p for p in paths)


class TestCodeReviewPhase2Investigate:
    @pytest.mark.asyncio
    async def test_investigate_returns_findings_per_concern(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        # focus=all → 6 リーダー全部 → 6 LLM 呼び出し
        responses = [
            {"content": _findings_json(c)}
            for c in [
                "algorithm",
                "reproducibility",
                "performance",
                "structure",
                "readability",
                "results",
            ]
        ]
        cr, mock = _make_code_review(tmp_path, responses=responses)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        findings = await cr._phase2_investigate(scan, focus="all")

        assert set(findings.keys()) == {
            "algorithm",
            "reproducibility",
            "performance",
            "structure",
            "readability",
            "results",
        }
        # 各 concern につき 1 findings (固定 JSON で生成)
        for concern, items in findings.items():
            assert len(items) == 1
            assert items[0]["title"].startswith(concern)
        # 6 リーダー並列 → 6 回 LLM 呼び出し
        mock.assert_call_count(6)

    @pytest.mark.asyncio
    async def test_investigate_empty_scan_returns_empty_dict(
        self, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(tmp_path)
        empty_scan = ScanResult(target_path=tmp_path / "missing")

        findings = await cr._phase2_investigate(empty_scan, focus="all")

        # ファイルなし → 全リーダー空 findings
        assert all(v == [] for v in findings.values())
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_investigate_handles_invalid_json(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        responses = [{"content": "not a json"}] * 6
        cr, _ = _make_code_review(tmp_path, responses=responses)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        findings = await cr._phase2_investigate(scan, focus="all")

        # JSON パース失敗 → 全 concern が空
        assert all(items == [] for items in findings.values())

    @pytest.mark.asyncio
    async def test_investigate_uses_focus_to_select_leaders(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        # focus=performance → 6 concern (reproducibility/readability weight=0.3
        # は WEIGHT_SKIP_THRESHOLD(0.3) に対し strict < 判定で残る)
        responses = [{"content": _findings_json("dummy")}] * 6
        cr, mock = _make_code_review(tmp_path, responses=responses)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        findings = await cr._phase2_investigate(scan, focus="performance")

        # focus=performance プリセットの 6 concern 分が返る
        assert "performance" in findings
        assert "structure" in findings
        # weight=0.3 はギリギリ含まれる
        assert "reproducibility" in findings


class TestCodeReviewAutoDetectFocus:
    @pytest.mark.asyncio
    async def test_auto_detect_uses_llm_response(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(
            tmp_path, responses=[{"content": "pre_publication"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._auto_detect_focus(scan, planner_model="gpt-5.4")

        # pre_publication → pre_submission
        assert focus == "pre_submission"
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_auto_detect_unknown_state_falls_back_to_all(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(
            tmp_path, responses=[{"content": "unknown_state_xyz"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._auto_detect_focus(scan)
        assert focus == "all"

    @pytest.mark.asyncio
    async def test_auto_detect_maps_prototype_to_structure(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(
            tmp_path, responses=[{"content": "prototype"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._auto_detect_focus(scan)
        assert focus == "structure"

    @pytest.mark.asyncio
    async def test_auto_detect_maps_optimization_to_performance(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(
            tmp_path, responses=[{"content": "optimization"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._auto_detect_focus(scan)
        assert focus == "performance"

    @pytest.mark.asyncio
    async def test_auto_detect_empty_response_falls_back(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(tmp_path, responses=[{"content": ""}])
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._auto_detect_focus(scan)
        assert focus == "all"


class TestCodeReviewResolveFocus:
    @pytest.mark.asyncio
    async def test_explicit_focus_skips_llm(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(tmp_path)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._resolve_focus("pre_submission", scan, "gpt-5.4")
        assert focus == "pre_submission"
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_auto_marker_triggers_llm(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(
            tmp_path, responses=[{"content": "experimental"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._resolve_focus("auto", scan, "gpt-5.4")
        assert focus == "all"  # experimental → all
        mock.assert_call_count(1)

    @pytest.mark.asyncio
    async def test_none_focus_triggers_llm(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(
            tmp_path, responses=[{"content": "production"}]
        )
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        focus = await cr._resolve_focus(None, scan, "gpt-5.4")
        assert focus == "handover"  # production → handover
        mock.assert_call_count(1)


class TestCodeReviewPhase3:
    @pytest.mark.asyncio
    async def test_phase3_passthrough_for_empty_findings(
        self, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(tmp_path)
        out = await cr._phase3_cross_question({})
        assert out == {}
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_phase3_invokes_cross_questioner(
        self, tmp_path: Path
    ) -> None:
        # algorithm <-> results ペアのみ relevant
        responses = [
            {"content": "正規化の有無を確認したい"},
            {"content": "テスト済み"},
            {"content": "差分原因は？"},
            {"content": "未確認"},
        ]
        cr, mock = _make_code_review(tmp_path, responses=responses)
        findings = {
            "algorithm": [_sample_finding("algorithm")],
            "results": [_sample_finding("results")],
        }

        enriched = await cr._phase3_cross_question(findings)

        # info entry が追加されている
        algo_info = [
            f for f in enriched["algorithm"] if f.get("severity") == "info"
        ]
        assert len(algo_info) >= 1
        # CrossQuestioner が API を呼んだ
        assert mock.call_count >= 1


class TestCodeReviewPhase4:
    @pytest.mark.asyncio
    async def test_phase4_empty_findings_returns_empty_log(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        cr, mock = _make_code_review(tmp_path)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)

        result = await cr._phase4_meeting(
            scan, findings={}, focus="all", conductor_model="gpt-4.1"
        )
        assert isinstance(result.discussion_log, DiscussionLog)
        assert result.discussion_log.rounds == []
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_phase4_runs_meeting_with_findings(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        # findings あり → 全体会議 3 ラウンド (1 リーダー × 3 発言)
        # Round 1: one_shot (1 発言) + 収束判定 (1)
        # Round 2: free_talk (最大 8 発言) + 収束判定 (1)
        # Round 3: one_shot (1 発言) + 収束判定 (1)
        # 余裕を持って 40 件のレスポンスを準備
        responses = (
            [{"content": "アルゴリズム所見を共有します", "usage": {}}] * 30
            + [
                {"content": '{"score": 0.8, "reasoning": "ok"}', "usage": {}}
            ] * 10
        )
        cr, mock = _make_code_review(tmp_path, responses=responses)
        scan = await cr._phase1_scan(sample_project, "gpt-5.4", None)
        findings = {"algorithm": [_sample_finding("algorithm")]}

        result = await cr._phase4_meeting(
            scan, findings=findings, focus="all", conductor_model="gpt-4.1"
        )

        # 3 ラウンド構成
        assert len(result.discussion_log.rounds) == 3
        # 各ラウンドに少なくとも 1 発言
        assert all(
            len(r.public_utterances) >= 1
            for r in result.discussion_log.rounds
        )
        assert mock.call_count >= 4


class TestCodeReviewPhase5:
    @pytest.mark.asyncio
    async def test_phase5_writes_report_files(self, tmp_path: Path) -> None:
        from features.code_review.report_builder import build_review_plan

        cr, _ = _make_code_review(tmp_path)
        scan = ScanResult(
            target_path=tmp_path,
            total_files=2,
            total_lines=100,
            file_details=[
                {"path": "a.py", "size_bytes": 50, "extension": ".py",
                 "lines": 50, "header": '"""doc"""\n'},
                {"path": "b.py", "size_bytes": 50, "extension": ".py",
                 "lines": 50, "header": '"""doc"""\n'},
            ],
        )
        findings = {
            "algorithm": [
                {
                    "severity": "critical", "file": "a.py", "line": "L1-5",
                    "title": "正規化漏れ", "problem": "p1",
                    "fix_suggestion": "f1", "impact": "i1",
                }
            ],
            "performance": [
                {
                    "severity": "warning", "file": "b.py", "line": "L10-20",
                    "title": "O(N^2) ループ", "problem": "p2",
                    "fix_suggestion": "f2",
                }
            ],
        }

        output_dir = tmp_path / "out"
        session_dir = await cr._phase5_report(
            scan_result=scan,
            findings=findings,
            discussion_log=DiscussionLog(),
            focus="all",
            output_dir=output_dir,
        )

        assert session_dir.exists()
        assert session_dir.parent == output_dir
        # 必須ファイル
        for name in (
            "report.md",
            "vibe_coding_prompt.md",
            "evaluation.md",
            "summary.txt",
            "session_meta.json",
            "full_conversation.md",
            "discussion.json",
        ):
            assert (session_dir / name).exists(), f"missing {name}"
        # report.md に Critical / 正規化漏れ が含まれる
        report_content = (session_dir / "report.md").read_text(encoding="utf-8")
        assert "Critical" in report_content
        assert "正規化漏れ" in report_content
        # vibe_coding_prompt.md にタスク
        vibe_content = (
            session_dir / "vibe_coding_prompt.md"
        ).read_text(encoding="utf-8")
        assert "Task 1" in vibe_content
        assert "正規化漏れ" in vibe_content
        # session_meta.json は code_review タイプ
        meta = (session_dir / "session_meta.json").read_text(encoding="utf-8")
        assert "code_review" in meta

    @pytest.mark.asyncio
    async def test_phase5_with_empty_findings_still_writes_files(
        self, tmp_path: Path
    ) -> None:
        cr, _ = _make_code_review(tmp_path)
        scan = ScanResult(target_path=tmp_path, total_files=1, total_lines=10)
        output_dir = tmp_path / "out"

        session_dir = await cr._phase5_report(
            scan_result=scan,
            findings={},
            discussion_log=DiscussionLog(),
            focus="all",
            output_dir=output_dir,
        )

        assert session_dir.exists()
        # 課題なしでも report.md は作られる
        report = (session_dir / "report.md").read_text(encoding="utf-8")
        assert "検出された課題はありません" in report
        # vibe_coding_prompt.md も作られる
        vibe = (
            session_dir / "vibe_coding_prompt.md"
        ).read_text(encoding="utf-8")
        assert "修正タスクはありません" in vibe


class TestCodeReviewRunFlow:
    @pytest.mark.asyncio
    async def test_run_executes_full_flow_returns_session_dir(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        """Phase 1-5 が走り切ってセッションディレクトリが返る。"""
        # focus="all" 明示 → Phase 1: 0 / Phase 2: 6 (6 リーダー並列調査)
        # Phase 3: 最大 5 ペア × 2 (Q+A) = 10
        # Phase 4: 6 役 (重複排除で 5) × 3 ラウンド + 3 収束判定 = 最大 30 強
        # Phase 5: 評価 (役×1) + 指揮者評価 (1) = 最大 6
        # → 余裕を持って多めにレスポンス用意
        responses = [{"content": _findings_json(f"c{i}")} for i in range(6)]
        responses += [
            {"content": "質問", "usage": {}},
            {"content": "回答", "usage": {}},
        ] * 12  # Phase 3 質問+回答
        responses += [
            {"content": "全体会議発言", "usage": {}}
        ] * 60  # Phase 4 発言 (3 ラウンド分余裕)
        responses += [
            {"content": '{"score": 0.8, "reasoning": "ok"}', "usage": {}}
        ] * 10  # Phase 4 収束判定 + Phase 5 評価フォールバック
        output_dir = tmp_path / "out"
        cr, _ = _make_code_review(tmp_path, responses=responses)

        result = await cr.run(
            target_path=sample_project,
            focus="all",
            output_dir=output_dir,
        )

        assert isinstance(result, Path)
        assert result.exists()
        assert result.parent == output_dir
        assert (result / "report.md").exists()
        assert (result / "vibe_coding_prompt.md").exists()

    @pytest.mark.asyncio
    async def test_run_empty_target_short_circuits(
        self, tmp_path: Path
    ) -> None:
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        cr, mock = _make_code_review(tmp_path)

        result = await cr.run(target_path=empty_root, focus="all")

        assert result is None
        # ファイルなし → Phase 2 以降スキップ → LLM 呼び出しなし
        mock.assert_call_count(0)

    @pytest.mark.asyncio
    async def test_run_with_auto_focus_calls_llm_for_detection(
        self, sample_project: Path, tmp_path: Path
    ) -> None:
        # auto focus → 推定 1 回。Phase 2: 6, 後続で十分な mock を準備
        responses = [{"content": "experimental"}]  # auto focus 推定
        responses += [{"content": _findings_json(f"c{i}")} for i in range(6)]
        responses += [{"content": "x", "usage": {}}] * 30  # Phase 3-4 余裕分
        responses += [
            {"content": '{"score": 0.8, "reasoning": "ok"}', "usage": {}}
        ] * 4
        output_dir = tmp_path / "out"
        cr, _ = _make_code_review(tmp_path, responses=responses)

        result = await cr.run(
            target_path=sample_project, focus="auto", output_dir=output_dir
        )

        assert isinstance(result, Path)
        assert result.exists()
        # report.md が存在
        assert (result / "report.md").exists()


