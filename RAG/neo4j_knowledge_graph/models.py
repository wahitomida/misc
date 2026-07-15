"""ノード・リレーションの dataclass 定義."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# 構造ノード
# =============================================================================


@dataclass(frozen=True)
class SegmentNode:
    """旧 IndustryNode. cluster_id の第1セグメント (セグメント/トピック)."""
    name: str


@dataclass(frozen=True)
class AppCategoryNode:
    name: str


@dataclass(frozen=True)
class ProcessNode:
    """工程ノード (Cluster 外せされた cluster_process)."""
    name: str
    description: str = ""


@dataclass(frozen=True)
class EquipmentNode:
    """設備/機器ノード (Cluster 外せされた cluster_equipment)."""
    name: str
    description: str = ""


@dataclass(frozen=True)
class WorkpieceNode:
    """ワークノード (Cluster 外せされた cluster_workpiece)."""
    name: str
    description: str = ""


@dataclass
class ClusterNode:
    cluster_id: str
    cluster_code: str
    segment: str          # IN_SEGMENT 用 (旧 industry)
    dominant_okng: str
    process: str = ""
    equipment: str = ""
    workpiece: str = ""
    objective: str = ""
    challenge: str = ""
    current_method: str = ""
    is_catchall: bool = False
    data_quality: Optional[str] = None  # "insufficient" など


@dataclass
class DealNode:
    deal_id: int
    cluster_id: str               # BELONGS_TO_CLUSTER 用
    app_category: Optional[str]   # CATEGORIZED_AS 用
    content: str
    content_full: Optional[str]
    content_truncated: bool
    score: Optional[float]
    okng: str
    okng_confidence: str
    okng_reason: str
    okng_detail_reason: str
    in_catchall_cluster: bool = False


# =============================================================================
# 分析知見ノード
# =============================================================================


@dataclass
class OKTendencyNode:
    text_hash: str
    deal_level: str = ""
    segment_level: str = ""
    il_level: str = ""
    data_quality: Optional[str] = None


@dataclass
class NGTendencyNode:
    text_hash: str
    deal_level: str = ""
    segment_level: str = ""
    il_level: str = ""
    data_quality: Optional[str] = None


@dataclass
class BoundaryNode:
    text_hash: str
    okng_boundary: str = ""
    il_boundary: str = ""
    key_difference: str = ""
    data_quality: Optional[str] = None


@dataclass
class AppealPointNode:
    text_hash: str
    deal_level: str = ""
    segment_level: str = ""
    data_quality: Optional[str] = None


@dataclass
class RecommendationNode:
    text_hash: str
    okng_level: str = ""
    il_level: str = ""
    actionable_insight: str = ""
    data_quality: Optional[str] = None
