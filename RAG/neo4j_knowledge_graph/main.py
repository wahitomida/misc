"""エントリポイント — CSV を Neo4j に投入 + 検証 + 可視化を一括実行."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from neo4j import GraphDatabase

from .config import (
    DEFAULT_CSV_CANDIDATES,
    DEFAULT_OUTPUT_DIR,
    EMBEDDING_MODEL,
    Neo4jSettings,
)
from .constraints import apply_constraints, clear_graph
from .csv_loader import (
    build_app_category_nodes,
    build_cluster_nodes,
    build_deal_nodes,
    build_equipment_nodes,
    build_insight_nodes_per_row,
    build_process_nodes,
    build_segment_nodes,
    build_workpiece_nodes,
    get_catchall_cluster_ids,
    load_csv,
)
from .graph_builder import (
    upsert_app_categories,
    upsert_clusters,
    upsert_deals,
    upsert_equipments,
    upsert_insights_and_relations,
    upsert_processes,
    upsert_segments,
    upsert_workpieces,
)
from .validation import (
    ValidationResult,
    render_node_statistics,
    render_relationship_heatmap,
    run_validation,
)
from .visualize_schema import render_schema
from .visualize_subgraph import (
    render_catchall_comparison,
    render_cluster_detail,
    render_cluster_hierarchy,
    render_equipment_crossref,
    render_sample_okng,
)


logger = logging.getLogger("neo4j_kg")


# =============================================================================
# ロガー設定
# =============================================================================


def setup_logger(verbose: bool = False, log_file: Optional[Path] = None) -> None:
    # Windows の cp932 stdout で UTF-8 文字 (絵文字等) を出すと
    # logging が UnicodeEncodeError でハングするため UTF-8 に再構成する
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # neo4j ドライバの DEBUG ログはバッチ毎に大量に出るため、
    # --verbose 時でも WARNING までに抑える
    logging.getLogger("neo4j").setLevel(logging.WARNING)


# =============================================================================
# CSV パス自動検出
# =============================================================================


def resolve_csv_path(arg_path: Optional[Path]) -> Path:
    if arg_path is not None:
        if arg_path.exists():
            return arg_path
        raise FileNotFoundError(f"--input で指定された CSV が存在しません: {arg_path}")
    for cand in DEFAULT_CSV_CANDIDATES:
        if cand.exists():
            logger.info("入力 CSV を自動検出: %s", cand)
            return cand
    raise FileNotFoundError(
        "入力 CSV が見つかりません。--input で指定してください。\n候補: "
        + ", ".join(str(p) for p in DEFAULT_CSV_CANDIDATES)
    )


# =============================================================================
# レポート生成
# =============================================================================


def _emoji(ok: bool) -> str:
    return "✅" if ok else "⚠️"


def write_report(
    output_dir: Path,
    csv_path: Path,
    csv_stats: dict,
    validation: ValidationResult,
    expected_node_counts: dict,
    timings: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Neo4j ナレッジグラフ構築レポート",
        "",
        f"## 実行日時",
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 入力データ",
        f"- ファイル: `{csv_path}`",
        f"- 総レコード数: {csv_stats['total_rows']}件",
        f"- OK件数: {csv_stats['ok_count']}件 / NG件数: {csv_stats['ng_count']}件",
        f"- クラスタ数: {csv_stats['cluster_count']}個 (うち catchall: {csv_stats.get('catchall_cluster_count', 0)})",
        f"- アプリ分類数: {csv_stats['app_category_count']}種",
        f"- Segment 数: {csv_stats.get('segment_count', 0)}種",
        f"- Process / Equipment / Workpiece: "
        f"{csv_stats.get('process_count', 0)} / {csv_stats.get('equipment_count', 0)} / {csv_stats.get('workpiece_count', 0)}",
        "",
        "## グラフ統計",
        "| ノードラベル | 件数 | 期待値 | 差異 |",
        "|---|---|---|---|",
    ]
    for label, count in validation.node_counts.items():
        expected = expected_node_counts.get(label, 0)
        ok = expected == 0 or abs(count - expected) <= max(1, expected * 0.01)
        lines.append(
            f"| {label} | {count} | {expected if expected else '-'} | {_emoji(ok)} |"
        )
    lines.extend([
        "",
        "## リレーション統計",
        "| リレーション | 件数 |",
        "|---|---|",
    ])
    for rel, cnt in validation.rel_counts.items():
        lines.append(f"| {rel} | {cnt} |")

    lines.extend([
        "",
        "## バリデーション結果",
        f"- {_emoji(validation.orphan_deals == 0)} 孤立Deal: {validation.orphan_deals}件",
        f"- {_emoji(validation.orphan_clusters == 0)} 孤立Cluster: {validation.orphan_clusters}件",
        f"- {_emoji(validation.deals_without_category == 0 or csv_stats['app_category_count'] == 0)} "
        f"AppCategory 未紐づけ Deal: {validation.deals_without_category}件",
        f"- {_emoji(validation.inconsistent_catchall_flags == 0)} "
        f"catchall フラグ不整合 (Cluster vs Deal): {validation.inconsistent_catchall_flags}件",
    ])
    if validation.insufficient_quality_counts:
        lines.append("- データ品質不足ノード:")
        for label, cnt in validation.insufficient_quality_counts.items():
            lines.append(f"    - {label}: {cnt}件")

    # 横断検索可能性 (改善2 検証)
    total_clusters = csv_stats["cluster_count"] or 1
    lines.extend([
        "",
        "## 横断検索可能性 (Cluster からの紐づき率)",
        "| 軸 | 設定済み Cluster | 未設定 Cluster | カバー率 |",
        "|---|---|---|---|",
    ])
    for axis_name, missing in (
        ("Process", validation.clusters_without_process),
        ("Equipment", validation.clusters_without_equipment),
        ("Workpiece", validation.clusters_without_workpiece),
    ):
        set_count = total_clusters - missing
        rate = 100.0 * set_count / total_clusters if total_clusters else 0.0
        lines.append(f"| {axis_name} | {set_count} | {missing} | {rate:.1f}% |")

    # Equipment 横断共有トップ10
    if validation.top_shared_equipment:
        lines.extend([
            "",
            "### 横断共有 Equipment (非 catchall クラスタで共有数の多い順 top10)",
            "| Equipment | 共有クラスタ数 |",
            "|---|---|",
        ])
        for row in validation.top_shared_equipment:
            lines.append(f"| {row['equipment']} | {row['cluster_count']} |")

    # catchall 統計
    catchall_cluster = validation.catchall_cluster_count
    catchall_deal = validation.catchall_deal_count
    non_catchall_cluster = max(0, total_clusters - catchall_cluster)
    non_catchall_deal = max(0, csv_stats["total_rows"] - catchall_deal)
    lines.extend([
        "",
        "## catchall 統計",
        "| 区分 | Cluster 数 | Deal 数 |",
        "|---|---|---|",
        f"| catchall | {catchall_cluster} | {catchall_deal} |",
        f"| 非 catchall | {non_catchall_cluster} | {non_catchall_deal} |",
    ])

    # Embedding 投入状況
    total_deals = csv_stats["total_rows"] or 1
    cov = 100.0 * validation.deals_with_embedding / total_deals if total_deals else 0.0
    lines.extend([
        "",
        "## Embedding 投入状況",
        f"- 投入済み Deal: {validation.deals_with_embedding} / 未投入 Deal: {validation.deals_without_embedding} "
        f"(カバー率 {cov:.1f}%)",
    ])

    lines.extend([
        "",
        "## クラスタ別 Deal 件数（上位 20）",
        "| cluster_id | dominant_okng | catchall | deal数 |",
        "|---|---|---|---|",
    ])
    for row in validation.cluster_deal_distribution:
        catchall_mark = "yes" if row.get("is_catchall") else ""
        lines.append(
            f"| {row['cluster_id']} | {row['dominant_okng']} | {catchall_mark} | {row['deal_count']} |"
        )

    lines.extend([
        "",
        "## 出力画像",
        "- [スキーマ全体図](./schema_diagram.png)",
        "- [OKサンプルサブグラフ](./sample_subgraph_ok.png)",
        "- [NGサンプルサブグラフ](./sample_subgraph_ng.png)",
        "- [クラスタ階層図](./cluster_hierarchy.png)",
        "- [クラスタ詳細](./cluster_detail.png)",
        "- [Equipment 横断検索](./equipment_crossref.png)",
        "- [catchall 比較](./catchall_comparison.png)",
        "- [ノード統計](./node_statistics.png)",
        "- [リレーション密度](./relationship_heatmap.png)",
        "",
        "## 所要時間",
    ])
    total = 0.0
    for key, sec in timings.items():
        lines.append(f"- {key}: {sec:.2f}秒")
        total += sec
    lines.append(f"- **合計: {total:.2f}秒**")
    lines.append("")

    out = output_dir / "report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("レポート保存: %s", out)


# =============================================================================
# パイプライン本体
# =============================================================================


def build_graph(
    driver,
    database: str,
    csv_path: Path,
    skip_clear: bool = True,
):
    """CSV → Neo4j 投入. 戻り値は (csv_stats, expected_node_counts, timings)."""
    timings: dict = {}

    if not skip_clear:
        t0 = time.perf_counter()
        clear_graph(driver, database)
        timings["clear_graph"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    apply_constraints(driver, database)
    timings["apply_constraints"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    df, resolved = load_csv(csv_path)
    clusters = build_cluster_nodes(df, resolved)
    catchall_ids = get_catchall_cluster_ids(clusters)
    deals = build_deal_nodes(df, resolved, catchall_cluster_ids=catchall_ids)
    segments = build_segment_nodes(clusters)
    app_categories = build_app_category_nodes(deals)
    processes, process_cluster_map = build_process_nodes(clusters)
    equipments, equipment_cluster_map = build_equipment_nodes(clusters)
    workpieces, workpiece_cluster_map = build_workpiece_nodes(clusters)
    insight_rows = build_insight_nodes_per_row(df, resolved)
    timings["csv_parse"] = time.perf_counter() - t0

    csv_stats = {
        "total_rows": len(df),
        "ok_count": sum(1 for d in deals if d.okng == "OK"),
        "ng_count": sum(1 for d in deals if d.okng == "NG"),
        "cluster_count": len(clusters),
        "app_category_count": len(app_categories),
        "segment_count": len(segments),
        "process_count": len(processes),
        "equipment_count": len(equipments),
        "workpiece_count": len(workpieces),
        "catchall_cluster_count": len(catchall_ids),
        "catchall_deal_count": sum(1 for d in deals if d.in_catchall_cluster),
    }
    logger.info(
        "CSV 集計: rows=%d OK=%d NG=%d clusters=%d (catchall=%d) apps=%d segments=%d "
        "process=%d equipment=%d workpiece=%d",
        csv_stats["total_rows"], csv_stats["ok_count"], csv_stats["ng_count"],
        csv_stats["cluster_count"], csv_stats["catchall_cluster_count"],
        csv_stats["app_category_count"], csv_stats["segment_count"],
        csv_stats["process_count"], csv_stats["equipment_count"], csv_stats["workpiece_count"],
    )

    expected = {
        "Deal": csv_stats["total_rows"],
        "Cluster": csv_stats["cluster_count"],
        "Segment": csv_stats["segment_count"],
        "AppCategory": csv_stats["app_category_count"],
        "Process": csv_stats["process_count"],
        "Equipment": csv_stats["equipment_count"],
        "Workpiece": csv_stats["workpiece_count"],
    }

    t0 = time.perf_counter()
    upsert_segments(driver, database, segments)
    upsert_clusters(driver, database, clusters)
    # Phase 2.5: Process / Equipment / Workpiece
    upsert_processes(driver, database, processes, process_cluster_map)
    upsert_equipments(driver, database, equipments, equipment_cluster_map)
    upsert_workpieces(driver, database, workpieces, workpiece_cluster_map)
    upsert_app_categories(driver, database, app_categories)
    upsert_deals(driver, database, deals)
    upsert_insights_and_relations(driver, database, insight_rows)
    timings["graph_upsert"] = time.perf_counter() - t0

    return csv_stats, expected, timings


def visualize_all(
    driver,
    database: str,
    output_dir: Path,
    cluster_id: Optional[str] = None,
    equipment_keyword: Optional[str] = None,
) -> dict:
    timings: dict = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    render_schema(driver, database, output_dir)
    timings["schema_diagram"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    render_sample_okng(driver, database, output_dir)
    render_cluster_hierarchy(driver, database, output_dir)
    render_cluster_detail(driver, database, output_dir, cluster_id=cluster_id)
    render_equipment_crossref(driver, database, output_dir, equipment_keyword=equipment_keyword)
    render_catchall_comparison(driver, database, output_dir)
    timings["subgraphs"] = time.perf_counter() - t0
    return timings


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="neo4j_knowledge_graph",
        description="商談分析CSV を Neo4j ナレッジグラフに変換し、構造を可視化する",
    )
    parser.add_argument("--input", type=Path, default=None, help="入力 CSV パス（省略時は自動検出）")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="画像・レポートの出力先")
    parser.add_argument("--clear-graph", action="store_true", help="投入前にグラフを全削除する")
    parser.add_argument("--skip-visualize", action="store_true", help="可視化をスキップ")
    parser.add_argument("--visualize-only", action="store_true", help="既存グラフの可視化のみ実行")
    parser.add_argument("--validate-only", action="store_true", help="バリデーションのみ実行")
    parser.add_argument(
        "--visualize-cluster", type=str, default=None, metavar="CLUSTER_ID",
        help="クラスタ詳細画像で使用する cluster_id を明示指定",
    )
    parser.add_argument(
        "--visualize-equipment", type=str, default=None, metavar="KEYWORD",
        help="Equipment 横断検索画像のキーワード (例: 'レーザー')",
    )
    parser.add_argument(
        "--generate-embeddings", action="store_true",
        help="パイプライン後に OpenAI Embedding API で Deal.embedding を生成する",
    )
    parser.add_argument(
        "--generate-embeddings-only", action="store_true",
        help="既存グラフに対し Embedding 生成のみを実行する",
    )
    parser.add_argument(
        "--model", type=str, default=EMBEDDING_MODEL, metavar="MODEL",
        help=f"OpenAI Embedding モデル名 (デフォルト: {EMBEDDING_MODEL})",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG ログを有効化")
    parser.add_argument("--log-file", type=Path, default=None, help="ログ出力ファイル (UTF-8)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logger(args.verbose, args.log_file)

    settings = Neo4jSettings.from_env()
    logger.info("Neo4j 接続: %s (db=%s)", settings.uri, settings.database)
    driver = GraphDatabase.driver(settings.uri, auth=(settings.user, settings.password))

    try:
        with driver.session(database=settings.database) as session:
            session.run("RETURN 1").single()
        logger.info("Neo4j 接続確認 OK")
    except Exception as e:
        logger.error("Neo4j 接続失敗: %s", e)
        driver.close()
        sys.exit(1)

    try:
        # ── visualize-only ───────────────────────────────
        if args.visualize_only:
            timings = visualize_all(
                driver, settings.database, args.output_dir,
                cluster_id=args.visualize_cluster,
                equipment_keyword=args.visualize_equipment,
            )
            logger.info("可視化完了: %s", timings)
            return

        # ── validate-only ────────────────────────────────
        if args.validate_only:
            t0 = time.perf_counter()
            result = run_validation(driver, settings.database)
            elapsed = time.perf_counter() - t0
            logger.info("バリデーション完了 (%.2f sec)", elapsed)
            logger.info("ノード件数: %s", result.node_counts)
            logger.info("リレーション件数: %s", result.rel_counts)
            logger.info(
                "孤立Deal=%d 孤立Cluster=%d / catchall: cluster=%d deal=%d / inconsistent=%d",
                result.orphan_deals, result.orphan_clusters,
                result.catchall_cluster_count, result.catchall_deal_count,
                result.inconsistent_catchall_flags,
            )
            logger.info(
                "横断未設定: process=%d equipment=%d workpiece=%d",
                result.clusters_without_process, result.clusters_without_equipment,
                result.clusters_without_workpiece,
            )
            logger.info(
                "Embedding: with=%d without=%d",
                result.deals_with_embedding, result.deals_without_embedding,
            )
            return

        # ── generate-embeddings-only ─────────────────────
        if args.generate_embeddings_only:
            from .embedding_generator import generate_embeddings
            from .config import OPENAI_API_KEY
            t0 = time.perf_counter()
            result = generate_embeddings(
                neo4j_uri=settings.uri,
                neo4j_user=settings.user,
                neo4j_password=settings.password,
                openai_api_key=OPENAI_API_KEY,
                database=settings.database,
                model=args.model,
            )
            logger.info(
                "Embedding 生成完了 (%.2f sec): %s",
                time.perf_counter() - t0, result,
            )
            return

        # ── 通常パイプライン ─────────────────────────────
        csv_path = resolve_csv_path(args.input)
        csv_stats, expected, build_timings = build_graph(
            driver, settings.database, csv_path, skip_clear=not args.clear_graph,
        )

        t0 = time.perf_counter()
        validation = run_validation(driver, settings.database)
        build_timings["validation"] = time.perf_counter() - t0

        if not args.skip_visualize:
            viz_timings = visualize_all(
                driver, settings.database, args.output_dir,
                cluster_id=args.visualize_cluster,
                equipment_keyword=args.visualize_equipment,
            )
            build_timings.update(viz_timings)

            try:
                render_node_statistics(validation, expected, args.output_dir / "node_statistics.png")
                render_relationship_heatmap(driver, settings.database, args.output_dir / "relationship_heatmap.png")
            except Exception as e:
                logger.exception("統計画像生成中にエラー: %s", e)

        # ── Embedding (パイプライン末尾で) ───────────────
        if args.generate_embeddings:
            from .embedding_generator import generate_embeddings
            from .config import OPENAI_API_KEY
            try:
                t0 = time.perf_counter()
                emb_result = generate_embeddings(
                    neo4j_uri=settings.uri,
                    neo4j_user=settings.user,
                    neo4j_password=settings.password,
                    openai_api_key=OPENAI_API_KEY,
                    database=settings.database,
                    model=args.model,
                )
                build_timings["embedding"] = time.perf_counter() - t0
                logger.info("Embedding 結果: %s", emb_result)
                # 追加バリデーションで最新件数を反映
                validation = run_validation(driver, settings.database)
            except Exception as e:
                logger.exception("Embedding 生成でエラー: %s", e)

        write_report(args.output_dir, csv_path, csv_stats, validation, expected, build_timings)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
