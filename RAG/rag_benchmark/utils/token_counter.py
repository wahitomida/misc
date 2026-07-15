"""tiktoken を用いたトークン数カウント. 失敗時は文字数 ÷ 2 で近似."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    _ENC = None
    logger.warning("tiktoken が使えないため文字数ベースの近似に切替")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:  # noqa: BLE001
            pass
    # 日本語混じりの簡易近似 (1 token ≈ 0.5 文字 〜 1 文字)
    return max(1, len(text) // 2)


def pack_contexts_within_budget(
    contexts: list[str],
    max_tokens: int,
    separator: str = "\n\n---\n\n",
) -> tuple[list[str], int]:
    """トークン上限内で先頭から詰める. (採用 contexts, 合計トークン) を返す."""
    sep_tokens = count_tokens(separator)
    selected: list[str] = []
    total = 0
    for ctx in contexts:
        t = count_tokens(ctx)
        extra = t + (sep_tokens if selected else 0)
        if total + extra > max_tokens:
            break
        selected.append(ctx)
        total += extra
    return selected, total
