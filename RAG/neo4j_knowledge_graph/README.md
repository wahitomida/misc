# Neo4j Knowledge Graph Pipeline

このプロジェクトは、構造化されたデータを Neo4j に読み込み、グラフ構造として可視化し、RAG / 検索評価の基盤を作るための実験的なパイプラインです。主な目的は、知識グラフの構築、ベクトル埋め込み、横断検索の検証です。

## できること

- CSV からノード・リレーションを作成して Neo4j に取り込む
- 依存関係やクラスタ構造を可視化する
- Embedding を用いたベクトル検索の試作
- GraphRAG / RAG 検索性能の比較評価に向けた土台作り

## 主な技術

- Python
- Neo4j
- OpenAI / Azure OpenAI Embeddings
- NetworkX / Matplotlib

## セットアップ

```bash
cd RAG/neo4j_knowledge_graph
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## 実行イメージ

```bash
python -m neo4j_knowledge_graph.main --input data/05_analysis.csv --skip-visualize
```

## ポートフォリオでの訴求ポイント

- LLM とグラフ構造を組み合わせた RAG の実装
- データ整形・構造化・検索可能性の設計力
- ベクトル検索とナレッジグラフの実験基盤づくり
