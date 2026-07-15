"""Idea Discussion と Code Review Meeting で共通の議論設定ヘルパー。

責務:
    - expertise (beginner / intermediate / expert) 別の tone prefix 定義
    - ``Agent.speaking_rules`` への統一的な注入
    - 会議固有の追加ルール (``extra_rules``) との合成

背景:
    Phase 1-3 の改善で以下は既に ``core/agent.py`` 側で共通化されている:
        - ``AGENT_BASE_ATTITUDE`` (会話の態度 - 引用強制は撤廃済み)
        - ``DIVERSITY_RULE`` (同じ構文の反復を避ける多様性ルール)
        - Layer 6 の直前発言強調
    本モジュールは残された「発言口調の expertise 制御」と
    「機能個別の追加ルール」の合成のみを担当する。

設計書: ``doc/06_agent.md`` §6.3, ``doc/11_idea_discussion.md`` §11.4
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent


DEFAULT_EXPERTISE = "intermediate"


# expertise 別の tone prefix (Agent.speaking_rules に注入して口調を制御)。
# 論文口調・独白調にさせず、自然な雑談の会話テンポを保つことに焦点を絞る。
# 「必ず具体例を入れる」「もし～だったら面白い を含める」などの構文強制は採用しない
# (テンプレ発言の源になるため)。
EXPERTISE_TONE_PREFIX: dict[str, str] = {
    "beginner": (
        "- 専門用語は避ける。使うときは直後に短い例えを添える\n"
        "- 中学生に説明するつもりで、難しい話も具体的に語る\n"
        "- 中身のない一般論ではなく、イメージできる場面を話す"
    ),
    "intermediate": (
        "- 専門用語 OK。ただし必要なときに丁寧に使う\n"
        "- 研究室の雑談のノリで、論文口調は使わない\n"
        "- 抽象論だけで終わらず、具体の一例や数字を一つは持ち込む"
    ),
    "expert": (
        "- 専門用語 OK。ただし論文口調は使わない\n"
        "- 研究室のホワイトボード前の実際のテンポ。雑に台本レベルの発想も OK\n"
        "- 具体例は短く、本質を突く"
    ),
}


def get_tone_prefix(expertise: str) -> str:
    """expertise キーから tone prefix 文字列を返す。

    Args:
        expertise: ``beginner`` / ``intermediate`` / ``expert``。
            未知キーは ``intermediate`` にフォールバック。

    Returns:
        tone prefix (複数行文字列)。
    """
    return EXPERTISE_TONE_PREFIX.get(
        expertise, EXPERTISE_TONE_PREFIX[DEFAULT_EXPERTISE]
    )


def apply_speaking_rules(
    agent: "Agent",
    expertise: str = DEFAULT_EXPERTISE,
    extra_rules: str = "",
) -> None:
    """Agent の ``speaking_rules`` に tone prefix + extra_rules を注入する。

    Idea Discussion では ``extra_rules`` は空 (tone のみ)。
    Code Review Meeting では ``MEETING_SPEAKING_RULES`` などを渡す。

    Args:
        agent: 対象 ``Agent``。
        expertise: ``beginner`` / ``intermediate`` / ``expert``。
        extra_rules: 機能固有の追加ルール。空文字なら追加しない。
    """
    tone = get_tone_prefix(expertise)
    stripped_extra = extra_rules.strip() if extra_rules else ""
    if stripped_extra:
        combined = f"{tone}\n\n{stripped_extra}"
    else:
        combined = tone
    agent.set_speaking_rules(combined)


__all__ = [
    "DEFAULT_EXPERTISE",
    "EXPERTISE_TONE_PREFIX",
    "get_tone_prefix",
    "apply_speaking_rules",
]
