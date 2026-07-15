"""CSV 読み込み・正規化・各種ノード dataclass への変換."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from .cluster_parser import ClusterInfo, is_catchall_cluster, parse_cluster_id
from .config import COLUMN_MAP
from .deduplication import (
    composite_hash,
    is_blank,
    is_insufficient_data,
    normalize_text,
    truncate_for_property,
)
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
from .text_normalizer import extract_short_name

logger = logging.getLogger(__name__)


# =============================================================================
# CSV 読み込み
# =============================================================================


def resolve_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """COLUMN_MAP に従い、論理名 -> 実 CSV カラム名 を解決する.

    論理名に対応する CSV カラムが見つからない場合は None を入れる。
    """
    resolved: Dict[str, Optional[str]] = {}
    for logical, candidates in COLUMN_MAP.items():
        match = next((c for c in candidates if c in df.columns), None)
        resolved[logical] = match
    return resolved


def load_csv(csv_path: Path) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    """CSV を `utf-8-sig` 優先で読み込み、カラム解決マップとともに返す."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    last_err: Optional[Exception] = None
    df: Optional[pd.DataFrame] = None
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            df = pd.read_csv(csv_path, encoding=enc, dtype=str)
            logger.info("CSV 読込: enc=%s rows=%d cols=%d", enc, len(df), len(df.columns))
            break
        except UnicodeDecodeError as e:
            last_err = e
            continue
    if df is None:
        raise RuntimeError(f"CSV のエンコーディングを判定できませんでした: {csv_path}") from last_err

    resolved = resolve_columns(df)
    missing_required = [
        k for k in ("deal_id", "content", "cluster_id", "okng")
        if resolved.get(k) is None
    ]
    if missing_required:
        raise ValueError(
            f"必須カラムが見つかりません（論理名）: {missing_required}\n"
            f"検出済みマップ: {resolved}"
        )
    return df, resolved


def get(row: pd.Series, resolved: Dict[str, Optional[str]], logical: str) -> str:
    col = resolved.get(logical)
    if not col:
        return ""
    return normalize_text(row.get(col))


def get_optional_float(row: pd.Series, resolved: Dict[str, Optional[str]], logical: str) -> Optional[float]:
    raw = get(row, resolved, logical)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def get_int(row: pd.Series, resolved: Dict[str, Optional[str]], logical: str) -> Optional[int]:
    raw = get(row, resolved, logical)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


# =============================================================================
# Deal / Cluster などのノード抽出
# =============================================================================


def build_deal_nodes(
    df: pd.DataFrame,
    resolved: Dict[str, Optional[str]],
    catchall_cluster_ids: Optional[Set[str]] = None,
) -> List[DealNode]:
    catchall_set: Set[str] = catchall_cluster_ids or set()
    deals: List[DealNode] = []
    skipped = 0
    for _, row in df.iterrows():
        deal_id = get_int(row, resolved, "deal_id")
        cluster_id = get(row, resolved, "cluster_id")
        if deal_id is None or not cluster_id:
            skipped += 1
            continue

        content_raw = get(row, resolved, "content")
        content, content_full, truncated = truncate_for_property(content_raw)

        okng = get(row, resolved, "okng").upper() or "NG"
        if okng not in ("OK", "NG"):
            okng = "NG"

        # detail_reason は ok_reason / ng_reason のうち空でない方を採用
        detail = get(row, resolved, "okng_detail_reason")
        if not detail:
            ok_col = resolved.get("okng_detail_reason")  # 既に解決済みの先頭候補
            for cand in ("deal_ok_reason", "deal_ng_reason"):
                if cand in df.columns:
                    val = normalize_text(row.get(cand))
                    if val:
                        detail = val
                        break

        deals.append(
            DealNode(
                deal_id=int(deal_id),
                cluster_id=cluster_id,
                app_category=get(row, resolved, "app_sort") or None,
                content=content,
                content_full=content_full,
                content_truncated=truncated,
                score=get_optional_float(row, resolved, "score"),
                okng=okng,
                okng_confidence=get(row, resolved, "okng_confidence") or "low",
                okng_reason=get(row, resolved, "okng_reason"),
                okng_detail_reason=detail,
                in_catchall_cluster=cluster_id in catchall_set,
            )
        )
    if skipped:
        logger.warning("Deal 構築でスキップ: %d 件 (deal_id か cluster_id が欠損)", skipped)
    return deals


def build_cluster_nodes(
    df: pd.DataFrame, resolved: Dict[str, Optional[str]]
) -> List[ClusterNode]:
    """同一 cluster_id は同一値のため `groupby('cluster_id').first()` で集約.

    同時に deal 件数に基づいて is_catchall フラグも計算する.
    """
    cluster_col = resolved["cluster_id"]
    if not cluster_col:
        return []

    sub = df[df[cluster_col].notna() & (df[cluster_col].astype(str).str.strip() != "")]
    if sub.empty:
        return []

    # クラスタごとの Deal 件数 / 全体件数 を事前集計 (catchall 判定に使う)
    cluster_counts: Dict[str, int] = sub[cluster_col].astype(str).value_counts().to_dict()
    total_deals = int(sub.shape[0])

    grouped = sub.groupby(cluster_col, sort=False).first().reset_index()
    nodes: List[ClusterNode] = []
    parse_failed = 0
    for _, row in grouped.iterrows():
        cid = normalize_text(row[cluster_col])
        if not cid:
            continue
        try:
            info = parse_cluster_id(cid)
        except ValueError as e:
            parse_failed += 1
            logger.warning("cluster_id パース失敗: %s (%s)", cid, e)
            continue

        process = get(row, resolved, "cluster_process")
        equipment = get(row, resolved, "cluster_equipment")
        workpiece = get(row, resolved, "cluster_workpiece")
        objective = get(row, resolved, "cluster_objective")
        challenge = get(row, resolved, "cluster_challenge")
        current_method = get(row, resolved, "cluster_current_method")

        # データ品質: 全プロパティが空 or 不足テキストならフラグ
        all_text = " ".join(
            [process, equipment, workpiece, objective, challenge, current_method]
        ).strip()
        data_quality = None
        if not all_text or is_insufficient_data(all_text):
            data_quality = "insufficient"

        deal_count = int(cluster_counts.get(cid, 0))
        catchall = is_catchall_cluster(info, deal_count, total_deals)

        nodes.append(
            ClusterNode(
                cluster_id=info.raw_id,
                cluster_code=info.cluster_code,
                segment=info.segment,
                dominant_okng=info.dominant_okng,
                process=process,
                equipment=equipment,
                workpiece=workpiece,
                objective=objective,
                challenge=challenge,
                current_method=current_method,
                is_catchall=catchall,
                data_quality=data_quality,
            )
        )
    if parse_failed:
        logger.warning("cluster_id パース失敗合計: %d 件", parse_failed)
    return nodes


def build_segment_nodes(clusters: Iterable[ClusterNode]) -> List[SegmentNode]:
    seen = set()
    nodes: List[SegmentNode] = []
    for c in clusters:
        if c.segment and c.segment not in seen:
            seen.add(c.segment)
            nodes.append(SegmentNode(name=c.segment))
    return nodes


def get_catchall_cluster_ids(clusters: Iterable[ClusterNode]) -> Set[str]:
    return {c.cluster_id for c in clusters if c.is_catchall}


def build_app_category_nodes(deals: Iterable[DealNode]) -> List[AppCategoryNode]:
    seen = set()
    nodes: List[AppCategoryNode] = []
    for d in deals:
        name = (d.app_category or "").strip()
        if name and name not in seen:
            seen.add(name)
            nodes.append(AppCategoryNode(name=name))
    return nodes


# =============================================================================
# 横断検索軸: Process / Equipment / Workpiece ノードの抽出
#   Cluster の cluster_process / cluster_equipment / cluster_workpiece を
#   `text_normalizer.extract_short_name` で短縮し、共通ノードとして外出しする.
#   各 Cluster → 各短縮名 の対応も同時に返す.
# =============================================================================


def _build_named_nodes(
    clusters: Iterable[ClusterNode],
    field: str,
    node_cls,
) -> Tuple[List, Dict[str, str]]:
    """clusters から (ノードリスト, cluster_id -> short_name マップ) を返す."""
    name_to_desc: Dict[str, str] = {}
    cluster_map: Dict[str, str] = {}
    for c in clusters:
        raw = getattr(c, field) or ""
        short = extract_short_name(raw)
        if short == "不明":
            continue
        cluster_map[c.cluster_id] = short
        if short not in name_to_desc:
            # 元の長文 (truncate 済み) を description として最初に投入されたものを保持
            name_to_desc[short] = raw[:1000] if raw else ""
    nodes = [node_cls(name=n, description=d) for n, d in name_to_desc.items()]
    return nodes, cluster_map


def build_process_nodes(
    clusters: Iterable[ClusterNode],
) -> Tuple[List[ProcessNode], Dict[str, str]]:
    """(ProcessNode リスト, cluster_id -> process 短縮名 マップ) を返す."""
    return _build_named_nodes(clusters, "process", ProcessNode)


def build_equipment_nodes(
    clusters: Iterable[ClusterNode],
) -> Tuple[List[EquipmentNode], Dict[str, str]]:
    """(EquipmentNode リスト, cluster_id -> equipment 短縮名 マップ) を返す."""
    return _build_named_nodes(clusters, "equipment", EquipmentNode)


def build_workpiece_nodes(
    clusters: Iterable[ClusterNode],
) -> Tuple[List[WorkpieceNode], Dict[str, str]]:
    """(WorkpieceNode リスト, cluster_id -> workpiece 短縮名 マップ) を返す."""
    return _build_named_nodes(clusters, "workpiece", WorkpieceNode)


# =============================================================================
# 分析知見ノードの抽出
#   ※ 各ノードは「テキスト集合」をキーにハッシュ化し、Deal / Cluster / AppCategory
#     から MERGE 可能にする。同じハッシュでも各 source からの呼出時にプロパティを
#     上書き埋めできるよう、ここでは Deal / Cluster / AppCategory ごとに別々に
#     エクスポートする（重複ハッシュは graph_builder 側で MERGE 集約）。
# =============================================================================


def _make_ok_tendency(deal_level: str, segment_level: str, il_level: str) -> Optional[OKTendencyNode]:
    if not any([deal_level, segment_level, il_level]):
        return None
    h = composite_hash(deal_level, segment_level, il_level)
    insufficient = all(
        not t or is_insufficient_data(t)
        for t in (deal_level, segment_level, il_level)
        if t
    ) and any([deal_level, segment_level, il_level])
    return OKTendencyNode(
        text_hash=h,
        deal_level=deal_level,
        segment_level=segment_level,
        il_level=il_level,
        data_quality="insufficient" if insufficient else None,
    )


def _make_ng_tendency(deal_level: str, segment_level: str, il_level: str) -> Optional[NGTendencyNode]:
    if not any([deal_level, segment_level, il_level]):
        return None
    h = composite_hash(deal_level, segment_level, il_level)
    insufficient = all(
        not t or is_insufficient_data(t)
        for t in (deal_level, segment_level, il_level)
        if t
    ) and any([deal_level, segment_level, il_level])
    return NGTendencyNode(
        text_hash=h,
        deal_level=deal_level,
        segment_level=segment_level,
        il_level=il_level,
        data_quality="insufficient" if insufficient else None,
    )


def _make_boundary(okng: str, il: str, key_diff: str) -> Optional[BoundaryNode]:
    if not any([okng, il, key_diff]):
        return None
    h = composite_hash(okng, il, key_diff)
    insufficient = all(
        not t or is_insufficient_data(t)
        for t in (okng, il, key_diff)
        if t
    ) and any([okng, il, key_diff])
    return BoundaryNode(
        text_hash=h,
        okng_boundary=okng,
        il_boundary=il,
        key_difference=key_diff,
        data_quality="insufficient" if insufficient else None,
    )


def _make_appeal(deal_level: str, segment_level: str) -> Optional[AppealPointNode]:
    if not any([deal_level, segment_level]):
        return None
    h = composite_hash(deal_level, segment_level)
    insufficient = all(
        not t or is_insufficient_data(t) for t in (deal_level, segment_level) if t
    ) and any([deal_level, segment_level])
    return AppealPointNode(
        text_hash=h,
        deal_level=deal_level,
        segment_level=segment_level,
        data_quality="insufficient" if insufficient else None,
    )


def _make_recommendation(okng_level: str, il_level: str, actionable: str) -> Optional[RecommendationNode]:
    if not any([okng_level, il_level, actionable]):
        return None
    h = composite_hash(okng_level, il_level, actionable)
    insufficient = all(
        not t or is_insufficient_data(t)
        for t in (okng_level, il_level, actionable)
        if t
    ) and any([okng_level, il_level, actionable])
    return RecommendationNode(
        text_hash=h,
        okng_level=okng_level,
        il_level=il_level,
        actionable_insight=actionable,
        data_quality="insufficient" if insufficient else None,
    )


def build_insight_nodes_per_row(
    df: pd.DataFrame, resolved: Dict[str, Optional[str]]
) -> List[Dict[str, object]]:
    """各行から Deal / Cluster / AppCategory に紐づく分析知見を抽出.

    Returns list of dicts with keys:
        deal_id, cluster_id, app_category,
        ok_tendency, ng_tendency, boundary, appeal, recommendation
    （各値は dataclass or None）
    """
    rows: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        deal_id = get_int(row, resolved, "deal_id")
        cluster_id = get(row, resolved, "cluster_id")
        if deal_id is None or not cluster_id:
            continue
        app_cat = get(row, resolved, "app_sort") or None

        ok_tendency = _make_ok_tendency(
            get(row, resolved, "okng_ok_tendency"),
            get(row, resolved, "analysis_segment_ok_tendency"),
            get(row, resolved, "analysis_il_ok_tendency"),
        )
        ng_tendency = _make_ng_tendency(
            get(row, resolved, "okng_ng_tendency"),
            get(row, resolved, "analysis_segment_ng_tendency"),
            get(row, resolved, "analysis_il_ng_tendency"),
        )
        boundary = _make_boundary(
            get(row, resolved, "okng_boundary"),
            get(row, resolved, "analysis_il_boundary"),
            get(row, resolved, "analysis_segment_key_difference"),
        )
        appeal = _make_appeal(
            get(row, resolved, "okng_appeal_point"),
            get(row, resolved, "analysis_segment_appeal_point"),
        )
        recommendation = _make_recommendation(
            get(row, resolved, "okng_recommendation"),
            get(row, resolved, "analysis_il_recommendation"),
            get(row, resolved, "analysis_segment_actionable_insight"),
        )

        rows.append(
            {
                "deal_id": int(deal_id),
                "cluster_id": cluster_id,
                "app_category": app_cat,
                "ok_tendency": ok_tendency,
                "ng_tendency": ng_tendency,
                "boundary": boundary,
                "appeal": appeal,
                "recommendation": recommendation,
            }
        )
    return rows
