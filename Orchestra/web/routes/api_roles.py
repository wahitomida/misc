"""ロール関連 API (CRUD + AI 自動生成)。

エンドポイント:
    - GET    /api/roles                   — 全ロール一覧 (統計サマリー付き)
    - POST   /api/roles                   — ロール新規作成
    - POST   /api/roles/generate          — description/perspective/tone から
                                            system_prompt 他を AI 自動生成
    - GET    /api/roles/_template         — 新規作成用のロール雛形
    - GET    /api/roles/_models           — 選択可能なモデル一覧
    - GET    /api/roles/{role_id}         — ロール詳細
    - PUT    /api/roles/{role_id}         — ロール更新
    - DELETE /api/roles/{role_id}         — ロール削除 (デフォルトは 403)
    - GET    /api/roles/{role_id}/stats   — パフォーマンス統計

設計書: doc/ui/10_web_api.md §6, doc/ui/07_roles_page.md §8
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from core.exceptions import (
    ConfigLoadError,
    RoleNotFoundError,
    RoleProtectedError,
    RoleValidationError,
)
from core.role_manager import (
    DEFAULT_ROLES,
    PROTECTED_FIELDS_ON_UPDATE,
    ROLE_ID_PATTERN,
    RoleManager,
)
from web.deps import get_api_client, get_role_manager

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

# display_name の先頭絵文字を抽出する正規表現
# 例: "🧮 理論屋" → ("🧮", "理論屋")
DISPLAY_NAME_PATTERN = re.compile(r"^(\S+)\s+(.+)$")

RECENT_FEEDBACK_LIMIT = 5

AVAILABLE_MODELS: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-4.1",
    "gpt-4.1-mini",
    "claude-sonnet-4-5",
)

# AI 自動生成に使うモデルとパラメータ
GENERATION_MODEL = "gpt-4.1"
GENERATION_TEMPERATURE = 0.7
GENERATION_MAX_TOKENS = 2000

# 新スキーマの新規ロール雛形 (共通テンプレート付与前提でプレースホルダーなし)
_TEMPLATE_SYSTEM_PROMPT = """あなたは(ロールの役割説明)です。

【役割】
- ここに役割を記述

【発言スタイル】
- ここにキャラクターと口調を記述

【提供すべき価値】
- 具体例・専門知見をどう提供するか
"""

router = APIRouter(prefix="/api/roles", tags=["roles"])


# ======================================================================
# GET /api/roles — 一覧
# ======================================================================


@router.get("")
async def list_roles(
    role_manager: RoleManager = Depends(get_role_manager),
) -> list[dict[str, Any]]:
    """全ロール一覧 (統計サマリー付き) を返す。

    Returns:
        各ロールが ``{id, name, emoji, specialty, is_default, stats}`` を持つリスト。
    """
    role_manager.refresh_cache()
    results: list[dict[str, Any]] = []
    for role_id in _iter_role_ids(role_manager):
        role = _safe_load(role_manager, role_id)
        if role is None:
            continue
        results.append(_to_summary(role))
    results.sort(key=lambda r: r["id"])
    return results


# ======================================================================
# GET /api/roles/_template — 新規作成用のロール雛形
# ======================================================================


@router.get("/_template")
async def get_role_template() -> dict[str, Any]:
    """新規作成時のロール定義テンプレートを返す。"""
    return {
        "role_id": "",
        "display_name": "",
        "model": "gpt-4.1",
        "default_level": "medium",
        "description": "",
        "perspective": "",
        "tone": "",
        "system_prompt": _TEMPLATE_SYSTEM_PROMPT,
        "domain_tags": [],
        "evaluation_criteria": [],
    }


# ======================================================================
# GET /api/roles/_models — 利用可能モデル一覧
# ======================================================================


@router.get("/_models")
async def get_available_models() -> dict[str, list[str]]:
    """モデル一覧を返す。"""
    return {"models": list(AVAILABLE_MODELS)}


# ======================================================================
# POST /api/roles/generate — AI 自動生成
# ======================================================================


@router.post("/generate")
async def generate_role_config(
    payload: dict[str, Any] = Body(...),
    api_client: Any = Depends(get_api_client),
) -> dict[str, Any]:
    """description/perspective/tone から system_prompt 他を AI 生成する。

    Body:
        ``{description, perspective, tone, display_name?, emoji?}``

    Returns:
        ``{system_prompt, domain_tags, evaluation_criteria}``

    Raises:
        HTTPException 400: 入力が不足。
        HTTPException 502: AI 生成に失敗。
    """
    description = (payload.get("description") or "").strip()
    perspective = (payload.get("perspective") or "").strip()
    tone = (payload.get("tone") or "").strip()
    display_name = (payload.get("display_name") or "").strip()
    emoji = (payload.get("emoji") or "").strip()

    if not (description or perspective or tone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="description / perspective / tone のいずれかは入力してください",
        )

    prompt = _build_generation_prompt(
        description=description,
        perspective=perspective,
        tone=tone,
        display_name=display_name,
        emoji=emoji,
    )

    try:
        response = await api_client.call(
            model=GENERATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたはAI議論参加者のロール定義を JSON で生成するアシスタントです。"
                        " 必ず有効な JSON オブジェクトを返してください。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=GENERATION_TEMPERATURE,
            max_tokens=GENERATION_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except Exception as e:  # noqa: BLE001 - AI 呼び出し失敗をまとめて 502 で返す
        logger.warning("Role generation LLM call failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI生成に失敗しました: {e}",
        ) from e

    content = str(response.get("content") or "").strip()
    parsed = _parse_generation_json(content)
    if parsed is None:
        logger.warning("Role generation response is not valid JSON: %s", content[:200])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI生成の応答が不正な形式でした。もう一度お試しください。",
        )
    return _normalize_generation_result(parsed)


# ======================================================================
# POST /api/roles — 新規作成
# ======================================================================


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: dict[str, Any] = Body(...),
    role_manager: RoleManager = Depends(get_role_manager),
) -> dict[str, str]:
    """ロールを新規作成する。

    Returns:
        ``{"role_id", "message"}``。

    Raises:
        HTTPException: 400 (role_id 無効), 409 (既存), 422 (バリデーション失敗)。
    """
    role_id = payload.get("role_id", "")
    if not isinstance(role_id, str) or not ROLE_ID_PATTERN.match(role_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role_id",
        )

    path = role_manager.roles_dir / f"{role_id}.yaml"
    if path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role '{role_id}' already exists",
        )

    # feedback 系はサーバー側で初期化 (ユーザー送信を無視)
    for field in PROTECTED_FIELDS_ON_UPDATE:
        payload.pop(field, None)

    errors = role_manager.validate_role_data(payload)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Validation failed", "errors": errors},
        )

    try:
        role_manager.save_role(payload)
    except (RoleValidationError, ConfigLoadError) as e:
        logger.warning("Failed to create role %s: %s", role_id, e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e), "errors": [str(e)]},
        ) from e

    return {"role_id": role_id, "message": "Role created"}


# ======================================================================
# GET /api/roles/{role_id} — 詳細
# ======================================================================


@router.get("/{role_id}")
async def get_role(
    role_id: str,
    role_manager: RoleManager = Depends(get_role_manager),
) -> dict[str, Any]:
    """ロール詳細を返す。"""
    role = _load_role(role_manager, role_id)
    emoji, name = _split_display_name(role.get("display_name", ""))
    personality = role.get("personality") or {}
    traits = personality.get("traits") or []
    return {
        "id": role.get("role_id"),
        "name": name,
        "emoji": emoji,
        "specialty": ", ".join(role.get("expertise") or []),
        "personality": (
            personality.get("communication_style")
            or (traits[0] if traits else "")
        ),
        "weaknesses": personality.get("weakness", ""),
        "speaking_rules": traits,
        "model": role.get("model"),
        "default_level": role.get("default_level"),
        "domain_tags": role.get("domain_tags") or [],
        "system_prompt": role.get("system_prompt", ""),
        "evaluation_criteria": role.get("evaluation_criteria") or [],
        "is_default": role_manager.is_default_role(role_id),
        # 編集フォーム用の完全な定義 (raw)
        "raw": _build_raw_role(role),
    }


# ======================================================================
# PUT /api/roles/{role_id} — 更新
# ======================================================================


@router.put("/{role_id}")
async def update_role(
    role_id: str,
    payload: dict[str, Any] = Body(...),
    role_manager: RoleManager = Depends(get_role_manager),
) -> dict[str, str]:
    """既存ロールを更新する。role_id は URL 側を優先し変更不可。

    ``feedback_history`` / ``feedback_stats`` はリクエストに含まれても
    既存 YAML の値で上書きされる (蓄積データの保護)。
    """
    if not ROLE_ID_PATTERN.match(role_id or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role_id",
        )
    try:
        existing = role_manager.load_role(role_id)
    except RoleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{role_id}' not found",
        ) from e

    merged: dict[str, Any] = {**existing, **payload}
    merged["role_id"] = role_id  # URL 側を最終権威に
    for field in PROTECTED_FIELDS_ON_UPDATE:
        if field in existing:
            merged[field] = existing[field]
        else:
            merged.pop(field, None)

    errors = role_manager.validate_role_data(merged)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Validation failed", "errors": errors},
        )

    try:
        role_manager.save_role(merged)
    except (RoleValidationError, ConfigLoadError) as e:
        logger.warning("Failed to update role %s: %s", role_id, e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e), "errors": [str(e)]},
        ) from e

    return {"role_id": role_id, "message": "Role updated"}


# ======================================================================
# DELETE /api/roles/{role_id} — 削除
# ======================================================================


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    role_manager: RoleManager = Depends(get_role_manager),
) -> dict[str, str]:
    """ロールを削除する。デフォルトロールは 403。"""
    try:
        role_manager.delete_role(role_id)
    except RoleProtectedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="デフォルトロールは削除できません",
        ) from e
    except RoleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{role_id}' not found",
        ) from e
    except ConfigLoadError as e:
        logger.warning("Failed to delete role %s: %s", role_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    return {"role_id": role_id, "message": "Role deleted"}


# ======================================================================
# GET /api/roles/{role_id}/stats — 統計
# ======================================================================


@router.get("/{role_id}/stats")
async def get_role_stats(
    role_id: str,
    role_manager: RoleManager = Depends(get_role_manager),
) -> dict[str, Any]:
    """ロール統計 (履歴 + 最近フィードバック) を返す。"""
    role = _load_role(role_manager, role_id)
    stats = role.get("feedback_stats") or {}
    history_full = role.get("feedback_history") or []

    history = [_to_history_entry(h) for h in history_full]
    recent_feedback = [
        _to_feedback_entry(h) for h in history_full[-RECENT_FEEDBACK_LIMIT:]
    ]
    recent_feedback.reverse()

    self_avg = float(stats.get("avg_self_score") or 0.0)
    peer_avg = float(stats.get("avg_peer_score") or 0.0)
    mvp_count = _count_mvp(history_full)

    return {
        "role_id": role.get("role_id"),
        "session_count": int(stats.get("total_sessions") or len(history_full)),
        "self_avg": self_avg,
        "peer_avg": peer_avg,
        "mvp_count": mvp_count,
        "trend": stats.get("trend") or "stable",
        "history": history,
        "recent_feedback": recent_feedback,
    }


# ======================================================================
# Helpers
# ======================================================================


def _iter_role_ids(role_manager: RoleManager):
    """``roles_dir`` の YAML から role_id (stem) を yield する。"""
    if not role_manager.roles_dir.exists():
        return
    for yaml_path in sorted(role_manager.roles_dir.glob("*.yaml")):
        yield yaml_path.stem


def _safe_load(
    role_manager: RoleManager, role_id: str
) -> dict[str, Any] | None:
    """バリデーション失敗などは警告してスキップ。"""
    try:
        return role_manager.load_role(role_id)
    except (RoleNotFoundError, RoleValidationError, ConfigLoadError) as e:
        logger.warning("Skipping role %s: %s", role_id, e)
        return None


def _load_role(role_manager: RoleManager, role_id: str) -> dict[str, Any]:
    """``role_id`` を検証しつつロード。失敗時は HTTPException。"""
    if not ROLE_ID_PATTERN.match(role_id or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role_id: {role_id}",
        )
    try:
        return role_manager.load_role(role_id)
    except RoleNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role not found: {role_id}",
        ) from e
    except (RoleValidationError, ConfigLoadError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


def _split_display_name(display_name: str) -> tuple[str, str]:
    """``"🧮 理論屋"`` → ``("🧮", "理論屋")`` に分割。

    フォーマット外なら ``("", display_name)`` を返す。
    """
    m = DISPLAY_NAME_PATTERN.match(display_name or "")
    if m:
        return m.group(1), m.group(2)
    return "", display_name or ""


def _to_summary(role: dict[str, Any]) -> dict[str, Any]:
    """一覧用サマリ。"""
    role_id = role.get("role_id", "")
    emoji, name = _split_display_name(role.get("display_name", ""))
    expertise = role.get("expertise") or []
    stats = role.get("feedback_stats") or {}
    history = role.get("feedback_history") or []
    self_avg = float(stats.get("avg_self_score") or 0.0)
    peer_avg = float(stats.get("avg_peer_score") or 0.0)
    avg = (self_avg + peer_avg) / 2 if (self_avg or peer_avg) else 0.0
    return {
        "id": role_id,
        "name": name,
        "emoji": emoji,
        "specialty": expertise[0] if expertise else "",
        "is_default": role_id in DEFAULT_ROLES,
        "stats": {
            "session_count": int(stats.get("total_sessions") or len(history)),
            "avg_score": round(avg, 2),
            "self_avg": round(self_avg, 2),
            "peer_avg": round(peer_avg, 2),
            "mvp_count": _count_mvp(history),
            "trend": stats.get("trend") or "stable",
        },
    }


def _build_raw_role(role: dict[str, Any]) -> dict[str, Any]:
    """編集フォーム用の完全な role dict (feedback 系を除外)。"""
    raw = {k: v for k, v in role.items() if k not in PROTECTED_FIELDS_ON_UPDATE}
    # display_name から emoji と name を分離してフォーム利便性を上げる
    emoji, name = _split_display_name(role.get("display_name", ""))
    raw["_emoji"] = emoji
    raw["_name"] = name
    return raw


def _to_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """feedback_history の 1 件を統計 history 用に整形。"""
    return {
        "session_id": entry.get("session_id"),
        "date": entry.get("date") or entry.get("completed_at"),
        "topic": entry.get("topic") or "",
        "self_eval_avg": float(
            entry.get("self_score_avg") or entry.get("self_eval_avg") or 0.0
        ),
        "peer_eval_avg": float(
            entry.get("peer_score_avg") or entry.get("peer_eval_avg") or 0.0
        ),
    }


def _to_feedback_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """feedback_history の 1 件を recent_feedback 用に整形。"""
    base = _to_history_entry(entry)
    base["orchestrator_feedback"] = entry.get("orchestrator_feedback") or ""
    return base


def _count_mvp(history: list[dict[str, Any]]) -> int:
    """``feedback_history`` の中で MVP 受賞回数をカウントする。"""
    return sum(1 for h in history if h.get("is_mvp"))


# ======================================================================
# AI 自動生成用ヘルパー
# ======================================================================


def _build_generation_prompt(
    *,
    description: str,
    perspective: str,
    tone: str,
    display_name: str,
    emoji: str,
) -> str:
    """LLM に投げる生成プロンプトを組み立てる。

    共通テンプレート (発言ルール等) は Agent 側で先頭に付与されるため、
    ここで生成する system_prompt はロール固有部分のみで良い。

    P0-P4 の知見を反映:
        - 独自価値の明示 (単なる〜ではない、〇〇するのが独自の価値)
        - 発言の型 3〜5 パターン (毎回違う型を使うことで口癖固定を防ぐ)
        - 文頭固定 & 感嘆連発の禁止
        - ロール類型別の追加ルール (ビジネス系なら数字 2-3 ステップ導出等)
    """
    header_lines: list[str] = []
    if display_name:
        header_lines.append(f"表示名: {display_name}")
    if emoji:
        header_lines.append(f"絵文字: {emoji}")
    header = "\n".join(header_lines)
    return f"""以下のイメージからAI議論参加者のロール設定を生成してください。

{header}
概要 (description): {description or '(未指定)'}
視点・専門性 (perspective): {perspective or '(未指定)'}
口調・キャラクター (tone): {tone or '(未指定)'}

【このロールが議論で成立するための重要な設計指針】
複数の AI が議論する場では、各ロールが「他とは違う独自の視点」を持ち、
毎回異なる型で発言することが決定的に重要です。以下 5 点を必ず生成物に
組み込んでください。

1. **独自価値**: このロールは単なる整理役や司会者ではなく、
   「参加者が気付いていない〇〇を指摘するのが独自の価値」と 1 文で明示する。
2. **発言の型 3〜5 個**: 毎回どれか 1 つを選んで発言する型のリスト。
   例: 「構造分解」「アナロジー提示」「前提疑い」「反例提示」「時間軸切り」など。
   型は互いに重複しないことが大事 (例: 「反例提示」と「エッジケース」は同種なので統合)。
3. **文頭固定禁止**: system_prompt の【発言スタイル】に
   「文頭固定禁止: 3 回連続で同じ文頭を使わない」を含める。
4. **感嘆連発禁止**: 「感嘆の連発 (キャラっぽい口癖の連続) は禁止」を含める。
5. **禁止事項 2〜3 個**: このロールがやってはいけないことを列挙 (例: 「毎ターン発言する」
   「細部の技術議論に踏み込みすぎる」「否定だけで代替案を出さない」など)。

【ロール類型別の追加ルール】
description / perspective / tone から類型を判断し、該当するルールを追加:
- **ビジネス系** (経営・投資・戦略・事業スケール等が主題):
  「数字を出す時は必ず 2〜3 ステップの導出ロジックを添える。単独の値だけ言うのは禁止。
   悪例:『ARR 100 億』良例:『対象市場 3000 億×浸透率 3% = 90 億』」
- **技術系** (実装・理論・実験等が主題):
  「疑似変数 (τ=0.8、ε=0.1 等) や単位の羅列は禁止。実際の会議で口頭で言える表現に留める」
- **反論系** (穴探し・悪魔の代弁者等):
  「反例の後には必ず修復案 (『じゃあ〇〇すれば回避できるかも』) を添える」
- **俯瞰系** (メタ整理・ファシリテーター等):
  「発言を要約するだけの回は禁止。必ず構造的な指摘を含める」
- **現場系** (製造・営業・顧客体験等):
  「抽象論は禁止。具体的な人・場面・数字を必ず 1 つ入れる」

【生成物のスキーマ (JSON オブジェクト 1 個で返す)】
{{
  "system_prompt": string,          // 400〜800 文字。下記構造を必ず含める
  "unique_value": string,           // 1〜2 文。「あなたは単なる〜ではない。〇〇するのが独自の価値」形式
  "speech_patterns": [              // 3〜5 個。毎回どれか 1 つを選ぶ型
    {{"name": string, "description": string}}
  ],
  "expertise": string[],            // 3〜6 個。専門スキル名 (日本語 OK)
  "personality": {{
    "traits": string[],              // 3〜5 個。性格・思考の特徴を短いフレーズで
    "communication_style": string,   // 100〜200 文字。口調を自然文で
    "weakness": string               // 50〜100 文字。自覚すべき限界
  }},
  "domain_tags": string[],          // 3〜5 個。英語スネークケース
  "evaluation_criteria": [          // 3 件
    {{"name": string, "description": string}}
  ]
}}

【system_prompt の必須構造 (以下のセクションを必ず含める)】
```
あなたは〇〇です。

【あなたが知っていること】
- (知識・専門領域 5 個以内)

【役割】
- (議論で果たす機能 3〜5 個)

【あなたの独自価値】
- (unique_value の内容を反映)
- 発言を要約するだけの回は禁止。必ず〇〇の指摘を含める。

【あなたの発言の型 (毎回どれか一つを選ぶ。連続で同じ型は禁止)】
- 型 1「〇〇」: (どんな時に、どう発言するか 1 文)
- 型 2「△△」: (同上)
- 型 3「□□」: (同上)
(4〜5 個あれば追加)

【発言スタイル】
- 1 発言 50〜150 文字。
- 文頭固定禁止: 3 回連続で同じ文頭を使わない。
- 感嘆の連発は禁止 (キャラっぽい口癖の連続は不可)。
- (ロール固有のスタイル 1〜2 個)

【禁止事項】
- (2〜3 個)
```

【制約】
- system_prompt に {{orchestrator_instruction}} や {{feedback_context}} を含めない
  (共通テンプレートで付与されるため)
- system_prompt に「発言ルール」「多様性ルール」等の共通ルールを重複させない
  (共通テンプレートで付与されるため)
- speech_patterns の各 name は 4〜10 文字の短いラベル
- unique_value の主語は「あなたは」で始める
- JSON 以外の説明文は絶対に出力しない
"""


def _parse_generation_json(content: str) -> dict[str, Any] | None:
    """LLM 応答から JSON オブジェクトを抽出する。

    ```json ... ``` フェンスが混入していた場合も除去する。
    """
    text = content.strip()
    if text.startswith("```"):
        # 先頭フェンス: ```json や ``` を除去
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _normalize_generation_result(parsed: dict[str, Any]) -> dict[str, Any]:
    """AI 生成結果を UI が扱いやすい形に整形する。

    P0-P4 の知見に基づく新フィールド:
        - unique_value: このロール独自の価値 (1〜2 文)
        - speech_patterns: 発言の型リスト (3〜5 個の {name, description})

    system_prompt に文頭固定禁止・感嘆連発禁止が含まれない場合、
    safety net として補完する (LLM が抜かした場合の防衛)。
    """
    system_prompt = str(parsed.get("system_prompt") or "").strip()
    system_prompt = _ensure_diversity_rules_in_prompt(system_prompt)

    unique_value = str(parsed.get("unique_value") or "").strip()

    raw_patterns = parsed.get("speech_patterns") or []
    speech_patterns: list[dict[str, str]] = []
    for p in raw_patterns:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        desc = str(p.get("description") or "").strip()
        if name and desc:
            speech_patterns.append({"name": name, "description": desc})
    speech_patterns = speech_patterns[:5]

    raw_tags = parsed.get("domain_tags") or []
    domain_tags = [
        str(t).strip() for t in raw_tags if isinstance(t, str) and t.strip()
    ][:5]

    raw_criteria = parsed.get("evaluation_criteria") or []
    criteria: list[dict[str, str]] = []
    for c in raw_criteria:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        desc = str(c.get("description") or "").strip()
        if name and desc:
            criteria.append({"name": name, "description": desc})
    criteria = criteria[:5]

    raw_expertise = parsed.get("expertise") or []
    expertise = [
        str(e).strip() for e in raw_expertise if isinstance(e, str) and e.strip()
    ][:6]

    raw_personality = parsed.get("personality") or {}
    if not isinstance(raw_personality, dict):
        raw_personality = {}
    raw_traits = raw_personality.get("traits") or []
    traits = [
        str(t).strip() for t in raw_traits if isinstance(t, str) and t.strip()
    ][:5]
    personality = {
        "traits": traits,
        "communication_style": str(
            raw_personality.get("communication_style") or ""
        ).strip(),
        "weakness": str(raw_personality.get("weakness") or "").strip(),
    }

    return {
        "system_prompt": system_prompt,
        "unique_value": unique_value,
        "speech_patterns": speech_patterns,
        "domain_tags": domain_tags,
        "evaluation_criteria": criteria,
        "expertise": expertise,
        "personality": personality,
    }


def _ensure_diversity_rules_in_prompt(system_prompt: str) -> str:
    """system_prompt に文頭固定禁止 / 感嘆連発禁止が無ければ末尾に追加する。

    P0-P4 で確立した多様性ルールの安全ネット。LLM が生成時に抜かしても
    UI に返す時点で必ず含まれるようにする。
    """
    if not system_prompt:
        return system_prompt

    has_bunto = "文頭" in system_prompt and (
        "固定禁止" in system_prompt or "固定しない" in system_prompt
    )
    has_kantan = "感嘆" in system_prompt and (
        "禁止" in system_prompt or "連発" in system_prompt
    )
    if has_bunto and has_kantan:
        return system_prompt

    safety_block = "\n\n【多様性ルール (自動補完)】"
    if not has_bunto:
        safety_block += (
            "\n- 文頭固定禁止: 3 回連続で同じ文頭を使わない。"
            "直前 2 回の自分の発言と同じ切り出し方を避ける。"
        )
    if not has_kantan:
        safety_block += (
            "\n- 感嘆の連発は禁止 (キャラっぽい口癖を毎回使うのは不可)。"
        )
    return system_prompt.rstrip() + safety_block
