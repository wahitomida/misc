"""Embedding 投入状況の簡易確認スクリプト."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

uri = os.environ["NEO4J_URI"]
user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j")
pw = os.environ["NEO4J_PASSWORD"]
db = os.environ.get("NEO4J_DATABASE", "neo4j")

drv = GraphDatabase.driver(uri, auth=(user, pw))
with drv.session(database=db) as s:
    with_ = s.run("MATCH (d:Deal) WHERE d.embedding IS NOT NULL RETURN count(d) AS c").single()["c"]
    wo = s.run("MATCH (d:Deal) WHERE d.embedding IS NULL RETURN count(d) AS c").single()["c"]
    sample = s.run(
        "MATCH (d:Deal) WHERE d.embedding IS NOT NULL "
        "RETURN d.deal_id AS id, size(d.embedding) AS dim LIMIT 1"
    ).single()

print(f"with_embedding={with_}")
print(f"without_embedding={wo}")
total = with_ + wo
pct = 100.0 * with_ / total if total else 0.0
print(f"coverage={pct:.1f}%")
if sample:
    print(f"sample_deal_id={sample['id']} embedding_dim={sample['dim']}")
drv.close()
