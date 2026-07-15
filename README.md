# AI Portfolio Projects

このワークスペースは、副業・案件受注向けのAIポートフォリオ用プロジェクトをまとめたリポジトリ構成例です。

## 概要

- AIと検索技術を組み合わせた業務自動化・情報調査アプリケーション
- RAG / GraphRAG を含むナレッジ検索・評価基盤
- Web検索グラウンディングによる調査パイプライン

## 代表プロジェクト

### 1. Exhibit
- パス: `exhibit/exhibit`
- 説明: 展示会前後の調査・レポート生成を支援するAI Webアプリ
- 技術: FastAPI, Jinja2, LLM, Web検索グラウンディング
- ドキュメント: `exhibit/exhibit/README.md`

### 2. RAG
- パス: `RAG`
  - 説明: Neo4jナレッジグラフと13種のRAG手法を収めた実験プロジェクト
  - ドキュメント: `RAG/README.md`
- パス: `RAG/RAG/neo4j_knowledge_graph`
  - 説明: Neo4jベースの知識グラフ構築・可視化パイプライン
  - 技術: Neo4j, Python, Embeddings
  - ドキュメント: `RAG/RAG/neo4j_knowledge_graph/README.md`
- パス: `RAG/RAG/rag_benchmark`
  - 説明: 13種のRAG手法を比較評価する実験基盤
  - 技術: Python, ベクトル検索, RAGAS評価
  - ドキュメント: `RAG/RAG/rag_benchmark/README.md`

### 3. Web Search
- パス: `web_search`
  - 説明: Vertex AI と検索グラウンディングを使った調査パイプライン試作
  - ドキュメント: `web_search/README.md`
- パス: `web_search/web_search/grounding-test`
  - 説明: Google検索グラウンディングを利用した調査・要約ツールの試作
  - 技術: Python, Web検索, LLM要約
  - ドキュメント: `web_search/web_search/grounding-test/README.md`

## 使い方

1. 利用したいプロジェクトのフォルダに移動します。
2. Pythonの仮想環境を作成して有効化します。
3. 各プロジェクトの`README.md`または`requirements.txt`に従って依存関係をインストールします。
4. `.env`ファイルを使ってAPIキーや設定を管理します。

例:

```powershell
cd exhibit\exhibit
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 公開時の注意

- `README.md`や`PORTFOLIO_SUMMARY.md`の内容は公開用の説明として整理しています。
- `.gitignore`には環境変数ファイルやローカルデータ、ログなどが含まれているため、APIキーや機密情報を含むファイルをそのまま公開しないでください。
- 各プロジェクトで`.env.example`がある場合は、そこから環境変数をコピーしてローカルで設定してください。

## ポートフォリオとしての訴求ポイント

- AIワークフローの自動化
- LLMと検索/グラフを組み合わせた情報整理
- 実務に近いプロトタイプの構成
- ドキュメントを含めた再現性ある実装

## 追加整備の提案

- `web_search`プロジェクトにREADMEを追加して、使い方と目的を明記する
- 各プロジェクトのセットアップ手順と実行例を統一する
- GitHubに公開する際は、不要なローカルファイルが含まれないことを確認する
