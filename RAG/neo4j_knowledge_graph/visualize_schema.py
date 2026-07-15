"""スキーマ全体図の画像出力（PNG / SVG）.

graphviz が利用可能ならば DOT で美しく描画し、
未インストールの場合は matplotlib + networkx の spring_layout にフォールバック。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

from neo4j import Driver

from .config import NODE_COLORS, NODE_LABELS, RELATIONSHIP_TYPES

logger = logging.getLogger(__name__)


# =============================================================================
# Neo4j のスキーマ取得
# =============================================================================


def fetch_schema(driver: Driver, database: str) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    """実際にデータが入っているノードラベル/リレーションを取得.

    Returns:
        labels   : 存在するノードラベル一覧
        rels     : (start_label, rel_type, end_label) のリスト
    """
    labels_in_db: List[str] = []
    rels: List[Tuple[str, str, str]] = []
    with driver.session(database=database) as session:
        rec = session.run(
            "MATCH (n) UNWIND labels(n) AS lbl RETURN DISTINCT lbl"
        )
        labels_in_db = [r["lbl"] for r in rec]
        rec = session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN DISTINCT labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS dst"
        )
        for row in rec:
            if row["src"] and row["dst"]:
                rels.append((row["src"], row["rel"], row["dst"]))
    return labels_in_db, rels


# =============================================================================
# 各ラベルのプロパティを取得（スキーマ図の補足表示用）
# =============================================================================


def fetch_label_properties(driver: Driver, database: str, label: str, sample: int = 1) -> List[str]:
    with driver.session(database=database) as session:
        rec = session.run(
            f"MATCH (n:{label}) RETURN keys(n) AS k LIMIT {sample}"
        ).single()
        if rec is None:
            return []
        return list(rec["k"])


# =============================================================================
# Graphviz 描画
# =============================================================================


def _try_graphviz_render(
    labels: List[str],
    rels: List[Tuple[str, str, str]],
    label_props: Dict[str, List[str]],
    output_dir: Path,
) -> bool:
    try:
        import graphviz  # type: ignore
    except ImportError:
        logger.warning("graphviz パッケージが未インストール。matplotlib にフォールバック")
        return False

    dot = graphviz.Digraph("schema", format="png")
    dot.attr(
        rankdir="LR",
        size="16,11!",
        ratio="fill",
        fontname="Yu Gothic",
        bgcolor="white",
    )
    dot.attr("node",
             shape="record",
             style="filled,rounded",
             fontname="Yu Gothic",
             fontsize="11",
             margin="0.2,0.1")
    dot.attr("edge", fontname="Yu Gothic", fontsize="9", color="#555555")

    def _escape_record(text: str) -> str:
        return (
            text.replace("\\", "\\\\")
                .replace("{", "\\{")
                .replace("}", "\\}")
                .replace("|", "\\|")
                .replace("<", "\\<")
                .replace(">", "\\>")
                .replace('"', '\\"')
        )

    used_labels = set(labels) | {s for s, _, _ in rels} | {d for _, _, d in rels}
    for lbl in NODE_LABELS:
        if lbl not in used_labels:
            continue
        props = label_props.get(lbl, [])
        prop_lines = [f"• {p}" for p in props[:8]]
        if len(props) > 8:
            prop_lines.append(f"... +{len(props) - 8} more")
        prop_text = _escape_record("\n".join(prop_lines)) if prop_lines else _escape_record("(no props)")
        # record shape: "{ Header | body }" の形式。改行は \l (左寄せ) を使う。
        body = "{ " + _escape_record(lbl) + " | " + prop_text.replace("\n", "\\l") + "\\l }"
        dot.node(
            lbl,
            label=body,
            fillcolor=NODE_COLORS.get(lbl, "#EEEEEE"),
        )

    for src, rel, dst in rels:
        dot.edge(src, dst, label=rel)

    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "schema_diagram"
    svg_path = output_dir / "schema_diagram"
    try:
        dot.render(str(png_path), format="png", cleanup=True)
        dot.render(str(svg_path), format="svg", cleanup=True)
    except Exception as e:
        logger.warning("graphviz レンダリング失敗 (%s)。matplotlib にフォールバック", e)
        return False
    logger.info("画像保存: %s.png / %s.svg", png_path, svg_path)
    return True


# =============================================================================
# matplotlib + networkx フォールバック
# =============================================================================


def _matplotlib_fallback(
    labels: List[str],
    rels: List[Tuple[str, str, str]],
    label_props: Dict[str, List[str]],
    output_dir: Path,
) -> None:
    import matplotlib

    candidates = ["Yu Gothic", "Yu Gothic UI", "Meiryo", "MS Gothic", "Noto Sans CJK JP"]
    for n in candidates:
        try:
            matplotlib.rcParams["font.family"] = n
            break
        except Exception:
            continue
    matplotlib.rcParams["axes.unicode_minus"] = False

    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.DiGraph()
    used_labels = set(labels) | {s for s, _, _ in rels} | {d for _, _, d in rels}
    for lbl in used_labels:
        g.add_node(lbl, color=NODE_COLORS.get(lbl, "#CCCCCC"))
    for src, rel, dst in rels:
        g.add_edge(src, dst, label=rel)

    fig, ax = plt.subplots(figsize=(16, 11), dpi=150)
    pos = nx.spring_layout(g, k=2.0, iterations=200, seed=42)
    node_colors = [g.nodes[n]["color"] for n in g.nodes]
    nx.draw_networkx_nodes(
        g, pos, node_color=node_colors, node_size=3500, edgecolors="#333", linewidths=1.5, ax=ax,
    )
    nx.draw_networkx_labels(g, pos, font_size=10, font_family=matplotlib.rcParams["font.family"], ax=ax)
    nx.draw_networkx_edges(g, pos, arrows=True, arrowsize=15, edge_color="#666", connectionstyle="arc3,rad=0.05", ax=ax)
    edge_labels = {(s, d): data["label"] for s, d, data in g.edges(data=True)}
    nx.draw_networkx_edge_labels(g, pos, edge_labels=edge_labels, font_size=8, ax=ax)
    ax.set_title("Neo4j スキーマ全体図（フォールバック描画）")
    ax.axis("off")
    fig.tight_layout()

    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / "schema_diagram.png"
    svg_path = output_dir / "schema_diagram.svg"
    fig.savefig(png_path, dpi=200)
    fig.savefig(svg_path)
    plt.close(fig)
    logger.info("画像保存: %s / %s", png_path, svg_path)


# =============================================================================
# エントリポイント
# =============================================================================


def render_schema(driver: Driver, database: str, output_dir: Path) -> None:
    labels, rels = fetch_schema(driver, database)
    if not labels and not rels:
        logger.warning("グラフが空のためスキーマ図をスキップ")
        return

    label_props: Dict[str, List[str]] = {}
    for lbl in labels:
        label_props[lbl] = fetch_label_properties(driver, database, lbl)

    if not _try_graphviz_render(labels, rels, label_props, output_dir):
        _matplotlib_fallback(labels, rels, label_props, output_dir)
