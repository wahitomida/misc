"""投入後グラフの整合性チェック + 統計画像生成."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from neo4j import Driver

from .config import NODE_COLORS, NODE_LABELS, RELATIONSHIP_TYPES

logger = logging.getLogger(__name__)


# =============================================================================
# 検証クエリ
# =============================================================================


_VALIDATION_QUERIES: Dict[str, str] = {
    "orphan_deals": "MATCH (d:Deal) WHERE NOT (d)-[:BELONGS_TO_CLUSTER]->(:Cluster) RETURN count(d) AS c",
    "orphan_clusters": "MATCH (c:Cluster) WHERE NOT (c)-[:IN_SEGMENT]->(:Segment) RETURN count(c) AS c",
    "deals_without_category": (
        "MATCH (d:Deal) "
        "WHERE d.okng IS NOT NULL "
        "  AND NOT (d)-[:CATEGORIZED_AS]->(:AppCategory) "
        "RETURN count(d) AS c"
    ),
    "node_count_total": "MATCH (n) RETURN count(n) AS c",
    "rel_count_total": "MATCH ()-[r]->() RETURN count(r) AS c",
    # 新規 (横断検索軸の網羅性チェック)
    "clusters_without_process": (
        "MATCH (c:Cluster) WHERE NOT (c)-[:HAS_PROCESS]->(:Process) RETURN count(c) AS c"
    ),
    "clusters_without_equipment": (
        "MATCH (c:Cluster) WHERE NOT (c)-[:USES_EQUIPMENT]->(:Equipment) RETURN count(c) AS c"
    ),
    "clusters_without_workpiece": (
        "MATCH (c:Cluster) WHERE NOT (c)-[:TARGETS_WORKPIECE]->(:Workpiece) RETURN count(c) AS c"
    ),
    # 新規 (catchall フラグ整合性: cluster.is_catchall と deal.in_catchall_cluster が食い違わないか)
    "inconsistent_catchall_flags": (
        "MATCH (d:Deal)-[:BELONGS_TO_CLUSTER]->(c:Cluster) "
        "WHERE coalesce(d.in_catchall_cluster, false) <> coalesce(c.is_catchall, false) "
        "RETURN count(d) AS c"
    ),
    # 新規 (Embedding 投入状況)
    "deals_with_embedding": "MATCH (d:Deal) WHERE d.embedding IS NOT NULL RETURN count(d) AS c",
    "deals_without_embedding": "MATCH (d:Deal) WHERE d.embedding IS NULL RETURN count(d) AS c",
}


# 横断共有上位 (catchall 以外の cluster で同じ Equipment を共有している top10)
_TOP_SHARED_EQUIPMENT_QUERY = """
MATCH (e:Equipment)<-[:USES_EQUIPMENT]-(c:Cluster)
WHERE coalesce(c.is_catchall, false) = false
WITH e.name AS equipment, count(DISTINCT c) AS cluster_count
WHERE cluster_count > 1
RETURN equipment, cluster_count
ORDER BY cluster_count DESC
LIMIT 10
"""


@dataclass
class ValidationResult:
    node_counts: Dict[str, int]
    rel_counts: Dict[str, int]
    orphan_deals: int
    orphan_clusters: int
    deals_without_category: int
    insufficient_quality_counts: Dict[str, int]
    cluster_deal_distribution: List[Dict[str, Any]]
    # 新規フィールド
    clusters_without_process: int = 0
    clusters_without_equipment: int = 0
    clusters_without_workpiece: int = 0
    inconsistent_catchall_flags: int = 0
    deals_with_embedding: int = 0
    deals_without_embedding: int = 0
    catchall_cluster_count: int = 0
    catchall_deal_count: int = 0
    top_shared_equipment: List[Dict[str, Any]] = None  # type: ignore[assignment]


def run_validation(driver: Driver, database: str) -> ValidationResult:
    with driver.session(database=database) as session:
        # ── 各ノードラベル件数 ──
        node_counts: Dict[str, int] = {}
        for label in NODE_LABELS:
            rec = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
            node_counts[label] = rec["c"] if rec else 0

        # ── 各リレーション件数 ──
        rel_counts: Dict[str, int] = {}
        for rt in RELATIONSHIP_TYPES:
            rec = session.run(f"MATCH ()-[r:{rt}]->() RETURN count(r) AS c").single()
            rel_counts[rt] = rec["c"] if rec else 0

        def _scalar(key: str) -> int:
            rec = session.run(_VALIDATION_QUERIES[key]).single()
            return int(rec["c"]) if rec else 0

        orphan_d = _scalar("orphan_deals")
        orphan_c = _scalar("orphan_clusters")
        no_cat = _scalar("deals_without_category")
        no_proc = _scalar("clusters_without_process")
        no_equip = _scalar("clusters_without_equipment")
        no_work = _scalar("clusters_without_workpiece")
        inconsistent = _scalar("inconsistent_catchall_flags")
        with_emb = _scalar("deals_with_embedding")
        without_emb = _scalar("deals_without_embedding")

        # ── catchall 統計 ──
        rec_catchall_c = session.run(
            "MATCH (c:Cluster) WHERE c.is_catchall = true RETURN count(c) AS c"
        ).single()
        catchall_cluster_count = int(rec_catchall_c["c"]) if rec_catchall_c else 0
        rec_catchall_d = session.run(
            "MATCH (d:Deal) WHERE d.in_catchall_cluster = true RETURN count(d) AS c"
        ).single()
        catchall_deal_count = int(rec_catchall_d["c"]) if rec_catchall_d else 0

        # ── 横断共有 top10 ──
        rows_equip = session.run(_TOP_SHARED_EQUIPMENT_QUERY)
        top_shared_equip = [
            {"equipment": r["equipment"], "cluster_count": int(r["cluster_count"])}
            for r in rows_equip
        ]

        # ── データ品質フラグ ──
        insufficient: Dict[str, int] = {}
        for label in NODE_LABELS:
            rec = session.run(
                f"MATCH (n:{label}) WHERE n.data_quality = 'insufficient' RETURN count(n) AS c"
            ).single()
            cnt = rec["c"] if rec else 0
            if cnt:
                insufficient[label] = cnt

        # ── クラスタ別 Deal 件数分布（上位 20） ──
        rows = session.run(
            "MATCH (c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
            "RETURN c.cluster_id AS cluster_id, c.dominant_okng AS dominant_okng, "
            "       c.is_catchall AS is_catchall, count(d) AS deal_count "
            "ORDER BY deal_count DESC LIMIT 20"
        )
        distribution = [
            {
                "cluster_id": r["cluster_id"],
                "dominant_okng": r["dominant_okng"],
                "is_catchall": bool(r["is_catchall"]),
                "deal_count": r["deal_count"],
            }
            for r in rows
        ]

    return ValidationResult(
        node_counts=node_counts,
        rel_counts=rel_counts,
        orphan_deals=orphan_d,
        orphan_clusters=orphan_c,
        deals_without_category=no_cat,
        insufficient_quality_counts=insufficient,
        cluster_deal_distribution=distribution,
        clusters_without_process=no_proc,
        clusters_without_equipment=no_equip,
        clusters_without_workpiece=no_work,
        inconsistent_catchall_flags=inconsistent,
        deals_with_embedding=with_emb,
        deals_without_embedding=without_emb,
        catchall_cluster_count=catchall_cluster_count,
        catchall_deal_count=catchall_deal_count,
        top_shared_equipment=top_shared_equip,
    )


# =============================================================================
# 統計可視化
# =============================================================================


def _setup_japanese_font() -> None:
    """matplotlib で日本語が文字化けしないようフォントを設定."""
    import matplotlib

    candidates = [
        "Yu Gothic", "Yu Gothic UI", "Meiryo", "MS Gothic",
        "Noto Sans CJK JP", "Hiragino Sans", "IPAexGothic",
    ]
    for name in candidates:
        try:
            matplotlib.rcParams["font.family"] = name
            return
        except Exception:
            continue
    matplotlib.rcParams["axes.unicode_minus"] = False


def render_node_statistics(result: ValidationResult, expected: Dict[str, int], output_path: Path) -> None:
    """ノード件数の棒グラフを描画.

    Cluster / Deal は catchall vs 非 catchall を積み上げ表示する.
    """
    import matplotlib.pyplot as plt

    _setup_japanese_font()
    labels = NODE_LABELS
    counts = [result.node_counts.get(l, 0) for l in labels]
    expected_counts = [expected.get(l, 0) for l in labels]
    colors = [NODE_COLORS.get(l, "#CCCCCC") for l in labels]

    # Cluster / Deal の catchall 分割値
    catchall_overlay: Dict[str, int] = {
        "Cluster": result.catchall_cluster_count,
        "Deal": result.catchall_deal_count,
    }

    fig, ax = plt.subplots(figsize=(13, 6), dpi=150)
    x = list(range(len(labels)))
    bars = ax.bar(x, counts, color=colors, edgecolor="black", linewidth=0.5,
                  label="全体 (うち non-catchall)")

    # catchall 部分を半透明グレーで重ね描き
    overlay_vals = [catchall_overlay.get(l, 0) for l in labels]
    if any(overlay_vals):
        ax.bar(x, overlay_vals, color="#888888", alpha=0.55, edgecolor="black",
               linewidth=0.3, label="catchall")

    for i, (b, c, e) in enumerate(zip(bars, counts, expected_counts)):
        if e > 0 and abs(c - e) > max(1, e * 0.01):
            b.set_edgecolor("red")
            b.set_linewidth(2.0)
        label_text = f"{c}"
        ov = overlay_vals[i]
        if ov > 0:
            label_text = f"{c}\n(catchall {ov})"
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + max(counts) * 0.01,
                label_text, ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("件数")
    ax.set_title("ノード種別ごとの件数（赤枠=期待値との乖離あり / グレー=catchall分）")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    logger.info("画像保存: %s", output_path)


def render_relationship_heatmap(driver: Driver, database: str, output_path: Path) -> None:
    """ノードラベル間のリレーション件数ヒートマップを描画."""
    import matplotlib.pyplot as plt
    import numpy as np

    _setup_japanese_font()
    matrix = np.zeros((len(NODE_LABELS), len(NODE_LABELS)), dtype=int)

    with driver.session(database=database) as session:
        rows = session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN labels(a)[0] AS src, labels(b)[0] AS dst, count(r) AS c"
        )
        for row in rows:
            try:
                i = NODE_LABELS.index(row["src"])
                j = NODE_LABELS.index(row["dst"])
            except ValueError:
                continue
            matrix[i, j] += row["c"]

    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(NODE_LABELS)))
    ax.set_yticks(range(len(NODE_LABELS)))
    ax.set_xticklabels(NODE_LABELS, rotation=30, ha="right")
    ax.set_yticklabels(NODE_LABELS)
    ax.set_xlabel("→ 終点ラベル")
    ax.set_ylabel("始点ラベル")
    ax.set_title("ノード間リレーション数ヒートマップ")
    for i in range(len(NODE_LABELS)):
        for j in range(len(NODE_LABELS)):
            v = matrix[i, j]
            color = "white" if v > matrix.max() * 0.5 else "black"
            ax.text(j, i, f"{v}", ha="center", va="center", color=color, fontsize=8)
    plt.colorbar(im, ax=ax, label="件数")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    logger.info("画像保存: %s", output_path)
