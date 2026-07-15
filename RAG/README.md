# RAG Projects

このディレクトリには、RAG（Retrieval-Augmented Generation）とGraphRAGを対象とした2つの実験プロジェクトが含まれています。

## 含まれるプロジェクト

### 1. Neo4j Knowledge Graph Pipeline
- パス: `RAG/RAG/neo4j_knowledge_graph`
- 説明: CSVデータをNeo4jに取り込み、知識グラフを構築・可視化するパイプラインです。
- 主な機能: ノード・リレーション構築、クラスタ・依存関係の可視化、Embeddingによるベクトル検索の試作。
- ドキュメント: `RAG/RAG/neo4j_knowledge_graph/README.md`

### 2. RAG Benchmark
- パス: `RAG/RAG/rag_benchmark`
- 説明: 13種類のRAG手法を比較評価するベンチマーク基盤です。
- 主な機能: 手法実装、評価スクリプト、RAGAS準拠評価の集計。
- ドキュメント: `RAG/RAG/rag_benchmark/README.md`

## 使い方

1. それぞれのサブプロジェクトディレクトリに移動します。
2. Python仮想環境を作成して依存関係をインストールします。
3. 各プロジェクトの `README.md` を参照して実行手順を確認してください。

## 公開時の注意

- APIキーや機密設定は `.env` ファイルで管理し、公開リポジトリには含めないでください。
- 実行にはNeo4jやクラウドAPIなどの外部環境が必要になる場合があります。
