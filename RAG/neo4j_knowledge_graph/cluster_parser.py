"""cluster_id のパースと catchall 判定."""
from __future__ import annotations

from dataclasses import dataclass

from .config import CATCHALL_SEGMENT_NAMES, CATCHALL_THRESHOLD_RATIO


@dataclass(frozen=True)
class ClusterInfo:
    raw_id: str
    segment: str
    dominant_okng: str
    cluster_code: str


def parse_cluster_id(cluster_id: str) -> ClusterInfo:
    """`segment__OKNG__cNNN` 形式をパースする.

    実データでは第1セグメントに application 名相当（例: '部品の高さ測定'）が
    入るため、これをスキーマ上は Segment ノードとしてモデル化する.

    >>> parse_cluster_id('unknown__NG__c2845')
    ClusterInfo(raw_id='unknown__NG__c2845', segment='unknown', dominant_okng='NG', cluster_code='c2845')
    >>> parse_cluster_id('部品の高さ測定__OK__c3')
    ClusterInfo(raw_id='部品の高さ測定__OK__c3', segment='部品の高さ測定', dominant_okng='OK', cluster_code='c3')
    """
    if not cluster_id:
        raise ValueError("cluster_id is empty")
    parts = cluster_id.split("__")
    if len(parts) != 3:
        raise ValueError(f"Invalid cluster_id format: {cluster_id!r}")
    segment, okng, code = parts
    okng_norm = okng.strip().upper()
    if okng_norm not in ("OK", "NG"):
        # 期待しない値でも raise は避けて素直に格納（後段の整合性チェックで検出）
        okng_norm = okng.strip()
    return ClusterInfo(
        raw_id=cluster_id,
        segment=segment.strip() or "unknown",
        dominant_okng=okng_norm or "NG",
        cluster_code=code.strip(),
    )


def is_catchall_cluster(
    cluster_info: ClusterInfo,
    deal_count_in_cluster: int,
    total_deals: int,
) -> bool:
    """このクラスタが「分類不能の受け皿」かを判定する.

    以下のいずれかを満たせば True:
      1. segment (第1セグメント) が CATCHALL_SEGMENT_NAMES (例: 'unknown', '無し') に含まれる
      2. cluster 内 Deal 件数が全体の CATCHALL_THRESHOLD_RATIO (例: 10%) を超える
    """
    if cluster_info.segment in CATCHALL_SEGMENT_NAMES:
        return True
    if total_deals > 0 and deal_count_in_cluster / total_deals > CATCHALL_THRESHOLD_RATIO:
        return True
    return False
