# RAG ベンチマーク (13 手法 × 20 クエリ)

既に構築済みの Neo4j ナレッジグラフ (12 ノード / 18 リレーション / 7,678 Deal / 3,072 次元 embedding) を共通データ基盤として、世の中で精度の高い RAG 手法を **13 種類** 実装し、結果を JSON / CSV に保存する。RAGAS 準拠の v2 評価器で同一データを採点する。

## 実装手法一覧

| ID | 手法名 | 出典 | 概要 |
|---|---|---|---|
| R01 | Naive Vector RAG | LangChain 標準 | Vector Top-K → LLM |
| R02 | Vector + Reranker | Cohere/OpenAI | Vector Top-50 → LLM Rerank → Top-K |
| R03 | HyDE | Gao et al. 2023 | 仮想回答生成 → その埋め込みで検索 |
| R04 | GraphRAG Local | Microsoft 2024 | エンティティ起点サブグラフ探索 |
| R05 | GraphRAG Global | Microsoft 2024 | Community Summary map-reduce |
| R06 | LightRAG Hybrid | HKUDS 2024 | Dual-level Keyword + Graph |
| R07 | Contextual Retrieval | Anthropic 2024 | Vector + BM25 RRF + 文脈付加 |
| R08 | Agentic RAG | OpenAI / LangGraph | LLM が tool 自律ループ |
| R09 | RAPTOR | Stanford 2024 (Sarthi) | 階層クラスタ要約ツリーから各レベル取得 |
| R10 | Self-RAG | Asai et al. 2023 | Retrieve 判定 + 関連度評価 + 支持度評価 |
| R11 | Corrective RAG | Yan et al. 2024 | 関連度評価 + 低品質時のフォールバック検索 |
| R12 | RAG-Fusion | 2023 | クエリ生成 + RRF 融合 |
| R13 | Adaptive Ensemble | 本実装 | クエリ分類 → 動的に 2-3 手法を選択して合議 |

## セットアップ

```powershell
cd c:\Users\hitomi\source\eigyo
.\venv\Scripts\Activate.ps1
pip install -r RAG\rag_benchmark\requirements.txt
copy RAG\rag_benchmark\.env.example RAG\rag_benchmark\.env
# .env を編集
```

## 実行

```powershell
cd c:\Users\hitomi\source\eigyo\RAG

# ベンチマーク (13 手法 × 20 クエリ = 260 ジョブ)
python -m rag_benchmark.main --all --concurrency 4

# 特定手法/クエリのみ
python -m rag_benchmark.main --methods R09 R13 --queries Q01 Q02

# 集計のみ (既存 JSON から CSV 再生成)
python -m rag_benchmark.main --aggregate-only

# v2 RAGAS 評価 (Retrieval / Generation / Hallucination の 3 段階)
python -m rag_benchmark.evaluation.evaluate_main_v2 --concurrency 8

# v1 LLM 5 軸評価 (旧、後方互換のため残置)
python -m rag_benchmark.evaluation.evaluate_main

# 集計スクリプト (Q × 手法 ヒートマップ生成)
python rag_benchmark\scripts\aggregate_all_queries.py > rag_benchmark\output\_aggregate_all.txt
```

## ディレクトリ構成

```
rag_benchmark/
├── main.py                  # CLI エントリポイント
├── config.py                # 設定 (RETRIEVER_CONFIGS など)
├── query_set.py             # 20 クエリ定義 (specific 10 + global 10)
├── retrievers/              # R01-R13 (13 ファイル) + base.py
├── generator/               # answer_generator.py
├── evaluation/              # evaluator.py / evaluate_main.py (v1)
│                            # evaluator_v2.py / evaluate_main_v2.py (RAGAS 準拠)
├── tools/                   # search_tools.py (R08 用)
├── utils/                   # llm_client / neo4j_client / context_compressor /
│                            # query_analyzer / synonym_dict / rrf / lucene / token_counter
├── scripts/                 # aggregate_all_queries / analyze_weakness / summarize_eval など
├── docs/
│   └── TECHNICAL_REVIEW_INPUT.md   # 技術検討書作成用 (Claude 入力)
└── output/
    ├── results/             # R*_*.json (各手法 × 全 20 クエリ)
    ├── all_results.csv      # 横断集計
    ├── evaluation_v2_*.{json,csv}  # v2 RAGAS 結果
    ├── bench_run.log / eval_v2_run.log
    └── before_improvement/  # 一次改善前スナップショット (参考)
```

## 設計上の制約

- Neo4j は **読み取りのみ** (`session.execute_read` 限定)
- 全手法で `CONTEXT_MAX_TOKENS = 6000` 上限で公平比較
- Context Compression (4800 tokens 超 → 3000 文字に LLM 圧縮) と OK/NG フィルタ (`query_analyzer`) が全手法デフォルト有効
- 1 ファイル = 1 Retriever の原則

## 評価軸

### v2 (RAGAS 準拠) — 推奨

- **Retrieval (重み 0.4)**: context_precision / context_recall / context_relevancy の平均
- **Generation (重み 0.5)**: faithfulness / answer_relevancy / answer_completeness の平均
- **Keyword (重み 0.1)**: 同義語辞書込みの期待 keyword 出現率
- **Hallucination (参考)**: not_supported 主張 / 全主張
- **Latency (参考)**: composite には含めない

`composite = (retrieval × 0.4 + generation × 0.5 + keyword × 0.1) × 100`

診断 (`diagnose`):
- `retrieval_failure`: retrieval < 0.4 かつ generation > 0.6
- `generation_failure`: retrieval > 0.6 かつ generation < 0.4
- `both_weak` / `both_good` / `mixed`

### v1 (LLM 5 軸) — 旧

relevance / accuracy / completeness / specificity / structure の平均 + speed_score + keyword_coverage を合成。後方互換のため残置。

## ドキュメント

- 技術検討書の素材は [docs/TECHNICAL_REVIEW_INPUT.md](docs/TECHNICAL_REVIEW_INPUT.md) を Claude に渡す
