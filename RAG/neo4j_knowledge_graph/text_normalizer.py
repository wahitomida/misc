"""長文テキストから代表的な短縮名を抽出.

Cluster の cluster_process / cluster_equipment / cluster_workpiece は
長文の説明文になっているため、そのままではノードの一意キーとして使えない。
本モジュールは「代表的な短縮名」を検出してノード名にする.
"""
from __future__ import annotations

import math
import re
from typing import Any


_BLANK_VALUES = {"", "nan", "none", "null", "nat"}

# 句点・セミコロン・改行で分割 (最初の一文を掴むため)
# ※ ピリオド (.) は小数点で誤動作するため含めない
_SENTENCE_SPLIT_RE = re.compile(r"[。．\n\r;；]+")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value).strip()
    if s.lower() in _BLANK_VALUES:
        return ""
    return s


def extract_short_name(long_text: Any, max_length: int = 50) -> str:
    """長文テキストから代表的な短縮名を抽出する.

    ルール:
      1. テキストが max_length 以下ならそのまま返す
      2. それを超えた場合:
         a. 句点 (、。、セミコロン、改行等) で分割し、最初の文を取る
         b. 最初の文も max_length 超なら先頭 max_length 文字 + 「...」
      3. 空文字 / NaN の場合は "不明" を返す

    >>> extract_short_name("ロボットハンドの位置決め")
    'ロボットハンドの位置決め'
    >>> extract_short_name("コンベアライン上でワークを搬送する。長い説明が続く。", max_length=30)
    'コンベアライン上でワークを搬送する'
    >>> extract_short_name("")
    '不明'
    >>> extract_short_name(None)
    '不明'
    """
    text = _to_text(long_text)
    if not text:
        return "不明"
    if len(text) <= max_length:
        return text

    # 最初の文だけ取り出す
    first = next((p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()), "")
    if first and len(first) <= max_length:
        return first

    return text[:max_length] + "..."
