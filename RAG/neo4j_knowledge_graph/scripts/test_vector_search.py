"""Vector Index で類似 Deal 検索ができるか動作確認."""
import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from openai import AzureOpenAI

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# Azure OpenAI で query をベクトル化
client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_KEY"],
    api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
)
deployment = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "embedding")
QUERY = "ロボットハンドでワークを掴むときに変位センサで位置決めしたい"
resp = client.embeddings.create(model=deployment, input=[QUERY])
qvec = resp.data[0].embedding
print(f"query='{QUERY}' dim={len(qvec)}")

# Neo4j Vector Index で上位5件取得
drv = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j"),
          os.environ["NEO4J_PASSWORD"]),
)
with drv.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
    rows = list(s.run(
        "CALL db.index.vector.queryNodes('deal_embedding_index', 5, $q) "
        "YIELD node, score "
        "RETURN node.deal_id AS deal_id, node.okng AS okng, "
        "       substring(node.content, 0, 120) AS preview, score",
        q=qvec,
    ))
print("\n=== Top 5 類似 Deal ===")
for r in rows:
    print(f"  score={r['score']:.4f} deal_id={r['deal_id']} okng={r['okng']}")
    print(f"    {r['preview']}")
drv.close()
