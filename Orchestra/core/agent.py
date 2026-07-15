"""議論に参加する AI エージェント。

責務:
    - ロール定義 + 指揮者指示 + フィードバックを統合した system prompt の構築
    - コンテキスト (Layer 2-6) を含む user message の構築
    - モデル種別に応じた API パラメータの選択 (GPT-5 / Claude thinking / 標準)
    - 発言長の 3 段防衛 (system prompt → max_tokens/verbosity → 事後短縮)
    - 発言を ``Utterance`` として返却

設計書: ``doc/06_agent.md`` 全体
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .api_client import (
    CLAUDE_THINKING_BUDGET,
    ResilientAPIClient,
)
from .data_models import AgentConfig, Utterance

if TYPE_CHECKING:
    from .config_loader import Settings
    from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# Constants
MAX_UTTERANCE_CHARS = 200
SHORTEN_MODEL = "gpt-4.1"
SHORTEN_TEMPERATURE = 0.3
SHORTEN_MAX_TOKENS = 200
SHORTEN_FALLBACK_ELLIPSIS = "…"
SHORTEN_LEVEL = "none"  # GPT-5 系を使う場合に reasoning_effort を送らせない用

DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS_FOR_UTTERANCE = 300
DEFAULT_GPT5_VERBOSITY = "low"

# 共通プロンプトテンプレート (Layer 1) の場所。
# 存在しない場合は後述の AGENT_BASE_ATTITUDE をフォールバックとして使用する。
_ROLE_BASE_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "role_base_template.txt"
)
_ROLE_BASE_TEMPLATE_CACHE: str | None = None

# role_base_template.txt が読み込めない場合の最小フォールバック。
# テンプレの構文強制は撤廃し「態度」だけを指定する (問題1・4対策)。
AGENT_BASE_ATTITUDE = """\
【会話の態度】
- 自然な会話として話す。テンプレートや定型文は使わない。
- 前の人の発言を踏まえて話を展開する。ただし「〇〇さんの『〜』について、」のような形式的な引用や名前の明示は不要。会話の流れに乗ることの方が重要。
- 1回の発言は50〜200文字。内容があれば短くて良い。冗長な前置きや締めのフレーズは書かない。
- 評論家にならない。抽象的な感想より、具体的なアイデア・提案・数字・エピソードを1つ出す。
- 前の発言に反応するか、新しい切り口を出す。文脈と無関係な発言はしない。
- 前の発言と同じ構文・同じ切り口・同じ結び方を繰り返さない。毎回違う言い回しで話す。
"""

# 全ロールの system_prompt 末尾に無条件で注入する多様性ルール (問題1対策)。
# ロール個別 YAML やテンプレの後で強調するため、末尾配置する。
DIVERSITY_RULE = """\
【多様性ルール】
- 直前の発言者と同じ出だし・同じ論理展開・同じ結び方を使ってはいけない
- あなたの発言が定型化していたら、途中でも書き直す。毎回違う切り口で発言する
- 疑似変数 (τ=0.8、ε=0.1、σ、δ 等) や単位の羅列 (bps、+3pt、≤0.5%、24h超過5% 等) を並べない。実際の会議で口頭で自然に言えるレベルの表現に留める
"""


def _load_role_base_template() -> str:
    """共通テンプレート (Layer 1) を読み込む。1 回だけキャッシュ。

    ``config/role_base_template.txt`` が存在すればその内容を返し、無ければ
    ``AGENT_BASE_ATTITUDE`` + プレースホルダをフォールバックとして返す。
    """
    global _ROLE_BASE_TEMPLATE_CACHE
    if _ROLE_BASE_TEMPLATE_CACHE is not None:
        return _ROLE_BASE_TEMPLATE_CACHE

    try:
        text = _ROLE_BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(
            "role_base_template.txt not found (%s); falling back to hardcoded template",
            e,
        )
        text = (
            f"{AGENT_BASE_ATTITUDE}\n\n"
            "{orchestrator_instruction}\n\n"
            "{feedback_context}\n"
        )

    _ROLE_BASE_TEMPLATE_CACHE = text.strip()
    return _ROLE_BASE_TEMPLATE_CACHE


class Agent:
    """AI エージェントの基底クラス。

    Attributes:
        config: ``AgentConfig``。
        role_definition: ロール YAML から読み込んだ辞書。
        api_client: 共有 API クライアント。
        memory: 共有会話メモリ。
        settings: ``Settings``。
        role_id / display_name / model / level: ``config`` と ``role_definition``
            から導出されるショートカット属性。
        private_instruction / feedback_context / speaking_rules: ``set_*`` で
            注入される動的情報。
    """

    def __init__(
        self,
        config: AgentConfig,
        role_definition: dict[str, Any],
        api_client: ResilientAPIClient,
        memory: "ConversationMemory",
        settings: "Settings",
    ) -> None:
        self.config = config
        self.role_definition = role_definition
        self.api_client = api_client
        self.memory = memory
        self.settings = settings

        self.role_id: str = config.role_id
        self.display_name: str = role_definition["display_name"]
        self.model: str = config.model
        self.level: str = config.level
        self.system_prompt_template: str = role_definition["system_prompt"]
        self.evaluation_criteria: list[dict[str, str]] = role_definition.get(
            "evaluation_criteria", []
        )
        self.personality: dict[str, Any] = role_definition.get("personality", {})
        self.expertise: list[str] = role_definition.get("expertise", [])
        self.domain_tags: list[str] = role_definition.get("domain_tags", [])

        self.private_instruction: str = ""
        self.feedback_context: str = ""
        self.speaking_rules: str = ""

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def speak(
        self,
        round_context: dict[str, Any],
        additional_instruction: str = "",
    ) -> Utterance:
        """1 回の発言を生成して ``Utterance`` を返す。

        Args:
            round_context: ``ConversationMemory.get_context_for_agent`` の
                返り値に ``odsc`` / ``round_goal`` / ``next_sequence`` などを
                追加した辞書。
            additional_instruction: 堂々巡り検知時などに追加する Layer 5。

        Returns:
            生成された ``Utterance``。発言長が ``MAX_UTTERANCE_CHARS`` を
            超えた場合は ``_request_shorter`` で短縮された内容が入る。
        """
        system_prompt = self._build_system_prompt()
        user_message = self._build_context_message(round_context, additional_instruction)
        params = self._build_api_params(system_prompt, user_message)

        start = time.time()
        response = await self.api_client.call(**params)
        duration = time.time() - start

        content = str(response.get("content") or "")
        if self._is_too_long(content):
            content = await self._request_shorter(content, round_context)

        return Utterance(
            sequence=int(round_context.get("next_sequence", 0)),
            speaker=self.role_id,
            speaker_display=self.display_name,
            type="discussion",
            content=content,
            model=self.model,
            level=self.level,
            tokens_used=dict(response.get("usage", {})) if response.get("usage") else {},
            duration_sec=duration,
        )

    async def evaluate(
        self,
        discussion_log: Any,
        all_agents: list["Agent"],
    ) -> dict[str, Any]:
        """自己評価と他者評価を生成する。

        Phase E (E-1) で詳細実装する。本クラスでは最小のスタブを置く。

        Args:
            discussion_log: 評価対象の ``DiscussionLog``。
            all_agents: 同セッションの全エージェント。

        Returns:
            空辞書 (スタブ)。

        Raises:
            NotImplementedError: 現状は Phase D 以降で実装するため。
        """
        del discussion_log, all_agents
        raise NotImplementedError("Agent.evaluate is implemented in Phase E.")

    def set_private_instruction(self, instruction: str) -> None:
        """指揮者からの個別指示を設定する。"""
        self.private_instruction = instruction

    def set_feedback_context(self, context: str) -> None:
        """過去フィードバックからの改善依頼を設定する。"""
        self.feedback_context = context

    def set_speaking_rules(self, rules: str) -> None:
        """発言ルール (共通 + expertise 別) を設定する。"""
        self.speaking_rules = rules

    # ------------------------------------------------------------------
    # システムプロンプト
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """共通テンプレート (Layer 1) + ロール固有 (Layer 2) を結合した
        完全な system prompt を返す。

        組み立て順:
            1. base template (発言ルール + 議論姿勢 + プレースホルダー)
            2. ロール固有 system_prompt (既存ロールの場合は末尾のプレースホルダーを除去)
            3. ``{orchestrator_instruction}`` / ``{feedback_context}`` を一度だけ置換
            4. ``speaking_rules`` の末尾追加 (既存弔き継ぎ)
        """
        base_template = _load_role_base_template()

        # ロール固有側のプレースホルダーは base template 側で一元化されるので
        # 二重展開を避けるため先に除去しておく。
        role_specific = self.system_prompt_template or ""
        role_specific = role_specific.replace("{orchestrator_instruction}", "")
        role_specific = role_specific.replace("{feedback_context}", "")
        role_specific = role_specific.strip()

        combined = f"{base_template}\n\n{role_specific}" if role_specific else base_template

        orchestrator_section = (
            f"【指揮者からの指示】\n{self.private_instruction}"
            if self.private_instruction
            else ""
        )
        feedback_section = (
            f"【過去のフィードバック（改善を期待しています）】\n{self.feedback_context}"
            if self.feedback_context
            else ""
        )
        combined = combined.replace("{orchestrator_instruction}", orchestrator_section)
        combined = combined.replace("{feedback_context}", feedback_section)

        if self.speaking_rules:
            combined = f"{combined}\n\n【発言ルール】\n{self.speaking_rules}"

        combined = f"{combined}\n\n{DIVERSITY_RULE}"

        return combined

    # ------------------------------------------------------------------
    # コンテキスト (Layer 2-6)
    # ------------------------------------------------------------------

    def _build_context_message(
        self,
        round_context: dict[str, Any],
        additional_instruction: str = "",
    ) -> str:
        """API に渡す user message を組み立てる。

        各 Layer は独立したヘルパーメソッドで構築し、責務を明確化する。

        Layer 構成:
            - Objective (最優先) / Phase 状態 / Round Goal / ODSC 参考項目
            - 過去サマリ / 禁止例 / 現ラウンド発言 / 直近フロー / 追加指示 /
              直前発言 / 自分の直近発言
        """
        parts: list[str] = []
        parts.extend(self._layer_objective(round_context))
        parts.extend(self._layer_phase_state(round_context))
        parts.extend(self._layer_round_goal(round_context))
        parts.extend(self._layer_odsc_extras(round_context))
        parts.extend(self._layer_previous_summary(round_context))
        parts.extend(self._layer_forbidden_examples(round_context))
        parts.extend(self._layer_current_utterances(round_context))
        parts.extend(self._layer_recent_flow(round_context))
        parts.extend(self._layer_additional_instruction(additional_instruction))
        parts.extend(self._layer_last_utterance(round_context))
        parts.extend(self._layer_own_recent_utterances(round_context))
        parts.append("上記を踏まえて、あなたの立場から自然に発言してください。")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Layer ヘルパー — 各 Layer は list[str] を返す (空なら [])
    # ------------------------------------------------------------------

    @staticmethod
    def _get_odsc_field(round_context: dict[str, Any], field: str) -> str:
        """round_context の ``odsc`` オブジェクトから ``field`` を安全に取り出す。"""
        odsc = round_context.get("odsc")
        if odsc is not None:
            value = getattr(odsc, field, None)
            if value:
                return str(value)
        return str(round_context.get(field, ""))

    def _layer_objective(self, round_context: dict[str, Any]) -> list[str]:
        """最上位で Objective を強調するブロック (最優先)。"""
        objective = self._get_odsc_field(round_context, "objective")
        return [
            "【★★★ 最優先: 全体議題 (Objective) ★★★】\n"
            f"{objective}\n"
            "→ すべての発言はこの Objective の達成にだけ貢献する。\n"
            "→ Objective と入れ替え可能な一般論や、自分の専門分野の自慢話は禁止。\n"
        ]

    @staticmethod
    def _layer_phase_state(round_context: dict[str, Any]) -> list[str]:
        """現在のフェーズ位置 (Round N / 総 M) と phase hint。"""
        round_number = round_context.get("round_number", 0)
        total_rounds = round_context.get("total_rounds", 0)
        if not (round_number and total_rounds):
            return []
        lines = [f"【現在のフェーズ】 Round {round_number} / {total_rounds}"]
        hint = round_context.get("round_phase_hint", "")
        if hint:
            lines.append(hint)
        return ["\n".join(lines) + "\n"]

    @staticmethod
    def _layer_round_goal(round_context: dict[str, Any]) -> list[str]:
        """このラウンドの下位目標。"""
        round_goal = round_context.get("round_goal", "")
        return [f"【このラウンドのゴール (Objective の下位目標)】\n{round_goal}\n"]

    def _layer_odsc_extras(self, round_context: dict[str, Any]) -> list[str]:
        """Deliverable / Success Criteria (参考、二の次扱い)。"""
        deliverable = self._get_odsc_field(round_context, "deliverable")
        success_criteria = self._get_odsc_field(round_context, "success_criteria")
        extras: list[str] = []
        if deliverable:
            extras.append(f"- 成果物 (Deliverable): {deliverable}")
        if success_criteria:
            extras.append(f"- 成功基準 (Success Criteria): {success_criteria}")
        if not extras:
            return []
        return [
            "【参考 (二の次 — これを先に埋めに行かない)】\n"
            + "\n".join(extras)
            + "\n"
        ]

    @staticmethod
    def _layer_previous_summary(round_context: dict[str, Any]) -> list[str]:
        """過去ラウンドの要約 (Layer 3)。"""
        previous_summary = round_context.get("previous_summary")
        if not previous_summary:
            return []
        return [f"【これまでの議論のサマリ】\n{previous_summary}\n"]

    @staticmethod
    def _layer_forbidden_examples(round_context: dict[str, Any]) -> list[str]:
        """既出禁止例リスト (Layer 3b) — 過去ラウンド具体例の再利用を防ぐ。"""
        forbidden = round_context.get("forbidden_examples") or []
        if not forbidden:
            return []
        return [
            "【今回避けるべき既出の具体例】\n"
            + "\n".join(f"- {e}" for e in forbidden)
            + "\n→ これらは既に議論で登場しています。同じ例を繰り返さず、"
            "新しい具体例・業界・シナリオを持ち出してください。\n"
        ]

    @staticmethod
    def _layer_current_utterances(round_context: dict[str, Any]) -> list[str]:
        """このラウンドでこれまでに発生した発言 (Layer 4)。"""
        current_utterances = round_context.get("current_round_utterances") or []
        if not current_utterances:
            return []
        lines = ["【このラウンドのこれまでの発言】"]
        for u in current_utterances:
            lines.append(f"{u['speaker_display']}: {u['content']}")
        lines.append("")
        return ["\n".join(lines)]

    @staticmethod
    def _layer_recent_flow(round_context: dict[str, Any]) -> list[str]:
        """直近 3 発言を「会話の流れ」として提示 (Layer 4b — 引用強制の代替)。"""
        recent_flow = round_context.get("recent_flow") or []
        if not recent_flow:
            return []
        lines = ["【直近の会話の流れ】"]
        for i, f in enumerate(recent_flow, 1):
            lines.append(f"{i}. {f['speaker_display']}: {f['content']}")
        lines.append(
            "→ この流れを踏まえて、あなたなら次に何を言うか自然に返してください。\n"
        )
        return ["\n".join(lines)]

    @staticmethod
    def _layer_additional_instruction(additional_instruction: str) -> list[str]:
        """指揮者からの追加指示 (Layer 5、任意)。"""
        if not additional_instruction:
            return []
        return [f"【追加指示】\n{additional_instruction}\n"]

    @staticmethod
    def _layer_last_utterance(round_context: dict[str, Any]) -> list[str]:
        """直前発言に自然に反応させる (Layer 6、引用強制なし)。"""
        last = round_context.get("last_utterance")
        if not last:
            return []
        return [
            "【直前の発言】\n"
            f"{last['speaker_display']}: {last['content']}\n\n"
            "→ 上記の流れに自然に反応してください。"
            "同意・発展・反論のどれでも良いが、"
            "「〇〇さんの『～』について」のような引用形式は使わない。\n"
        ]

    @staticmethod
    def _layer_own_recent_utterances(
        round_context: dict[str, Any],
    ) -> list[str]:
        """自分の直近発言 (Layer 11、問題 P3-B 対策)。

        直前 2 回の自分の発言と同じ切り出し方・同じ論理展開を避けさせる。
        ``round_context["own_recent_utterances"]`` に
        ``[{speaker_display, content, round}]`` が渡される想定。
        """
        own = round_context.get("own_recent_utterances") or []
        if not own:
            return []
        lines = ["【あなたの直近の発言】"]
        for u in own:
            content = str(u.get("content", ""))[:150]
            lines.append(f"- (Round {u.get('round', '?')}) {content}")
        lines.append(
            "→ 上記と同じ文頭・同じ切り口・同じ論理展開を繰り返してはいけません。"
            "毎回違う型で発言してください。\n"
        )
        return ["\n".join(lines)]

    # ------------------------------------------------------------------
    # API パラメータ構築 (モデル種別別)
    # ------------------------------------------------------------------

    def _build_api_params(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        """モデル種別を判定し、適切な ``_build_api_params_*`` に分岐する。"""
        if self._is_gpt5_series(self.model):
            return self._build_api_params_gpt5(system_prompt, user_message)
        if self._is_claude_thinking_model(self.model) and self.level not in ("none", "minimal"):
            return self._build_api_params_claude_thinking(system_prompt, user_message)
        return self._build_api_params_standard(system_prompt, user_message)

    def _build_api_params_gpt5(self, system_prompt: str, user_message: str) -> dict[str, Any]:
        """GPT-5 系のパラメータ構築。

        不変条件:
            - ``temperature`` / ``max_tokens`` を**絶対に送らない**
            - ``level != "none"`` のとき ``reasoning_effort`` を送る
            - 発言用なので ``verbosity = "low"`` を付ける
            - mode == "openai" のときのみ ``extra_body.allowed_openai_params``
              (azure モードでは付与禁止 = 400 エラー回避)
        """
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "verbosity": DEFAULT_GPT5_VERBOSITY,
        }
        if self.level != "none":
            params["level"] = self.level  # ResilientAPIClient._build_params が reasoning_effort に変換
        return params

    def _build_api_params_claude_thinking(
        self, system_prompt: str, user_message: str
    ) -> dict[str, Any]:
        """Claude 拡張思考のパラメータ構築。

        - level に対応する ``budget_tokens`` を ``ResilientAPIClient`` に伝える
          (``level`` キー経由)。``ResilientAPIClient._build_params`` が
          ``extra_body.thinking`` に変換する。
        - ``temperature`` は通常通り設定可能 (送信)。``max_tokens`` は
          拡張思考時は省略推奨のため送らない。
        """
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "level": self.level,  # api_client 側で budget_tokens に変換
            "temperature": DEFAULT_TEMPERATURE,
        }
        return params

    def _build_api_params_standard(
        self, system_prompt: str, user_message: str
    ) -> dict[str, Any]:
        """標準モデル (gpt-4.1, claude-opus-4-1 等) のパラメータ構築。"""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS_FOR_UTTERANCE,
        }

    # ------------------------------------------------------------------
    # 発言長の事後制御 (3 段目)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_too_long(content: str) -> bool:
        """発言が ``MAX_UTTERANCE_CHARS`` を超えているか判定する。"""
        return len(content) > MAX_UTTERANCE_CHARS

    async def _request_shorter(
        self,
        original_content: str,
        round_context: dict[str, Any],
    ) -> str:
        """長すぎる発言を ``SHORTEN_MODEL`` で短縮する。

        Args:
            original_content: 元の発言。
            round_context: コンテキスト辞書 (現状は未使用、将来の利用に備える)。

        Returns:
            ``MAX_UTTERANCE_CHARS`` 以内に収まる短縮版。失敗 / さらに長い
            場合は末尾を ``"…"`` で切り詰める。
        """
        del round_context  # 現状は未使用 (将来の文脈反映に備える)

        prompt = (
            f"以下の発言が長すぎます（{len(original_content)}文字）。\n"
            "50〜150文字に要約してください。要点だけ。会話調を維持。\n\n"
            f"【元の発言】\n{original_content}\n\n"
            "【ルール】\n"
            "- 最も重要な1ポイントだけ残す\n"
            "- 会話のトーンを崩さない\n"
            "- 数値やキーワードは保持する\n\n"
            "短縮版:"
        )

        try:
            response = await self.api_client.call(
                model=SHORTEN_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=SHORTEN_TEMPERATURE,
                max_tokens=SHORTEN_MAX_TOKENS,
            )
        except Exception as e:  # noqa: BLE001 - 失敗時はフォールバック
            logger.warning("Shorten request failed; falling back to truncation: %s", e)
            return self._truncate_with_ellipsis(original_content)

        shortened = str(response.get("content") or "").strip()
        if not shortened or self._is_too_long(shortened):
            return self._truncate_with_ellipsis(shortened or original_content)
        return shortened

    @staticmethod
    def _truncate_with_ellipsis(content: str) -> str:
        """末尾を ``…`` で切り詰めて ``MAX_UTTERANCE_CHARS`` 内に収める。"""
        if len(content) <= MAX_UTTERANCE_CHARS:
            return content
        cutoff = MAX_UTTERANCE_CHARS - len(SHORTEN_FALLBACK_ELLIPSIS)
        return content[:cutoff] + SHORTEN_FALLBACK_ELLIPSIS

    # ------------------------------------------------------------------
    # モデル判別
    # ------------------------------------------------------------------

    @staticmethod
    def _is_gpt5_series(model: str) -> bool:
        """``gpt-5`` / ``gpt-5-mini`` / ``gpt-5.1`` などを GPT-5 系と判定する。"""
        return ResilientAPIClient._is_gpt5_series(model)

    @staticmethod
    def _is_claude_thinking_model(model: str) -> bool:
        """拡張思考に対応する Claude モデルか判定する。"""
        return ResilientAPIClient._is_claude_thinking(model)


__all__ = [
    "Agent",
    "AgentConfig",
    "MAX_UTTERANCE_CHARS",
    "CLAUDE_THINKING_BUDGET",
]
