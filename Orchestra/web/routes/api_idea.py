"""Idea Discussion API (計画立案 + SSE ストリーミング実行)。

エンドポイント:
    - POST /api/idea/plan   — Phase 1 (計画立案) のみ実行 → JSON
    - POST /api/idea/stream — Phase 2 (議論) + Phase 3 (統合) を SSE で配信

設計書:
    - doc/ui/08_sse_realtime.md §6
    - doc/ui/10_web_api.md §3
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.api_client import ResilientAPIClient
from core.base_feature import PhaseKey
from core.config_loader import Settings
from core.feedback import FeedbackManager
from core.intervention import SSEInterventionHandler
from core.orchestrator import Orchestrator
from core.rate_tracker import RateLimitTracker
from core.role_manager import RoleManager
from web.deps import (
    get_api_client,
    get_feedback_manager,
    get_rate_tracker,
    get_role_manager,
    get_settings,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

MIN_PROMPT_CHARS = 5
MAX_PROMPT_CHARS = 5000
MIN_TIME_LIMIT_SEC = 60
MAX_TIME_LIMIT_SEC = 1800
MIN_AGENTS = 2
MAX_AGENTS = 8
MAX_ATTACHED_FILES = 5
SSE_KEEPALIVE_SEC = 30.0
SSE_QUEUE_MAXSIZE = 1000
MAX_CONCURRENT_SESSIONS = 3
EXPERTISE_VALUES = ("beginner", "intermediate", "expert")

# 同時実行セッション数を制限するセマフォ
_sse_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)

router = APIRouter(prefix="/api/idea", tags=["idea"])


# ----------------------------------------------------------------------
# Request / Response models
# ----------------------------------------------------------------------


class IdeaPlanRequest(BaseModel):
    """POST /api/idea/plan のリクエスト。"""

    prompt: str = Field(..., min_length=MIN_PROMPT_CHARS, max_length=MAX_PROMPT_CHARS)
    planner_model: str = "gpt-5.4"
    conductor_model: str = "gpt-4.1"
    synth_model: str = "gpt-5.4"
    time_limit: int = Field(300, ge=MIN_TIME_LIMIT_SEC, le=MAX_TIME_LIMIT_SEC)
    max_agents: int = Field(5, ge=MIN_AGENTS, le=MAX_AGENTS)
    expertise: Literal["beginner", "intermediate", "expert"] = "intermediate"
    follow_up_id: str | None = None
    attached_files: list[str] = Field(default_factory=list, max_length=MAX_ATTACHED_FILES)
    # ユーザーが UI でクリックして選択した優先候補ロール。
    # 空なら指揮者に全自動選定させる。
    preferred_role_ids: list[str] = Field(default_factory=list, max_length=MAX_AGENTS)


class IdeaStreamRequest(BaseModel):
    """POST /api/idea/stream のリクエスト。"""

    plan: dict[str, Any]
    prompt: str = Field(..., min_length=MIN_PROMPT_CHARS, max_length=MAX_PROMPT_CHARS)
    conductor_model: str = "gpt-4.1"
    synth_model: str = "gpt-5.4"
    time_limit: int = Field(300, ge=MIN_TIME_LIMIT_SEC, le=MAX_TIME_LIMIT_SEC)
    expertise: Literal["beginner", "intermediate", "expert"] = "intermediate"


# ----------------------------------------------------------------------
# POST /api/idea/plan
# ----------------------------------------------------------------------


@router.post("/plan")
async def plan_idea(
    request: IdeaPlanRequest,
    settings: Settings = Depends(get_settings),
    api_client: ResilientAPIClient = Depends(get_api_client),
    role_manager: RoleManager = Depends(get_role_manager),
    feedback_manager: FeedbackManager = Depends(get_feedback_manager),
    rate_tracker: RateLimitTracker = Depends(get_rate_tracker),
) -> dict[str, Any]:
    """Phase 1 (計画立案) のみ実行して結果を返す。

    Args:
        request: 計画立案リクエスト。

    Returns:
        ``{"plan": dict, "estimated_requests": int, "remaining_quota": int}``

    Raises:
        HTTPException: 422 (バリデーション) / 500 (内部エラー)。
    """
    orchestrator = Orchestrator(
        api_client=api_client,
        role_manager=role_manager,
        feedback_manager=feedback_manager,
        settings=settings,
    )

    try:
        plan = await orchestrator.plan(
            user_input=request.prompt,
            model=request.planner_model,
            time_limit_sec=float(request.time_limit),
            max_agents=request.max_agents,
            expertise=request.expertise,
            preferred_role_ids=request.preferred_role_ids,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("plan generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"計画立案に失敗しました: {e}",
        ) from e

    plan_dict = _plan_to_dict(plan)
    estimated_requests = _estimate_total_requests(plan)
    return {
        "plan": plan_dict,
        "estimated_requests": estimated_requests,
        "remaining_quota": rate_tracker.remaining(),
    }


# ----------------------------------------------------------------------
# POST /api/idea/stream
# ----------------------------------------------------------------------


@router.post("/stream")
async def stream_idea_discussion(request: IdeaStreamRequest) -> StreamingResponse:
    """議論を SSE でストリーミングする。

    同時実行は最大 ``MAX_CONCURRENT_SESSIONS`` セッション。
    超過時は 429 を返す。
    """
    if _sse_semaphore.locked() and _sse_semaphore._value <= 0:  # type: ignore[attr-defined]
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": (
                    f"同時実行セッション数の上限 ({MAX_CONCURRENT_SESSIONS}) です。"
                    "しばらくお待ちください。"
                )
            },
        )

    return StreamingResponse(
        _event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ----------------------------------------------------------------------
# SSE event generator
# ----------------------------------------------------------------------


async def _event_generator(
    request: IdeaStreamRequest,
) -> AsyncIterator[str]:
    """SSE イベントを生成する非同期ジェネレータ。

    動作:
        1. ``asyncio.Queue`` と ``SSEInterventionHandler`` を作る
        2. ``_run_orchestra`` をバックグラウンドタスクで起動
        3. キューからイベントを取り出して ``data: {...}\\n\\n`` 形式で yield
        4. 30 秒イベントなしなら ``: keepalive\\n\\n`` を送信
        5. ``done`` / ``error`` でループ終了
        6. クライアント切断時はタスクをキャンセル
    """
    async with _sse_semaphore:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE)
        intervention = SSEInterventionHandler(queue)
        task = asyncio.create_task(_run_orchestra(request, intervention, queue))

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_SEC)
                except asyncio.TimeoutError:
                    # 30 秒イベントなし → keepalive コメント
                    yield ": keepalive\n\n"
                    if task.done():
                        # タスクが終わっていたのに通知が来ていない (異常系)
                        break
                    continue

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if event.get("type") in ("done", "error"):
                    break

        except (asyncio.CancelledError, GeneratorExit):
            logger.info("SSE client disconnected; cancelling orchestra task")
            raise
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass


# ----------------------------------------------------------------------
# Core engine runner
# ----------------------------------------------------------------------


async def _run_orchestra(
    request: IdeaStreamRequest,
    intervention: SSEInterventionHandler,
    queue: "asyncio.Queue[dict[str, Any]]",
) -> None:
    """コアエンジン (IdeaDiscussion) を実行し、SSE イベントを送信する。

    Note:
        現状の ``IdeaDiscussion`` は ``on_phase(name)`` callback しか
        持たないため、SSE で配信できるのは粗粒度のフェーズ通知のみ。
        将来 ``Conductor`` 側に ``notify_progress`` の呼び出しを足せば
        ``utterance`` / ``round_start`` 等の細粒度イベントを配信できる。
    """
    from cli_runner import build_idea_discussion, load_settings

    try:
        await intervention.notify_progress_async("discussion_start", {})

        settings = load_settings()
        feature = build_idea_discussion(settings, no_confirm=True)

        def _on_phase(name: str) -> None:
            """下位互換: フェーズ表示名だけを SSE に転送する。

            新形式の判定 (synthesis_start など) は ``_on_phase_key`` で行う。
            """
            logger.info("orchestra phase (name): %s", name)

        def _on_phase_key(key: PhaseKey, name: str) -> None:
            """新形式: PhaseKey ベースの通知と派生イベントを送る。

            Phase 4 (結果) に入ったタイミングで ``synthesis_start`` を発火し、
            フロントでタイマー停止 + 統合開始 UI を出す。
            """
            logger.info("orchestra phase: %s (%s)", key.value, name)
            intervention.notify_progress("phase", {
                "key": key.value,
                "name": name,
            })
            if key == PhaseKey.RESULT:
                intervention.notify_progress("synthesis_start", {"name": name})

        # Web UI で送られてきた plan を dict → OrchestraPlan に復元 (Phase 1 スキップ)
        try:
            plan = Orchestrator.plan_from_dict(request.plan)
        except Exception as e:  # noqa: BLE001
            logger.exception("failed to reconstruct plan from request")
            await intervention.notify_progress_async("error", {
                "message": f"計画データの復元に失敗しました: {e}",
                "recoverable": False,
                "error_type": type(e).__name__,
            })
            return

        logger.info(
            "starting run_from_plan: %d agents, %d rounds, time_limit=%ds",
            len(plan.selected_agents),
            len(plan.discussion_plan.round_config) if plan.discussion_plan else 0,
            request.time_limit,
        )

        output_path = await feature.run_from_plan(
            user_input=request.prompt,
            plan=plan,
            conductor_model=request.conductor_model,
            synth_model=request.synth_model,
            time_limit=float(request.time_limit),
            expertise=request.expertise,
            on_phase=_on_phase,
            on_phase_key=_on_phase_key,
            intervention=intervention,
        )

        if output_path is None:
            await intervention.notify_progress_async("error", {
                "message": "議論がキャンセルされました",
                "recoverable": False,
                "error_type": "Cancelled",
            })
            return

        session_id = output_path.name
        await intervention.notify_progress_async("done", {
            "session_id": session_id,
            "output_dir": str(output_path),
            "statistics": {},
        })
    except asyncio.CancelledError:
        # クライアント切断
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestra execution failed")
        try:
            await intervention.notify_progress_async("error", {
                "message": str(e),
                "recoverable": False,
                "error_type": type(e).__name__,
            })
        except Exception:  # noqa: BLE001
            pass
    finally:
        # ジェネレータ側に終了を伝えるため done を保証
        if queue.empty():
            try:
                queue.put_nowait({"type": "done", "session_id": None, "output_dir": None})
            except asyncio.QueueFull:
                pass


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _plan_to_dict(plan: Any) -> dict[str, Any]:
    """``OrchestraPlan`` を JSON-safe な dict に変換する。

    ``Path`` 等の非シリアライズ値が含まれていれば str に丸める。
    """
    raw = dataclasses.asdict(plan)
    return _normalize(raw)


def _normalize(obj: Any) -> Any:
    """ネストした dict/list を再帰的に JSON-safe にする。"""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _estimate_total_requests(plan: Any) -> int:
    """計画から推定リクエスト数を返す。

    ``discussion_plan.total_estimated_requests`` があればそれを優先、
    なければラウンド数 × 平均発言者数で粗推定する。
    """
    dp = getattr(plan, "discussion_plan", None)
    if dp is None:
        return 0
    if getattr(dp, "total_estimated_requests", 0):
        return int(dp.total_estimated_requests)
    rounds = getattr(dp, "round_config", []) or []
    return sum(len(getattr(r, "speakers", [])) + 1 for r in rounds)
