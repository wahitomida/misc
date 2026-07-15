"""Neo4j ドライバ + セッションのシングルトン管理 (読み取り専用)."""
from __future__ import annotations

import logging
from typing import Any

from neo4j import GraphDatabase, Driver, Session

from .. import config

logger = logging.getLogger(__name__)


class Neo4jClient:
    """読み取り専用 Neo4j クライアント (シングルトン)."""

    _instance: "Neo4jClient | None" = None
    _driver: Driver | None = None

    def __new__(cls) -> "Neo4jClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
            )
            logger.info("Neo4j driver initialized: %s", config.NEO4J_URI)
        return cls._instance

    def session(self) -> Session:
        assert self._driver is not None
        return self._driver.session(database=config.NEO4J_DATABASE)

    def run_read(self, cypher: str, **params: Any) -> list[dict]:
        """READ クエリを実行して結果を list[dict] で返す.

        書き込みクエリ (CREATE/MERGE/SET/DELETE) は許可しない.
        """
        cy_upper = cypher.upper()
        for forbidden in ("CREATE ", "MERGE ", "SET ", "DELETE ", "REMOVE ", "DROP "):
            if forbidden in cy_upper:
                raise ValueError(f"Write operation '{forbidden.strip()}' is forbidden in Neo4jClient.run_read")
        with self.session() as s:
            return [dict(r) for r in s.execute_read(
                lambda tx: list(tx.run(cypher, **params, timeout=config.NEO4J_QUERY_TIMEOUT_SEC))
            )]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            Neo4jClient._instance = None
            logger.info("Neo4j driver closed")


def get_neo4j_client() -> Neo4jClient:
    return Neo4jClient()
