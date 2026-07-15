"""Phase 1: 議論の計画立案を担う指揮者 (Orchestrator)。

ユーザー入力から ODSC・参加エージェント・ラウンド構成・個別指示を生成し、
``OrchestraPlan`` として返す。実装上は指揮者 LLM への 1 回の API 呼び出しで
JSON 形式の計画を取得し、構造化する。

設計書: ``doc/04_orchestrator.md`` 全体
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .api_client import ResilientAPIClient
from .data_models import (
    AgentConfig,
    DiscussionPlan,
    ODSC,
    OrchestraPlan,
    PrivateInstruction,
    RoundConfig,
)
from .exceptions import (
    InputTooLongError,
    InputTooShortError,
    PlanValidationError,
)
from .turn_calculator import TurnCalculator

if TYPE_CHECKING:
    from .config_loader import Settings
    from .role_manager import RoleManager

logger = logging.getLogger(__name__)

# Constants (設計書 §4 と settings.yaml の defaults より)
MIN_INPUT_CHARS = 5
MAX_INPUT_CHARS = 8000
DEFAULT_PLANNER_MODEL = "gpt-5.4"
DEFAULT_PLANNER_LEVEL = "medium"
DEFAULT_TIME_LIMIT_SEC = 300.0
DEFAULT_MAX_AGENTS = 5
DEFAULT_EXPERTISE = "intermediate"
DEFAULT_CONVERGENCE_THRESHOLD = 0.8
PHASE3_OVERHEAD_SEC = 25.0
BUDGET_SAFETY_RATIO = 0.9

# OrchestraPlan の必須トップレベルキー (LLM 出力検証用)
REQUIRED_PLAN_KEYS: tuple[str, ...] = (
    "odsc",
    "selected_agents",
    "discussion_plan",
    "private_instructions",
)

REQUIRED_ODSC_KEYS: tuple[str, ...] = (
    "objective",
    "deliverable",
    "success_criteria",
)

REQUIRED_AGENT_KEYS: tuple[str, ...] = (
    "role_id",
    "model",
    "level",
)

REQUIRED_ROUND_KEYS: tuple[str, ...] = (
    "round",
    "phase_name",
    "speakers",
    "pattern",
    "level",
    "time_budget_sec",
    "goal",
)


# ----------------------------------------------------------------------
# プロンプトテンプレートローダー
#   外部ファイル ``config/prompts/planning_prompt.txt`` を優先し、
#   存在しない場合はモジュール内定数 ``PLANNING_PROMPT`` にフォールバックする。
# ----------------------------------------------------------------------
_PLANNING_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "prompts"
    / "planning_prompt.txt"
)
_PLANNING_PROMPT_CACHE: str | None = None


def _load_planning_prompt_template() -> str:
    """``planning_prompt.txt`` の内容を返す。初回のみファイルにアクセスしキャッシュする。

    ファイルが存在しない場合はフォールバック定数 ``PLANNING_PROMPT`` を返す。
    テストやデバッグでキャッシュをリセットしたい場合は
    ``_PLANNING_PROMPT_CACHE = None`` を直接代入する。
    """
    global _PLANNING_PROMPT_CACHE
    if _PLANNING_PROMPT_CACHE is not None:
        return _PLANNING_PROMPT_CACHE
    try:
        text = _PLANNING_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(
            "planning_prompt.txt not found (%s); falling back to inline PLANNING_PROMPT",
            e,
        )
        text = PLANNING_PROMPT
    _PLANNING_PROMPT_CACHE = text
    return _PLANNING_PROMPT_CACHE

# LLM が生成しがちな pattern 名 → 正規名 3 種にマップする。
# ここで正規化することで conductor / turn_calculator の
# "Unknown round pattern" 警告を防ぐ。
_PATTERN_ALIASES: dict[str, str] = {
    # 発散/概観系 → one_shot
    "one_shot": "one_shot",
    "roundrobin": "one_shot",
    "round_robin": "one_shot",
    "idea_expansion": "one_shot",
    "expansion": "one_shot",
    "overview": "one_shot",
    "brainstorm": "one_shot",
    # 反論/深掘り系 → ping_pong
    "ping_pong": "ping_pong",
    "pingpong": "ping_pong",
    "adversarial": "ping_pong",
    "adversarial_build": "ping_pong",
    "debate": "ping_pong",
    "socratic": "ping_pong",
    # 自由発言/創発系 → free_talk
    "free_talk": "free_talk",
    "freetalk": "free_talk",
    "experiment_sprint": "free_talk",
    "sprint": "free_talk",
    "creative": "free_talk",
    "open_discussion": "free_talk",
}
_VALID_PATTERNS: frozenset[str] = frozenset({"one_shot", "ping_pong", "free_talk"})


def _normalize_pattern(raw: str) -> str:
    """LLM が返した pattern 名を正規 3 値に丸める。"""
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _VALID_PATTERNS:
        return key
    mapped = _PATTERN_ALIASES.get(key)
    if mapped is not None:
        logger.info("Pattern alias mapped: %r → %r", raw, mapped)
        return mapped
    logger.warning("Unrecognized pattern %r; defaulting to free_talk", raw)
    return "free_talk"


# ----------------------------------------------------------------------
# FeedbackManager のインターフェース
# ----------------------------------------------------------------------


class FeedbackProtocol(Protocol):
    """``FeedbackManager`` (E-1) の最低限のインターフェース。

    Phase D-1 は循環依存を避けるためインターフェースのみを参照する。
    """

    def generate_context_from_history(self, role_id: str) -> str:
        ...


# ----------------------------------------------------------------------
# プロンプトテンプレート
# ----------------------------------------------------------------------


PLANNING_PROMPT = """\
あなたはAI Orchestraの指揮者です。制限時間 {time_limit_sec:.0f} 秒で
アイデアを発展・深化させる議論の計画を立ててください。
目的は合意形成ではなくアイデアの深化。時間まで継続し早期終了はしません。

【ブレインストーミングの性格】
- 40% 創造的発想 / 30% 実現可能性 / 20% ユーザー・ビジネス視点 / 10% 技術裏付け
- 論文調・研究調の goal は禁止。口語的で具体的に。

【★ 最優先: Objective の中心性 ★】
Objective が議論全体の唯一の判断軸です。Deliverable / Success Criteria は
成果物のフォーマット指定にすぎず、内容は Objective に沿っているかで評価
されます。各ラウンドの goal は Objective の分解であること。

【★ 議論フェーズ構造 (絶対遵守) ★】
議論は以下 4 段構造で組み立てる。各段階を跳ばさず、途中で急に絞り込まない。

段階 1 (Round 1) 発散 / 持ち寄り: pattern="one_shot" 必須、全員 speakers に入れる。
  goal 例「各 AI が Objective に対する切り口を 1 つ提示 (合計 N 案)」。
  制約: 数値・実装詳細・製品名に踏み込まない。切り口タイトルレベル。
  goal に「特定業務・特定製品に踏み込まない」を必ず含める。

段階 2 (中間 Round) 比較評価: pattern="free_talk" or "ping_pong"。
  goal 例「Phase 1 の各案に長所 1 + 懸念 1 を指摘し比較する」。
  【絶対禁止】この段階で 1 案に絞り込む goal を書いてはいけない。
  複数の案を並行して比較する。goal に「特定 1 案の深掘りに入り込まない」を必ず含める。

段階 3 (最終前 Round、総 3 以上のとき) 選択と具体化: pattern="ping_pong"。
  goal 例「最有望案 1 つに合意し、実現方法の骨子を描く」。
  ここで初めて絞り込みに入る。

段階 4 (最終 Round) 統合とまとめ: pattern="free_talk"。
  goal 例「選ばれた案の MVP・KPI・リスク要素を具体化し、全体像と未解決課題を振り返る」。

総ラウンド 2 → 段階 1+4 統合可。総 3 → 段階 1+2+3/4 統合。

【★ goal の書き方 (絶対遵守) ★】
「動詞 + 具体成果物 + 数字」の形。数字必須。
良い例: 「切り口 5 案を出す」「主要リスク 3 つと回避策」「MVP 機能 3 つを決める」。
悪い例: 「議論する」「検討する」「分析する」「体験ストーリーを描く」(数字なし)。

【★ 会議の自然さ (数値過剰の抑制) ★】
実際の会議では、口頭で自然に言える範囲の数字しか扱いません。goal や発言では
以下のレベルに留めてください:
- 疑似変数 (τ=0.8、ε=0.1、δ、σ 等) を並べない
- 単位や接頭子を過剰に付けない (bps、+3pt、≤10ms などの羅列は禁止)
- パーセンテージは代表となる 1 – 2 個に絞り、それ以外は言葉で描写する
- 数字は「意思決定に直接影響する値」だけ (例: 想定 ARR、ターゲットユーザー数)

悪い例 (実際の会議でこんな発言はしない):
  「MVP は ①担当 ID 付き返却表 ②τ=0.8 未満は保留 ③全件に版番号＋理由ログ。
   KPI は誤返却率 ≤0.5%、翼営業日解決率 ≥95%。
   主リスクは保留 24h 超過 5% と、月次ドリフトで誤停止 +3pt」
良い例 (同じ内容を会議で口頭で言う):
  「MVP は 3 つ。担当者 ID を返却情報に付ける仕組み、
   自信度が低いときの自動保留、履歴を全部残す仕組みです。
   KPI は誤返却率と翼営業日解決率。目標値は事業サイドと調整。
   リスクは保留が長期化することと、モデル精度がじわじわ落ちること」

→ 「同僚に口頭で 3 分で説明できるレベル」を基準にする。
→ goal や結論でも同様に、口頭で交わされない疑似数式は禁止。

【計画原則】
- 時間 {time_limit_sec:.0f} 秒の 90-100% を使い切る計画にする
- 各ラウンドの time_budget_sec は 60-180 秒
- 最低ラウンド数: 制限時間 ≤300s → 3, 300-600s → 4, >600s → 5
- level は minimal / low / medium のみ (high 禁止 = タイムアウト原因)
- 進行 3 秒 + 結論 10 秒 /ラウンド、Phase 3 (統合) 25 秒
- 合計が制限時間の 95% 以内に収まる計画にすること

【制約】
- 参加可能 AI 数: 最大 {max_agents} 体
- expertise レベル: {expertise}
- level 別推定時間: minimal=3秒, low=5秒, medium=10秒

【ユーザー入力】
{user_input}

【利用可能ロール】
{roles_section}

【★ role_id ルール (絶対遵守) ★】
role_id は上記【利用可能ロール】各行先頭の「role_id: xxx」の値
(英小文字・アンダースコアのみ) をそのまま使う。絵文字・日本語名は禁止。
  OK: "theorist"    NG: "🧮"    NG: "理論屋"    NG: "🧮 理論屋"

【speakers 設計】
- speakers[0] はそのラウンドの主導者。ラウンド末で結論を出す
- **各ラウンドの speakers は必ず 3 名以上** 含めること (絶対遵守)。
  ping_pong の場合も、主な話者 2 名に加えて働聴・補足役を 1 名以上入れる。
  free_talk の深掘りでも、單独発言者のラウンドは作らない。
  → 実際の会議でも 1 対 1 のモノローグは会議にならないため。
- ビジネス系ロール (matushita_kounosuke / son_masayoshi など domain に
  business_* / management_* を含む) 参加時:
  1 ラウンド以上を ping_pong: [技術系, ビジネス系] にする。
  one_shot の speakers 順序は「技術系 → ビジネス系」の交互配置
- 個性派カスタムロール (bird_eye / devil 以外) を 1 ラウンド以上の
  主導者 (speakers[0]) にも配置する

【pattern】
- "one_shot"  : 各 speaker が順に 1 回発言 (発散/概観)
- "ping_pong" : 2 人が交互に応答 (深掘り/反論)
- "free_talk" : 主導者中心の自由発言 (拡張/創発)
- Round 1 は "one_shot" のみ。Round 2 以降は "one_shot" 禁止。
- 対立が予想される議題: ping_pong 優先。拡散重視: free_talk 優先。

【private_instructions のロール別 focus_points】
- ビジネス系: 事業規模 (想定 ARR/TAM)、初期顧客セグメント、競合との差別化
- 現場系: 現場の困り事、導入抵抗、教育・体制整備
- 技術系 (theorist / implementer / experimentalist): 実装ボトルネック、
  代替アーキテクチャ、性能の数値目標
- 全ロール共通の constraints: 「他者と同じ具体例・言い回しを繰り返さない」
{preferred_roles_section}{follow_up_section}{scenario_section}
【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
  "odsc": {{
    "objective": "...",
    "deliverable": "...",
    "success_criteria": "...",
    "convergence_threshold": 0.85
  }},
  "selected_agents": [
    {{"role_id": "theorist", "model": "...", "level": "...",
      "reason": "...", "expected_contribution": "..."}}
  ],
  "discussion_plan": {{
    "estimated_rounds": 3,
    "round_config": [
      {{"round": 1, "phase_name": "...", "speakers": ["id1", "id2"],
        "pattern": "one_shot", "level": "medium",
        "time_budget_sec": 90, "goal": "..."}}
    ],
    "total_estimated_time_sec": 280,
    "total_estimated_requests": 30
  }},
  "private_instructions": {{
    "role_id_1": {{
      "expected_contribution": "...",
      "focus_points": ["...", "..."],
      "constraints": ["..."],
      "context_from_plan": "...",
      "feedback_reminder": "..."
    }}
  }}
}}
"""


# ----------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------


class Orchestrator:
    """Phase 1 (計画立案) を担当する指揮者。

    Attributes:
        api_client: 指揮者 LLM の API クライアント。
        role_manager: 利用可能ロールの取得元。
        feedback_manager: 過去フィードバックの取得元 (任意)。
        settings: 全体設定。
        turn_calculator: 時間制約の検証に使う。
    """

    def __init__(
        self,
        api_client: ResilientAPIClient,
        role_manager: "RoleManager",
        feedback_manager: FeedbackProtocol | None,
        settings: "Settings",
    ) -> None:
        self.api_client = api_client
        self.role_manager = role_manager
        self.feedback_manager = feedback_manager
        self.settings = settings
        self.turn_calculator = TurnCalculator(settings=settings)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def plan(
        self,
        user_input: str,
        model: str | None = None,
        level: str | None = None,
        time_limit_sec: float | None = None,
        max_agents: int | None = None,
        expertise: str | None = None,
        follow_up_context: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
        preferred_role_ids: list[str] | None = None,
    ) -> OrchestraPlan:
        """ユーザー入力から ``OrchestraPlan`` を生成する。

        Args:
            user_input: 議論テーマ。
            model: 指揮者モデル。``None`` なら ``settings.models["planner"]``。
            level: 指揮者の reasoning level。``None`` なら ``settings`` から。
            time_limit_sec: 議論全体の制限時間。``None`` なら settings から。
            max_agents: 最大参加 AI 数。``None`` なら settings から。
            expertise: ``beginner`` / ``intermediate`` / ``expert``。
            follow_up_context: フォローアップ情報 (任意)。
                ``previous_session_id`` / ``previous_conclusion`` /
                ``previous_hypotheses`` / ``unresolved_issues`` / ``new_input``。
            scenario: シナリオ YAML 由来の追加コンテキスト (任意)。

        Returns:
            検証済みの ``OrchestraPlan``。

        Raises:
            InputTooShortError: 入力が短すぎる。
            InputTooLongError: 入力が長すぎる。
            PlanValidationError: LLM の応答が不正。
        """
        self._validate_input(user_input)

        planner_model = model or self.settings.models.get("planner", DEFAULT_PLANNER_MODEL)
        planner_level = level or self.settings.models.get("planner_level", DEFAULT_PLANNER_LEVEL)
        time_limit = (
            time_limit_sec
            if time_limit_sec is not None
            else float(self.settings.time_limits.get("idea_default_sec", DEFAULT_TIME_LIMIT_SEC))
        )
        agents_cap = max_agents or int(
            self.settings.agents.get("idea_default_max", DEFAULT_MAX_AGENTS)
        )
        expertise_level = expertise or self.settings.default_expertise or DEFAULT_EXPERTISE

        roles = self.role_manager.list_available_roles()
        prompt = self._build_planning_prompt(
            user_input=user_input,
            roles=roles,
            time_limit_sec=time_limit,
            max_agents=agents_cap,
            expertise=expertise_level,
            follow_up=follow_up_context,
            scenario=scenario,
            preferred_role_ids=preferred_role_ids or [],
        )

        response = await self.api_client.call(
            model=planner_model,
            messages=[
                {"role": "system", "content": "あなたはAI Orchestraの指揮者です。"},
                {"role": "user", "content": prompt},
            ],
            level=planner_level,
        )

        content = str(response.get("content") or "")
        plan = self._parse_plan_response(content)
        return self._validate_plan(plan, time_limit)

    # ------------------------------------------------------------------
    # 入力検証
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_input(user_input: str) -> None:
        """入力長を検証する。"""
        if user_input is None:
            raise InputTooShortError("user_input must not be None")
        stripped = user_input.strip()
        if len(stripped) < MIN_INPUT_CHARS:
            raise InputTooShortError(
                f"user_input must be at least {MIN_INPUT_CHARS} characters "
                f"(got {len(stripped)})"
            )
        if len(stripped) > MAX_INPUT_CHARS:
            raise InputTooLongError(
                f"user_input must be at most {MAX_INPUT_CHARS} characters "
                f"(got {len(stripped)})"
            )

    # ------------------------------------------------------------------
    # プロンプト構築
    # ------------------------------------------------------------------

    def _build_planning_prompt(
        self,
        user_input: str,
        roles: list[dict[str, Any]],
        time_limit_sec: float,
        max_agents: int,
        expertise: str,
        follow_up: dict[str, Any] | None,
        scenario: dict[str, Any] | None,
        preferred_role_ids: list[str] | None = None,
    ) -> str:
        """指揮者に渡すユーザーメッセージを構築する。"""
        roles_section = self._format_roles_section(roles)
        follow_up_section = self._format_follow_up_section(follow_up)
        scenario_section = self._format_scenario_section(scenario)
        preferred_roles_section = self._format_preferred_roles_section(
            preferred_role_ids or [], roles
        )

        return _load_planning_prompt_template().format(
            user_input=user_input.strip(),
            time_limit_sec=time_limit_sec,
            max_agents=max_agents,
            expertise=expertise,
            roles_section=roles_section,
            follow_up_section=follow_up_section,
            scenario_section=scenario_section,
            preferred_roles_section=preferred_roles_section,
        )

    def _format_roles_section(self, roles: list[dict[str, Any]]) -> str:
        """利用可能ロール一覧をプロンプト用にフォーマットする。

        新スキーマ (``description`` / ``perspective``) を優先表示し、無い
        場合は旧フィールド (``expertise`` / ``personality``) にフォールバック。
        role_id を行頭に置き、LLM が ``role_id`` フィールドへ表示名や絵文字を
        誤って格納しないよう視覚的に強調する。
        """
        lines: list[str] = []
        for i, role in enumerate(roles, start=1):
            role_id = role.get("role_id", "?")
            display_name = role.get("display_name", role_id)
            description = (role.get("description") or "").strip()
            perspective = (role.get("perspective") or "").strip()
            expertise_list = role.get("expertise") or []
            domain_tags = role.get("domain_tags") or []
            model = role.get("model", "?")
            stats = role.get("feedback_stats") or {}

            lines.append(
                f"{i}. role_id: {role_id} | 表示名: {display_name}"
            )
            # 概要: description があれば優先、なければ expertise の要約
            if description:
                lines.append(f"   - 概要: {description}")
            elif expertise_list:
                lines.append(f"   - 概要: {', '.join(expertise_list[:3])} 中心")
            # 視点: perspective 優先、なければ expertise 一覧
            if perspective:
                # 長すぎる perspective は先頭 120 字に丸める
                short = perspective if len(perspective) <= 120 else perspective[:117] + "..."
                lines.append(f"   - 視点: {short}")
            elif expertise_list:
                lines.append(f"   - 得意: {', '.join(expertise_list[:6])}")
            if domain_tags:
                lines.append(f"   - 分野: {', '.join(domain_tags)}")
            lines.append(f"   - デフォルトモデル: {model}")

            feedback_line = self._format_feedback_line(role_id, stats)
            if feedback_line:
                lines.append(feedback_line)
        return "\n".join(lines)

    def _format_feedback_line(
        self, role_id: str, stats: dict[str, Any]
    ) -> str:
        """ロールごとの過去実績行を構築する。"""
        parts: list[str] = []
        if stats.get("total_sessions"):
            parts.append(f"sessions={stats['total_sessions']}")
        if "avg_peer_score" in stats:
            parts.append(f"avg_peer={stats['avg_peer_score']}")
        if stats.get("trend"):
            parts.append(f"trend={stats['trend']}")
        if stats.get("top_strength"):
            parts.append(f"強み「{stats['top_strength']}」")

        history_context = ""
        if self.feedback_manager is not None:
            try:
                history_context = self.feedback_manager.generate_context_from_history(role_id)
            except Exception as e:  # noqa: BLE001 - フィードバック取得失敗は致命的でない
                logger.warning("Failed to fetch feedback for %s: %s", role_id, e)

        if not parts and not history_context:
            return ""

        line_parts: list[str] = []
        if parts:
            line_parts.append(f"   - 過去実績: {', '.join(parts)}")
        if history_context:
            indent_context = history_context.replace("\n", "\n     ")
            line_parts.append(f"   - 改善依頼: {indent_context}")
        return "\n".join(line_parts)

    @staticmethod
    def _format_follow_up_section(follow_up: dict[str, Any] | None) -> str:
        """follow-up セクションを構築する (未指定なら空文字列)。"""
        if not follow_up:
            return ""
        lines = ["", "【follow-up情報】"]
        for key, label in (
            ("previous_session_id", "前回セッション"),
            ("previous_conclusion", "前回の結論"),
            ("previous_hypotheses", "前回の仮説テーブル"),
            ("unresolved_issues", "前回の未解決問題"),
            ("new_input", "今回の新情報"),
        ):
            value = follow_up.get(key)
            if value:
                lines.append(f"- {label}: {value}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_scenario_section(scenario: dict[str, Any] | None) -> str:
        """シナリオセクションを構築する (未指定なら空文字列)。"""
        if not scenario:
            return ""
        lines = ["", "【シナリオ設定】"]
        for key, value in scenario.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _format_preferred_roles_section(
        preferred_role_ids: list[str],
        roles: list[dict[str, Any]],
    ) -> str:
        """ユーザーが明示的に指定した優先ロールセクションを構築する。

        指定 role_id は available roles と突き合わせて display_name を添える。
        未指定なら空文字列を返す。
        """
        if not preferred_role_ids:
            return ""
        role_map = {r.get("role_id"): r for r in roles}
        lines = ["", "【ユーザー指定の優先候補 (最優先で selected_agents に採用してください)】"]
        for rid in preferred_role_ids:
            role = role_map.get(rid)
            if role is None:
                lines.append(f"- {rid} (定義未検出のためスキップ可)")
            else:
                display = role.get("display_name") or rid
                lines.append(f"- {rid} : {display}")
        lines.append(
            "※ 上記のロールは max_agents の範囲で必ず selected_agents に含めてください。"
            " 議題との相性を判断してもよいが、明示的な理由なく除外しないこと。"
        )
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # パース
    # ------------------------------------------------------------------

    @classmethod
    def _parse_plan_response(cls, response_content: str) -> OrchestraPlan:
        """LLM の応答テキストから ``OrchestraPlan`` を構築する。

        Markdown コードフェンス (``` または ```json) を許容する。

        Args:
            response_content: LLM の応答テキスト。

        Returns:
            ``OrchestraPlan``。

        Raises:
            PlanValidationError: JSON でない / 必須キー欠落。
        """
        if not response_content or not response_content.strip():
            raise PlanValidationError("Planner returned empty content")

        json_text = cls._extract_json(response_content)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise PlanValidationError(
                f"Planner response is not valid JSON: {e}"
            ) from e

        if not isinstance(data, dict):
            raise PlanValidationError(
                f"Planner response must be a JSON object, got {type(data).__name__}"
            )

        cls._require_keys(data, REQUIRED_PLAN_KEYS, "plan")

        odsc = cls._parse_odsc(data["odsc"])
        agents = cls._parse_agents(data["selected_agents"])
        discussion_plan = cls._parse_discussion_plan(data["discussion_plan"])
        instructions = cls._parse_private_instructions(data["private_instructions"])

        return OrchestraPlan(
            odsc=odsc,
            selected_agents=agents,
            discussion_plan=discussion_plan,
            private_instructions=instructions,
        )

    @classmethod
    def plan_from_dict(cls, data: dict[str, Any]) -> OrchestraPlan:
        """既存の dict (Web UI 経由の再送信など) から ``OrchestraPlan`` を再構築。

        Phase 1 の再実行を避けるため、``/api/idea/plan`` で得た計画を
        ``/api/idea/stream`` にそのまま渡して使いたい場合に利用する。
        """
        cls._require_keys(data, REQUIRED_PLAN_KEYS, "plan")
        return OrchestraPlan(
            odsc=cls._parse_odsc(data["odsc"]),
            selected_agents=cls._parse_agents(data["selected_agents"]),
            discussion_plan=cls._parse_discussion_plan(data["discussion_plan"]),
            private_instructions=cls._parse_private_instructions(
                data["private_instructions"]
            ),
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Markdown コードフェンスや前後テキストから JSON 本体を抽出する。"""
        text = text.strip()
        # ```json ... ``` または ``` ... ``` 形式
        fence_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            return fence_match.group(1)
        # フェンスなし: 最初の `{` から最後の `}` まで
        start = text.find("{")
        if start == -1:
            raise PlanValidationError("No JSON object found in planner response")
        end = text.rfind("}")
        if end <= start:
            # `}` が見つからない / 不正な順序: 末尾までを返して ``json.loads``
            # に解析を委ねる (「壊れた JSON」エラーとして検出される)
            return text[start:]
        return text[start : end + 1]

    @staticmethod
    def _require_keys(data: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
        missing = [k for k in keys if k not in data]
        if missing:
            raise PlanValidationError(
                f"{context} is missing required keys: {missing}"
            )

    @classmethod
    def _parse_odsc(cls, raw: Any) -> ODSC:
        if not isinstance(raw, dict):
            raise PlanValidationError(
                f"odsc must be an object, got {type(raw).__name__}"
            )
        cls._require_keys(raw, REQUIRED_ODSC_KEYS, "odsc")
        threshold = raw.get("convergence_threshold", DEFAULT_CONVERGENCE_THRESHOLD)
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as e:
            raise PlanValidationError(
                f"odsc.convergence_threshold must be a number: {e}"
            ) from e
        return ODSC(
            objective=str(raw["objective"]),
            deliverable=str(raw["deliverable"]),
            success_criteria=str(raw["success_criteria"]),
            convergence_threshold=threshold,
        )

    @classmethod
    def _parse_agents(cls, raw: Any) -> list[AgentConfig]:
        if not isinstance(raw, list) or not raw:
            raise PlanValidationError(
                "selected_agents must be a non-empty list"
            )
        agents: list[AgentConfig] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise PlanValidationError(
                    f"selected_agents[{i}] must be an object"
                )
            cls._require_keys(item, REQUIRED_AGENT_KEYS, f"selected_agents[{i}]")
            agents.append(
                AgentConfig(
                    role_id=str(item["role_id"]),
                    model=str(item["model"]),
                    level=str(item["level"]),
                    reason=str(item.get("reason", "")),
                    expected_contribution=str(item.get("expected_contribution", "")),
                )
            )
        return agents

    @classmethod
    def _parse_discussion_plan(cls, raw: Any) -> DiscussionPlan:
        if not isinstance(raw, dict):
            raise PlanValidationError(
                f"discussion_plan must be an object, got {type(raw).__name__}"
            )
        round_configs_raw = raw.get("round_config", [])
        if not isinstance(round_configs_raw, list):
            raise PlanValidationError("discussion_plan.round_config must be a list")

        round_configs: list[RoundConfig] = []
        for i, rc in enumerate(round_configs_raw):
            if not isinstance(rc, dict):
                raise PlanValidationError(
                    f"discussion_plan.round_config[{i}] must be an object"
                )
            cls._require_keys(rc, REQUIRED_ROUND_KEYS, f"discussion_plan.round_config[{i}]")
            speakers = rc["speakers"]
            if not isinstance(speakers, list):
                raise PlanValidationError(
                    f"discussion_plan.round_config[{i}].speakers must be a list"
                )
            try:
                round_configs.append(
                    RoundConfig(
                        round=int(rc["round"]),
                        phase_name=str(rc["phase_name"]),
                        speakers=[str(s) for s in speakers],
                        pattern=_normalize_pattern(rc["pattern"]),
                        level=str(rc["level"]),
                        time_budget_sec=float(rc["time_budget_sec"]),
                        goal=str(rc["goal"]),
                    )
                )
            except (TypeError, ValueError) as e:
                raise PlanValidationError(
                    f"discussion_plan.round_config[{i}] has invalid types: {e}"
                ) from e

        # Round 2 以降の one_shot はラリー感を損なうため free_talk に自動昇格
        # (LLM がプロンプトを無視して one_shot を連発するケースへのセーフティネット)
        for rc in round_configs[1:]:
            if rc.pattern == "one_shot":
                logger.warning(
                    "Round %d: one_shot is not allowed after Round 1; "
                    "auto-promoting to free_talk",
                    rc.round,
                )
                rc.pattern = "free_talk"

        try:
            estimated_rounds = int(raw.get("estimated_rounds", len(round_configs)))
            total_time = float(raw.get("total_estimated_time_sec", 0.0))
            total_requests = int(raw.get("total_estimated_requests", 0))
        except (TypeError, ValueError) as e:
            raise PlanValidationError(
                f"discussion_plan numeric fields are invalid: {e}"
            ) from e

        return DiscussionPlan(
            estimated_rounds=estimated_rounds,
            round_config=round_configs,
            total_estimated_time_sec=total_time,
            total_estimated_requests=total_requests,
        )

    @classmethod
    def _parse_private_instructions(
        cls, raw: Any
    ) -> dict[str, PrivateInstruction]:
        if not isinstance(raw, dict):
            raise PlanValidationError(
                "private_instructions must be an object"
            )
        result: dict[str, PrivateInstruction] = {}
        for role_id, item in raw.items():
            if not isinstance(item, dict):
                raise PlanValidationError(
                    f"private_instructions[{role_id}] must be an object"
                )
            result[str(role_id)] = PrivateInstruction(
                role_id=str(role_id),
                expected_contribution=str(item.get("expected_contribution", "")),
                focus_points=cls._coerce_string_list(item.get("focus_points")),
                constraints=cls._coerce_string_list(item.get("constraints")),
                context_from_plan=str(item.get("context_from_plan", "")),
                feedback_reminder=str(item.get("feedback_reminder", "")),
                speaking_rules=str(item.get("speaking_rules", "")),
            )
        return result

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(v) for v in value]

    # ------------------------------------------------------------------
    # 構造検証
    # ------------------------------------------------------------------

    @staticmethod
    def _build_display_to_role_id_map(
        roles: list[dict[str, Any]],
    ) -> dict[str, str]:
        """display_name や絵文字単体から ``role_id`` へ逆引きする辞書を作る。

        LLM が ``role_id`` フィールドに ``"🧮 理論屋"`` や ``"🧮"`` といった
        表示用文字列を返した場合の救済用。``display_name`` は
        ``"<絵文字> <日本語名>"`` 形式を想定し、全体・絵文字部分・名前部分の
        3 通りをキーとして登録する。
        """
        mapping: dict[str, str] = {}
        for role in roles:
            rid = role.get("role_id")
            dname = role.get("display_name")
            if not rid or not isinstance(dname, str):
                continue
            dname_stripped = dname.strip()
            if not dname_stripped:
                continue
            mapping.setdefault(dname_stripped, rid)
            parts = dname_stripped.split(maxsplit=1)
            if len(parts) == 2:
                emoji, japanese = parts[0].strip(), parts[1].strip()
                if emoji:
                    mapping.setdefault(emoji, rid)
                if japanese:
                    mapping.setdefault(japanese, rid)
        return mapping

    @staticmethod
    def _remap_unknown_role_ids(
        plan: OrchestraPlan,
        available_role_ids: set[str],
        display_to_role_id: dict[str, str],
    ) -> None:
        """``plan`` 内の未知 role_id を逆引きで補正する (副作用あり)。

        補正対象は ``selected_agents`` / ``discussion_plan.round_config[].speakers``
        / ``private_instructions`` の 3 箇所。逆引きで見つからない場合は
        そのまま残し、後続の検証で ``PlanValidationError`` を発生させる。
        """

        def remap(value: str) -> str:
            if value in available_role_ids:
                return value
            mapped = display_to_role_id.get(value)
            if mapped is None:
                return value
            logger.warning(
                "Remapped role_id %r -> %r via display_name fallback",
                value, mapped,
            )
            return mapped

        # selected_agents
        for agent in plan.selected_agents:
            agent.role_id = remap(agent.role_id)

        # discussion_plan.round_config[].speakers
        if plan.discussion_plan is not None:
            for rc in plan.discussion_plan.round_config:
                rc.speakers = [remap(s) for s in rc.speakers]

        # private_instructions: dict のキーを差し替え
        remapped_instructions: dict[str, PrivateInstruction] = {}
        for key, instr in plan.private_instructions.items():
            new_key = remap(key)
            instr.role_id = new_key
            remapped_instructions[new_key] = instr
        plan.private_instructions = remapped_instructions

    def _validate_plan(
        self,
        plan: OrchestraPlan,
        time_limit: float,
    ) -> OrchestraPlan:
        """構造的・整合性的な検証を行う。

        - 各エージェントの ``role_id`` が利用可能ロールに存在するか
          (絵文字や日本語表示名で返ってきた場合は逆引きで自動補正を試みる)
        - 各ラウンドの ``speakers`` が ``selected_agents`` に含まれるか
        - 合計推定時間が制限時間の 90% を超えていないか (超えていたら警告)

        Args:
            plan: 検証対象の計画。
            time_limit: 制限時間 (秒)。

        Returns:
            検証済みの ``plan`` (逆引き補正により破壊的に書き換わる場合あり)。

        Raises:
            PlanValidationError: 構造的に致命的な不整合 (role_id 不在など)。
        """
        roles = self.role_manager.list_available_roles()
        available_role_ids = {r["role_id"] for r in roles}
        display_to_role_id = self._build_display_to_role_id_map(roles)

        # ★ Phase 1 LLM が role_id に display_name や絵文字を入れた場合の補正
        self._remap_unknown_role_ids(plan, available_role_ids, display_to_role_id)

        agent_role_ids = {a.role_id for a in plan.selected_agents}

        # 各エージェントが利用可能ロールに存在するか
        unknown_roles = agent_role_ids - available_role_ids
        if unknown_roles:
            raise PlanValidationError(
                f"selected_agents contains unknown role_ids: {sorted(unknown_roles)}"
            )

        # 各ラウンドの speakers が選定済みエージェントに含まれるか
        if plan.discussion_plan is not None:
            for rc in plan.discussion_plan.round_config:
                unknown_speakers = set(rc.speakers) - agent_role_ids
                if unknown_speakers:
                    raise PlanValidationError(
                        f"Round {rc.round} contains speakers not in selected_agents: "
                        f"{sorted(unknown_speakers)}"
                    )

            # 時間制約: 厳密な estimated > limit*0.9 は警告
            estimated = self.turn_calculator.calculate_total_time(plan.discussion_plan)
            budget = time_limit * BUDGET_SAFETY_RATIO - PHASE3_OVERHEAD_SEC
            if estimated > budget:
                logger.warning(
                    "Plan estimated time %.1fs exceeds discussion budget %.1fs "
                    "(time_limit=%.1fs)",
                    estimated,
                    budget,
                    time_limit,
                )

        return plan


__all__ = [
    "Orchestrator",
    "PLANNING_PROMPT",
    "FeedbackProtocol",
    "REQUIRED_PLAN_KEYS",
    "REQUIRED_ODSC_KEYS",
    "REQUIRED_AGENT_KEYS",
    "REQUIRED_ROUND_KEYS",
    "MIN_INPUT_CHARS",
    "MAX_INPUT_CHARS",
]
