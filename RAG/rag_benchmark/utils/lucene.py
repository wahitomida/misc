"""Lucene クエリ用エスケープ. 全 Retriever で共用."""
from __future__ import annotations

# Lucene の予約文字 (含 /)
# https://lucene.apache.org/core/2_9_4/queryparsersyntax.html#Escaping%20Special%20Characters
_LUCENE_SPECIAL = '+-&|!(){}[]^"~*?:\\/'


def sanitize_lucene(text: str) -> str:
    """Lucene 予約文字を空白に置換し、空白で分割した語を OR 結合風 (空白区切り) で返す.

    キーワードが空になる場合は元テキストをそのまま返す.

    >>> sanitize_lucene('EtherNet/IP通信')
    'EtherNet IP通信'
    >>> sanitize_lucene('ZP-L*')
    'ZP L'
    """
    if not text:
        return ""
    cleaned = "".join(" " if c in _LUCENE_SPECIAL else c for c in text)
    terms = [t for t in cleaned.split() if t and len(t) > 1]
    return " ".join(terms) or text
