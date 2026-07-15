"""発言順序の制御戦略 (Fixed / Dialectic / Shuffle / Dynamic)。

設計書: ``doc/05_conductor.md`` §5.2
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

if TYPE_CHECKING:
    from .api_client import ResilientAPIClient
    from .data_models import RoundConfig, Utterance

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MAX_EXCHANGES = 3
DYNAMIC_ORDER_MAX_TOKENS = 20
DYNAMIC_ORDER_TEMPERATURE = 0.0
DEFAULT_DYNAMIC_MODEL = "gpt-4.1"
DYNAMIC_HANDOFF_MAX_TOKENS = 200  # 振り文言込みの場合の上限


class NextSpeakerDecision(NamedTuple):
    """``DynamicOrder.decide_next_speaker_with_handoff`` の戻り値。

    Attributes:
        role_id: 次発言者の役割 ID。
        handoff_prompt: Conductor から次発言者に伝える「振り」文言。
            空文字の場合はフォールバック (LLM 応答パース失敗) を意味する。
    """

    role_id: str
    handoff_prompt: str

# 対立するロールのマップ (doc/05_conductor.md §5.2.2 より)
OPPOSITION_MAP: dict[str, tuple[str, ...]] = {
    "theorist": ("implementer", "experimentalist"),
    "devil": ("theorist", "literature"),
    "bird_eye": ("implementer",),
    "creative_thinker": ("devil",),
}


# ----------------------------------------------------------------------
# プロトコル
# ----------------------------------------------------------------------


class SpeakingOrder(Protocol):
    """静的な発言順序を返す戦略のインターフェース。"""

    def get_speaking_order(
        self,
        speakers: list[str],
        round_config: "RoundConfig",
        context: dict[str, Any],
    ) -> list[str]:
        ...


# ----------------------------------------------------------------------
# FixedOrder
# ----------------------------------------------------------------------


class FixedOrder:
    """計画通りの固定順序 (``round_config.speakers`` をそのまま返す)。"""

    def get_speaking_order(
        self,
        speakers: list[str],
        round_config: "RoundConfig",
        context: dict[str, Any],
    ) -> list[str]:
        """``speakers`` をそのまま返す (副作用なし)。"""
        del round_config, context
        return list(speakers)


# ----------------------------------------------------------------------
# DialecticOrder
# ----------------------------------------------------------------------


class DialecticOrder:
    """対立するロールを交互に配置する。

    2 者が指定されていればそのまま交互配置。3 者以上なら
    ``OPPOSITION_MAP`` を使って最も対立度の高いペアを選ぶ。
    """

    OPPOSITION_MAP: dict[str, tuple[str, ...]] = OPPOSITION_MAP

    def __init__(self, max_exchanges: int = DEFAULT_MAX_EXCHANGES) -> None:
        """Args: max_exchanges: 交互応答の往復数。"""
        self.max_exchanges = max_exchanges

    def get_speaking_order(
        self,
        speakers: list[str],
        round_config: "RoundConfig",
        context: dict[str, Any],
    ) -> list[str]:
        """対立ペアを ``max_exchanges`` 回交互に配置したリストを返す。"""
        del round_config, context
        if not speakers:
            return []
        if len(speakers) < 2:
            # 1 人しかいなければそのまま (交互配置不能)
            return [speakers[0]] * self.max_exchanges

        pair = self._find_best_opposition_pair(speakers)
        return self._interleave(pair, self.max_exchanges)

    @staticmethod
    def _interleave(pair: list[str], max_exchanges: int) -> list[str]:
        """A, B, A, B, ... の順を生成する。"""
        order: list[str] = []
        for _ in range(max_exchanges):
            order.append(pair[0])
            order.append(pair[1])
        return order

    @classmethod
    def _find_best_opposition_pair(cls, speakers: list[str]) -> list[str]:
        """``speakers`` の中から最も対立度の高いペアを選ぶ。"""
        for s in speakers:
            opposites = cls.OPPOSITION_MAP.get(s, ())
            for opp in opposites:
                if opp in speakers and opp != s:
                    return [s, opp]
        # 対立関係が見つからなければ先頭 2 者
        return speakers[:2]


# ----------------------------------------------------------------------
# ShuffleOrder
# ----------------------------------------------------------------------


class ShuffleOrder:
    """毎ラウンドでランダム順序にする (テスト時は seed 固定可能)。"""

    def __init__(self, seed: int | None = None) -> None:
        """Args: seed: 乱数シード。``None`` ならシステム既定。"""
        self._rng = random.Random(seed)

    def get_speaking_order(
        self,
        speakers: list[str],
        round_config: "RoundConfig",
        context: dict[str, Any],
    ) -> list[str]:
        """``speakers`` のコピーをシャッフルして返す。"""
        del round_config, context
        shuffled = list(speakers)
        self._rng.shuffle(shuffled)
        return shuffled


# ----------------------------------------------------------------------
# DynamicOrder (free_talk 用)
# ----------------------------------------------------------------------


DYNAMIC_NEXT_SPEAKER_PROMPT = """\
次に発言すべきAIを選んでください。

【直前の発言】
{last_speaker}: {last_content}

【参加AI (発言回数)】
{speakers_with_counts}

【このラウンドの目標】
{round_goal}

【ルール】
- 直前の発言に最も有効な応答ができるAIを選ぶ
- まだ発言が少ないAIを優先
- 同じAIが連続3回発言しないこと
- 目標達成に最も貢献できるAIを選ぶ

出力: role_id のみ（1語、余計な説明不要）
"""


# 次発言者選定と同時に「振り文言」も生成するプロンプト (free_talk 用)。
# 応答は必ず 2 行: 1行目=role_id、2行目=Conductor が次発言者に伝える振り文言。
DYNAMIC_NEXT_SPEAKER_WITH_HANDOFF_PROMPT = """\
次に発言すべきAIを選び、そのAIへの「振り (きっかけ質問)」を生成してください。

【直前の発言】
{last_speaker}: {last_content}

【参加AI (発言回数)】
{speakers_with_counts}

【このラウンドの目標】
{round_goal}

【選定ルール】
- 直前の発言に最も鋭い応答ができるAIを選ぶ
- まだ発言が少ないAIを優先
- 同じAIが連続3回発言しないこと

【振り文言のルール (問題4対策 — 必ず質問形式)】
- 必ず疑問形で終わる 質問文にする (「〜ですか?」「〜どう思いますか?」)
- 構造: [名指し] + [直前発言の要点を1つ抜き出す] + [次発言者の視点で問う]
- 良い例:
  「松下さん、孫さんが言った『月額固定＋ピーク従量』の課金モデル、
   現場で運用する営業担当の目線から見て、どこに落とし穴がありそうですか?」
  「実装屋さん、理論屋の『O(N²)は厳しい』という指摘に対して、
   具体的な実装で回避する方法はありますか?」
- 悪い例 (禁止):
  「次は松下さんです」「実装屋さん、お願いします」
  「〜について発言してください」(命令形は不可)
- 40〜100 文字。会話調で自然に。

【出力形式 (2 行、それ以外の説明文なし)】
role_id: <選んだ role_id>
handoff: <振り文言>
"""


class DynamicOrder:
    """Conductor LLM が次発言者を動的に決定する戦略 (free_talk 用)。"""

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        model: str = DEFAULT_DYNAMIC_MODEL,
    ) -> None:
        self.api_client = api_client
        self.model = model

    async def decide_next_speaker(
        self,
        speakers: list[str],
        utterances: list["Utterance"],
        utterance_counts: dict[str, int],
        round_goal: str,
    ) -> str:
        """直近文脈から次発言者を 1 体決定する。

        Args:
            speakers: 参加 AI の ``role_id`` リスト。
            utterances: これまでの発言。
            utterance_counts: ``role_id`` → 発言回数。
            round_goal: ラウンドの目標。

        Returns:
            次発言者の ``role_id``。LLM 応答がパースできない場合は発言数
            最少の AI、それも複数候補なら先頭を返す。
        """
        if not speakers:
            raise ValueError("speakers must be non-empty")

        if not utterances:
            return speakers[0]

        last = utterances[-1]
        counts_text = self._format_counts(speakers, utterance_counts)
        prompt = DYNAMIC_NEXT_SPEAKER_PROMPT.format(
            last_speaker=last.speaker_display,
            last_content=last.content,
            speakers_with_counts=counts_text,
            round_goal=round_goal,
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DYNAMIC_ORDER_TEMPERATURE,
            max_tokens=DYNAMIC_ORDER_MAX_TOKENS,
        )
        raw = str(response.get("content") or "").strip()
        return self._resolve_speaker(raw, speakers, utterance_counts)

    @staticmethod
    def _format_counts(
        speakers: list[str],
        counts: dict[str, int],
    ) -> str:
        return "\n".join(
            f"- {s}: {counts.get(s, 0)} 回" for s in speakers
        )

    @staticmethod
    def _resolve_speaker(
        raw: str,
        speakers: list[str],
        counts: dict[str, int],
    ) -> str:
        """LLM 応答を ``speakers`` のいずれかに解決する。

        - 完全一致 → そのまま採用
        - 含まれる ``role_id`` を順に検索
        - 失敗時は発言数最少の AI を返す
        """
        candidate = raw.strip().lower()
        # トークン余分や引用符を除去
        candidate = candidate.strip(' .\n\r\t"\'`')

        for s in speakers:
            if candidate == s.lower():
                return s
        for s in speakers:
            if s.lower() in candidate:
                return s

        logger.warning(
            "DynamicOrder: failed to parse next speaker (%r); falling back.", raw
        )
        # フォールバック: 発言数最少の AI
        sorted_speakers = sorted(speakers, key=lambda s: counts.get(s, 0))
        return sorted_speakers[0]

    async def decide_next_speaker_with_handoff(
        self,
        speakers: list[str],
        utterances: list["Utterance"],
        utterance_counts: dict[str, int],
        round_goal: str,
    ) -> NextSpeakerDecision:
        """次発言者と Conductor からの「振り」文言を同時に決定する。

        LLM に 1 回だけ問い合わせ、2 行応答 (``role_id:`` と ``handoff:``)
        をパースする。応答が壊れた場合は ``decide_next_speaker`` と同じ
        フォールバックで役割 ID のみ返し、``handoff_prompt`` は空文字。

        Args:
            speakers: 参加 AI の ``role_id`` リスト。
            utterances: これまでの発言。
            utterance_counts: ``role_id`` → 発言回数。
            round_goal: ラウンドの目標。

        Returns:
            ``NextSpeakerDecision(role_id, handoff_prompt)``。
        """
        if not speakers:
            raise ValueError("speakers must be non-empty")

        if not utterances:
            return NextSpeakerDecision(role_id=speakers[0], handoff_prompt="")

        last = utterances[-1]
        counts_text = self._format_counts(speakers, utterance_counts)
        prompt = DYNAMIC_NEXT_SPEAKER_WITH_HANDOFF_PROMPT.format(
            last_speaker=last.speaker_display,
            last_content=last.content,
            speakers_with_counts=counts_text,
            round_goal=round_goal,
        )

        response = await self.api_client.call(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DYNAMIC_ORDER_TEMPERATURE,
            max_tokens=DYNAMIC_HANDOFF_MAX_TOKENS,
        )
        raw = str(response.get("content") or "").strip()
        role_id, handoff = self._parse_handoff_response(raw, speakers, utterance_counts)
        return NextSpeakerDecision(role_id=role_id, handoff_prompt=handoff)

    @classmethod
    def _parse_handoff_response(
        cls,
        raw: str,
        speakers: list[str],
        counts: dict[str, int],
    ) -> tuple[str, str]:
        """LLM 応答から ``(role_id, handoff)`` を抽出する。

        期待形式:
            role_id: <id>
            handoff: <text>

        いずれかが取れない場合は :meth:`_resolve_speaker` のフォールバックを
        使用し、handoff は空文字とする。
        """
        role_line = ""
        handoff_line = ""
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if lower.startswith("role_id:") or lower.startswith("role:"):
                _, _, value = stripped.partition(":")
                role_line = value.strip()
            elif lower.startswith("handoff:") or lower.startswith("振り:"):
                _, _, value = stripped.partition(":")
                handoff_line = value.strip()

        if not role_line:
            # 1 行目を role_id とみなす
            first = next((l.strip() for l in raw.splitlines() if l.strip()), "")
            role_line = first

        role_id = cls._resolve_speaker(role_line, speakers, counts)
        return role_id, handoff_line


__all__ = [
    "SpeakingOrder",
    "FixedOrder",
    "DialecticOrder",
    "ShuffleOrder",
    "DynamicOrder",
    "NextSpeakerDecision",
    "OPPOSITION_MAP",
    "DYNAMIC_NEXT_SPEAKER_PROMPT",
    "DYNAMIC_NEXT_SPEAKER_WITH_HANDOFF_PROMPT",
]
