"""コンテキスト圧縮レイヤー: トークン予算超過時のみ LLM で要点抽出.

すべての Retriever 共通で main.py から呼び出される.
Ground Truth キーワードは参照しない (評価データへの過学習禁止).
"""
from __future__ import annotations

import logging

from .llm_client import LLMClient
from .token_counter import count_tokens

logger = logging.getLogger(__name__)


COMPRESS_SYSTEM_TEMPLATE = (
    "あなたはコンテキスト圧縮器です.\n"
    "以下の商談テキスト群から、ユーザ質問への回答に必要な情報のみを抽出してください.\n"
    "ルール:\n"
    "  - 各 Deal について 1-3 行の簡潔な要点に圧縮\n"
    "  - 不要な挨拶・日程調整・重複情報を除去\n"
    "  - Deal#ID と OK/NG ラベルは必ず保持\n"
    "  - 数値・固有名詞 (機器名・工程名) は保持\n"
    "  - 合計 {max_chars} 字以内に収める\n"
    "出力: 圧縮済みコンテキスト本文のみ (前置きや説明なし)"
)


class ContextCompressor:
    """トークン予算ベースの動的圧縮器."""

    def __init__(self, llm: LLMClient, max_chars: int = 3000):
        self.llm = llm
        self.max_chars = max_chars

    def compress(
        self,
        query: str,
        contexts: list[str],
        threshold_tokens: int,
    ) -> tuple[list[str], dict]:
        """threshold_tokens を超える場合のみ圧縮.

        Returns
        -------
        (compressed_contexts, info)
            info: {"applied": bool, "before_tokens": int, "after_tokens": int,
                   "before_count": int, "after_count": int,
                   "llm_input_tokens": int, "llm_output_tokens": int}
        """
        before_tokens = sum(count_tokens(c) for c in contexts)
        info: dict = {
            "applied": False,
            "before_tokens": before_tokens,
            "after_tokens": before_tokens,
            "before_count": len(contexts),
            "after_count": len(contexts),
            "llm_input_tokens": 0,
            "llm_output_tokens": 0,
        }
        if before_tokens <= threshold_tokens or not contexts:
            return contexts, info

        # LLM への入力長も上限を切る (gpt-4o context window 配慮)
        joined = "\n\n".join(contexts)
        if len(joined) > 12000:
            joined = joined[:12000]

        try:
            result = self.llm.chat(
                COMPRESS_SYSTEM_TEMPLATE.format(max_chars=self.max_chars),
                f"質問: {query}\n\n以下を圧縮:\n{joined}",
                temperature=0.1,
                max_tokens=max(512, self.max_chars),
            )
            compressed_text = result.text.strip()
            after_tokens = count_tokens(compressed_text)
            info.update({
                "applied": True,
                "after_tokens": after_tokens,
                "after_count": 1,
                "llm_input_tokens": result.input_tokens,
                "llm_output_tokens": result.output_tokens,
            })
            return [compressed_text], info
        except Exception as e:  # noqa: BLE001
            logger.warning("context 圧縮失敗 (元のまま返却): %s", e)
            return contexts, info
