"""Neo4j の制約・インデックスを冪等に作成する."""
from __future__ import annotations

import logging
from typing import List

from neo4j import Driver

from .config import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)


_CONSTRAINTS: List[str] = [
    "CREATE CONSTRAINT deal_id_unique IF NOT EXISTS FOR (d:Deal) REQUIRE d.deal_id IS UNIQUE",
    "CREATE CONSTRAINT cluster_id_unique IF NOT EXISTS FOR (c:Cluster) REQUIRE c.cluster_id IS UNIQUE",
    "CREATE CONSTRAINT segment_name_unique IF NOT EXISTS FOR (s:Segment) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT app_category_unique IF NOT EXISTS FOR (a:AppCategory) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT process_name_unique IF NOT EXISTS FOR (p:Process) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT equipment_name_unique IF NOT EXISTS FOR (e:Equipment) REQUIRE e.name IS UNIQUE",
    "CREATE CONSTRAINT workpiece_name_unique IF NOT EXISTS FOR (w:Workpiece) REQUIRE w.name IS UNIQUE",
    "CREATE CONSTRAINT ok_tendency_hash_unique IF NOT EXISTS FOR (o:OKTendency) REQUIRE o.text_hash IS UNIQUE",
    "CREATE CONSTRAINT ng_tendency_hash_unique IF NOT EXISTS FOR (n:NGTendency) REQUIRE n.text_hash IS UNIQUE",
    "CREATE CONSTRAINT boundary_hash_unique IF NOT EXISTS FOR (b:Boundary) REQUIRE b.text_hash IS UNIQUE",
    "CREATE CONSTRAINT appeal_hash_unique IF NOT EXISTS FOR (a:AppealPoint) REQUIRE a.text_hash IS UNIQUE",
    "CREATE CONSTRAINT recommendation_hash_unique IF NOT EXISTS FOR (r:Recommendation) REQUIRE r.text_hash IS UNIQUE",
]


_FULLTEXT_INDEXES: List[str] = [
    "CREATE FULLTEXT INDEX deal_content_fulltext IF NOT EXISTS FOR (d:Deal) ON EACH [d.content]",
    "CREATE FULLTEXT INDEX cluster_objective_fulltext IF NOT EXISTS FOR (c:Cluster) "
    "ON EACH [c.objective, c.challenge, c.process]",
    "CREATE FULLTEXT INDEX process_name_fulltext IF NOT EXISTS FOR (p:Process) "
    "ON EACH [p.name, p.description]",
    "CREATE FULLTEXT INDEX equipment_name_fulltext IF NOT EXISTS FOR (e:Equipment) "
    "ON EACH [e.name, e.description]",
    "CREATE FULLTEXT INDEX workpiece_name_fulltext IF NOT EXISTS FOR (w:Workpiece) "
    "ON EACH [w.name, w.description]",
]


# Vector Index は Neo4j 5.13+ 専用構文.
# 環境によっては未サポートの場合があるため失敗を許容する.
_VECTOR_INDEXES: List[str] = [
    (
        "CREATE VECTOR INDEX deal_embedding_index IF NOT EXISTS "
        "FOR (d:Deal) ON d.embedding "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {EMBEDDING_DIMENSIONS}, "
        "`vector.similarity_function`: 'cosine'"
        "}}"
    ),
]


def apply_constraints(driver: Driver, database: str) -> None:
    """全制約・全フルテキストインデックス・Vector インデックスを冪等に作成."""
    with driver.session(database=database) as session:
        for stmt in _CONSTRAINTS:
            session.run(stmt)
            logger.info("制約適用: %s", stmt.split("FOR")[0].strip())
        for stmt in _FULLTEXT_INDEXES:
            session.run(stmt)
            logger.info("FULLTEXT INDEX 適用: %s", stmt.split("FOR")[0].strip())
        for stmt in _VECTOR_INDEXES:
            try:
                session.run(stmt)
                logger.info("VECTOR INDEX 適用: %s", stmt.split("FOR")[0].strip())
            except Exception as e:  # noqa: BLE001 - 旧版互換のため
                logger.warning("VECTOR INDEX 作成スキップ (Neo4j 5.13+ 必要): %s", e)


def clear_graph(driver: Driver, database: str) -> None:
    """全ノード・全リレーションを削除する（破壊的操作・確認は呼び出し側）."""
    logger.warning("グラフ全削除を実行")
    with driver.session(database=database) as session:
        # 大規模グラフ向けに 50000 件ずつバッチ削除
        while True:
            res = session.run(
                "MATCH (n) WITH n LIMIT 50000 DETACH DELETE n RETURN count(*) AS c"
            ).single()
            count = (res or {}).get("c", 0) if res else 0
            if not count:
                break
            logger.info("  削除中... %d 件", count)
    logger.info("グラフ全削除 完了")
