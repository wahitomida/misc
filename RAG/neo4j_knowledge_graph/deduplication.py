"""テキスト正規化・ハッシュ化・データ品質判定."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Optional

from .config import (
    INSUFFICIENT_DATA_PATTERNS,
    MAX_PROPERTY_LENGTH,
    TRUNCATE_HEAD_LENGTH,
)


_INSUFFICIENT_RE = re.compile("|".join(INSUFFICIENT_DATA_PATTERNS), re.IGNORECASE)


def normalize_text(value: Any) -> str:
    """NaN / None / "nan" 等を空文字に揃え、前後空白を除去する."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none", "nat", "null"):
        return ""
    return s


def is_blank(value: Any) -> bool:
    return normalize_text(value) == ""


def is_insufficient_data(text: str) -> bool:
    """『データが不足』系の定型句かを判定."""
    if not text:
        return False
    return bool(_INSUFFICIENT_RE.search(text))


def compute_text_hash(text: str) -> str:
    """テキストの SHA256 を 16 桁で返す（ノードの一意キー用）."""
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def composite_hash(*parts: str) -> str:
    """複数フィールドを組み合わせたハッシュ（OKTendency など複数 level 持ちノード用）."""
    joined = "\u0001".join(p.strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def truncate_for_property(text: str) -> tuple[str, Optional[str], bool]:
    """5000 文字を超える場合に先頭 3000 文字に切り詰める.

    Returns:
        (content, content_full, truncated)
            content      : Neo4j に格納する短縮版
            content_full : 切り詰めた場合のみ元テキスト、それ以外は None
            truncated    : 切り詰めたかどうかのフラグ
    """
    if len(text) <= MAX_PROPERTY_LENGTH:
        return text, None, False
    return text[:TRUNCATE_HEAD_LENGTH], text, True
