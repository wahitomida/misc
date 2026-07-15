"""議論の収束・堂々巡り・同意しすぎを判定する検知器。

Conductor から呼び出される非同期検知器群。各検知器は ``ResilientAPIClient``
を介して軽量モデル (gpt-4.1, temperature=0) に問い合わせ、JSON 応答をパースする。

設計書: ``doc/05_conductor.md`` §5.3, §5.4, §5.6
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from .data_models import ConvergenceResult, RepetitionResult, RoundLog, Utterance

if TYPE_CHECKING:
    from .api_client import ResilientAPIClient
    from .data_models import OrchestraPlan
    from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CONDUCTOR_MODEL = "gpt-4.1"
DEFAULT_CONDUCTOR_TEMPERATURE = 0.0
CONVERGENCE_MAX_TOKENS = 200
REPETITION_MAX_TOKENS = 150
AGREEMENT_MAX_TOKENS = 10

DEFAULT_STAGNATION_WINDOW = 3
DEFAULT_STAGNATION_TOLERANCE = 0.05
DEFAULT_REPETITION_WINDOW = 4
DEFAULT_AGREEMENT_WINDOW = 3


# ----------------------------------------------------------------------
# プロンプト
# ----------------------------------------------------------------------


CONVERGENCE_CHECK_PROMPT = """\
以下の議論ログを分析し、参加者間の合意度を評価してください。

【必須】回答は必ず有効な JSON オブジェクトのみ。前後の説明文・前置き・
コードフェンスの内側以外に何も付けないこと。

【ODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【このラウンドの目標】
{round_goal}

【直近の議論（このラウンド全文）】
{round_utterances}

【これまでの収束スコア推移】
{previous_scores}

【スコア変化ルール（絶対遵守）】
- 前回スコアが存在する場合、今回は必ず「前進した理由」または「後退した理由」を
  reasoning に明記すること。
- 前回と同じ値を安易に返すのは禁止。停滞に見えても、微細な進展/後退を
  観察して差分を出すこと。
- 前進していれば +0.05 以上、後退していれば -0.05 以上変化させる。
- どうしても同じスコアにする場合は reasoning に「完全に同水準である理由」を
  1 文で明示する。

【評価の観点】
1. アイデアが十分に膨らんだか（新しい切り口・展開が出尽くしたか）
2. 反対意見や死角が指摘され、それに対する代替案が出たか
3. 具体的な次のアクションや実験が提案されたか
4. Success Criteria の達成度はどの程度か
5. まだ深掘りできる未探索の方向性が残っていないか

【重要】
- 単に「方向性が合っている」だけでは収束とみなさない
- 「まだこういう展開もありえる」が残っている限り、スコアを高くしない
- 全員が同意しているだけの状態は 0.5 程度（深掘り不足の可能性）

【出力形式 (JSON のみ)】
{{
  "score": 0.75,
  "reasoning": "合意度の根拠（1-2文）",
  "remaining_disagreements": ["未解決の論点1", "論点2"],
  "recommendation": "continue"
}}

score の目安:
- 0.0-0.3: 方向性すら定まっていない
- 0.3-0.5: 方向性は見えるが、アイデアの広がりが不十分
- 0.5-0.65: 複数の切り口が出たが、深掘り・具体化が足りない
- 0.65-0.8: 主要な方向性が探索され、具体的アクションも一部出た
- 0.8-0.9: アイデアが十分に発展し、次のステップが明確
- 0.9-1.0: 完全に議論し尽くした（稀）

recommendation:
- "continue": まだ深掘りや新しい切り口の余地がある
- "conclude": アイデアが十分に発展し、次のアクションが明確になった
- "pivot": 議論が行き詰まっている。別の角度から攻める必要がある
"""


REPETITION_CHECK_PROMPT = """\
以下の直近{window}発言を分析し、堂々巡りが起きているか判定してください。

【必須】回答は必ず有効な JSON オブジェクトのみ。前後の説明文は不要。

【直近の発言】
{utterances_text}

【判定基準】
- 同じ論点が2回以上繰り返されている → 堂々巡り
- 新しい情報・視点が追加されず、同じ主張の言い換え → 堂々巡り
- 前の発言を踏まえて深まっている → 堂々巡りではない

【出力形式 (JSON のみ)】
{{
  "is_repeating": true,
  "repeated_topic": "繰り返されている論点（なければ空文字）",
  "suggestion": "議論を前に進めるための提案"
}}
"""


AGREEMENT_CHECK_PROMPT = """\
以下の直近{window}発言を分析してください。

{utterances_text}

全員が同じ方向に同意しているだけで、新しい視点や批判が出ていない場合は true を返してください。
出力: true または false のみ
"""


# ----------------------------------------------------------------------
# 共通ヘルパー
# ----------------------------------------------------------------------


def _format_utterances(utterances: list[Utterance]) -> str:
    """``Utterance`` のリストを ``speaker_display: content`` 行に整形する。"""
    return "\n".join(f"{u.speaker_display}: {u.content}" for u in utterances)


def _extract_json_object(text: str) -> dict[str, Any]:
    """LLM 応答から最初の JSON オブジェクトを抽出する。

    Markdown コードフェンス (``` または ```json) を許容する。
    """
    if not text or not text.strip():
        raise ValueError("Empty response from API")
    text = text.strip()

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
            raise ValueError("No JSON object found")
        end = text.rfind("}")
        payload = text[start : end + 1] if end > start else text[start:]

    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    return data


# ----------------------------------------------------------------------
# ConvergenceChecker
# ----------------------------------------------------------------------


class ConvergenceChecker:
    """ラウンド終了時の収束スコア計算と停滞検知。

    Attributes:
        api_client: 軽量モデル用 API クライアント。
        model: 収束判定モデル (デフォルト ``gpt-4.1``)。
        score_history: ラウンドごとの収束スコア履歴。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        model: str = DEFAULT_CONDUCTOR_MODEL,
    ) -> None:
        self.api_client = api_client
        self.model = model
        self.score_history: list[float] = []

    async def check(
        self,
        round_log: RoundLog,
        plan: "OrchestraPlan",
        memory: "ConversationMemory | None" = None,
    ) -> ConvergenceResult:
        """ラウンド終了時に収束スコアを取得する。

        Args:
            round_log: 評価対象のラウンド。
            plan: 議論計画 (``odsc.objective`` / ``odsc.success_criteria`` を参照)。
            memory: 共有メモリ (現状は未使用、将来の文脈拡張用)。

        Returns:
            ``ConvergenceResult``。LLM 応答が不正な場合は score=0.0,
            recommendation="continue" のフォールバック結果を返す。
        """
        del memory  # 現状は未使用 (将来の文脈拡張点)

        prompt = CONVERGENCE_CHECK_PROMPT.format(
            objective=plan.odsc.objective,
            success_criteria=plan.odsc.success_criteria,
            round_goal=round_log.goal,
            round_utterances=_format_utterances(round_log.public_utterances),
            previous_scores=self._format_score_history(),
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_CONDUCTOR_TEMPERATURE,
            max_tokens=CONVERGENCE_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        result = self._parse_convergence(content)
        self.score_history.append(result.score)
        return result

    def should_terminate(self, result: ConvergenceResult, threshold: float) -> bool:
        """議論を終了すべきか判定する。

        Args:
            result: 直近の収束判定結果。
            threshold: ``odsc.convergence_threshold``。

        Returns:
            ``score >= threshold`` または ``recommendation == "conclude"``。
        """
        return result.score >= threshold or result.recommendation == "conclude"

    def is_stagnating(
        self,
        window: int = DEFAULT_STAGNATION_WINDOW,
        tolerance: float = DEFAULT_STAGNATION_TOLERANCE,
    ) -> bool:
        """収束スコアが直近 ``window`` ラウンドで停滞しているか。

        Args:
            window: 比較するラウンド数。
            tolerance: 停滞と判定するスコア変動の閾値。

        Returns:
            履歴が ``window`` 未満なら ``False``。
            ``max - min < tolerance`` なら ``True``。
        """
        if len(self.score_history) < window:
            return False
        recent = self.score_history[-window:]
        return (max(recent) - min(recent)) < tolerance

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _format_score_history(self) -> str:
        if not self.score_history:
            return "(まだ履歴なし)"
        return ", ".join(f"{s:.2f}" for s in self.score_history)

    @staticmethod
    def _parse_convergence(content: str) -> ConvergenceResult:
        """LLM 応答 JSON を ``ConvergenceResult`` に変換する (フォールバック付き)。

        失敗時のフォールバック段階:
            1. JSON オブジェクト抽出失敗 → 正規表現で score だけ抽出
            2. score 抽出も失敗 → score=0.5 の中間値を返す (議論を継続させるため、
               0.0 ではなく 0.5)
        """
        try:
            data = _extract_json_object(content)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse convergence response: %s", e)
            # フォールバック 1: score 値を正規表現で抽出
            m = re.search(r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', content or "")
            if m:
                try:
                    score = max(0.0, min(1.0, float(m.group(1))))
                    return ConvergenceResult(
                        score=score,
                        reasoning="parse_partial",
                        recommendation="continue",
                    )
                except ValueError:
                    pass
            # フォールバック 2: 中間値で議論を継続させる
            return ConvergenceResult(
                score=0.5,
                reasoning="parse_error_fallback",
                recommendation="continue",
            )

        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))  # クリップ

        recommendation = str(data.get("recommendation", "continue"))
        if recommendation not in ("continue", "conclude", "pivot"):
            recommendation = "continue"

        disagreements = data.get("remaining_disagreements") or []
        if not isinstance(disagreements, list):
            disagreements = [str(disagreements)]
        else:
            disagreements = [str(d) for d in disagreements]

        return ConvergenceResult(
            score=score,
            reasoning=str(data.get("reasoning", "")),
            remaining_disagreements=disagreements,
            recommendation=recommendation,
        )


# ----------------------------------------------------------------------
# RepetitionDetector
# ----------------------------------------------------------------------


class RepetitionDetector:
    """発言の繰り返し (堂々巡り) を検知する。"""

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        model: str = DEFAULT_CONDUCTOR_MODEL,
    ) -> None:
        self.api_client = api_client
        self.model = model

    async def check_repetition(
        self,
        recent_utterances: list[Utterance],
        window: int = DEFAULT_REPETITION_WINDOW,
    ) -> RepetitionResult:
        """直近 ``window`` 発言に堂々巡りがあるかを判定する。

        Args:
            recent_utterances: ``Utterance`` のリスト。
            window: 末尾から見るウィンドウサイズ。

        Returns:
            ``RepetitionResult``。発言数が ``window`` 未満なら
            ``is_repeating=False`` を即座に返す (API 呼び出しなし)。
        """
        if len(recent_utterances) < window:
            return RepetitionResult(is_repeating=False)

        target = recent_utterances[-window:]
        prompt = REPETITION_CHECK_PROMPT.format(
            window=window,
            utterances_text=_format_utterances(target),
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_CONDUCTOR_TEMPERATURE,
            max_tokens=REPETITION_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        return self._parse_repetition(content)

    @staticmethod
    def _parse_repetition(content: str) -> RepetitionResult:
        try:
            data = _extract_json_object(content)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse repetition response: %s", e)
            return RepetitionResult(is_repeating=False)

        is_repeating = bool(data.get("is_repeating", False))
        return RepetitionResult(
            is_repeating=is_repeating,
            repeated_topic=str(data.get("repeated_topic", "")),
            suggestion=str(data.get("suggestion", "")),
        )


# ----------------------------------------------------------------------
# AgreementDetector
# ----------------------------------------------------------------------


class AgreementDetector:
    """直近発言が同意一色になっていないかを検知する。"""

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        model: str = DEFAULT_CONDUCTOR_MODEL,
    ) -> None:
        self.api_client = api_client
        self.model = model

    async def check_excessive_agreement(
        self,
        recent_utterances: list[Utterance],
        window: int = DEFAULT_AGREEMENT_WINDOW,
    ) -> bool:
        """直近 ``window`` 発言が全て同意的かを判定する。

        Args:
            recent_utterances: ``Utterance`` のリスト。
            window: 末尾から見るウィンドウサイズ。

        Returns:
            ``True`` なら同意過剰。発言数が ``window`` 未満なら ``False``
            (API 呼び出しなし)。
        """
        if len(recent_utterances) < window:
            return False

        target = recent_utterances[-window:]
        prompt = AGREEMENT_CHECK_PROMPT.format(
            window=window,
            utterances_text=_format_utterances(target),
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_CONDUCTOR_TEMPERATURE,
            max_tokens=AGREEMENT_MAX_TOKENS,
        )
        content = str(response.get("content") or "").strip().lower()
        return content.startswith("true")


__all__ = [
    "ConvergenceChecker",
    "RepetitionDetector",
    "AgreementDetector",
    "CONVERGENCE_CHECK_PROMPT",
    "REPETITION_CHECK_PROMPT",
    "AGREEMENT_CHECK_PROMPT",
    "DEFAULT_CONDUCTOR_MODEL",
    "DEFAULT_STAGNATION_WINDOW",
    "DEFAULT_STAGNATION_TOLERANCE",
    "DEFAULT_REPETITION_WINDOW",
    "DEFAULT_AGREEMENT_WINDOW",
]
