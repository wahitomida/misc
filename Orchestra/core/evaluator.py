"""Phase 3 の評価ステージを担う ``Evaluator``。

各エージェントに自己評価と他者評価を依頼し、構造化された結果を返す。
集計・MVP 選出・指揮者総合評価は ``Synthesizer`` (D-4) の責務。

設計書: ``doc/09_evaluation_feedback.md`` §9.1, §9.2
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .data_models import (
    AgentEvaluations,
    DiscussionLog,
    OrchestraPlan,
    PeerEvaluation,
    SelfEvaluation,
    Utterance,
)

if TYPE_CHECKING:
    from .agent import Agent
    from .api_client import ResilientAPIClient
    from .config_loader import Settings

logger = logging.getLogger(__name__)

# Constants
DEFAULT_EVALUATOR_MODEL_KEY = "evaluator"
DEFAULT_EVALUATOR_MODEL = "gpt-4.1"
DEFAULT_EVALUATOR_TEMPERATURE = 0.0
DEFAULT_EVALUATOR_MAX_TOKENS = 800
DEFAULT_PEER_MAX_TOKENS = 600
DEFAULT_COMBINED_MAX_TOKENS = 1200

SCORE_MIN = 1
SCORE_MAX = 5


# ----------------------------------------------------------------------
# プロンプトテンプレート
# ----------------------------------------------------------------------


SELF_EVALUATION_PROMPT = """\
議論が完了しました。自分の貢献を振り返り、評価してください。

【あなたの役割】
{role_display_name} ({role_id})

【あなたに期待されていたこと】
{expected_contribution}

【あなたの評価基準】
{evaluation_criteria_formatted}

【議論のODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【議論ログ（あなたの発言は ** で囲んでハイライトしています）】
{discussion_log_with_highlights}

【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
  "scores": {{
{scores_template}
  }},
  "avg_score": <平均値 小数点1桁>,
  "reasoning": "<3-5文で振り返り。何ができて何ができなかったか>",
  "key_contributions": ["<主な貢献1>", "<主な貢献2>"],
  "missed_opportunities": ["<やるべきだったがやらなかったこと>"]
}}

【評価の心がけ】
- 自分に甘くしない。客観的に。
- 5は「完璧にできた」。4は「おおむねできた」。3は「普通」。2は「不十分」。1は「全くできなかった」。
- missed_opportunities は必ず1つ以上挙げること（完璧な議論はない）。
"""


PEER_EVALUATION_PROMPT = """\
議論の参加者をそれぞれ評価してください。

【あなた】
{self_role_display_name} ({self_role_id})

【評価対象】
{other_agents_list}

【議論ログ】
{discussion_log}

【評価基準】
各参加者の「議論への貢献度」を5点満点で評価し、1行コメントを添えてください。

- 5: 議論を決定的に前進させた。この人がいなければ結論が変わった。
- 4: 有用な貢献をした。議論の質を上げた。
- 3: 普通の貢献。可もなく不可もなく。
- 2: 貢献が薄かった。もっとやれたはず。
- 1: 議論を阻害した。

【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
{peer_template}
}}

【注意】
- 自分自身は評価しない
- 同調圧力に流されず、正直に評価する
- コメントは具体的に（「良かった」ではなく「Round 2のXXの指摘が議論を転換させた」）
"""


COMBINED_EVALUATION_PROMPT = """\
議論が完了しました。自己評価と他者評価をまとめて行ってください。

【あなたの役割】
{role_display_name} ({role_id})

【あなたに期待されていたこと】
{expected_contribution}

【あなたの評価基準（自己評価用）】
{evaluation_criteria_formatted}

【他の参加者（他者評価対象）】
{other_agents_list}

【議論のODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【議論ログ（あなたの発言は ** で囲んでハイライトしています）】
{discussion_log_with_highlights}

【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
  "self_evaluation": {{
    "scores": {{
{scores_template}
    }},
    "avg_score": <平均値 小数点1桁>,
    "reasoning": "<3-5文で振り返り>",
    "key_contributions": ["<主な貢献1>", "<主な貢献2>"],
    "missed_opportunities": ["<やるべきだったがやらなかったこと>"]
  }},
  "peer_evaluations": {{
{peer_template}
  }}
}}

【注意】
- 自分自身は peer_evaluations に含めない
- 自己評価は厳しく、他者評価は具体的に
- スコアは 1〜5 の整数
"""


# ----------------------------------------------------------------------
# Evaluator
# ----------------------------------------------------------------------


class Evaluator:
    """エージェントごとの評価結果を LLM 経由で取得する。

    Attributes:
        api_client: 軽量モデル用 API クライアント。
        settings: 全体設定。
        model: 評価に使うモデル。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        settings: "Settings",
        model: str | None = None,
    ) -> None:
        self.api_client = api_client
        self.settings = settings
        self.model = model or settings.models.get(
            DEFAULT_EVALUATOR_MODEL_KEY, DEFAULT_EVALUATOR_MODEL
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def request_self_evaluation(
        self,
        agent: "Agent",
        discussion_log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> SelfEvaluation:
        """``agent`` に自己評価を依頼する。"""
        prompt = self._build_self_eval_prompt(agent, discussion_log, plan)
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_EVALUATOR_TEMPERATURE,
            max_tokens=DEFAULT_EVALUATOR_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        return self._parse_self_evaluation(content, agent)

    async def request_peer_evaluation(
        self,
        agent: "Agent",
        other_agents: list["Agent"],
        discussion_log: DiscussionLog,
    ) -> dict[str, PeerEvaluation]:
        """``agent`` に ``other_agents`` への評価を依頼する。

        ``other_agents`` に ``agent`` 自身が含まれていても評価対象から除外する。
        """
        targets = [a for a in other_agents if a.role_id != agent.role_id]
        if not targets:
            return {}

        prompt = self._build_peer_eval_prompt(agent, targets, discussion_log)
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_EVALUATOR_TEMPERATURE,
            max_tokens=DEFAULT_PEER_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        return self._parse_peer_evaluation(content, agent, targets)

    async def request_combined_evaluation(
        self,
        agent: "Agent",
        other_agents: list["Agent"],
        discussion_log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> AgentEvaluations:
        """自己評価と他者評価を 1 回の API 呼び出しで取得する。

        ``other_agents`` に ``agent`` 自身が含まれていても peer 対象から除外する。
        """
        targets = [a for a in other_agents if a.role_id != agent.role_id]
        prompt = self._build_combined_eval_prompt(
            agent, targets, discussion_log, plan
        )
        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_EVALUATOR_TEMPERATURE,
            max_tokens=DEFAULT_COMBINED_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        data = self._parse_evaluation_response(content)

        self_eval = self._build_self_eval_from_dict(data.get("self_evaluation"), agent)
        peer_evals = self._build_peer_evals_from_dict(
            data.get("peer_evaluations"), targets
        )
        return AgentEvaluations(self_eval=self_eval, peer_evals=peer_evals)

    # ------------------------------------------------------------------
    # プロンプト構築
    # ------------------------------------------------------------------

    def _build_self_eval_prompt(
        self,
        agent: "Agent",
        log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> str:
        return SELF_EVALUATION_PROMPT.format(
            role_display_name=agent.display_name,
            role_id=agent.role_id,
            expected_contribution=self._get_expected_contribution(agent),
            evaluation_criteria_formatted=self._format_evaluation_criteria(agent),
            objective=plan.odsc.objective,
            success_criteria=plan.odsc.success_criteria,
            discussion_log_with_highlights=self._format_discussion_log_with_highlights(
                agent, log
            ),
            scores_template=self._build_scores_template(agent),
        )

    def _build_peer_eval_prompt(
        self,
        agent: "Agent",
        others: list["Agent"],
        log: DiscussionLog,
    ) -> str:
        return PEER_EVALUATION_PROMPT.format(
            self_role_display_name=agent.display_name,
            self_role_id=agent.role_id,
            other_agents_list=self._format_other_agents_list(others),
            discussion_log=self._format_full_log(log),
            peer_template=self._build_peer_template(others),
        )

    def _build_combined_eval_prompt(
        self,
        agent: "Agent",
        others: list["Agent"],
        log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> str:
        return COMBINED_EVALUATION_PROMPT.format(
            role_display_name=agent.display_name,
            role_id=agent.role_id,
            expected_contribution=self._get_expected_contribution(agent),
            evaluation_criteria_formatted=self._format_evaluation_criteria(agent),
            other_agents_list=self._format_other_agents_list(others),
            objective=plan.odsc.objective,
            success_criteria=plan.odsc.success_criteria,
            discussion_log_with_highlights=self._format_discussion_log_with_highlights(
                agent, log
            ),
            scores_template=self._build_scores_template(agent),
            peer_template=self._build_peer_template(others),
        )

    # ------------------------------------------------------------------
    # フォーマッタ
    # ------------------------------------------------------------------

    @staticmethod
    def _get_expected_contribution(agent: "Agent") -> str:
        """``Agent.config.expected_contribution`` を取り出す (空でも安全)。"""
        config = getattr(agent, "config", None)
        return getattr(config, "expected_contribution", "") or "(指定なし)"

    @staticmethod
    def _format_evaluation_criteria(agent: "Agent") -> str:
        criteria = getattr(agent, "evaluation_criteria", []) or []
        if not criteria:
            return "(評価基準なし)"
        lines: list[str] = []
        for c in criteria:
            name = c.get("name", "?")
            desc = c.get("description", "")
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _build_scores_template(agent: "Agent") -> str:
        """JSON テンプレートの scores 部を組み立てる。"""
        criteria = getattr(agent, "evaluation_criteria", []) or []
        if not criteria:
            return '    "総合": <1-5の整数>'
        items: list[str] = []
        for c in criteria:
            name = c.get("name", "?")
            items.append(f'    "{name}": <1-5の整数>')
        return ",\n".join(items)

    @staticmethod
    def _build_peer_template(others: list["Agent"]) -> str:
        if not others:
            return ""
        items: list[str] = []
        for a in others:
            items.append(
                f'  "{a.role_id}": {{\n'
                f'    "score": <1-5>,\n'
                f'    "comment": "<1行コメント>"\n'
                f"  }}"
            )
        return ",\n".join(items)

    @staticmethod
    def _format_other_agents_list(others: list["Agent"]) -> str:
        if not others:
            return "(他の参加者なし)"
        lines: list[str] = []
        for a in others:
            lines.append(f"- {a.display_name} ({a.role_id})")
        return "\n".join(lines)

    @classmethod
    def _format_discussion_log_with_highlights(
        cls,
        agent: "Agent",
        log: DiscussionLog,
    ) -> str:
        """議論ログを ``round_num`` ごとに整形し、``agent`` の発言を ``**`` で囲む。"""
        lines: list[str] = []
        for round_log in log.rounds:
            lines.append(
                f"\n--- Round {round_log.round}: {round_log.phase_name} ---"
            )
            for u in round_log.public_utterances:
                lines.append(cls._format_utterance(u, agent.role_id))
        return "\n".join(lines) if lines else "(ログなし)"

    @classmethod
    def _format_full_log(cls, log: DiscussionLog) -> str:
        """ハイライトなしの議論ログ整形。"""
        lines: list[str] = []
        for round_log in log.rounds:
            lines.append(f"\n--- Round {round_log.round}: {round_log.phase_name} ---")
            for u in round_log.public_utterances:
                lines.append(f"{u.speaker_display}: {u.content}")
        return "\n".join(lines) if lines else "(ログなし)"

    @staticmethod
    def _format_utterance(u: Utterance, highlight_role_id: str) -> str:
        if u.speaker == highlight_role_id:
            return f"**{u.speaker_display}: {u.content}**"
        return f"{u.speaker_display}: {u.content}"

    # ------------------------------------------------------------------
    # パーサ
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_evaluation_response(content: str) -> dict[str, Any]:
        """LLM 応答テキストから JSON オブジェクトを抽出する。

        Markdown フェンス / 前後説明文を許容。失敗時は空辞書を返す。
        """
        if not content or not content.strip():
            return {}
        text = content.strip()

        fence_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            payload = fence_match.group(1)
        else:
            start = text.find("{")
            if start == -1:
                logger.warning("Evaluator: no JSON object found in response")
                return {}
            end = text.rfind("}")
            payload = text[start : end + 1] if end > start else text[start:]

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.warning("Evaluator: failed to parse JSON: %s", e)
            return {}

        if not isinstance(data, dict):
            return {}
        return data

    @classmethod
    def _parse_self_evaluation(
        cls,
        content: str,
        agent: "Agent",
    ) -> SelfEvaluation:
        """LLM 応答を ``SelfEvaluation`` に変換する。失敗時はゼロ値を返す。"""
        data = cls._parse_evaluation_response(content)
        return cls._build_self_eval_from_dict(data, agent)

    @classmethod
    def _parse_peer_evaluation(
        cls,
        content: str,
        agent: "Agent",
        targets: list["Agent"],
    ) -> dict[str, PeerEvaluation]:
        """LLM 応答を ``role_id`` → ``PeerEvaluation`` に変換する。

        ``agent`` 自身のキーがあっても除外する。``targets`` に含まれない
        ``role_id`` は警告ログのみで無視する。
        """
        data = cls._parse_evaluation_response(content)
        return cls._build_peer_evals_from_dict(data, targets, exclude=agent.role_id)

    @classmethod
    def _build_self_eval_from_dict(
        cls,
        data: dict[str, Any] | None,
        agent: "Agent",
    ) -> SelfEvaluation:
        if not data:
            return SelfEvaluation()
        raw_scores = data.get("scores") or {}
        scores = cls._clip_scores(raw_scores)
        avg = data.get("avg_score")
        try:
            avg = float(avg) if avg is not None else cls._average(scores)
        except (TypeError, ValueError):
            avg = cls._average(scores)

        return SelfEvaluation(
            scores=scores,
            avg_score=round(avg, 2) if isinstance(avg, float) else 0.0,
            reasoning=str(data.get("reasoning", "")),
            key_contributions=cls._coerce_string_list(data.get("key_contributions")),
            missed_opportunities=cls._coerce_string_list(
                data.get("missed_opportunities")
            ),
        )

    @classmethod
    def _build_peer_evals_from_dict(
        cls,
        data: dict[str, Any] | None,
        targets: list["Agent"],
        exclude: str | None = None,
    ) -> dict[str, PeerEvaluation]:
        if not data:
            return {}
        valid_role_ids = {a.role_id for a in targets}
        result: dict[str, PeerEvaluation] = {}
        for role_id, value in data.items():
            if exclude and role_id == exclude:
                continue
            if role_id not in valid_role_ids:
                logger.warning(
                    "Evaluator: peer evaluation for unknown role_id %r ignored",
                    role_id,
                )
                continue
            if not isinstance(value, dict):
                continue
            try:
                score = int(value.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            score = max(SCORE_MIN, min(SCORE_MAX, score)) if score else 0
            result[role_id] = PeerEvaluation(
                score=score,
                comment=str(value.get("comment", "")),
            )
        return result

    # ------------------------------------------------------------------
    # 数値ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _clip_scores(raw_scores: dict[str, Any]) -> dict[str, int]:
        clipped: dict[str, int] = {}
        for name, value in raw_scores.items():
            try:
                v = int(value)
            except (TypeError, ValueError):
                logger.warning("Evaluator: non-numeric score %r=%r ignored", name, value)
                continue
            clipped[str(name)] = max(SCORE_MIN, min(SCORE_MAX, v))
        return clipped

    @staticmethod
    def _average(scores: dict[str, int]) -> float:
        if not scores:
            return 0.0
        return sum(scores.values()) / len(scores)

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(v) for v in value if v is not None]


__all__ = [
    "Evaluator",
    "SELF_EVALUATION_PROMPT",
    "PEER_EVALUATION_PROMPT",
    "COMBINED_EVALUATION_PROMPT",
    "DEFAULT_EVALUATOR_MODEL",
]
