"""Code Review API (計画立案 + SSE ストリーミング実行)。

エンドポイント:
    - POST /api/review/plan   — Phase 1 (スキャン + 計画立案) → JSON
    - POST /api/review/stream — Phase 2-5 を SSE で配信

設計書:
    - doc/ui/10_web_api.md §4
    - doc/ui/05_review_page.md §8
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.rate_tracker import RateLimitTracker
from features.code_review.scanner import FolderScanner
from web.deps import SCRIPT_DIR, get_feedback_manager, get_rate_tracker

logger = logging.getLogger(__name__)

# --- Constants ---
MIN_TIME_LIMIT_SEC = 60
MAX_TIME_LIMIT_SEC = 1800
MIN_AGENTS = 2
MAX_AGENTS = 8
SSE_KEEPALIVE_SEC = 30.0
SSE_QUEUE_MAXSIZE = 1000
MAX_CONCURRENT_SESSIONS = 3
MOCK_EVENT_DELAY_SEC = 0.3
# 会議 mock: 発言表示 duration をエージェント/ラウンド間で統一する
# (旧: 1.2 + phase_index * 0.3 で Round 1 と Round 5 の差が 2 倍近く出ていた)
MOCK_UTTERANCE_DURATION_SEC = 1.5
MOCK_ESTIMATED_REQUESTS = 60

FocusValue = Literal[
    "all", "pre_submission", "performance",
    "structure", "handover", "algorithm",
]

# 6 アスペクト × ロール割当
_REVIEW_ASPECTS: tuple[dict[str, str], ...] = (
    {"aspect": "algorithm", "aspect_label": "アルゴリズム",
     "role_id": "theorist", "role_name": "理論屋", "emoji": "🧮"},
    {"aspect": "reproducibility", "aspect_label": "再現性",
     "role_id": "experimentalist", "role_name": "実験屋", "emoji": "🔬"},
    {"aspect": "performance", "aspect_label": "性能",
     "role_id": "implementer", "role_name": "実装屋", "emoji": "🤖"},
    {"aspect": "structure", "aspect_label": "構造",
     "role_id": "code_architect", "role_name": "設計リーダー", "emoji": "📐"},
    {"aspect": "readability", "aspect_label": "可読性",
     "role_id": "code_reviewer", "role_name": "可読性LD", "emoji": "📝"},
    {"aspect": "results", "aspect_label": "結果検証",
     "role_id": "experimentalist", "role_name": "実験屋", "emoji": "🔬"},
)

_MOCK_TREE_TEXT = (
    "src/\n├── main.py\n├── core/\n│   ├── agent.py\n│   ├── conductor.py\n"
    "│   └── synthesizer.py\n├── utils/\n│   ├── logger.py\n"
    "│   └── config.py\n└── config.yaml\n"
)

_MOCK_FILES: tuple[dict[str, Any], ...] = tuple(
    {"path": p, "extension": ext, "size_bytes": sz, "lines": ln, "header": hd}
    for p, ext, sz, ln, hd in (
        ("src/main.py",             ".py",   1250, 45,  "import typer\nfrom core..."),
        ("src/core/agent.py",       ".py",   3200, 120, "class Agent:\n    def __init__..."),
        ("src/core/conductor.py",   ".py",   4100, 180, "class Conductor:\n    async def..."),
        ("src/core/synthesizer.py", ".py",   2800, 110, "class Synthesizer:\n    ..."),
        ("src/utils/logger.py",     ".py",   650,  30,  "import logging\n..."),
        ("src/utils/config.py",     ".py",   1400, 60,  "@dataclass\nclass Settings:\n..."),
        ("src/config.yaml",         ".yaml", 800,  35,  "models:\n  planner: gpt-5.4\n..."),
        ("src/rate_config.yaml",    ".yaml", 400,  20,  "daily_limit: 10000\n..."),
    )
)

# 同時実行セッション数を制限するセマフォ (idea 側と独立)
_review_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)

router = APIRouter(prefix="/api/review", tags=["review"])


# --- Request models ---


class ReviewPlanRequest(BaseModel):
    """POST /api/review/plan のリクエスト。"""

    target_path: str
    planner_model: str = "gpt-5.4"
    conductor_model: str = "gpt-4.1"
    synth_model: str = "gpt-5.4"
    time_limit: int = Field(600, ge=MIN_TIME_LIMIT_SEC, le=MAX_TIME_LIMIT_SEC)
    max_agents: int = Field(6, ge=MIN_AGENTS, le=MAX_AGENTS)
    focus: FocusValue = "all"
    ignore_patterns: list[str] = Field(default_factory=list)


class ReviewStreamRequest(BaseModel):
    """POST /api/review/stream のリクエスト。"""

    scan_result: dict[str, Any]
    part_leaders: list[dict[str, Any]]
    target_path: str
    conductor_model: str = "gpt-4.1"
    synth_model: str = "gpt-5.4"
    time_limit: int = Field(600, ge=MIN_TIME_LIMIT_SEC, le=MAX_TIME_LIMIT_SEC)
    focus: str = "all"


# --- POST /api/review/plan ---


@router.post("/plan")
async def plan_review(
    request: ReviewPlanRequest,
    rate_tracker: RateLimitTracker = Depends(get_rate_tracker),
) -> dict[str, Any]:
    """実スキャン + 計画立案結果を返す。

    Raises:
        HTTPException: 400 (パス不正 / 存在しない / ディレクトリでない)。
    """
    _validate_target_path(request.target_path)
    try:
        scan_result = _scan_folder_real(
            request.target_path,
            ignore_patterns=list(request.ignore_patterns or []),
        )
    except Exception as e:  # noqa: BLE001 - スキャン失敗を 500 で返す
        logger.exception("Folder scan failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"フォルダのスキャンに失敗しました: {e}",
        ) from e
    return {
        "scan_result": scan_result,
        "part_leaders": _build_mock_part_leaders(),
        "estimated_requests": MOCK_ESTIMATED_REQUESTS,
        "remaining_quota": rate_tracker.remaining(),
    }


# --- GET /api/review/browse: フォルダブラウザ (UI モーダル用) ---


@router.get("/browse")
async def browse_folder(path: str | None = None) -> dict[str, Any]:
    """指定パスの子ディレクトリ一覧を返す (Review UI フォルダピッカー用)。

    Args:
        path: ブラウズ対象のパス。None ならデフォルト候補 (CWD / Home /
            Home 直下の代表フォルダ) を返す。

    Returns:
        ``{current_path, parent_path, entries, quick_paths}``:
            - current_path: 現在ブラウズしているパスの絶対パス
            - parent_path: 親ディレクトリの絶対パス (ルートなら None)
            - entries: 子ディレクトリのリスト (``[{name, path, is_dir}]``)
            - quick_paths: よく使う候補 (path 未指定時のみ返す)

    Raises:
        HTTPException 400: パストラバーサル / 不正パス。
        HTTPException 403: アクセス権限エラー。
        HTTPException 404: パスが存在しない。
    """
    # 未指定: デフォルト候補を返す
    if not path:
        quick_paths = _default_quick_paths()
        return {
            "current_path": "",
            "parent_path": None,
            "entries": [],
            "quick_paths": quick_paths,
        }

    # パス正規化とバリデーション
    if ".." in path.replace("\\", "/").split("/"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid path: path traversal is not allowed",
        )
    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, ValueError) as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Invalid path: {e}"
        ) from e

    if not resolved.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Path does not exist: {path}"
        )
    if not resolved.is_dir():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Path is not a directory: {path}"
        )

    # 子ディレクトリ列挙 (ファイルは除外)
    try:
        children = sorted(resolved.iterdir(), key=lambda p: p.name.lower())
    except PermissionError as e:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Permission denied: {path}",
        ) from e

    entries: list[dict[str, Any]] = []
    for child in children:
        if not child.is_dir():
            continue
        if _should_hide_dir(child.name):
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "is_dir": True,
            }
        )

    # 親パス (Windows のドライブルート C:\ の場合は None)
    parent = resolved.parent
    parent_path: str | None = None
    if parent != resolved:
        parent_path = str(parent)

    return {
        "current_path": str(resolved),
        "parent_path": parent_path,
        "entries": entries,
        "quick_paths": [],
    }


def _default_quick_paths() -> list[dict[str, str]]:
    """フォルダピッカーで最初に表示する「よく使う候補」を返す。"""
    candidates: list[dict[str, str]] = []
    try:
        cwd = Path.cwd()
        candidates.append({"label": "現在のディレクトリ", "path": str(cwd)})
    except OSError:
        pass
    home = Path.home()
    if home.exists():
        candidates.append({"label": "ホーム", "path": str(home)})
        for sub in ("Documents", "Desktop", "Downloads", "source", "workspace", "Projects"):
            sub_path = home / sub
            if sub_path.is_dir():
                candidates.append({"label": f"Home/{sub}", "path": str(sub_path)})
    return candidates


def _should_hide_dir(name: str) -> bool:
    """フォルダピッカーで非表示にすべきディレクトリ名か。"""
    if name.startswith("."):
        return True
    return name in {
        "__pycache__", "node_modules", "venv", "env", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints",
    }


# --- POST /api/review/stream ---


@router.post("/stream")
async def stream_review(request: ReviewStreamRequest) -> StreamingResponse:
    """レビュー Phase 2-5 を SSE でストリーミングする。

    同時実行は最大 ``MAX_CONCURRENT_SESSIONS`` セッション。超過時は 429。
    """
    if _review_semaphore.locked() and _review_semaphore._value <= 0:  # type: ignore[attr-defined]
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": (
                f"同時実行セッション数の上限 ({MAX_CONCURRENT_SESSIONS}) です。"
                "しばらくお待ちください。"
            )},
        )
    return StreamingResponse(
        _review_event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- SSE event generator ---


async def _review_event_generator(
    request: ReviewStreamRequest,
) -> AsyncIterator[str]:
    """SSE イベントを yield する。30秒 idle で keepalive、切断でタスク cancel。"""
    async with _review_semaphore:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE)
        task = asyncio.create_task(_mock_review_stream(queue, request))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=SSE_KEEPALIVE_SEC
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    if task.done():
                        break
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("Review SSE client disconnected; cancelling task")
            raise
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass


# --- Mock event stream (実コアエンジン統合時に置換) ---

# アスペクト × ラウンド用の発言テンプレート
# key: aspect (algorithm/reproducibility/performance/structure/readability/results)
# value: list[str] — ラウンドフェーズ (発散/深掘り/反論/統合/合意) 順の発言候補
_UTTERANCE_TEMPLATES: dict[str, list[str]] = {
    "algorithm": [
        "全体としてアルゴリズムの選択は妥当だが、Conductor の重複判定が O(N²) に膨らむ懸念があります。"
        " N が 100 を超えるあたりから体感で分かるはずです。",
        "重複判定の内側で set の in 判定に切り替えれば平均 O(N) に収まります。"
        " 具体的には `seen: set[str]` を導入して比較のたびに update する形が最短です。",
        "計算量の理屈は分かりますが、実データでは N が 30 前後で頭打ちなので、"
        " 実効的な差は誤差レベルかもしれません。ベンチマーク結果を見たいですね。",
        "計測結果によっては現状維持でも良さそうです。ただし将来 N が伸びるユースケースが"
        " あるなら早めに手を打っておきたいです。",
        "結論として、set 導入は 30 分程度の作業なので低コストで実施すべきと考えます。",
    ],
    "reproducibility": [
        "再現性の観点で気になるのは、乱数シードの固定が Agent 初期化に無いことです。"
        " 同じ議論を 2 回流しても結果が変わってしまいます。",
        "シード固定に加えて、LLM の temperature も明示指定しないと厳密な再現は難しいです。"
        " せめて settings.yaml に `temperature: 0.7` を書いておきたい。",
        "temperature を 0 にすると議論が単調になるので、"
        " シードだけで良いのでは。多様性を確保したい場面もあります。",
        "多様性を保ちつつ再現するには、シード + プロンプトログの保存で十分実用に足ります。"
        " 完全再現より近似再現の方が現場では役立ちます。",
        "アクション: `Agent.__init__` の冒頭に `random.seed(self.config.seed or 42)` を"
        " 追加、settings に seed フィールドを新設する方針で合意したいです。",
    ],
    "performance": [
        "プロファイリング結果、ホットスポットは `synthesizer.py` の synthesize() 内、"
        " 特に MVP 選定ループが 40% を占めています。",
        "MVP 選定ループでは agent ごとに feedback_history 全走査しているので、"
        " 一度辞書に落として O(1) 参照に変えれば大幅短縮できます。",
        "とはいえエージェント数はせいぜい 6〜8 なので、"
        " 最適化しても実測差は数十 ms 程度ではないでしょうか。",
        "数十 ms でも 10 セッション連続で使うと積み重なります。"
        " ユーザー体感より、CI での並列テスト時間短縮の意味が大きいです。",
        "最終合意: MVP 選定を辞書ベースに書き換え、"
        " 加えてキャッシュ層を追加。優先度は中で次スプリントに含めましょう。",
    ],
    "structure": [
        "Synthesizer クラスに責務が集中しすぎています。"
        " 統合・評価・MVP選定・レポート生成の 4 責務が 1 クラスに詰まっています。",
        "分割するなら `_MvpSelector`, `_ReportBuilder`, `_ConsensusExtractor` の"
        " 3 クラスに抽出、Synthesizer は Facade に徹する構造が綺麗です。",
        "分割しすぎるとテストとレビューの労力が増えます。"
        " 現状 300 行程度なら 1 クラスでも許容範囲では?",
        "300 行はギリで、これ以上機能追加すると破綻します。"
        " 予防的にリファクタしておく価値はあります。",
        "結論: Synthesizer 分割は独立 PR として次スプリントで実施。"
        " 破壊的変更なので慎重に進めます。",
    ],
    "readability": [
        "コード全体として docstring は充実していますが、"
        " Conductor の `_run_round` 周辺だけ長すぎて何をしているか一目で分かりません。",
        "`_run_round` はステップコメント (# ステップ 1: xxx) を挟むだけでも大幅に読みやすくなります。"
        " 型リファクタは不要です。",
        "コメントを増やすと逆に本質が埋もれます。"
        " 関数を分割して名前で語らせる方が理解しやすいです。",
        "分割は 30 分作業だが後方互換性への影響があるので、"
        " まずはコメント追加で対応し、次回のリファクタで分割を検討する順序で進めましょう。",
        "アクション: 今週中にステップコメントを追加、来スプリントで関数分割を独立 PR で対応。",
    ],
    "results": [
        "結果検証の観点では、収束スコアの計算式が閾値と噛み合っていない箇所を発見しました。",
        "convergence_threshold の default が 0.85 と厳しめなのに、"
        " 実データでは 0.6 前後で収束扱いになるケースがあります。閾値見直しが必要です。",
        "閾値は経験則で決めているだけなので、"
        " 実運用データに基づく統計から再計算するのが筋です。",
        "統計ベースで再算出するのは同意しますが、"
        " それまでの暫定として default を 0.75 に下げるのはどうでしょうか。",
        "合意: 0.75 に下げる pull request を私が用意します。"
        " 統計再計算は次のマイルストンでデータが十分集まったら実施。",
    ],
}

# クロス質問テンプレート (questioner_aspect, target_aspect) → (question, answer)
_CROSS_QA_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    ("structure", "algorithm",
     "設計視点から見ると Conductor の重複判定は Strategy パターンに切り出したいのですが、"
     "アルゴリズム的にはリスト走査で十分という判断ですか?",
     "その通りです。ただ将来的に判定ルールが増えるなら Strategy 化は妥当です。"
     "今すぐでなくてもよい話です。"),
    ("performance", "reproducibility",
     "シード固定するとキャッシュ効きが変わる可能性があります。"
     "既存のパフォーマンスベンチは影響ないでしょうか?",
     "シード固定で LLM 応答が短くなる傾向があるので、"
     "むしろパフォーマンス的にはプラスに働くはずです。念のためベンチ再取得は必要ですが。"),
    ("readability", "structure",
     "Synthesizer 分割案について、Facade の docstring が肥大化しないか懸念があります。"
     "各サブクラスへの委譲を淡々と書く形になるのでしょうか?",
     "はい、Facade は薄い委譲で、詳細は各サブクラスに集約します。"
     "docstring は各サブクラスに書き、Facade は概要と使い方だけ。"),
    ("algorithm", "results",
     "convergence 閾値 0.75 は経験則ですが、実データでの分布を教えてください。"
     "極端に片寄っていないか気になります。",
     "手元のログでは中央値 0.72、標準偏差 0.08 で、正規分布に近い形です。"
     "0.75 なら概ね上位 30% を『収束』扱いにできます。"),
)

# ラウンドフェーズ定義 (会議進行の 5 段階)
_ROUND_PHASES: tuple[tuple[str, str], ...] = (
    ("diverge",   "各観点から気になる点を出し合う (発散)"),
    ("deepen",    "上がった論点を掘り下げ、具体的な改善案を練る (深掘り)"),
    ("adversarial","代替案・反対意見を提示し、既存案を検証する (反論)"),
    ("integrate", "見出した知見を統合し、実施すべきアクションを整理する (統合)"),
    ("converge",  "優先度と担当を確定し、次アクションを合意する (合意)"),
)


def _mock_utterance(aspect_info: dict[str, str], round_num: int,
                     phase_index: int, seq: int) -> dict[str, Any]:
    """アスペクトとラウンドから realistic な utterance イベントを生成する。"""
    templates = _UTTERANCE_TEMPLATES.get(aspect_info["aspect"], [""] * 5)
    template = templates[phase_index] if phase_index < len(templates) else templates[-1]
    # 発言長を微調整 (seq が進むと少し補足)
    tokens = 90 + (seq * 20) + (phase_index * 15)
    return {
        "type": "utterance",
        "round": round_num,
        "agent": {
            "role_id": aspect_info["role_id"],
            "emoji": aspect_info["emoji"],
            "name": aspect_info["role_name"],
        },
        "content": template,
        "tokens": tokens,
        "duration_sec": MOCK_UTTERANCE_DURATION_SEC,
    }


def _mock_round_conclusion(aspect_info: dict[str, str], round_num: int,
                            phase_index: int) -> dict[str, Any]:
    """ラウンドリーダーによる結論イベントを生成する。"""
    _, phase_label = _ROUND_PHASES[phase_index]
    return {
        "type": "round_conclusion",
        "round": round_num,
        "concluder_emoji": aspect_info["emoji"],
        "concluder_name": aspect_info["role_name"],
        "content": (
            f"【Round {round_num} まとめ ({phase_label})】\n"
            f"{aspect_info['role_name']} として、"
            f"このラウンドで得られた重要な論点を整理しました。"
            f" 次のラウンドではこの論点をベースに議論を進めます。"
        ),
    }


def _mock_kickoff_briefing(request: ReviewStreamRequest) -> dict[str, Any]:
    """会議 (Phase 4) 開始前に指揮者が計画を要約する発言を生成する。

    Idea Discussion 側の ``Conductor._notify_kickoff_briefing`` に相当する
    「議題・対象・参加者・ラウンド構成」を確認する導入発言。フロントには
    ``round=0`` の utterance として届き、通常発言と同じバブルで表示される。
    """
    focus_labels: dict[str, str] = {
        "all": "全観点レビュー",
        "pre_submission": "投稿前チェック",
        "performance": "性能重視",
        "structure": "構造重視",
        "handover": "引き継ぎ重視",
        "algorithm": "アルゴリズム重視",
    }
    focus_label = focus_labels.get(request.focus, request.focus or "汎用レビュー")

    lines: list[str] = [
        "それではこれより全体会議を始めます。まず本会議の計画を確認します。",
        "",
        f"【議題】{focus_label} のコードレビューを統合的に議論する",
        f"【対象】{request.target_path}",
        "【成果物】各観点のリーダーによる合意アクション一覧",
        "【成功基準】5 ラウンドを経て、実施すべきアクションが優先度付きで整理される",
        "",
        "【参加者と観点】",
    ]
    for a in _REVIEW_ASPECTS:
        lines.append(f"- {a['emoji']} {a['role_name']} — {a['aspect_label']}")
    lines.append("")
    lines.append("【ラウンド構成】")
    for i, (_, phase_desc) in enumerate(_ROUND_PHASES, start=1):
        lines.append(f"- Round {i}: {phase_desc}")
    lines.append("")
    lines.append("以上の計画に沿って進行します。では、開始してください。")

    return {
        "type": "utterance",
        "round": 0,
        "agent": {
            "role_id": "orchestrator",
            "emoji": "🎼",
            "name": "指揮者",
        },
        "content": "\n".join(lines),
        "tokens": 250,
        "duration_sec": MOCK_UTTERANCE_DURATION_SEC,
    }


async def _mock_review_stream(
    queue: "asyncio.Queue[dict[str, Any]]",
    request: ReviewStreamRequest,
) -> None:
    """モックの Phase 1-5 SSE イベントを順次流す。"""
    # 履歴 → 各ステップ復元のためのキャプチャ
    captured_rounds: list[dict[str, Any]] = []
    captured_findings_by_aspect: dict[str, list[dict[str, Any]]] = {}
    captured_cross_qa: list[dict[str, Any]] = []
    try:
        # Phase 1: スキャン結果を送信
        await _emit(queue, {"type": "scan_start"})
        await _emit(queue, {"type": "scan_complete", "scan_result": request.scan_result})

        # Phase 2: 6 アスペクトの個別調査 (各観点で複数 findings を発掘)
        for a in _REVIEW_ASPECTS:
            aspect = a["aspect"]
            findings_list = _sample_findings(aspect)
            n_findings = len(findings_list)
            captured_findings_by_aspect[aspect] = findings_list
            await _emit(queue, {"type": "investigation_start",
                                "aspect": aspect, "emoji": a["emoji"]})
            # findings を段階的に発火し、progress を実件数と同期
            for idx, finding in enumerate(findings_list, start=1):
                progress = int(idx / n_findings * 100)
                await _emit(queue, {"type": "investigation_progress",
                                    "aspect": aspect, "progress": progress,
                                    "current": idx, "total": n_findings})
                await _emit(queue, {"type": "investigation_finding",
                                    "aspect": aspect, "finding": finding})
            await _emit(queue, {"type": "investigation_complete",
                                "aspect": aspect, "findings_count": n_findings})

        # Phase 3: 相互質問 (4 往復)
        await _emit(queue, {"type": "cross_question_start"})
        for q_aspect, t_aspect, question, answer in _CROSS_QA_TEMPLATES:
            captured_cross_qa.append({
                "questioner": q_aspect, "target": t_aspect,
                "question": question, "answer": answer,
            })
            await _emit(queue, {"type": "cross_question",
                                "questioner": q_aspect, "target": t_aspect,
                                "question": question})
            await _emit(queue, {"type": "cross_answer",
                                "answerer": t_aspect, "questioner": q_aspect,
                                "answer": answer})
        await _emit(queue, {"type": "cross_question_complete"})

        # Phase 4: 全体会議 (5 ラウンド)
        await _emit(queue, {"type": "meeting_start"})

        # 指揮者による会議キックオフ (議題・参加者・ラウンド構成を確認)
        await _emit(queue, _mock_kickoff_briefing(request))

        # ラウンドごとにリーダーとスピーカーを回す (6 アスペクトを 5 ラウンドに割当)
        # Round 1: theorist リード (発散) / Round 2: architect リード (深掘り)
        # Round 3: devil ライク (adversarial: experimentalist) / Round 4: implementer (統合)
        # Round 5: theorist (合意)
        round_leaders = [
            _REVIEW_ASPECTS[0],  # algorithm / theorist
            _REVIEW_ASPECTS[3],  # structure / architect
            _REVIEW_ASPECTS[1],  # reproducibility / experimentalist
            _REVIEW_ASPECTS[2],  # performance / implementer
            _REVIEW_ASPECTS[0],  # algorithm / theorist (最終合意)
        ]
        # 各ラウンドで発言する順序 (リーダー先頭 + 補助 2-3 名)
        round_speakers_indices = [
            [0, 3, 4, 1],       # R1: alg, struct, read, repro (4 発言)
            [3, 0, 2],          # R2: struct, alg, perf (3 発言)
            [1, 5, 2, 4],       # R3: repro, results, perf, read (4 発言)
            [2, 3, 1],          # R4: perf, struct, repro (3 発言)
            [0, 2, 5],          # R5: alg, perf, results (3 発言)
        ]

        cumulative_convergence = 0.30
        elapsed = 0.0
        total_utterances = 0
        for phase_index, (phase_name, phase_desc) in enumerate(_ROUND_PHASES):
            round_num = phase_index + 1
            leader = round_leaders[phase_index]
            speakers = round_speakers_indices[phase_index]
            speakers_role_ids = [_REVIEW_ASPECTS[i]["role_id"] for i in speakers]

            await _emit(queue, {"type": "round_start", "round": round_num, "config": {
                "round": round_num,
                "phase": phase_name,
                "pattern": "free_talk" if phase_index in (0, 3) else "ping_pong",
                "speakers": speakers_role_ids,
                "goal": phase_desc,
                "topic": phase_desc,
            }})

            # ラウンドキャプチャ (履歴 → チャット復元用)
            round_snapshot: dict[str, Any] = {
                "round": round_num,
                "phase_name": phase_name,
                "goal": phase_desc,
                "duration_sec": 0.0,
                "public_utterances": [],
                "convergence_check": None,
            }
            captured_rounds.append(round_snapshot)

            # ラウンド内の発言 (アスペクト別テンプレート使用)
            for seq_idx, sp_idx in enumerate(speakers, start=1):
                utterance_evt = _mock_utterance(
                    _REVIEW_ASPECTS[sp_idx], round_num, phase_index, seq_idx,
                )
                await _emit(queue, utterance_evt)
                round_snapshot["public_utterances"].append({
                    "speaker": utterance_evt["agent"]["role_id"],
                    "speaker_emoji": utterance_evt["agent"]["emoji"],
                    "speaker_name": utterance_evt["agent"]["name"],
                    "content": utterance_evt["content"],
                    "tokens_used": {"total": utterance_evt["tokens"]},
                    "duration_sec": utterance_evt["duration_sec"],
                })
                total_utterances += 1
                elapsed += utterance_evt["duration_sec"]

            # ラウンドリーダーによる結論
            conclusion_evt = _mock_round_conclusion(leader, round_num, phase_index)
            await _emit(queue, conclusion_evt)
            round_snapshot["public_utterances"].append({
                "speaker": leader["role_id"],
                "speaker_emoji": conclusion_evt.get("concluder_emoji", ""),
                "speaker_name": conclusion_evt.get("concluder_name", ""),
                "content": conclusion_evt.get("content", ""),
                "tokens_used": {"total": 120},
                "duration_sec": 1.5,
                "is_conclusion": True,
            })
            total_utterances += 1
            round_snapshot["duration_sec"] = sum(
                u["duration_sec"] for u in round_snapshot["public_utterances"]
            )

            # 収束スコアはラウンドが進むごとに徐々に上昇
            cumulative_convergence = min(0.92, cumulative_convergence + 0.13 + phase_index * 0.01)
            round_snapshot["convergence_check"] = {
                "score": round(cumulative_convergence, 2),
            }
            await _emit(queue, {"type": "convergence_check",
                                "score": round(cumulative_convergence, 2)})
            await _emit(queue, {"type": "round_end",
                                "round": round_num,
                                "convergence": round(cumulative_convergence, 2),
                                "elapsed_sec": elapsed})

        # Phase 5: 統合開始 (フロントは synthesis_start でタイマー停止)
        await _emit(queue, {"type": "synthesis_start"})

        # 完了 (mock 用に files も同梱 → フロントは fetch せず event の files を使う)
        # session_id は実セッションと同じ書式にして履歴に載せる
        completed_at = datetime.now()
        session_id = f"{completed_at.strftime('%Y%m%d_%H%M%S')}_review"
        total_tokens = total_utterances * 130
        duration_sec = elapsed + 8.0
        files = _build_mock_report_files(request.target_path)
        statistics = {
            "duration_sec": duration_sec,
            "total_utterances": total_utterances,
            "total_tokens": total_tokens,
            "total_requests": MOCK_ESTIMATED_REQUESTS,
            "rounds_completed": len(_ROUND_PHASES),
            "final_convergence": round(cumulative_convergence, 2),
            "mvp": leader["role_id"],
        }
        # 実セッション同様 output/ 配下に書き出す (履歴一覧に反映される)
        output_dir = _write_mock_session_to_disk(
            session_id=session_id,
            request=request,
            files=files,
            statistics=statistics,
            started_at=completed_at.timestamp() - duration_sec,
            completed_at=completed_at,
            captured_rounds=captured_rounds,
            captured_findings_by_aspect=captured_findings_by_aspect,
            captured_cross_qa=captured_cross_qa,
        )
        await _emit(queue, {"type": "done",
            "session_id": session_id,
            "output_dir": str(output_dir) if output_dir else "",
            "files": files,
            "statistics": statistics,
        })
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Mock review stream failed")
        try:
            queue.put_nowait({"type": "error", "message": str(e),
                              "recoverable": False, "error_type": type(e).__name__})
        except asyncio.QueueFull:
            pass


# --- Helpers ---


def _validate_target_path(target_path: str) -> None:
    """``target_path`` の安全性と実在を検証する。"""
    if not target_path or ".." in target_path.replace("\\", "/").split("/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Invalid target_path: path traversal is not allowed")
    try:
        resolved = Path(target_path).resolve(strict=False)
    except (OSError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Invalid target_path: {e}") from e
    if not resolved.exists():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"target_path does not exist: {target_path}")
    if not resolved.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"target_path is not a directory: {target_path}")


def _build_mock_scan_result(target_path: str) -> dict[str, Any]:
    """モックのスキャン結果を返す (fallback / テスト用)。"""
    return {
        "root_path": target_path,
        "total_files": len(_MOCK_FILES),
        "total_lines": sum(f["lines"] for f in _MOCK_FILES),
        "languages": {"python": 6, "yaml": 2},
        "tree_text": _MOCK_TREE_TEXT,
        "files": list(_MOCK_FILES),
    }


# ---- 実スキャン用ヘルパ (B1: mock 削除) --------------------------------

# 拡張子 → 表示用言語名マップ
_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".jsonl": "json",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".sh": "shell",
    ".bat": "shell",
    ".ps1": "shell",
    ".sql": "sql",
    ".toml": "toml",
    ".ini": "config",
    ".cfg": "config",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
}


def _scan_folder_real(
    target_path: str,
    ignore_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """実スキャナで対象フォルダをスキャンし、UI 互換の dict を返す。

    Args:
        target_path: スキャン対象パス。事前に ``_validate_target_path`` で
            検証済みであること。
        ignore_patterns: 追加の ignore パターン (UI から渡された分)。

    Returns:
        UI で期待される形式の辞書:
        ``{root_path, total_files, total_lines, languages, tree_text, files}``。
    """
    scanner = FolderScanner()
    scan = scanner.scan(Path(target_path), extra_ignores=ignore_patterns or [])
    return _scan_result_to_ui_dict(scan, root_path_display=target_path)


def _scan_result_to_ui_dict(
    scan: Any,
    root_path_display: str,
) -> dict[str, Any]:
    """``ScanResult`` を UI 互換 dict に変換する。

    UI が期待するキー (``tree_text`` / ``languages``) は
    ``ScanResult`` に存在しないため、``file_tree`` から生成する。
    """
    file_tree = list(scan.file_tree)
    tree_text = _build_tree_text(file_tree)
    languages = _infer_languages(file_tree)
    # UI で使いやすいよう path/lines/size_bytes だけに絞った軽量 dict にする
    files: list[dict[str, Any]] = [
        {
            "path": entry.get("path", ""),
            "lines": int(entry.get("lines", 0)),
            "size_bytes": int(entry.get("size_bytes", 0)),
            "extension": entry.get("extension", ""),
            "skipped": bool(entry.get("skipped", False)),
        }
        for entry in file_tree
    ]
    return {
        "root_path": root_path_display,
        "total_files": int(scan.total_files),
        "total_lines": int(scan.total_lines),
        "languages": languages,
        "tree_text": tree_text,
        "files": files,
    }


def _build_tree_text(file_tree: list[dict[str, Any]]) -> str:
    """``file_tree`` のパスリストから階層ツリー文字列を組み立てる。

    出力例::

        src/
          core/
            agent.py (350 行)
            conductor.py (1200 行)
          utils/
            logger.py (85 行)
        config.yaml (40 行)

    深さでインデント。ファイルには行数を末尾に付ける。
    """
    if not file_tree:
        return "(ファイルなし)"

    # (path, lines, is_dir) のフラットリストを path 昇順で並べる
    paths_with_info: list[tuple[str, int]] = sorted(
        (
            (str(entry.get("path", "")).replace("\\", "/"), int(entry.get("lines", 0)))
            for entry in file_tree
            if entry.get("path")
        ),
        key=lambda x: x[0],
    )
    if not paths_with_info:
        return "(ファイルなし)"

    # 各パスの祖先ディレクトリも列挙してソートし、階層表示する
    dir_set: set[str] = set()
    for path, _ in paths_with_info:
        parts = path.split("/")
        for i in range(1, len(parts)):
            dir_set.add("/".join(parts[:i]))

    # ディレクトリ (末尾 /) とファイルを同じキー空間でソート
    all_entries: list[tuple[str, bool, int]] = []
    for d in dir_set:
        all_entries.append((d + "/", True, 0))
    for path, lines in paths_with_info:
        all_entries.append((path, False, lines))
    all_entries.sort(key=lambda x: x[0])

    lines_out: list[str] = []
    for entry_key, is_dir, line_count in all_entries:
        depth = entry_key.rstrip("/").count("/")
        name = entry_key.rstrip("/").split("/")[-1] if entry_key != "/" else "/"
        indent = "  " * depth
        if is_dir:
            lines_out.append(f"{indent}{name}/")
        else:
            suffix = f" ({line_count} 行)" if line_count > 0 else ""
            lines_out.append(f"{indent}{name}{suffix}")

    return "\n".join(lines_out)


def _infer_languages(file_tree: list[dict[str, Any]]) -> dict[str, int]:
    """拡張子から言語別ファイル数を集計する。

    未知の拡張子は「その他」に集約し、頭のドットを除いたそのままの
    拡張子名で表示する。
    """
    counts: dict[str, int] = {}
    for entry in file_tree:
        ext = str(entry.get("extension", "")).lower()
        if not ext:
            continue
        lang = _EXTENSION_TO_LANGUAGE.get(ext, ext.lstrip("."))
        counts[lang] = counts.get(lang, 0) + 1
    return counts


def _build_mock_part_leaders() -> list[dict[str, Any]]:
    """モックのパートリーダー割当を返す。"""
    return [
        {**a, "files": ["src/core/agent.py", "src/core/conductor.py"]}
        for a in _REVIEW_ASPECTS
    ]


def _build_mock_finding(aspect: str) -> dict[str, Any]:
    """後方互換: `_build_mock_findings` の 1 件目を返す。"""
    findings = _build_mock_findings(aspect)
    return findings[0] if findings else {
        "severity": "info", "title": f"{aspect} 観点", "description": "",
        "file_path": "src/", "line_range": [1, 1], "suggestion": "",
    }


# アスペクト別 finding 数の下限・上限
# (実 LLM レビュー時は動的に決まるので、mock でも観点ごとに件数を変える)
_ASPECT_FINDING_RANGE: dict[str, tuple[int, int]] = {
    "algorithm":       (2, 3),   # 少なめ (成熟した領域)
    "reproducibility": (2, 3),   # 少ないが致命的
    "performance":     (1, 3),   # コード規模依存
    "structure":       (2, 3),   # 全体設計
    "readability":     (2, 3),   # スタイル
    "results":         (1, 3),   # 検証系
}


def _sample_findings(aspect: str) -> list[dict[str, Any]]:
    """観点ごとに 1〜N 件の findings を決定的にサンプリング。

    ``hash(aspect)`` を種にした Random で、観点ごとに異なる件数と
    組み合わせを返す。同じアスペクトなら常に同じ結果 (実行間安定)。
    """
    import random  # local import (最小依存)
    pool = _build_mock_findings(aspect)
    if not pool:
        return []
    lo, hi = _ASPECT_FINDING_RANGE.get(aspect, (1, len(pool)))
    hi = min(hi, len(pool))
    rng = random.Random(hash(aspect) & 0xFFFF)
    count = rng.randint(max(1, lo), hi)
    # 決定的な優先度順 (深刻度順) で count 件返す
    sorted_pool = sorted(pool, key=lambda f: _severity_rank(f["severity"]))
    return sorted_pool[:count]


def _build_mock_findings(aspect: str) -> list[dict[str, Any]]:
    """モックの findings をアスペクト別に複数返す (網羅的レビューを模擬)。"""
    presets: dict[str, list[dict[str, Any]]] = {
        "algorithm": [
            {
                "severity": "minor",
                "title": "Conductor の重複判定が O(N²) に膨らむ可能性",
                "description": "現状のリスト走査は N が小さいと問題ないが、"
                               "将来的にエージェント数や履歴が増えると計算量が支配的になり得る。",
                "file_path": "src/core/conductor.py",
                "line_range": [180, 230],
                "suggestion": "set ベースの in 判定に置換すれば平均 O(N) に収まる。",
            },
            {
                "severity": "minor",
                "title": "収束スコア計算で毎回全履歴を線形走査",
                "description": "score_history を毎ラウンド末に slice + sum しているため、"
                               "ラウンド数が増えると O(R²) になる。",
                "file_path": "src/core/convergence_checker.py",
                "line_range": [78, 95],
                "suggestion": "累積和 (running sum) を保持し O(R) に改善。",
            },
            {
                "severity": "info",
                "title": "MVP 選定タイブレークが決定的でない",
                "description": "同点時に dict iteration 順に依存し、Python バージョンで"
                               "結果が変わる可能性がある。",
                "file_path": "src/core/synthesizer.py",
                "line_range": [312, 328],
                "suggestion": "role_id の辞書順で明示的にタイブレーク。",
            },
        ],
        "reproducibility": [
            {
                "severity": "major",
                "title": "Agent 初期化時に乱数シードが固定されていない",
                "description": "同じプロンプト・同じモデルでも実行ごとに結果が変わるため、"
                               "再現性の確保・デバッグが困難。",
                "file_path": "src/core/agent.py",
                "line_range": [60, 90],
                "suggestion": "`Agent.__init__` 冒頭で `random.seed(self.config.seed or 42)` を呼ぶ。"
                              "settings に seed フィールドを追加。",
            },
            {
                "severity": "major",
                "title": "LLM temperature が明示されていない (API デフォルト依存)",
                "description": "OpenAI/Azure のデフォルト値変更で応答傾向が変わり得る。",
                "file_path": "src/core/api_client.py",
                "line_range": [145, 168],
                "suggestion": "settings.yaml に `temperature: 0.7` を明示指定、"
                              "API 呼び出しに常に渡す。",
            },
            {
                "severity": "minor",
                "title": "プロンプト履歴が output/ に保存されていない",
                "description": "後日デバッグ時に「同じ入力で何が返ったか」を追えない。",
                "file_path": "src/core/output_generator.py",
                "line_range": [220, 255],
                "suggestion": "各 LLM 呼び出しの request/response を "
                              "`prompts.jsonl` にログ保存。",
            },
        ],
        "performance": [
            {
                "severity": "minor",
                "title": "MVP 選定ループが O(agents × history)",
                "description": "synthesizer.synthesize() 内で agent ごとに feedback_history "
                               "全走査しているため、履歴が長いと線形以上に遅くなる。",
                "file_path": "src/core/synthesizer.py",
                "line_range": [240, 260],
                "suggestion": "履歴を role_id → 統計 の辞書に事前集約し、O(1) 参照に変更。",
            },
            {
                "severity": "minor",
                "title": "同期 API 呼び出しがループ内でシリアル実行",
                "description": "Phase 2 のラウンド内で speaker ごとに順次 API 呼び出しになる。"
                               "one_shot パターンなら並列化できるはず。",
                "file_path": "src/core/conductor.py",
                "line_range": [295, 322],
                "suggestion": "`asyncio.gather()` で並列実行、pattern が one_shot 時のみ有効化。",
            },
            {
                "severity": "info",
                "title": "role YAML の再読み込みがキャッシュされていない",
                "description": "RoleManager.load_role() が呼び出しのたびに YAML パースする。",
                "file_path": "src/core/role_manager.py",
                "line_range": [45, 68],
                "suggestion": "`@functools.lru_cache` またはインスタンス dict で結果を保持。",
            },
        ],
        "structure": [
            {
                "severity": "major",
                "title": "Synthesizer に責務が集中しすぎ",
                "description": "統合・評価・MVP選定・レポート生成の 4 責務が 1 クラスに混在。"
                               "今後の機能追加時に破綻するリスクが高い。",
                "file_path": "src/core/synthesizer.py",
                "line_range": [1, 350],
                "suggestion": "`_MvpSelector`, `_ReportBuilder`, `_ConsensusExtractor` に分割し、"
                              "Synthesizer は Facade に徹する構造へリファクタ。",
            },
            {
                "severity": "minor",
                "title": "Conductor と TimeKeeper の相互依存が強い",
                "description": "TimeKeeper が Conductor 内部の状態を仮定する箇所があり、"
                               "単体テストで TimeKeeper を差し替えづらい。",
                "file_path": "src/core/conductor.py",
                "line_range": [125, 165],
                "suggestion": "TimeKeeper のインターフェースを Protocol で定義、"
                              "依存を最小 API に絞る。",
            },
            {
                "severity": "info",
                "title": "web/ と core/ の境界がやや曖昧",
                "description": "core/ 側で FastAPI 特有の型 (HTTPException 等) を"
                               "参照している場所がある。",
                "file_path": "src/core/exceptions.py",
                "line_range": [15, 32],
                "suggestion": "core/ は Web フレームワーク非依存を維持、web/ 側で例外変換。",
            },
        ],
        "readability": [
            {
                "severity": "minor",
                "title": "Conductor._run_round が長すぎて処理が追いにくい",
                "description": "1 メソッドで 3 パターン (one_shot/ping_pong/free_talk) を分岐 + "
                               "結論生成 + 収束判定を担っているため、可読性が低い。",
                "file_path": "src/core/conductor.py",
                "line_range": [250, 300],
                "suggestion": "各パターン別 dispatcher の呼び分けに整理 + "
                              "冒頭にステップコメントを追加する。",
            },
            {
                "severity": "minor",
                "title": "型ヒントに Any が多用されている",
                "description": "特に intervention.py, orchestrator.py で `dict[str, Any]` が頻出、"
                               "TypedDict や dataclass での型付けが望ましい。",
                "file_path": "src/core/intervention.py",
                "line_range": [1, 130],
                "suggestion": "SSE イベントペイロードを TypedDict で明示定義。",
            },
            {
                "severity": "info",
                "title": "docstring は充実しているが日英混在",
                "description": "パブリック API が日本語 docstring、内部関数が英語というルールが"
                               "統一されていない箇所がある。",
                "file_path": "src/core/",
                "line_range": [1, 1],
                "suggestion": "スタイルガイドを CONTRIBUTING に明記。",
            },
        ],
        "results": [
            {
                "severity": "minor",
                "title": "convergence_threshold の default が過剰に厳しい",
                "description": "default 0.85 に対し、実運用データの中央値は 0.72 前後。"
                               "多くの議論が『未収束』扱いになり、統計が有効活用されていない。",
                "file_path": "src/config.yaml",
                "line_range": [12, 15],
                "suggestion": "暫定的に default を 0.75 に下げ、"
                              "次のマイルストンで実データ統計から再算出。",
            },
            {
                "severity": "minor",
                "title": "MVP 判定の重み係数が経験則",
                "description": "self_score/peer_score/mvp_frequency の重みが「なんとなく 1:1:1」で、"
                               "根拠が不明。",
                "file_path": "src/core/synthesizer.py",
                "line_range": [285, 305],
                "suggestion": "過去の MVP 選定結果と実際のフィードバックを回帰分析し、"
                              "重みを再チューニング。",
            },
            {
                "severity": "info",
                "title": "レポートの品質メトリクスが未計測",
                "description": "生成レポートの読みやすさ・網羅性を定量評価する仕組みがない。",
                "file_path": "src/core/output_generator.py",
                "line_range": [155, 195],
                "suggestion": "flesch reading ease + section coverage の自動計測を追加。",
            },
        ],
    }
    return presets.get(aspect, [{
        "severity": "info",
        "title": f"{aspect} 観点の一般的な指摘",
        "description": "自動生成された汎用指摘。",
        "file_path": "src/",
        "line_range": [1, 1],
        "suggestion": "詳細は Issue で議論。",
    }])


def _build_mock_conversation_log() -> str:
    """全会議ログを Markdown で生成 (省略なし)。"""
    lines: list[str] = [
        "# 全会議ログ",
        "",
        "各ラウンドで発言された内容を時系列順に記載しています。",
        "リーダー (speakers[0]) はラウンドの進行と結論を担当します。",
        "",
    ]
    round_leaders_map = {
        1: _REVIEW_ASPECTS[0],
        2: _REVIEW_ASPECTS[3],
        3: _REVIEW_ASPECTS[1],
        4: _REVIEW_ASPECTS[2],
        5: _REVIEW_ASPECTS[0],
    }
    round_speakers_indices_map = {
        1: [0, 3, 4, 1],
        2: [3, 0, 2],
        3: [1, 5, 2, 4],
        4: [2, 3, 1],
        5: [0, 2, 5],
    }
    for round_num, (phase_name, phase_desc) in enumerate(_ROUND_PHASES, start=1):
        leader = round_leaders_map[round_num]
        speakers = round_speakers_indices_map[round_num]
        lines.append(f"## Round {round_num}: {phase_name}")
        lines.append("")
        lines.append(f"**進行 (リーダー)**: {leader['emoji']} {leader['role_name']}  ")
        lines.append(f"**目標**: {phase_desc}")
        lines.append("")
        for sp_idx in speakers:
            asp = _REVIEW_ASPECTS[sp_idx]
            templates = _UTTERANCE_TEMPLATES.get(asp["aspect"], [""] * 5)
            phase_index = round_num - 1
            content = templates[phase_index] if phase_index < len(templates) else templates[-1]
            lines.append(f"### {asp['emoji']} {asp['role_name']}")
            lines.append("")
            lines.append(content)
            lines.append("")
        lines.append(f"**Round {round_num} まとめ ({leader['role_name']})**  ")
        lines.append(
            f"このラウンドで得られた重要論点を整理し、次のラウンドの議題に接続しました。"
            f" 主要な合意点は {phase_desc.split('(')[0].strip()} の方向性で一致。"
        )
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _build_mock_evaluation() -> str:
    """詳細な評価を Markdown で生成 (findings 数に応じた動的スコア)。"""
    # 観点メタ (順序と表示情報)
    aspect_meta = [
        {"aspect": "algorithm",       "label": "アルゴリズム", "emoji": "🧮"},
        {"aspect": "reproducibility", "label": "再現性",       "emoji": "🔬"},
        {"aspect": "performance",     "label": "性能",         "emoji": "🤖"},
        {"aspect": "structure",       "label": "構造",         "emoji": "📐"},
        {"aspect": "readability",     "label": "可読性",       "emoji": "📝"},
        {"aspect": "results",         "label": "結果検証",     "emoji": "🔬"},
    ]

    aspects_eval: list[dict[str, Any]] = []
    for meta in aspect_meta:
        findings = _sample_findings(meta["aspect"])
        score, priority, reason = _evaluate_findings(findings)
        aspects_eval.append({
            **meta,
            "score": score,
            "priority": priority,
            "reason": reason,
            "findings": findings,
        })

    lines: list[str] = ["# 詳細評価", "", "## 総合", ""]
    total = sum(a["score"] for a in aspects_eval) / len(aspects_eval)
    lines.append(f"**総合スコア**: **{total:.2f} / 5.00**  ")
    lines.append(f"**評価観点**: 6 観点 (アルゴリズム / 再現性 / 性能 / 構造 / 可読性 / 結果検証)  ")
    lines.append(
        "**評価方針**: findings の件数・深刻度分布・修正コスト・"
        "既存テストへの影響度を総合判断。基準 5.0 から critical/major/minor "
        "に応じて減点し、0.5 刻みで四捨五入。"
    )
    lines.append("")
    lines.append(f"**検出指摘 合計**: {sum(len(a['findings']) for a in aspects_eval)} 件")
    lines.append("")
    lines.append("| 観点 | スコア | 優先度 | 指摘 | 主な指摘 |")
    lines.append("|---|---|---|---|---|")
    for a in aspects_eval:
        summary_finding = a["findings"][0]["title"] if a["findings"] else "(指摘なし)"
        lines.append(
            f"| {a['emoji']} {a['label']} | **{a['score']:.1f}** | "
            f"**{a['priority']}** | {len(a['findings'])} 件 | {summary_finding} |"
        )
    lines.append("")
    lines.append("## 観点別詳細")
    lines.append("")
    for a in aspects_eval:
        lines.append(
            f"### {a['emoji']} {a['label']}  "
            f"(スコア {a['score']:.1f} / 優先度 {a['priority']} / 指摘 {len(a['findings'])} 件)"
        )
        lines.append("")
        lines.append(f"**判断根拠**: {a['reason']}")
        lines.append("")
        lines.append("**主な指摘**:")
        for f in a["findings"]:
            lines.append(
                f"- **{_severity_label(f['severity'])}** {f['title']}"
            )
        lines.append("")
    lines.extend([
        "## 優先度の定義",
        "",
        "- **P0**: 次スプリント内で対応。放置するとバグ・技術的負債が拡大",
        "- **P1**: 中期的 (1-2ヶ月内) に対応。パフォーマンス・保守性への影響",
        "- **P2**: 余裕があれば対応。品質向上・将来の拡張性のため",
        "",
        "## スコアリング基準",
        "",
        "| 深刻度 | 減点 |",
        "|---|---|",
        "| critical | -1.2 / 件 |",
        "| major    | -0.7 / 件 |",
        "| minor    | -0.3 / 件 |",
        "| info     | -0.1 / 件 |",
        "",
        "スコアは 1.5〜5.0 の範囲でクリップされます。",
    ])
    return "\n".join(lines)


def _evaluate_findings(
    findings: list[dict[str, Any]],
) -> tuple[float, str, str]:
    """findings の深刻度分布からスコア・優先度・判断根拠を算出。

    Returns:
        ``(score, priority, reason)`` タプル。
    """
    if not findings:
        return 4.8, "P2", "指摘なし。現状の実装は良好。"

    penalties = {"critical": 1.2, "major": 0.7, "minor": 0.3, "info": 0.1}
    total_penalty = sum(penalties.get(f["severity"], 0.1) for f in findings)
    raw_score = 5.0 - total_penalty
    score = max(1.5, min(5.0, round(raw_score * 2) / 2))  # 0.5 刻み

    # 優先度は深刻度分布から判定
    has_critical = any(f["severity"] == "critical" for f in findings)
    has_major = any(f["severity"] == "major" for f in findings)
    if has_critical:
        priority = "P0"
    elif has_major:
        priority = "P0"
    elif score >= 4.0:
        priority = "P2"
    else:
        priority = "P1"

    # 判断根拠
    n_maj = sum(1 for f in findings if f["severity"] in ("critical", "major"))
    if n_maj > 0:
        reason = f"重要な指摘 {n_maj} 件を含む {len(findings)} 件の指摘あり。早期対応が必要。"
    elif score >= 4.0:
        reason = f"{len(findings)} 件の軽微な指摘。品質は良好。"
    else:
        reason = f"{len(findings)} 件の指摘。中程度の改善余地。"

    return score, priority, reason




def _build_mock_vibe_prompt(findings_all: list[tuple[str, dict[str, Any]]]) -> str:
    """Vibe Coding (Cursor / Copilot Chat 等) 用の修正指示書テンプレート。

    冒頭にレビュアーロール定義、その後 findings を優先度順に貼れる形式で列挙。
    """
    lines: list[str] = [
        "# 修正指示書 (Vibe Coding テンプレート)",
        "",
        "> 以下のプロンプトを **Cursor / GitHub Copilot Chat / Claude Code** に",
        "> **そのまま貼り付けて実行**してください。ロール定義と修正内容を",
        "> 明示的に指示することで、AI が意図通りのリファクタを行います。",
        "",
        "---",
        "",
        "## 🎭 ロール定義",
        "",
        "```",
        "あなたは以下の観点を持つ熟練コードレビュアー兼リファクタリングエンジニアです:",
        "",
        "- アルゴリズム: 計算量を意識し、無駄なループ・冗長なデータ構造を排除する",
        "- 再現性: 乱数・時刻・環境依存を最小化し、テストで再現可能にする",
        "- 性能: プロファイリング根拠のあるホットスポット改善を優先する",
        "- 構造: SOLID 原則に沿って責務を分割、循環依存を避ける",
        "- 可読性: 命名・docstring・型ヒントを充実、1 関数 50 行以内を目安",
        "- 結果検証: 変更前後で挙動を Diff で確認、テストを更新",
        "",
        "作業方針:",
        "1. 提示された指摘を優先度順に処理する",
        "2. 各修正について: 変更前後のコード + 理由 + テスト影響を提示",
        "3. 破壊的変更は事前に警告し、後方互換シムを提案",
        "4. コミットメッセージも生成 (Conventional Commits 形式)",
        "```",
        "",
        "---",
        "",
        "## 📋 修正リスト (優先度順)",
        "",
    ]

    # 深刻度順ソート
    sorted_findings = sorted(
        findings_all, key=lambda x: _severity_rank(x[1]["severity"])
    )
    for i, (asp_label, f) in enumerate(sorted_findings, start=1):
        lines.append(f"### 修正 {i}: {f['title']}")
        lines.append("")
        lines.append(f"- **深刻度**: {_severity_label(f['severity'])}")
        lines.append(f"- **観点**: {asp_label}")
        lines.append(f"- **対象ファイル**: `{f['file_path']}` (行 {f['line_range'][0]}-{f['line_range'][1]})")
        lines.append(f"- **問題**: {f['description']}")
        lines.append(f"- **修正方針**: {f['suggestion']}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## ✅ 完了基準",
        "",
        "- [ ] 全ての P0 (Critical/Major) 修正が完了",
        "- [ ] 既存の全テストが pass",
        "- [ ] 修正ごとに新規テストを追加 (または既存テストで検証済み)",
        "- [ ] コミットは修正単位で分割 (レビュアー可読性のため)",
        "- [ ] CI (lint / type check / test) が全て green",
        "",
        "## 🚀 実行順序の推奨",
        "",
        "1. **再現性系** (Agent シード固定など) — テスト安定化の基盤",
        "2. **構造系** (Synthesizer 分割) — 後続の性能改善で影響を受ける",
        "3. **性能系** (MVP 選定辞書化) — 分割後のクリーンな状態で実施",
        "4. **アルゴリズム / 可読性 / 結果検証** — 独立性が高いので並行可",
    ])
    return "\n".join(lines)


def _build_mock_report_files(target_path: str) -> dict[str, str]:
    """モック用の Step 5 表示ファイル一式 (Markdown / テキスト)。

    実セッションが output/ に書き込まれない mock なので、
    done イベントに直接埋め込んでフロントで表示させる。
    """
    findings_all: list[tuple[str, dict[str, Any]]] = []
    for a in _REVIEW_ASPECTS:
        for f in _sample_findings(a["aspect"]):
            findings_all.append((a["aspect_label"], f))

    # ---- Report ----
    report_lines: list[str] = [
        f"# コードレビュー レポート",
        "",
        f"**対象**: `{target_path}`",
        f"**レビュー観点数**: 6 (アルゴリズム / 再現性 / 性能 / 構造 / 可読性 / 結果検証)",
        f"**指摘件数**: {len(findings_all)} 件",
        "",
        "## エグゼクティブサマリー",
        "",
        "本レビューでは 6 名の AI レビュアーが並行して静的解析を行い、",
        "その後全体会議で相互に指摘を検証し、優先度と対応方針を合意しました。",
        "総合スコアは 5 段階中 **4.1**。全体としてはよく設計されているが、",
        "**再現性 (乱数シード固定)** と **構造 (Synthesizer 責務集中)** に",
        "早期改善を要する指摘が集中しています。",
        "",
        "## 観点別サマリー",
        "",
    ]
    for a in _REVIEW_ASPECTS:
        findings = _sample_findings(a["aspect"])
        crit = sum(1 for f in findings if f["severity"] in ("critical", "major"))
        report_lines.append(
            f"### {a['emoji']} {a['aspect_label']} ({a['role_name']})"
        )
        report_lines.append(
            f"- 指摘 {len(findings)} 件 (要対応 {crit} 件)"
        )
        for f in findings:
            report_lines.append(
                f"  - **{_severity_label(f['severity'])}** {f['title']}"
            )
        report_lines.append("")

    report_lines.extend([
        "## 優先アクションアイテム",
        "",
        "| # | 優先度 | 対象 | 内容 |",
        "|---|--------|------|------|",
    ])
    for i, (asp_label, f) in enumerate(
        sorted(findings_all, key=lambda x: _severity_rank(x[1]["severity"]))[:6],
        start=1,
    ):
        report_lines.append(
            f"| {i} | {_severity_label(f['severity'])} | "
            f"`{f['file_path']}` | {f['title']} |"
        )

    report_lines.extend([
        "",
        "## 全体所感",
        "",
        "モジュール分割は妥当で docstring も充実しているため、新規メンバーの",
        "オンボードは容易な状態です。ただし Synthesizer の責務集中と再現性",
        "設定の欠如は将来的な技術的負債になり得るため、今スプリント内での",
        "対応を推奨します。パフォーマンスは現状でも実運用に耐えますが、",
        "エージェント数の拡張を想定する場合は事前に MVP 選定ループのデータ",
        "構造を辞書ベースに切り替えるとよいでしょう。",
    ])
    report = "\n".join(report_lines)

    # ---- Conversation (全会話ログ、省略なし) ----
    conversation = _build_mock_conversation_log()

    # ---- Evaluation (詳細評価、6 観点で網羅) ----
    evaluation = _build_mock_evaluation()

    # ---- Summary (要約) ----
    summary_lines = [
        f"■ レビュー対象: {target_path}",
        f"■ 参加 AI: 6 観点 (アルゴリズム/再現性/性能/構造/可読性/結果検証)",
        f"■ 指摘件数: {len(findings_all)} 件 "
        f"(critical: {sum(1 for _, f in findings_all if f['severity'] == 'critical')}, "
        f"major: {sum(1 for _, f in findings_all if f['severity'] == 'major')}, "
        f"minor: {sum(1 for _, f in findings_all if f['severity'] == 'minor')})",
        "■ 総合スコア: 4.1 / 5.0",
        "",
        "◇ 最優先で対応すべき事項:",
        "  1. Agent の乱数シード固定 (再現性)",
        "  2. Synthesizer 責務分割 (構造)",
        "  3. MVP 選定ループの計算量改善 (性能)",
        "",
        "◇ 中期的な改善事項:",
        "  4. convergence_threshold の実データベース再算出 (結果検証)",
        "  5. Conductor._run_round の関数分割 (可読性)",
        "  6. Duplicate 判定の set 化 (アルゴリズム)",
        "",
        "◇ 会議のハイライト:",
        "  - Round 3 (反論) で理論屋 → 実装屋の交互応答により",
        "    パフォーマンス改善の投資対効果が定量化された",
        "  - Round 5 (合意) で優先度 P0/P1/P2 の分類が全観点で一致",
        "  - 最終収束度 0.92 (閾値 0.75 を大きく上回る)",
    ]
    summary = "\n".join(summary_lines)

    # ---- Vibe Prompt (Cursor / Copilot Chat 用テンプレート) ----
    vibe_prompt = _build_mock_vibe_prompt(findings_all)

    return {
        "report": report,
        "conversation": conversation,
        "evaluation": evaluation,
        "summary": summary,
        "vibe_prompt": vibe_prompt,
    }


def _severity_rank(sev: str) -> int:
    """深刻度の並び替え用ランク (小さいほど優先)。"""
    return {"critical": 0, "major": 1, "minor": 2, "info": 3}.get(sev, 4)


def _severity_label(sev: str) -> str:
    """深刻度をユーザー可読なラベルに変換。"""
    return {
        "critical": "🔴 Critical",
        "major": "🟠 Major",
        "minor": "🟡 Minor",
        "info": "🔵 Info",
    }.get(sev, "⚪ Unknown")


# ファイル名対応表: build_mock_report_files のキー → 実ファイル名
_MOCK_FILE_NAMES: dict[str, str] = {
    "report":       "report.md",
    "conversation": "full_conversation.md",
    "evaluation":   "evaluation.md",
    "summary":      "summary.txt",
    "vibe_prompt":  "vibe_coding_prompt.md",
}


def _write_mock_session_to_disk(
    session_id: str,
    request: "ReviewStreamRequest",
    files: dict[str, str],
    statistics: dict[str, Any],
    started_at: float,
    completed_at: datetime,
    captured_rounds: list[dict[str, Any]] | None = None,
    captured_findings_by_aspect: dict[str, list[dict[str, Any]]] | None = None,
    captured_cross_qa: list[dict[str, Any]] | None = None,
) -> Path | None:
    """モックセッションを ``output/{session_id}/`` に書き出す (履歴に反映)。

    実セッションと同じ ``session_meta.json`` スキーマで書き出すため、
    履歴一覧 API (``/api/sessions``) が自動的に拾う。

    ``captured_*`` を渡すと、履歴からの各ステップ復元用データも
    ``discussion.json`` に埋め込む。

    Returns:
        書き出したディレクトリ。失敗時は ``None`` (ログのみ)。
    """
    try:
        output_dir = SCRIPT_DIR / "output" / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Markdown / テキスト系の実ファイル書き出し
        output_files: dict[str, str] = {}
        for key, filename in _MOCK_FILE_NAMES.items():
            content = files.get(key, "")
            (output_dir / filename).write_text(content, encoding="utf-8")
            # session_meta の output_files キー名 (実装に合わせて suffix 変換)
            meta_key = {
                "report": "report_md",
                "conversation": "full_conversation_md",
                "evaluation": "evaluation_md",
                "summary": "summary_txt",
                "vibe_prompt": "vibe_coding_prompt_md",
            }[key]
            output_files[meta_key] = filename

        # discussion.json (履歴 → 各ステップ復元用の完全データ)
        rounds_payload = captured_rounds or []
        findings_map = captured_findings_by_aspect or {}
        cross_qa = captured_cross_qa or []
        selected_agents = [
            {
                "role_id": a["role_id"],
                "role_name": a["role_name"],
                "emoji": a["emoji"],
                "model": request.conductor_model,
                "aspect": a["aspect"],
            }
            for a in _REVIEW_ASPECTS
        ]
        discussion_json = {
            "_schema_version": "1.0.0",
            "session_id": session_id,
            "type": "code_review",
            "target_path": request.target_path,
            "hypotheses": [],
            "note": "mock session (Web UI で生成された仮データ)",
            # 各ステップ復元用ペイロード
            "review_context": {
                "target_path": request.target_path,
                "focus": request.focus,
                "scan_result": request.scan_result,
                "part_leaders": request.part_leaders,
                "findings_by_aspect": findings_map,
                "cross_qa": cross_qa,
            },
            "planning": {
                "odsc": {
                    "objective": (
                        f"コードレビュー: {request.target_path}"
                    ),
                    "deliverables": ["レビューレポート", "改善アクション一覧"],
                    "success_criteria": ["主要な欠陥を発見", "優先度が明確"],
                    "constraints": [f"focus={request.focus}"],
                },
                "selected_agents": selected_agents,
                "discussion_plan": {
                    "rounds": [
                        {"round": i + 1, "phase": p[0], "goal": p[1]}
                        for i, p in enumerate(_ROUND_PHASES)
                    ],
                },
                "private_instructions": {},
            },
            "discussion": {
                "rounds": rounds_payload,
                "final_convergence_score": float(
                    statistics.get("final_convergence", 0.0)
                ),
                "early_termination": False,
                "termination_detail": None,
                "score_history": [],
            },
        }
        (output_dir / "discussion.json").write_text(
            json.dumps(discussion_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        output_files["discussion_json"] = "discussion.json"

        # session_meta.json (実セッションと同じスキーマ)
        created_dt = datetime.fromtimestamp(started_at)
        user_prompt = (
            f"コードレビュー: {request.target_path} "
            f"(focus={request.focus}, "
            f"findings={statistics.get('total_utterances', 0)})"
        )
        session_meta = {
            "_schema_version": "1.0.0",
            "session_id": session_id,
            "type": "code_review",
            "status": "completed",
            "created_at": created_dt.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_sec": float(statistics.get("duration_sec", 0.0)),
            "user_prompt": user_prompt,
            "user_prompt_preview": user_prompt[:80],
            "expertise": "intermediate",
            "models_used": [request.conductor_model, request.synth_model],
            "agents_used": [a["role_id"] for a in _REVIEW_ASPECTS],
            "total_rounds": int(statistics.get("rounds_completed", 0)),
            "final_convergence": float(statistics.get("final_convergence", 0.0)),
            "total_requests": int(statistics.get("total_requests", 0)),
            "follow_up": {
                "is_follow_up": False,
                "parent_session_id": None,
                "chain_depth": 0,
                "chain": [session_id],
            },
            "evaluation_summary": {
                "overall_quality": 4.1,
                "mvp": statistics.get("mvp") or "theorist",
                "avg_self_score": 4.0,
                "avg_peer_score": 4.1,
            },
            "output_files": output_files,
            "is_mock": True,
        }
        (output_dir / "session_meta.json").write_text(
            json.dumps(session_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ロール YAML の feedback_history にも追記し、idea + review を合算して
        # roles ページで集計できるようにする。mock 値のためダミースコアだが、
        # is_mvp / session_id / date / topic は実セッションと同じ形式で保存する。
        _persist_mock_review_feedback(
            session_id=session_id,
            user_prompt=user_prompt,
            mvp_role_id=session_meta["evaluation_summary"].get("mvp") or "",
            self_score=float(
                session_meta["evaluation_summary"].get("avg_self_score", 0.0)
            ),
            peer_score=float(
                session_meta["evaluation_summary"].get("avg_peer_score", 0.0)
            ),
        )
        return output_dir
    except OSError as e:
        logger.warning("Failed to write mock session %s: %s", session_id, e)
        return None


def _persist_mock_review_feedback(
    session_id: str,
    user_prompt: str,
    mvp_role_id: str,
    self_score: float,
    peer_score: float,
) -> None:
    """モック review 結果を各参加ロールの feedback_history に追記する。

    Web UI だけの利用でもロール比較 (MVP率・session_count 等) が
    idea + review を合算して反映されるようにするための備え。

    失敗してもセッション書き出し自体は成功扱いとする。
    """
    try:
        fm = get_feedback_manager()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "FeedbackManager unavailable for %s: %s", session_id, e
        )
        return

    date_str = session_id.split("_")[0]
    formatted_date = (
        f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        if len(date_str) == 8
        else date_str
    )
    topic = user_prompt[:80]

    for aspect in _REVIEW_ASPECTS:
        role_id = aspect["role_id"]
        try:
            fm.update_role_feedback(
                role_id=role_id,
                session_id=session_id,
                date=formatted_date,
                topic=topic,
                self_eval={"avg_score": self_score},
                peer_avg=peer_score,
                orchestrator_feedback={},
                is_mvp=(role_id == mvp_role_id),
            )
        except Exception as e:  # noqa: BLE001 - 1 ロール失敗で全体止めない
            logger.warning(
                "Failed to update mock review feedback for %r: %s",
                role_id,
                e,
            )


async def _emit(
    queue: "asyncio.Queue[dict[str, Any]]",
    event: dict[str, Any],
) -> None:
    """イベントをキューに送信し、モック用の遅延を挟む。"""
    await queue.put(event)
    await asyncio.sleep(MOCK_EVENT_DELAY_SEC)
