"""Neo4j への接続疎通テスト。"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # RAG/
sys.path.insert(0, str(ROOT))

from misc_26.RAG.neo4j_knowledge_graph.config import Neo4jSettings  # noqa: E402

try:
    from neo4j import GraphDatabase
except ImportError as e:
    print(f"[NG] neo4j package not installed: {e}")
    sys.exit(1)


def main() -> int:
    s = Neo4jSettings.from_env()
    print(f"URI      : {s.uri}")
    print(f"USER     : {s.user}")
    print(f"DATABASE : {s.database}")
    print(f"PASSWORD : {'*' * len(s.password)} ({len(s.password)} chars)")
    try:
        driver = GraphDatabase.driver(s.uri, auth=(s.user, s.password))
        with driver.session(database=s.database) as session:
            result = session.run("RETURN 'hello' AS msg, datetime() AS now")
            row = result.single()
            print(f"[OK] Cypher response: msg={row['msg']}, now={row['now']}")
        driver.close()
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[NG] Connection failed: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
