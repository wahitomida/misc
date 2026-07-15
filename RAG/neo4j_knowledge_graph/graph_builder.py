"""Neo4j へのバッチ MERGE 投入."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional

from neo4j import Driver
from tqdm import tqdm

from .config import BATCH_SIZE
from .models import (
    AppCategoryNode,
    AppealPointNode,
    BoundaryNode,
    ClusterNode,
    DealNode,
    EquipmentNode,
    NGTendencyNode,
    OKTendencyNode,
    ProcessNode,
    RecommendationNode,
    SegmentNode,
    WorkpieceNode,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 共通ユーティリティ
# =============================================================================


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """None 値のキーを除いた dict を返す（Neo4j プロパティが None で埋まらないように）."""
    return {k: v for k, v in d.items() if v is not None}


def _chunked(items: List[Dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[List[Dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _run_batch(
    driver: Driver, database: str, query: str, batch: List[Dict[str, Any]], desc: str
) -> None:
    if not batch:
        logger.info("[%s] 件数 0 のためスキップ", desc)
        return
    start = time.perf_counter()
    total = 0
    with driver.session(database=database) as session:
        for chunk in tqdm(list(_chunked(batch)), desc=desc, leave=False):
            session.execute_write(lambda tx: tx.run(query, batch=chunk))
            total += len(chunk)
    logger.info("[%s] 投入完了: %d 件 (%.2f sec)", desc, total, time.perf_counter() - start)


# =============================================================================
# Phase 1: Segment (旧 Industry)
# =============================================================================


_Q_SEGMENT = """
UNWIND $batch AS row
MERGE (s:Segment {name: row.name})
"""


def upsert_segments(driver: Driver, database: str, nodes: List[SegmentNode]) -> None:
    batch = [{"name": n.name} for n in nodes]
    _run_batch(driver, database, _Q_SEGMENT, batch, "Phase1 Segment")


# =============================================================================
# Phase 2: Cluster + IN_SEGMENT
# =============================================================================


_Q_CLUSTER = """
UNWIND $batch AS row
MERGE (c:Cluster {cluster_id: row.cluster_id})
SET c.cluster_code   = row.cluster_code,
    c.dominant_okng  = row.dominant_okng,
    c.process        = row.process,
    c.equipment      = row.equipment,
    c.workpiece      = row.workpiece,
    c.objective      = row.objective,
    c.challenge      = row.challenge,
    c.current_method = row.current_method,
    c.is_catchall    = row.is_catchall
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET c.data_quality = row.data_quality
)
WITH c, row
MERGE (s:Segment {name: row.segment})
MERGE (c)-[:IN_SEGMENT]->(s)
"""


def upsert_clusters(driver: Driver, database: str, nodes: List[ClusterNode]) -> None:
    batch = [_strip_none(asdict(n)) for n in nodes]
    # 後段の MATCH/MERGE で None になりうるフィールドは空文字に揃える
    for row in batch:
        for key in ("process", "equipment", "workpiece", "objective", "challenge", "current_method"):
            row.setdefault(key, "")
        row.setdefault("is_catchall", False)
    _run_batch(driver, database, _Q_CLUSTER, batch, "Phase2 Cluster")


# =============================================================================
# Phase 2.5: Process / Equipment / Workpiece + Cluster→これら の横断リレーション
#   description は「最初に投入されたものを保持」(ON CREATE SET のみ)
# =============================================================================


_Q_PROCESS = """
UNWIND $batch AS row
MERGE (p:Process {name: row.name})
ON CREATE SET p.description = row.description
"""

_Q_EQUIPMENT = """
UNWIND $batch AS row
MERGE (e:Equipment {name: row.name})
ON CREATE SET e.description = row.description
"""

_Q_WORKPIECE = """
UNWIND $batch AS row
MERGE (w:Workpiece {name: row.name})
ON CREATE SET w.description = row.description
"""

_Q_CLUSTER_HAS_PROCESS = """
UNWIND $batch AS row
MATCH (c:Cluster {cluster_id: row.cluster_id}), (p:Process {name: row.name})
MERGE (c)-[:HAS_PROCESS]->(p)
"""

_Q_CLUSTER_USES_EQUIPMENT = """
UNWIND $batch AS row
MATCH (c:Cluster {cluster_id: row.cluster_id}), (e:Equipment {name: row.name})
MERGE (c)-[:USES_EQUIPMENT]->(e)
"""

_Q_CLUSTER_TARGETS_WORKPIECE = """
UNWIND $batch AS row
MATCH (c:Cluster {cluster_id: row.cluster_id}), (w:Workpiece {name: row.name})
MERGE (c)-[:TARGETS_WORKPIECE]->(w)
"""


def upsert_processes(
    driver: Driver,
    database: str,
    nodes: List[ProcessNode],
    cluster_map: Dict[str, str],
) -> None:
    """Process ノード + Cluster-HAS_PROCESS を投入."""
    node_batch = [{"name": n.name, "description": n.description} for n in nodes]
    _run_batch(driver, database, _Q_PROCESS, node_batch, "Phase2.5 Process")
    rel_batch = [{"cluster_id": cid, "name": name} for cid, name in cluster_map.items()]
    _run_batch(driver, database, _Q_CLUSTER_HAS_PROCESS, rel_batch, "Phase2.5 rel HAS_PROCESS")


def upsert_equipments(
    driver: Driver,
    database: str,
    nodes: List[EquipmentNode],
    cluster_map: Dict[str, str],
) -> None:
    """Equipment ノード + Cluster-USES_EQUIPMENT を投入."""
    node_batch = [{"name": n.name, "description": n.description} for n in nodes]
    _run_batch(driver, database, _Q_EQUIPMENT, node_batch, "Phase2.5 Equipment")
    rel_batch = [{"cluster_id": cid, "name": name} for cid, name in cluster_map.items()]
    _run_batch(driver, database, _Q_CLUSTER_USES_EQUIPMENT, rel_batch, "Phase2.5 rel USES_EQUIPMENT")


def upsert_workpieces(
    driver: Driver,
    database: str,
    nodes: List[WorkpieceNode],
    cluster_map: Dict[str, str],
) -> None:
    """Workpiece ノード + Cluster-TARGETS_WORKPIECE を投入."""
    node_batch = [{"name": n.name, "description": n.description} for n in nodes]
    _run_batch(driver, database, _Q_WORKPIECE, node_batch, "Phase2.5 Workpiece")
    rel_batch = [{"cluster_id": cid, "name": name} for cid, name in cluster_map.items()]
    _run_batch(driver, database, _Q_CLUSTER_TARGETS_WORKPIECE, rel_batch, "Phase2.5 rel TARGETS_WORKPIECE")


# =============================================================================
# Phase 3: AppCategory
# =============================================================================


_Q_APP_CATEGORY = """
UNWIND $batch AS row
MERGE (a:AppCategory {name: row.name})
"""


def upsert_app_categories(driver: Driver, database: str, nodes: List[AppCategoryNode]) -> None:
    batch = [{"name": n.name} for n in nodes]
    _run_batch(driver, database, _Q_APP_CATEGORY, batch, "Phase3 AppCategory")


# =============================================================================
# Phase 4: Deal + BELONGS_TO_CLUSTER + CATEGORIZED_AS
# =============================================================================


_Q_DEAL = """
UNWIND $batch AS row
MERGE (d:Deal {deal_id: row.deal_id})
SET d.content              = row.content,
    d.score                = row.score,
    d.okng                 = row.okng,
    d.okng_confidence      = row.okng_confidence,
    d.okng_reason          = row.okng_reason,
    d.okng_detail_reason   = row.okng_detail_reason,
    d.content_truncated    = row.content_truncated,
    d.in_catchall_cluster  = row.in_catchall_cluster
FOREACH (_ IN CASE WHEN row.content_full IS NULL THEN [] ELSE [1] END |
    SET d.content_full = row.content_full
)
FOREACH (_ IN CASE WHEN row.app_category IS NULL OR row.app_category = '' THEN [] ELSE [1] END |
    MERGE (a:AppCategory {name: row.app_category})
    MERGE (d)-[:CATEGORIZED_AS]->(a)
)
WITH d, row
OPTIONAL MATCH (c:Cluster {cluster_id: row.cluster_id})
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
    MERGE (d)-[:BELONGS_TO_CLUSTER]->(c)
)
"""


def upsert_deals(driver: Driver, database: str, nodes: List[DealNode]) -> None:
    batch: List[Dict[str, Any]] = []
    for d in nodes:
        row = asdict(d)
        row.setdefault("in_catchall_cluster", False)
        batch.append(row)
    _run_batch(driver, database, _Q_DEAL, batch, "Phase4 Deal")


# =============================================================================
# Phase 5: 分析知見ノード + リレーション
# =============================================================================


# OKTendency
_Q_OK_TENDENCY = """
UNWIND $batch AS row
MERGE (o:OKTendency {text_hash: row.text_hash})
ON CREATE SET o.deal_level    = row.deal_level,
              o.segment_level = row.segment_level,
              o.il_level      = row.il_level
ON MATCH SET  o.deal_level    = COALESCE(NULLIF(o.deal_level, ''),    row.deal_level),
              o.segment_level = COALESCE(NULLIF(o.segment_level, ''), row.segment_level),
              o.il_level      = COALESCE(NULLIF(o.il_level, ''),      row.il_level)
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET o.data_quality = row.data_quality
)
"""


_Q_NG_TENDENCY = """
UNWIND $batch AS row
MERGE (n:NGTendency {text_hash: row.text_hash})
ON CREATE SET n.deal_level    = row.deal_level,
              n.segment_level = row.segment_level,
              n.il_level      = row.il_level
ON MATCH SET  n.deal_level    = COALESCE(NULLIF(n.deal_level, ''),    row.deal_level),
              n.segment_level = COALESCE(NULLIF(n.segment_level, ''), row.segment_level),
              n.il_level      = COALESCE(NULLIF(n.il_level, ''),      row.il_level)
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET n.data_quality = row.data_quality
)
"""


_Q_BOUNDARY = """
UNWIND $batch AS row
MERGE (b:Boundary {text_hash: row.text_hash})
ON CREATE SET b.okng_boundary  = row.okng_boundary,
              b.il_boundary    = row.il_boundary,
              b.key_difference = row.key_difference
ON MATCH SET  b.okng_boundary  = COALESCE(NULLIF(b.okng_boundary, ''),  row.okng_boundary),
              b.il_boundary    = COALESCE(NULLIF(b.il_boundary, ''),    row.il_boundary),
              b.key_difference = COALESCE(NULLIF(b.key_difference, ''), row.key_difference)
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET b.data_quality = row.data_quality
)
"""


_Q_APPEAL = """
UNWIND $batch AS row
MERGE (a:AppealPoint {text_hash: row.text_hash})
ON CREATE SET a.deal_level    = row.deal_level,
              a.segment_level = row.segment_level
ON MATCH SET  a.deal_level    = COALESCE(NULLIF(a.deal_level, ''),    row.deal_level),
              a.segment_level = COALESCE(NULLIF(a.segment_level, ''), row.segment_level)
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET a.data_quality = row.data_quality
)
"""


_Q_RECOMMENDATION = """
UNWIND $batch AS row
MERGE (r:Recommendation {text_hash: row.text_hash})
ON CREATE SET r.okng_level         = row.okng_level,
              r.il_level           = row.il_level,
              r.actionable_insight = row.actionable_insight
ON MATCH SET  r.okng_level         = COALESCE(NULLIF(r.okng_level, ''),         row.okng_level),
              r.il_level           = COALESCE(NULLIF(r.il_level, ''),           row.il_level),
              r.actionable_insight = COALESCE(NULLIF(r.actionable_insight, ''), row.actionable_insight)
FOREACH (_ IN CASE WHEN row.data_quality IS NULL THEN [] ELSE [1] END |
    SET r.data_quality = row.data_quality
)
"""


def _upsert_insight_node(driver: Driver, database: str, query: str, dataclass_objs: list, desc: str) -> None:
    batch = [_strip_none(asdict(n)) for n in dataclass_objs]
    _run_batch(driver, database, query, batch, desc)


# Deal -> insight relationships
_Q_DEAL_REL = {
    "HAS_OK_TENDENCY":   "MATCH (d:Deal {deal_id: row.deal_id}), (o:OKTendency {text_hash: row.text_hash}) MERGE (d)-[:HAS_OK_TENDENCY]->(o)",
    "HAS_NG_TENDENCY":   "MATCH (d:Deal {deal_id: row.deal_id}), (n:NGTendency {text_hash: row.text_hash}) MERGE (d)-[:HAS_NG_TENDENCY]->(n)",
    "HAS_BOUNDARY":      "MATCH (d:Deal {deal_id: row.deal_id}), (b:Boundary {text_hash: row.text_hash}) MERGE (d)-[:HAS_BOUNDARY]->(b)",
    "HAS_APPEAL":        "MATCH (d:Deal {deal_id: row.deal_id}), (a:AppealPoint {text_hash: row.text_hash}) MERGE (d)-[:HAS_APPEAL]->(a)",
    "HAS_RECOMMENDATION":"MATCH (d:Deal {deal_id: row.deal_id}), (r:Recommendation {text_hash: row.text_hash}) MERGE (d)-[:HAS_RECOMMENDATION]->(r)",
}


# Cluster -> insight relationships
_Q_CLUSTER_REL = {
    "CLUSTER_OK_TENDENCY":   "MATCH (c:Cluster {cluster_id: row.cluster_id}), (o:OKTendency {text_hash: row.text_hash}) MERGE (c)-[:CLUSTER_OK_TENDENCY]->(o)",
    "CLUSTER_NG_TENDENCY":   "MATCH (c:Cluster {cluster_id: row.cluster_id}), (n:NGTendency {text_hash: row.text_hash}) MERGE (c)-[:CLUSTER_NG_TENDENCY]->(n)",
    "CLUSTER_BOUNDARY":      "MATCH (c:Cluster {cluster_id: row.cluster_id}), (b:Boundary {text_hash: row.text_hash}) MERGE (c)-[:CLUSTER_BOUNDARY]->(b)",
    "CLUSTER_APPEAL":        "MATCH (c:Cluster {cluster_id: row.cluster_id}), (a:AppealPoint {text_hash: row.text_hash}) MERGE (c)-[:CLUSTER_APPEAL]->(a)",
    "CLUSTER_RECOMMENDATION":"MATCH (c:Cluster {cluster_id: row.cluster_id}), (r:Recommendation {text_hash: row.text_hash}) MERGE (c)-[:CLUSTER_RECOMMENDATION]->(r)",
}


# AppCategory -> insight relationships
_Q_APP_REL = {
    "APP_OK_TENDENCY": "MATCH (a:AppCategory {name: row.name}), (o:OKTendency {text_hash: row.text_hash}) MERGE (a)-[:APP_OK_TENDENCY]->(o)",
    "APP_NG_TENDENCY": "MATCH (a:AppCategory {name: row.name}), (n:NGTendency {text_hash: row.text_hash}) MERGE (a)-[:APP_NG_TENDENCY]->(n)",
}


def upsert_insights_and_relations(
    driver: Driver,
    database: str,
    insight_rows: List[Dict[str, Any]],
) -> None:
    """各行から抽出した分析知見ノードと、Deal/Cluster/AppCategory からのリレーションを投入."""

    # 1) ノード重複排除（text_hash 単位）
    ok_map: Dict[str, OKTendencyNode] = {}
    ng_map: Dict[str, NGTendencyNode] = {}
    bd_map: Dict[str, BoundaryNode] = {}
    ap_map: Dict[str, AppealPointNode] = {}
    rc_map: Dict[str, RecommendationNode] = {}

    for r in insight_rows:
        for key, target_map in (
            ("ok_tendency", ok_map),
            ("ng_tendency", ng_map),
            ("boundary", bd_map),
            ("appeal", ap_map),
            ("recommendation", rc_map),
        ):
            obj = r.get(key)
            if obj is None:
                continue
            existing = target_map.get(obj.text_hash)
            if existing is None:
                target_map[obj.text_hash] = obj
            else:
                # 既存に空欄があれば埋める
                for fld in obj.__dataclass_fields__:
                    cur = getattr(existing, fld)
                    new = getattr(obj, fld)
                    if (cur is None or cur == "") and new not in (None, ""):
                        setattr(existing, fld, new)

    # 2) ノード MERGE
    _upsert_insight_node(driver, database, _Q_OK_TENDENCY, list(ok_map.values()), "Phase5 OKTendency")
    _upsert_insight_node(driver, database, _Q_NG_TENDENCY, list(ng_map.values()), "Phase5 NGTendency")
    _upsert_insight_node(driver, database, _Q_BOUNDARY, list(bd_map.values()), "Phase5 Boundary")
    _upsert_insight_node(driver, database, _Q_APPEAL, list(ap_map.values()), "Phase5 AppealPoint")
    _upsert_insight_node(driver, database, _Q_RECOMMENDATION, list(rc_map.values()), "Phase5 Recommendation")

    # 3) Deal -> insight リレーション
    deal_rel_batches: Dict[str, List[Dict[str, Any]]] = {k: [] for k in _Q_DEAL_REL}
    for r in insight_rows:
        deal_id = r["deal_id"]
        for rel_key, attr_key in (
            ("HAS_OK_TENDENCY", "ok_tendency"),
            ("HAS_NG_TENDENCY", "ng_tendency"),
            ("HAS_BOUNDARY", "boundary"),
            ("HAS_APPEAL", "appeal"),
            ("HAS_RECOMMENDATION", "recommendation"),
        ):
            obj = r.get(attr_key)
            if obj is not None:
                deal_rel_batches[rel_key].append({"deal_id": deal_id, "text_hash": obj.text_hash})

    for rel_type, batch in deal_rel_batches.items():
        if batch:
            query = f"UNWIND $batch AS row {_Q_DEAL_REL[rel_type]}"
            _run_batch(driver, database, query, batch, f"Phase5 rel {rel_type}")

    # 4) Cluster -> insight リレーション（同一クラスタ内の同一ハッシュは1本に集約）
    cluster_rel_batches: Dict[str, set] = {k: set() for k in _Q_CLUSTER_REL}
    for r in insight_rows:
        cid = r["cluster_id"]
        for rel_key, attr_key in (
            ("CLUSTER_OK_TENDENCY", "ok_tendency"),
            ("CLUSTER_NG_TENDENCY", "ng_tendency"),
            ("CLUSTER_BOUNDARY", "boundary"),
            ("CLUSTER_APPEAL", "appeal"),
            ("CLUSTER_RECOMMENDATION", "recommendation"),
        ):
            obj = r.get(attr_key)
            if obj is not None:
                cluster_rel_batches[rel_key].add((cid, obj.text_hash))

    for rel_type, pairs in cluster_rel_batches.items():
        batch = [{"cluster_id": cid, "text_hash": h} for cid, h in pairs]
        if batch:
            query = f"UNWIND $batch AS row {_Q_CLUSTER_REL[rel_type]}"
            _run_batch(driver, database, query, batch, f"Phase5 rel {rel_type}")

    # 5) AppCategory -> OK/NG Tendency リレーション
    app_rel_batches: Dict[str, set] = {k: set() for k in _Q_APP_REL}
    for r in insight_rows:
        app = r.get("app_category")
        if not app:
            continue
        for rel_key, attr_key in (
            ("APP_OK_TENDENCY", "ok_tendency"),
            ("APP_NG_TENDENCY", "ng_tendency"),
        ):
            obj = r.get(attr_key)
            if obj is not None:
                app_rel_batches[rel_key].add((app, obj.text_hash))

    for rel_type, pairs in app_rel_batches.items():
        batch = [{"name": name, "text_hash": h} for name, h in pairs]
        if batch:
            query = f"UNWIND $batch AS row {_Q_APP_REL[rel_type]}"
            _run_batch(driver, database, query, batch, f"Phase5 rel {rel_type}")
