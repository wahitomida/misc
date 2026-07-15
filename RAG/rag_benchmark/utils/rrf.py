"""Reciprocal Rank Fusion."""
from __future__ import annotations

from collections import defaultdict


def reciprocal_rank_fusion(
    rankings: list[list],
    k: int = 60,
) -> list[tuple[object, float]]:
    """複数ランキングを RRF で統合.

    Parameters
    ----------
    rankings : list[list]
        各要素は順位順に並んだ ID のリスト.
    k : int
        RRF 定数. 一般に 60.

    Returns
    -------
    list[tuple[id, rrf_score]] : RRF スコア降順
    """
    scores: dict[object, float] = defaultdict(float)
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
