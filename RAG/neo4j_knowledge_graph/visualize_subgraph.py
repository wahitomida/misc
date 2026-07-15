"""実データのサブグラフを画像出力する."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Driver

from .config import NODE_COLORS

logger = logging.getLogger(__name__)


# =============================================================================
# 内部ユーティリティ
# =============================================================================


def _setup_japanese_font() -> str:
    import matplotlib

    candidates = ["Yu Gothic", "Yu Gothic UI", "Meiryo", "MS Gothic", "Noto Sans CJK JP"]
    for n in candidates:
        try:
            matplotlib.rcParams["font.family"] = n
            matplotlib.rcParams["axes.unicode_minus"] = False
            return n
        except Exception:
            continue
    return matplotlib.rcParams["font.family"]


def _truncate(s: Any, n: int = 30) -> str:
    if s is None:
        return ""
    text = str(s)
    return text[:n] + "..." if len(text) > n else text


def _node_caption(node: Any) -> str:
    """ノードから 1〜2 行の表示文字列を生成."""
    labels = list(node.labels)
    label = labels[0] if labels else "?"
    props = dict(node)
    if label == "Segment":
        return f"Segment\n{_truncate(props.get('name'))}"
    if label == "AppCategory":
        return f"App\n{_truncate(props.get('name'))}"
    if label in ("Process", "Equipment", "Workpiece"):
        return f"{label}\n{_truncate(props.get('name'), 25)}"
    if label == "Cluster":
        catchall_mark = " *" if props.get("is_catchall") else ""
        return f"Cluster{catchall_mark}\n{_truncate(props.get('cluster_id'), 25)}"
    if label == "Deal":
        return f"Deal#{props.get('deal_id')}\n{props.get('okng', '')}"
    # 分析知見ノードは代表テキストを表示
    for key in ("deal_level", "okng_boundary", "okng_level", "segment_level"):
        if props.get(key):
            return f"{label}\n{_truncate(props[key])}"
    return f"{label}\n{props.get('text_hash', '')[:8]}"


def _path_to_graph(records: List[Any]) -> Tuple[Dict[Any, Any], List[Tuple[Any, Any, str]]]:
    """Neo4j の Path / Node / Relationship をノードIDキーの dict にする."""
    nodes: Dict[Any, Any] = {}
    edges: List[Tuple[Any, Any, str]] = []
    for rec in records:
        for key in rec.keys():
            obj = rec[key]
            if obj is None:
                continue
            # Path
            if hasattr(obj, "nodes") and hasattr(obj, "relationships"):
                for n in obj.nodes:
                    nodes[n.element_id] = n
                for r in obj.relationships:
                    edges.append((r.start_node.element_id, r.end_node.element_id, r.type))
            elif hasattr(obj, "labels"):
                nodes[obj.element_id] = obj
            elif hasattr(obj, "type"):
                edges.append((obj.start_node.element_id, obj.end_node.element_id, obj.type))
    return nodes, edges


def _draw_graph(
    nodes: Dict[Any, Any],
    edges: List[Tuple[Any, Any, str]],
    title: str,
    output_path: Path,
) -> None:
    if not nodes:
        logger.warning("[%s] 描画対象が空のためスキップ", title)
        return

    font = _setup_japanese_font()
    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.DiGraph()
    for nid, n in nodes.items():
        labels = list(n.labels)
        label = labels[0] if labels else "?"
        g.add_node(nid, label=label, caption=_node_caption(n), props_count=len(dict(n)))
    for s, d, rel in edges:
        if s in nodes and d in nodes:
            g.add_edge(s, d, label=rel)

    pos = nx.spring_layout(g, k=2.5, iterations=300, seed=42)
    fig, ax = plt.subplots(figsize=(14, 10), dpi=150)
    fig.patch.set_facecolor("white")

    node_colors = [NODE_COLORS.get(g.nodes[n]["label"], "#CCCCCC") for n in g.nodes]
    node_sizes = [400 + g.nodes[n]["props_count"] * 80 for n in g.nodes]

    nx.draw_networkx_nodes(g, pos, node_color=node_colors, node_size=node_sizes,
                           edgecolors="#333", linewidths=1.0, ax=ax)
    nx.draw_networkx_labels(
        g, pos,
        labels={n: g.nodes[n]["caption"] for n in g.nodes},
        font_size=7, font_family=font, ax=ax,
    )

    # 同種エッジを集計して太さを変える
    rel_counter: Dict[str, int] = {}
    for _, _, rel in edges:
        rel_counter[rel] = rel_counter.get(rel, 0) + 1
    edge_widths = []
    for s, d in g.edges():
        rel = g[s][d]["label"]
        edge_widths.append(0.8 + min(rel_counter.get(rel, 1) / 50.0, 2.5))

    nx.draw_networkx_edges(
        g, pos, arrows=True, arrowsize=12, edge_color="#666",
        width=edge_widths, connectionstyle="arc3,rad=0.07", ax=ax,
    )
    nx.draw_networkx_edge_labels(
        g, pos,
        edge_labels={(s, d): g[s][d]["label"] for s, d in g.edges()},
        font_size=6, ax=ax,
    )
    ax.set_title(title)
    ax.axis("off")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    logger.info("画像保存: %s (nodes=%d edges=%d)", output_path, len(nodes), len(edges))


# =============================================================================
# 各サブグラフ
# =============================================================================


def _fetch_paths(driver: Driver, database: str, query: str, **params) -> List[Any]:
    with driver.session(database=database) as session:
        return list(session.run(query, **params))


def render_sample_okng(driver: Driver, database: str, output_dir: Path) -> None:
    queries = {
        "OK": (
            "MATCH (d:Deal {okng: 'OK'}) "
            "WHERE d.okng_confidence = 'high' "
            "WITH d LIMIT 1 "
            "MATCH path = (d)-[*1..2]-(n) "
            "RETURN path LIMIT 60"
        ),
        "NG": (
            "MATCH (d:Deal {okng: 'NG'}) "
            "WHERE d.okng_confidence = 'high' "
            "WITH d LIMIT 1 "
            "MATCH path = (d)-[*1..2]-(n) "
            "RETURN path LIMIT 60"
        ),
    }
    for okng, q in queries.items():
        recs = _fetch_paths(driver, database, q)
        if not recs:
            logger.warning("[sample %s] パスが取得できないためスキップ", okng)
            continue
        nodes, edges = _path_to_graph(recs)
        out = output_dir / f"sample_subgraph_{okng.lower()}.png"
        _draw_graph(nodes, edges, f"{okng} 案件サンプル サブグラフ（2ホップ）", out)


def render_cluster_hierarchy(driver: Driver, database: str, output_dir: Path) -> None:
    q = (
        "MATCH path = (s:Segment)<-[:IN_SEGMENT]-(c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
        "RETURN path LIMIT 200"
    )
    recs = _fetch_paths(driver, database, q)
    if not recs:
        logger.warning("[cluster_hierarchy] データが取得できないためスキップ")
        return
    nodes, edges = _path_to_graph(recs)
    out = output_dir / "cluster_hierarchy.png"
    _draw_graph(nodes, edges, "Segment → Cluster → Deal 階層図（最大200パス）", out)


def render_cluster_detail(driver: Driver, database: str, output_dir: Path, cluster_id: Optional[str] = None) -> None:
    """指定クラスタのサブグラフ。cluster_id 未指定なら最大件数のクラスタを使用."""
    if cluster_id is None:
        with driver.session(database=database) as session:
            rec = session.run(
                "MATCH (c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
                "RETURN c.cluster_id AS cid, count(d) AS cnt "
                "ORDER BY cnt DESC LIMIT 1"
            ).single()
            if rec is None:
                logger.warning("[cluster_detail] クラスタが見つからないためスキップ")
                return
            cluster_id = rec["cid"]

    q = (
        "MATCH path = (c:Cluster {cluster_id: $cid})<-[:BELONGS_TO_CLUSTER]-(d:Deal)-[*0..1]-(n) "
        "RETURN path LIMIT 100"
    )
    recs = _fetch_paths(driver, database, q, cid=cluster_id)
    if not recs:
        logger.warning("[cluster_detail] cluster_id=%s でパスが取得できないためスキップ", cluster_id)
        return
    nodes, edges = _path_to_graph(recs)
    out = output_dir / "cluster_detail.png"
    _draw_graph(nodes, edges, f"クラスタ詳細: {cluster_id}", out)


def render_equipment_crossref(
    driver: Driver,
    database: str,
    output_dir: Path,
    equipment_keyword: Optional[str] = None,
) -> None:
    """Equipment を起点にした横断クエリの可視化 (Equipment → Cluster → Deal).

    `equipment_keyword` 指定なら e.name CONTAINS で絞り込み、
    未指定なら共有 cluster 数 top1 の Equipment を起点にする.
    """
    if equipment_keyword:
        cond = "WHERE e.name CONTAINS $kw"
        params: Dict[str, Any] = {"kw": equipment_keyword}
        title_suffix = f" (キーワード: '{equipment_keyword}')"
    else:
        with driver.session(database=database) as session:
            rec = session.run(
                "MATCH (e:Equipment)<-[:USES_EQUIPMENT]-(c:Cluster) "
                "WHERE coalesce(c.is_catchall, false) = false "
                "WITH e, count(DISTINCT c) AS cluster_cnt "
                "WHERE cluster_cnt > 1 "
                "RETURN e.name AS name ORDER BY cluster_cnt DESC LIMIT 1"
            ).single()
        if rec is None:
            logger.warning("[equipment_crossref] 横断 Equipment が見つからずスキップ")
            return
        cond = "WHERE e.name = $kw"
        params = {"kw": rec["name"]}
        title_suffix = f" (top共有: '{rec['name']}')"

    q = (
        "MATCH path = (e:Equipment)<-[:USES_EQUIPMENT]-(c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
        f"{cond} "
        "RETURN path LIMIT 80"
    )
    recs = _fetch_paths(driver, database, q, **params)
    if not recs:
        logger.warning("[equipment_crossref] 該当パスが取得できないためスキップ")
        return
    nodes, edges = _path_to_graph(recs)
    out = output_dir / "equipment_crossref.png"
    _draw_graph(nodes, edges, f"Equipment 横断検索{title_suffix}", out)


def render_catchall_comparison(driver: Driver, database: str, output_dir: Path) -> None:
    """catchall vs 非 catchall クラスタの比較サブグラフ (横並びの2枚).

    左: catchall クラスタの代表例 / 右: 非 catchall クラスタの代表例.
    各サブグラフは Cluster + Deal + Process/Equipment/Workpiece までを 1 ホップで取得.
    """
    font = _setup_japanese_font()
    import matplotlib.pyplot as plt
    import networkx as nx

    def _fetch_for(is_catchall: bool) -> Tuple[Dict[Any, Any], List[Tuple[Any, Any, str]], Optional[str]]:
        with driver.session(database=database) as session:
            rec = session.run(
                "MATCH (c:Cluster)<-[:BELONGS_TO_CLUSTER]-(d:Deal) "
                "WHERE coalesce(c.is_catchall, false) = $is_catchall "
                "RETURN c.cluster_id AS cid, count(d) AS cnt "
                "ORDER BY cnt DESC LIMIT 1",
                is_catchall=is_catchall,
            ).single()
        if rec is None:
            return {}, [], None
        cid = rec["cid"]
        q = (
            "MATCH path = (c:Cluster {cluster_id: $cid})-[*0..1]-(n) "
            "RETURN path LIMIT 60"
        )
        recs = _fetch_paths(driver, database, q, cid=cid)
        nodes, edges = _path_to_graph(recs)
        return nodes, edges, cid

    catch_n, catch_e, catch_cid = _fetch_for(True)
    norm_n, norm_e, norm_cid = _fetch_for(False)

    if not catch_n and not norm_n:
        logger.warning("[catchall_comparison] 比較対象が取得できないためスキップ")
        return

    fig, axes = plt.subplots(1, 2, figsize=(20, 9), dpi=150)
    fig.patch.set_facecolor("white")

    for ax, (nodes, edges, cid), tag in zip(
        axes,
        [(catch_n, catch_e, catch_cid), (norm_n, norm_e, norm_cid)],
        ["catchall", "非 catchall"],
    ):
        ax.set_title(f"{tag}: {cid}" if cid else f"{tag}: なし")
        ax.axis("off")
        if not nodes:
            ax.text(0.5, 0.5, "該当データなし", ha="center", va="center", fontsize=14)
            continue
        g = nx.DiGraph()
        for nid, n in nodes.items():
            labels = list(n.labels)
            lbl = labels[0] if labels else "?"
            g.add_node(nid, label=lbl, caption=_node_caption(n), props_count=len(dict(n)))
        for s, d, rel in edges:
            if s in nodes and d in nodes:
                g.add_edge(s, d, label=rel)
        pos = nx.spring_layout(g, k=2.2, iterations=200, seed=42)
        node_colors = [NODE_COLORS.get(g.nodes[n]["label"], "#CCCCCC") for n in g.nodes]
        node_sizes = [400 + g.nodes[n]["props_count"] * 60 for n in g.nodes]
        nx.draw_networkx_nodes(g, pos, node_color=node_colors, node_size=node_sizes,
                               edgecolors="#333", linewidths=1.0, ax=ax)
        nx.draw_networkx_labels(
            g, pos,
            labels={n: g.nodes[n]["caption"] for n in g.nodes},
            font_size=7, font_family=font, ax=ax,
        )
        nx.draw_networkx_edges(g, pos, arrows=True, arrowsize=10, edge_color="#666",
                               width=0.9, connectionstyle="arc3,rad=0.07", ax=ax)
        nx.draw_networkx_edge_labels(
            g, pos,
            edge_labels={(s, d): g[s][d]["label"] for s, d in g.edges()},
            font_size=6, ax=ax,
        )

    fig.suptitle("catchall クラスタ vs 非 catchall クラスタ（代表例）", fontsize=14)
    fig.tight_layout()
    out = output_dir / "catchall_comparison.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200)
    plt.close(fig)
    logger.info("画像保存: %s (catchall=%s vs non=%s)", out, catch_cid, norm_cid)
