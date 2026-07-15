"""セッション関連 API。

エンドポイント:
    - GET    /api/sessions               — 一覧 (ページネーション・フィルタ・ソート)
    - GET    /api/sessions/recent        — 最新N件 (ホーム用)
    - GET    /api/sessions/{id}          — メタ情報
    - GET    /api/sessions/{id}/content  — 全コンテンツ
    - GET    /api/sessions/{id}/download — ファイルDL (単体 or ZIP)
    - DELETE /api/sessions/{id}          — 削除

設計書:
    - doc/ui/10_web_api.md §5
    - doc/ui/06_history_replay.md §5
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from web.deps import SCRIPT_DIR

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

OUTPUT_DIR = SCRIPT_DIR / "output"
SESSION_META_FILENAME = "session_meta.json"
DISCUSSION_JSON_FILENAME = "discussion.json"
DEFAULT_RECENT_LIMIT = 5
MAX_RECENT_LIMIT = 50
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 50
PROMPT_PREVIEW_MAX_CHARS = 80

# パストラバーサル防止
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# session_meta.json の type → API レスポンスの type
INTERNAL_TYPE_TO_API = {
    "idea_discussion": "idea",
    "code_review": "review",
}
API_TYPE_TO_INTERNAL = {v: k for k, v in INTERNAL_TYPE_TO_API.items()}

# ダウンロード可能ファイル
FILE_KEY_TO_FILENAME = {
    "report": "report.md",
    "conversation": "full_conversation.md",
    "evaluation": "evaluation.md",
    "summary": "summary.txt",
    "vibe_prompt": "vibe_coding_prompt.md",
}

# 既知ロールの絵文字 (display_name パース失敗時のフォールバック)
ROLE_EMOJI_MAP = {
    "theorist": "🧮",
    "experimentalist": "🔬",
    "implementer": "🤖",
    "literature": "📚",
    "devil": "😈",
    "bird_eye": "🎯",
    "code_architect": "📐",
    "code_reviewer": "📝",
}


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ----------------------------------------------------------------------
# GET /api/sessions — 一覧
# ----------------------------------------------------------------------


@router.get("")
async def list_sessions(
    page: int = Query(1, ge=1, description="ページ番号 (1始まり)"),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    type: Literal["idea", "review"] | None = Query(None, description="タイプフィルタ"),
    search: str | None = Query(None, description="テーマ部分一致検索"),
    sort: Literal[
        "date_desc", "date_asc", "duration_desc", "convergence_desc"
    ] = "date_desc",
    show_chains: bool = Query(False, description="チェーン情報を含める"),
) -> dict[str, Any]:
    """セッション一覧を返す。

    Args:
        page: ページ番号 (1始まり)。
        limit: 1ページの件数。
        type: ``idea`` / ``review`` でフィルタ。
        search: テーマ部分一致 (大文字小文字無視)。
        sort: ソート順。
        show_chains: ``true`` でチェーン情報を ``chains`` キーに含める。

    Returns:
        ``{"sessions": [...], "total": int, "page": int, "pages": int,
        "chains": [...]?}``
    """
    all_sessions = _load_all_sessions(OUTPUT_DIR)

    if type:
        internal_type = API_TYPE_TO_INTERNAL[type]
        all_sessions = [s for s in all_sessions if s.get("type") == internal_type]

    if search:
        kw = search.lower()
        all_sessions = [
            s for s in all_sessions
            if kw in (s.get("user_prompt") or "").lower()
        ]

    all_sessions.sort(key=_resolve_sort_key(sort), reverse=_is_descending(sort))

    total = len(all_sessions)
    pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
    start = (page - 1) * limit
    end = start + limit
    page_items = all_sessions[start:end]

    response: dict[str, Any] = {
        "sessions": [_to_list_summary(meta) for meta in page_items],
        "total": total,
        "page": page,
        "pages": pages,
    }
    if show_chains:
        response["chains"] = _build_chains(all_sessions)
    return response


# ----------------------------------------------------------------------
# GET /api/sessions/recent — 最新N件
# ----------------------------------------------------------------------


@router.get("/recent")
async def get_recent_sessions(
    limit: int = Query(
        DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT,
        description="返却するセッション数の上限",
    ),
    type: Literal["idea", "review"] | None = Query(None),
) -> dict[str, Any]:
    """最新N件のセッションを返す (ホーム用の軽量版)。"""
    all_sessions = _load_all_sessions(OUTPUT_DIR)

    if type:
        internal_type = API_TYPE_TO_INTERNAL[type]
        all_sessions = [s for s in all_sessions if s.get("type") == internal_type]

    all_sessions.sort(key=_sort_key_date, reverse=True)
    trimmed = [_to_recent_summary(meta) for meta in all_sessions[:limit]]
    return {"sessions": trimmed, "total": len(all_sessions)}


# ----------------------------------------------------------------------
# GET /api/sessions/{id} — メタ情報
# ----------------------------------------------------------------------


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """セッションのメタ情報を返す。"""
    session_dir = _resolve_session_dir(session_id)
    meta = _read_meta(session_dir / SESSION_META_FILENAME)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    return _to_detail(meta)


# ----------------------------------------------------------------------
# GET /api/sessions/{id}/content — 全コンテンツ
# ----------------------------------------------------------------------


@router.get("/{session_id}/content")
async def get_session_content(session_id: str) -> dict[str, Any]:
    """セッションの全出力ファイル内容を返す。"""
    session_dir = _resolve_session_dir(session_id)
    meta = _read_meta(session_dir / SESSION_META_FILENAME)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    files: dict[str, str | None] = {}
    for key, filename in FILE_KEY_TO_FILENAME.items():
        path = session_dir / filename
        files[key] = _safe_read_text(path) if path.exists() else None

    follow_up = meta.get("follow_up") or {}
    chain = follow_up.get("chain") or [session_id]
    hypotheses = _extract_hypotheses(session_dir / DISCUSSION_JSON_FILENAME)

    return {
        "session_id": session_id,
        "files": files,
        "chain": chain,
        "hypotheses": hypotheses,
    }


# ----------------------------------------------------------------------
# GET /api/sessions/{id}/restore — 各フェーズ復元用データ
# ----------------------------------------------------------------------


@router.get("/{session_id}/restore")
async def get_session_restore(session_id: str) -> dict[str, Any]:
    """履歴セッションを ``/idea`` or ``/review`` の各ステップに復元するデータを返す。

    Returns:
        ``{type, prompt, plan, review_context?, chat, result}``

        - ``type``: ``idea`` / ``review``
        - ``prompt``: ユーザー入力 (Step 1 復元用)
        - ``plan``: OrchestraPlan の raw dict (Step 2 復元用)
        - ``review_context``: レビュー時のみ ``{scan_result, part_leaders,
            target_path, focus}`` (Step 2 復元用)
        - ``chat``: ``[{type, ...}]`` の配列 (Step 3/4 復元用)
        - ``result``: 各ファイルの Markdown / txt (Step 4/5 復元用)
    """
    session_dir = _resolve_session_dir(session_id)
    meta = _read_meta(session_dir / SESSION_META_FILENAME)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    discussion = _read_json(session_dir / DISCUSSION_JSON_FILENAME) or {}
    internal_type = meta.get("type", "idea_discussion")
    api_type = INTERNAL_TYPE_TO_API.get(internal_type, "idea")

    # ---- Step 1 復元: プロンプト ----
    prompt = meta.get("user_prompt") or ""

    # ---- Step 2 復元: 計画 (odsc / selected_agents / discussion_plan / private_instructions) ----
    planning = discussion.get("planning") or {}
    plan = {
        "odsc": planning.get("odsc") or {},
        "selected_agents": planning.get("selected_agents") or [],
        "discussion_plan": planning.get("discussion_plan") or {},
        "private_instructions": planning.get("private_instructions") or {},
    }

    # ---- Review 固有: スキャン結果と担当割当 ----
    review_context: dict[str, Any] | None = None
    if api_type == "review":
        review_context = discussion.get("review_context") or {
            "target_path": meta.get("user_prompt", ""),
            "scan_result": {},
            "part_leaders": [],
            "focus": "all",
        }

    # ---- Step 3 復元: チャット (round_divider + utterance + conclusion) ----
    chat = _build_chat_items(discussion)

    # ---- Step 4/5 復元: 結果ファイル ----
    files: dict[str, str | None] = {}
    for key, filename in FILE_KEY_TO_FILENAME.items():
        path = session_dir / filename
        files[key] = _safe_read_text(path) if path.exists() else None

    result = {
        "report": files.get("report"),
        "conversation": files.get("conversation"),
        "evaluation": files.get("evaluation"),
        "summary": files.get("summary"),
        "vibe_prompt": files.get("vibe_prompt"),
        "statistics": {
            "duration_sec": meta.get("duration_sec"),
            "total_rounds": meta.get("total_rounds"),
            "final_convergence": meta.get("final_convergence"),
            "mvp": (meta.get("evaluation_summary") or {}).get("mvp"),
            "overall_quality": (
                meta.get("evaluation_summary") or {}
            ).get("overall_quality"),
        },
    }

    return {
        "session_id": session_id,
        "type": api_type,
        "prompt": prompt,
        "plan": plan,
        "review_context": review_context,
        "chat": chat,
        "result": result,
        "meta": {
            "created_at": meta.get("created_at"),
            "completed_at": meta.get("completed_at"),
            "expertise": meta.get("expertise"),
            "is_mock": meta.get("is_mock", False),
        },
    }


# ----------------------------------------------------------------------
# GET /api/sessions/{id}/download — ファイルDL
# ----------------------------------------------------------------------


@router.get("/{session_id}/download")
async def download_session_file(
    session_id: str,
    file: Literal[
        "report", "conversation", "evaluation", "summary", "vibe_prompt", "all"
    ] = Query("report"),
) -> Response:
    """セッションファイルをダウンロードする。

    Args:
        session_id: セッションID。
        file: ``all`` で ZIP、それ以外で単体ファイル。
    """
    session_dir = _resolve_session_dir(session_id)
    if not session_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    if file == "all":
        return _build_zip_response(session_dir, session_id)

    filename = FILE_KEY_TO_FILENAME[file]
    path = session_dir / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {filename}",
        )

    return FileResponse(
        path=path,
        media_type="application/octet-stream",
        filename=f"{session_id}_{filename}",
    )


# ----------------------------------------------------------------------
# DELETE /api/sessions/{id} — 削除
# ----------------------------------------------------------------------


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """セッションディレクトリごと削除する。"""
    session_dir = _resolve_session_dir(session_id)
    if not session_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    try:
        shutil.rmtree(session_dir)
    except OSError as e:
        logger.exception("Failed to delete session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete session: {e}",
        ) from e
    return {"status": "deleted", "session_id": session_id}


# ======================================================================
# Helpers
# ======================================================================


def _resolve_session_dir(session_id: str) -> Path:
    """``session_id`` を検証してディレクトリパスを返す。

    パストラバーサルを防ぐため、英数・``_``・``-`` のみ許可。
    """
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session_id: {session_id}",
        )
    return OUTPUT_DIR / session_id


def _load_all_sessions(output_dir: Path) -> list[dict[str, Any]]:
    """``output_dir`` 配下の全 session_meta.json を読み込む。"""
    if not output_dir.exists() or not output_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for sub in output_dir.iterdir():
        if not sub.is_dir():
            continue
        meta = _read_meta(sub / SESSION_META_FILENAME)
        if meta is not None:
            results.append(meta)
    return results


def _read_meta(meta_path: Path) -> dict[str, Any] | None:
    """``session_meta.json`` を 1 つ読み込む。失敗時は警告して ``None``。"""
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s", meta_path, e)
        return None


def _safe_read_text(path: Path) -> str | None:
    """ファイルを UTF-8 で読み込む。失敗時は ``None``。"""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None


def _extract_hypotheses(discussion_path: Path) -> list[dict[str, Any]] | None:
    """``discussion.json`` から hypotheses を抽出する。"""
    if not discussion_path.exists():
        return None
    try:
        data = json.loads(discussion_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    hyp = data.get("hypotheses")
    if not isinstance(hyp, list):
        return None
    return hyp


def _read_json(path: Path) -> dict[str, Any] | None:
    """任意の JSON を読み込む。失敗時は ``None`` を返す。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _build_chat_items(discussion: dict[str, Any]) -> list[dict[str, Any]]:
    """``discussion.json`` から Step 3 チャット復元用の配列を組み立てる。

    フロント (idea.html / review.html) の ``chatItems`` と互換の形式。
    round_divider → utterance* → conclusion? の順で並べる。
    """
    items: list[dict[str, Any]] = []
    rounds = (discussion.get("discussion") or {}).get("rounds") or []
    if not isinstance(rounds, list):
        return items

    for round_data in rounds:
        if not isinstance(round_data, dict):
            continue
        round_num = round_data.get("round", 0)

        items.append({
            "id": f"divider_{round_num}",
            "type": "round_divider",
            "round": {
                "number": round_num,
                "topic": round_data.get("goal", ""),
                "pattern": round_data.get("phase_name", ""),
            },
        })

        utterances = round_data.get("public_utterances") or []
        if not isinstance(utterances, list):
            continue
        for idx, u in enumerate(utterances, start=1):
            if not isinstance(u, dict):
                continue
            speaker = u.get("speaker") or ""
            items.append({
                "id": f"utt_{round_num}_{idx}",
                "type": "utterance",
                "utterance": {
                    "agent": {
                        "role_id": speaker,
                        "emoji": u.get("speaker_emoji") or "🎭",
                        "name": u.get("speaker_name") or speaker,
                    },
                    "content": u.get("content", ""),
                    "round": round_num,
                    "tokens": _extract_tokens(u.get("tokens_used")),
                    "duration_sec": float(u.get("duration_sec") or 0.0),
                    "is_conclusion": bool(u.get("is_conclusion")),
                },
            })

    return items


def _extract_tokens(value: Any) -> int:
    """``tokens_used`` が dict でも int でも扱えるよう抽出。"""
    if isinstance(value, dict):
        try:
            return int(value.get("total") or 0)
        except (TypeError, ValueError):
            return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sort_key_date(meta: dict[str, Any]) -> str:
    """``completed_at`` 優先、なければ ``created_at``。"""
    return str(meta.get("completed_at") or meta.get("created_at") or "")


def _sort_key_duration(meta: dict[str, Any]) -> float:
    return float(meta.get("duration_sec") or 0.0)


def _sort_key_convergence(meta: dict[str, Any]) -> float:
    eval_sum = meta.get("evaluation_summary") or {}
    return float(eval_sum.get("overall_quality") or 0.0)


def _is_descending(sort: str) -> bool:
    """ソートが降順か。"""
    return sort != "date_asc"


def _resolve_sort_key(sort: str) -> Callable[[dict[str, Any]], Any]:
    """ソート関数を返す。"""
    if sort == "duration_desc":
        return _sort_key_duration
    if sort == "convergence_desc":
        return _sort_key_convergence
    return _sort_key_date


def _to_recent_summary(meta: dict[str, Any]) -> dict[str, Any]:
    """recent エンドポイント用の軽量サマリ。"""
    preview = meta.get("user_prompt_preview")
    if not preview:
        prompt = meta.get("user_prompt") or ""
        preview = prompt[:PROMPT_PREVIEW_MAX_CHARS] if prompt else ""
    return {
        "session_id": meta.get("session_id"),
        "type": meta.get("type"),
        "status": meta.get("status"),
        "created_at": meta.get("created_at"),
        "completed_at": meta.get("completed_at"),
        "duration_sec": meta.get("duration_sec"),
        "total_rounds": meta.get("total_rounds"),
        "user_prompt_preview": preview,
    }


def _to_list_summary(meta: dict[str, Any]) -> dict[str, Any]:
    """list エンドポイント用 (仕様書 §5.1 形式)。"""
    internal_type = meta.get("type") or ""
    api_type = INTERNAL_TYPE_TO_API.get(internal_type, internal_type)

    eval_sum = meta.get("evaluation_summary") or {}
    mvp_id = eval_sum.get("mvp")
    mvp_emoji = ROLE_EMOJI_MAP.get(mvp_id) if mvp_id else None

    follow_up = meta.get("follow_up") or {}
    agents = meta.get("agents_used") or []
    parameters = meta.get("parameters") or {}

    preview = meta.get("user_prompt_preview")
    if not preview:
        prompt = meta.get("user_prompt") or ""
        preview = prompt[:PROMPT_PREVIEW_MAX_CHARS] if prompt else ""

    return {
        "id": meta.get("session_id"),
        "type": api_type,
        "theme": preview,
        "date": meta.get("completed_at") or meta.get("created_at"),
        "duration_sec": meta.get("duration_sec"),
        "convergence": meta.get("final_convergence"),
        "mvp_role_id": mvp_id,
        "mvp_emoji": mvp_emoji,
        "focus": parameters.get("focus"),
        "chain_depth": follow_up.get("chain_depth", 0),
        "agents_count": len(agents),
        "rounds_completed": meta.get("total_rounds", 0),
    }


def _to_detail(meta: dict[str, Any]) -> dict[str, Any]:
    """単一セッション詳細レスポンス (仕様書 §5.3 形式)。"""
    internal_type = meta.get("type") or ""
    api_type = INTERNAL_TYPE_TO_API.get(internal_type, internal_type)
    eval_sum = meta.get("evaluation_summary") or {}
    follow_up = meta.get("follow_up") or {}

    return {
        "id": meta.get("session_id"),
        "type": api_type,
        "theme": meta.get("user_prompt"),
        "created_at": meta.get("created_at"),
        "completed_at": meta.get("completed_at"),
        "parameters": meta.get("parameters") or {},
        "agents": meta.get("agents_used") or [],
        "models_used": meta.get("models_used") or [],
        "statistics": {
            "duration_sec": meta.get("duration_sec"),
            "total_utterances": meta.get("total_utterances"),
            "total_tokens": meta.get("total_tokens"),
            "total_requests": meta.get("total_requests"),
            "rounds_completed": meta.get("total_rounds"),
            "final_convergence": meta.get("final_convergence"),
            "mvp": eval_sum.get("mvp"),
        },
        "follow_up": {
            "previous_session_id": follow_up.get("parent_session_id"),
            "chain_depth": follow_up.get("chain_depth", 0),
            "chain": follow_up.get("chain") or [meta.get("session_id")],
        },
    }


def _build_chains(sessions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """フォローアップチェーンを集計する。

    2 件以上のチェーンのみ返す。重複は除外。
    """
    seen: set[tuple[str, ...]] = set()
    chains: list[list[dict[str, Any]]] = []

    by_id: dict[str, dict[str, Any]] = {
        s["session_id"]: s for s in sessions if s.get("session_id")
    }

    for s in sessions:
        follow_up = s.get("follow_up") or {}
        chain_ids = follow_up.get("chain") or []
        if len(chain_ids) < 2:
            continue
        key = tuple(chain_ids)
        if key in seen:
            continue
        seen.add(key)

        chain_items: list[dict[str, Any]] = []
        for cid in chain_ids:
            meta = by_id.get(cid)
            theme = ""
            date = None
            if meta:
                theme = meta.get("user_prompt_preview") or (
                    (meta.get("user_prompt") or "")[:PROMPT_PREVIEW_MAX_CHARS]
                )
                date = meta.get("completed_at") or meta.get("created_at")
            chain_items.append({"id": cid, "date": date, "theme": theme})
        chains.append(chain_items)
    return chains


def _build_zip_response(session_dir: Path, session_id: str) -> Response:
    """セッションディレクトリ内の全ファイルを ZIP にして返す。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in session_dir.iterdir():
            if child.is_file():
                zf.write(child, arcname=f"{session_id}/{child.name}")

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}.zip"',
        },
    )
