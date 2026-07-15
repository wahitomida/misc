# RAG 13 手法 × 20 クエリ 技術検討書 入力資料 (Claude 用)

> 本文書は `RAG/rag_benchmark/` の最新ベンチマーク (NEW 改善版・全 13 手法 × 全 20 クエリ = 260 ジョブ) と
> RAGAS 準拠 v2 評価結果を、Claude が技術検討書を書くのに必要十分な形で集約したもの。
>
> - ベンチマーク実行: 2026-06-18 10:11-10:30
> - v2 評価実行: 2026-06-18 10:36-10:44
> - 元データ: `output/results/R*.json`, `output/evaluation_v2_*.{json,csv}`, `output/_aggregate_all.txt`

---

## 1. ベンチマーク基盤

| 項目 | 値 |
|---|---|
| Knowledge Graph | Neo4j 5.24 / 7,678 Deal / 12 ノード × 18 リレーション |
| Deal embedding | text-embedding-3-large (3072 次元) |
| LLM (chat / 評価) | Azure OpenAI gpt-4o (temperature=0.0、評価器は JSON mode) |
| Cluster 数 | 264 (cluster_objective_fulltext index 利用) |
| 共通制約 | CONTEXT_MAX_TOKENS=6000、Neo4j 読み取り専用、1 ファイル 1 Retriever |
| 共通改善 | OK/NG フィルタ ON、Context Compression ON (4800 tokens 超 → 3000 文字)、Cluster Embedding Cache ON |

## 2. 評価設計 (v2 RAGAS 準拠)

| 軸 | サブ指標 | 重み | 採点者 | 入力 |
|---|---|---:|---|---|
| Retrieval | context_precision / context_recall / context_relevancy の平均 | 0.4 | LLM | コンテキストのみ（回答は見せない） |
| Generation | faithfulness / answer_relevancy / answer_completeness の平均 | 0.5 | LLM | コンテキスト + 回答 |
| Keyword | 同義語辞書込みの期待 keyword 出現率 | 0.1 | プログラム | 回答テキスト |
| Hallucination | not_supported 主張 / 全主張 | 参考 | LLM | 主張ごとに supported / partially_supported / not_supported |
| Latency | total_time_ms | 参考 | プログラム | composite には含めない |

`composite = (retrieval × 0.4 + generation × 0.5 + keyword × 0.1) × 100`

診断ラベル:
- `retrieval_failure`: retrieval < 0.4 かつ generation > 0.6
- `generation_failure`: retrieval > 0.6 かつ generation < 0.4
- `both_weak` / `both_good` / `mixed`

---

## 3. 全体ランキング (260 ジョブ、composite_score 降順)

| 順位 | ID | 手法 | composite | retrieval | generation | faithful | hall | keyword | latency |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | **R11** | Corrective RAG | **73.93** | 0.593 | 0.885 | **0.910** | 0.021 | 0.596 | 15.4 s |
| 2 | **R09** | RAPTOR | 73.79 | 0.615 | 0.835 | 0.835 | 0.015 | **0.746** | **10.0 s** |
| 3 | **R05** | GraphRAG Global | 72.32 | **0.684** | 0.753 | 0.765 | **0.085** | 0.729 | 32.6 s |
| 4 | R03 | HyDE | 71.76 | 0.582 | 0.840 | 0.895 | **0.000** | 0.650 | 13.1 s |
| 5 | R13 | Adaptive Ensemble | 71.33 | 0.595 | 0.817 | 0.850 | 0.005 | 0.671 | 22.5 s |
| 6 | R06 | LightRAG Hybrid | 70.81 | 0.549 | 0.858 | **0.910** | 0.014 | 0.592 | **9.0 s** |
| 7 | R01 | Naive Vector RAG | 68.16 | 0.460 | **0.873** | 0.910 | 0.042 | 0.608 | **8.0 s** |
| 8 | R02 | Vector + Reranker | 68.06 | 0.521 | 0.818 | 0.850 | 0.005 | 0.629 | 16.9 s |
| 9 | R04 | GraphRAG Local | 67.86 | 0.480 | 0.840 | 0.880 | 0.032 | 0.667 | 13.7 s |
| 10 | R10 | Self-RAG | 67.83 | 0.478 | 0.847 | 0.880 | **0.000** | 0.637 | 14.4 s |
| 11 | R12 | RAG-Fusion | 66.27 | 0.453 | 0.828 | 0.875 | 0.026 | 0.671 | 19.0 s |
| 12 | R07 | Contextual Retrieval | 65.78 | 0.515 | 0.788 | 0.815 | 0.005 | 0.575 | 14.3 s |
| 13 | R08 | Agentic RAG | 64.81 | 0.454 | 0.805 | 0.840 | 0.033 | 0.637 | 18.3 s |

**観察**:
- composite トップは R11 (73.93)、ボトムは R08 (64.81)。**差は 9.12 pt** — 全 13 手法が同水準帯に収束 (改善前の差 19.66 から大幅縮小)
- R05 GraphRAG Global は retrieval 1 位だが hallucination 0.085 (最悪) で順位を落とす
- R03 HyDE と R10 Self-RAG は hallucination 0.000、本番運用での信頼性に強い
- R09 RAPTOR は generation 0.835、latency 10.0 秒で **コストパフォーマンス最強**

---

## 4. クエリ別 composite ヒートマップ

太字: 各 Q のトップ。

| Q | type | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 | R12 | R13 | Q平均 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Q01 | spe | 84.0 | 66.7 | 83.3 | **89.6** | 74.7 | 68.3 | 86.7 | 74.9 | 78.3 | 63.4 | 71.7 | 84.6 | 67.3 | 76.4 |
| Q02 | spe | 81.0 | 90.7 | 86.0 | 92.0 | 92.8 | 51.9 | 89.5 | 89.6 | 90.8 | 87.1 | 88.2 | 80.0 | **93.3** | 85.6 |
| Q03 | spe | 87.1 | 89.5 | 89.6 | 74.0 | 77.8 | 86.4 | 84.2 | 90.8 | 88.3 | 82.1 | **93.5** | 63.2 | 80.8 | 83.6 |
| Q04 | spe | 73.0 | 59.7 | 51.7 | 51.7 | 71.0 | 71.8 | 62.3 | 56.3 | **77.3** | **77.3** | 68.3 | 63.0 | 63.0 | 65.1 |
| Q05 | spe | 78.0 | **87.3** | 67.0 | 78.0 | 74.7 | 51.7 | 67.0 | 50.0 | 73.3 | 74.4 | 76.7 | 84.0 | 76.7 | 72.2 |
| Q06 | spe | 86.3 | 78.4 | 80.0 | 76.4 | 85.3 | 80.0 | 70.7 | 76.7 | 70.0 | 80.4 | **90.0** | 72.7 | 70.0 | 78.2 |
| Q07 | spe | 76.0 | **78.4** | 63.0 | 70.0 | 78.0 | 60.0 | 72.0 | 60.0 | 73.1 | 75.0 | 77.7 | 77.7 | 76.7 | 72.1 |
| Q08 | spe | 76.3 | 90.7 | 76.0 | 68.0 | 82.0 | 72.7 | 86.7 | 79.7 | 76.7 | 80.7 | **92.0** | 58.4 | 74.7 | 78.0 |
| Q09 | spe | 84.7 | 74.3 | 51.0 | 77.3 | 84.0 | 61.7 | **85.3** | 73.0 | 72.6 | 76.4 | 55.0 | 68.0 | 63.4 | 71.3 |
| Q10 | spe | 64.6 | 53.4 | 56.1 | 53.7 | 6.7 | 43.3 | 61.4 | 81.3 | 51.7 | 77.3 | **93.1** | 63.7 | 72.1 | 59.9 |
| Q11 | glo | 57.0 | 46.8 | **71.7** | 49.3 | 55.0 | 63.3 | 40.4 | 33.7 | 49.0 | 35.0 | 60.0 | 43.4 | 56.6 | 50.9 |
| Q12 | glo | 50.0 | 66.7 | **88.5** | 60.0 | 80.3 | 83.8 | 66.0 | 76.7 | 68.2 | 66.0 | 65.6 | 56.0 | 83.8 | 70.1 |
| Q13 | glo | 61.3 | 38.4 | 74.2 | 77.5 | 75.3 | **90.6** | 61.7 | 72.0 | 89.5 | 60.0 | 67.5 | 70.3 | 83.1 | 70.9 |
| Q14 | glo | 52.0 | 40.9 | 46.9 | 59.9 | 71.7 | **79.2** | 50.0 | 46.7 | 66.7 | 33.4 | 55.1 | 43.4 | 40.9 | 52.8 |
| Q15 | glo | 43.7 | 55.0 | 58.0 | 50.0 | 61.4 | 62.7 | 20.0 | 45.0 | **92.0** | 52.0 | 55.0 | 70.0 | 46.1 | 54.7 |
| Q16 | glo | 88.3 | 87.3 | 86.3 | 90.0 | 76.7 | 66.7 | 87.3 | 76.7 | 83.3 | 87.9 | 86.7 | **92.0** | 85.3 | 84.2 |
| Q17 | glo | 53.0 | 70.0 | **90.0** | 61.3 | 73.7 | 82.3 | 48.4 | 44.4 | 67.0 | 79.8 | 73.3 | 47.7 | 58.4 | 65.3 |
| Q18 | glo | 41.6 | 28.4 | 36.6 | 36.6 | 47.7 | **75.0** | 41.7 | 41.0 | 66.7 | 28.4 | 45.0 | 45.0 | **75.0** | 46.8 |
| Q19 | glo | 71.0 | 76.7 | **88.7** | 60.6 | 86.7 | 73.3 | 52.7 | 56.0 | 61.3 | 71.3 | 77.3 | 66.0 | 73.3 | 70.4 |
| Q20 | glo | 54.3 | 82.2 | 90.8 | 81.3 | **91.2** | **91.5** | 81.7 | 71.7 | 79.9 | 68.8 | 86.8 | 76.4 | 86.2 | 80.2 |
| avg |  | 68.2 | 68.1 | 71.8 | 67.9 | 72.3 | 70.8 | 65.8 | 64.8 | **73.8** | 67.8 | **73.9** | 66.3 | 71.3 | — |

**観察**:
- クエリ別ベストが多手法に分散 → 単一手法では全カバー困難
- specific 平均 76.3 vs global 平均 64.6 → global が一様に難しい (-11.7 pt)
- 最難 Q ベスト 3: Q18 (46.8), Q11 (50.9), Q14 (52.8) — すべて global で「データに直接答えがない」性質
- 最易 Q ベスト 3: Q02 (85.6), Q16 (84.2), Q03 (83.6) — 具体・事例検索が得意
- **手法別最頻トップ**: R03 4 Q (Q11/Q12/Q17/Q19)、R05 2 Q、R06 3 Q (Q13/Q14/Q18)、R09 2 Q (Q04/Q15)、R11 4 Q (Q03/Q06/Q08/Q10)
- 改善前 R05 が圧倒的だったが、改善後は **R11, R03, R06, R09 など多様な手法が頭角**

---

## 5. クエリ別 retrieval_score ヒートマップ

| Q | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 | R12 | R13 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Q01 | 0.60 | 0.42 | 0.58 | **0.74** | 0.45 | 0.58 | 0.67 | 0.71 | **0.83** | 0.46 | 0.42 | **0.74** | 0.60 |
| Q02 | 0.59 | 0.77 | 0.65 | 0.80 | **0.88** | 0.40 | 0.80 | 0.74 | 0.83 | 0.74 | 0.77 | 0.50 | 0.83 |
| Q03 | 0.74 | 0.80 | 0.74 | 0.68 | **0.88** | 0.72 | 0.67 | 0.83 | 0.77 | 0.74 | **0.90** | 0.68 | 0.83 |
| Q04 | 0.45 | 0.62 | 0.50 | 0.42 | 0.73 | **0.92** | 0.68 | 0.53 | 0.77 | 0.68 | 0.75 | 0.62 | 0.62 |
| Q05 | 0.53 | **0.77** | 0.51 | 0.53 | 0.70 | 0.42 | 0.51 | 0.29 | 0.42 | 0.44 | 0.50 | 0.68 | 0.50 |
| Q06 | 0.66 | 0.46 | 0.50 | 0.41 | **0.88** | 0.50 | 0.52 | 0.42 | 0.25 | 0.51 | 0.75 | 0.32 | 0.50 |
| Q07 | 0.40 | 0.46 | 0.41 | 0.25 | 0.45 | 0.00 | 0.30 | 0.00 | 0.33 | **0.50** | 0.44 | 0.44 | 0.42 |
| Q08 | 0.53 | 0.77 | 0.65 | 0.53 | **0.80** | 0.40 | 0.67 | 0.62 | 0.67 | 0.77 | **0.80** | 0.50 | 0.62 |
| Q09 | 0.70 | 0.69 | 0.40 | 0.52 | 0.68 | 0.50 | **0.72** | 0.53 | **0.73** | 0.66 | 0.50 | 0.53 | 0.42 |
| Q10 | 0.74 | 0.46 | 0.44 | 0.38 | 0.00 | 0.00 | 0.66 | 0.53 | 0.42 | 0.68 | 0.83 | 0.72 | **0.84** |
| Q11 | 0.30 | 0.46 | **0.67** | 0.32 | **0.67** | **0.67** | 0.30 | 0.38 | 0.52 | 0.17 | 0.25 | 0.00 | 0.50 |
| Q12 | 0.00 | 0.42 | **0.90** | 0.25 | 0.88 | 0.78 | 0.40 | 0.67 | 0.52 | 0.40 | 0.64 | 0.15 | 0.78 |
| Q13 | 0.28 | 0.00 | 0.42 | 0.50 | 0.80 | **0.83** | 0.58 | 0.30 | 0.80 | 0.00 | 0.50 | 0.51 | 0.64 |
| Q14 | 0.30 | 0.25 | 0.40 | 0.60 | **0.67** | **0.67** | 0.25 | 0.33 | **0.67** | 0.00 | 0.40 | 0.25 | 0.25 |
| Q15 | 0.38 | 0.46 | 0.74 | 0.42 | 0.70 | 0.44 | 0.17 | 0.42 | **0.80** | 0.38 | 0.67 | 0.50 | 0.44 |
| Q16 | 0.71 | 0.68 | 0.74 | **0.83** | 0.50 | 0.50 | 0.77 | 0.42 | 0.67 | 0.70 | 0.75 | 0.80 | 0.72 |
| Q17 | 0.53 | 0.67 | 0.83 | 0.45 | **0.88** | 0.64 | 0.42 | 0.32 | 0.55 | 0.66 | 0.50 | 0.40 | 0.50 |
| Q18 | 0.00 | 0.00 | 0.00 | 0.00 | 0.40 | **0.67** | 0.25 | 0.32 | 0.50 | 0.00 | 0.00 | 0.00 | **0.67** |
| Q19 | 0.44 | 0.67 | 0.72 | 0.43 | **0.83** | 0.50 | 0.32 | 0.32 | 0.45 | 0.53 | 0.77 | 0.32 | 0.50 |
| Q20 | 0.32 | 0.62 | 0.83 | 0.53 | **0.88** | **0.85** | 0.67 | 0.42 | 0.81 | 0.53 | 0.73 | 0.41 | 0.72 |
| avg | 0.46 | 0.52 | 0.58 | 0.48 | **0.68** | 0.55 | 0.52 | 0.45 | 0.61 | 0.48 | 0.59 | 0.45 | 0.59 |

**観察**:
- R05 が 13 Q で retrieval トップ — Community summary が「広域横断」に最強
- R09 RAPTOR が 6 Q でトップ — 階層集約が specific/global 両方で安定
- **retrieval = 0.0 が発生する Q**: Q07 (R06/R08)、Q10 (R05/R06)、Q12 (R01)、Q13 (R02/R10)、Q14 (R10)、Q18 (R01/R02/R03/R04/R10/R11/R12) — Q18 業界別比較がもっとも難しい
- R12 RAG-Fusion は retrieval 平均 0.45 で最下位、4 バリエーション生成が逆に「query intent を曖昧化」した可能性

---

## 6. クエリ別 generation_score ヒートマップ

| Q | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 | R12 | R13 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Q01 | 1.00 | 0.80 | 1.00 | 1.00 | 0.93 | 0.70 | 1.00 | 0.73 | 0.70 | 0.70 | 0.90 | 0.90 | 0.67 |
| Q02 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.57 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q03 | 1.00 | 1.00 | 1.00 | 0.73 | 0.70 | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 1.00 | 0.57 | 0.80 |
| Q04 | 0.90 | 0.57 | 0.57 | 0.57 | 0.63 | 0.57 | 0.57 | 0.57 | 0.73 | 0.80 | 0.63 | 0.57 | 0.57 |
| Q05 | 1.00 | 1.00 | 0.80 | 1.00 | 0.80 | 0.57 | 0.80 | 0.57 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q06 | 1.00 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.80 |
| Q07 | 1.00 | 1.00 | 0.73 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 1.00 | 1.00 | 1.00 |
| Q08 | 0.90 | 1.00 | 0.80 | 0.73 | 0.80 | 1.00 | 1.00 | 0.90 | 0.80 | 0.80 | 1.00 | 0.57 | 0.80 |
| Q09 | 1.00 | 0.80 | 0.57 | 1.00 | 1.00 | 0.70 | 1.00 | 0.90 | 0.73 | 0.80 | 0.57 | 0.80 | 0.80 |
| Q10 | 0.57 | 0.57 | 0.57 | 0.57 | **0.00** | 0.73 | 0.57 | 1.00 | 0.57 | 0.80 | 1.00 | 0.57 | 0.57 |
| Q11 | 0.90 | 0.57 | 0.90 | 0.73 | 0.57 | 0.73 | 0.57 | **0.37** | 0.57 | 0.57 | 1.00 | 0.87 | 0.73 |
| Q12 | 1.00 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 0.80 | 1.00 | 1.00 |
| Q13 | 0.80 | 0.57 | 1.00 | 1.00 | 0.67 | 1.00 | 0.57 | 1.00 | 1.00 | 1.00 | 0.80 | 0.80 | 1.00 |
| Q14 | 0.70 | 0.57 | 0.57 | 0.57 | 0.70 | 1.00 | 0.70 | 0.57 | 0.70 | 0.57 | 0.73 | 0.57 | 0.57 |
| Q15 | 0.57 | 0.63 | 0.57 | 0.57 | 0.57 | 0.90 | **0.27** | 0.57 | 1.00 | 0.73 | 0.57 | 0.90 | 0.57 |
| Q16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Q17 | 0.57 | 0.80 | 1.00 | 0.80 | 0.57 | 1.00 | 0.57 | 0.57 | 0.70 | 1.00 | 1.00 | 0.57 | 0.57 |
| Q18 | 0.83 | 0.57 | 0.73 | 0.73 | 0.57 | 0.90 | 0.57 | 0.57 | 0.80 | 0.57 | 0.90 | 0.90 | 0.90 |
| Q19 | 1.00 | 0.93 | 1.00 | 0.80 | 1.00 | 1.00 | 0.80 | 0.80 | 0.80 | 1.00 | 0.80 | 1.00 | 1.00 |
| Q20 | 0.73 | 1.00 | 1.00 | 1.00 | 0.97 | 1.00 | 1.00 | 1.00 | 0.80 | 0.80 | 1.00 | 1.00 | 1.00 |
| avg | **0.87** | 0.82 | 0.84 | 0.84 | 0.75 | 0.86 | 0.79 | 0.81 | 0.83 | 0.85 | **0.89** | 0.83 | 0.82 |

**観察**:
- R11 Corrective RAG が generation 平均 0.89 で最高
- R01 Naive Vector が 0.87 と 2 位 — シンプルな vector でも generation は十分高い (= 「LLM が乏しい retrieval をカバーする」現象)
- **generation = 0.00** という致命: R05 Q10「EtherNet/IP 通信の成約傾向」で **answer_relevancy = 0.00 / completeness = 0.00**
  - 期待方向「NG 傾向」に対し R05 は「成約に至っている傾向あり」と逆方向結論 → 完全な期待外れ
  - 別ジョブ R05 Q10 では community summary が OK 寄り deal で埋まり、生成が引きずられた
- R08 Q11 で generation 0.37、R07 Q15 で 0.27 — both_weak 診断の典型

---

## 7. クエリ別 hallucination_rate ヒートマップ

| Q | R01 | R02 | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 | R12 | R13 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Q02 | 0 | 0 | 0 | 0 | 0.20 | **0.29** | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 |
| Q03 | 0 | 0 | 0 | 0 | 0.20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q04 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q05 | 0 | 0 | 0 | 0 | 0.25 | 0 | 0 | 0.12 | 0 | 0 | 0 | 0 | 0 |
| Q06 | 0.20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 |
| Q07 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q08 | 0 | 0 | 0 | **0.33** | 0.14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.10 |
| Q09 | 0 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0.20 | 0.10 | 0 |
| Q10 | 0.14 | 0 | 0 | 0 | 0 | 0 | 0 | 0.20 | 0 | 0 | 0 | 0 | 0 |
| Q11 | 0 | 0 | 0 | 0 | 0.20 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 |
| Q12 | 0 | 0 | 0 | 0 | 0.20 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 |
| Q13 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.17 | 0 |
| Q15 | **0.40** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q17 | 0 | 0 | 0 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q18 | 0 | 0 | 0 | 0.11 | 0 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 |
| Q19 | 0 | 0 | 0 | 0.10 | 0.30 | 0 | 0 | 0.14 | 0 | 0 | 0.10 | 0.14 | 0 |
| Q20 | 0 | 0 | 0 | 0 | 0.10 | 0 | 0 | 0 | 0 | 0 | 0.12 | 0.10 | 0 |
| avg | 0.04 | 0.01 | **0.00** | 0.03 | **0.08** | 0.01 | 0.01 | 0.03 | 0.02 | **0.00** | 0.02 | 0.03 | 0.01 |

**観察**:
- R03 / R10 が hallucination 平均 0.00 — 主張がすべてコンテキストに裏付けられる
- R05 が 0.08 で最悪 — Community summary 経由で外挿しやすい
- 突出値: R01 Q15 (0.40)、R04 Q08 (0.33)、R06 Q02 (0.29)、R05 Q19 (0.30)、R02 / R06 / R09 / R10 はほぼ全 Q で 0 安定

---

## 8. 手法別プロファイル

各手法について戦略・強み・弱み・推奨ユースケースを記載。

### R01 Naive Vector RAG — composite 7 位 (68.16)
- 戦略: Deal.content_embedding と質問 embed の cosine 類似度 Top-15、OK/NG フィルタ ON
- 強み: latency 8.0 秒で最速、generation 平均 0.87 で 2 位、Q03/Q12/Q16 で composite 80 超
- 弱み: retrieval 平均 0.46 (下位)、Q12/Q15/Q18 で hallucination 高
- 推奨: チャットボットのデフォルト、低リソース環境

### R02 Vector + Reranker — composite 8 位 (68.06)
- 戦略: Vector Top-50 を LLM (gpt-4o) で 1-5 再採点 → Top-K
- 強み: hallucination 0.01、Q05 Q07 でトップ
- 弱み: latency 16.9 秒で中速、rerank コスト分の品質向上が限定的
- 推奨: 説明責任が問われる用途、NG Deal を含めた多面取得

### R03 HyDE — composite 4 位 (71.76)
- 戦略: 質問から仮想回答を LLM 生成 → その embedding で検索
- 強み: **hallucination 0.00** (1 位)、Q11/Q12/Q17/Q19 で 4 Q トップ — global 質問に異常な強さ
- 弱み: Q04/Q09/Q15 で composite 60 未満、retrieval が振れる
- 推奨: global / 推奨型クエリ、信頼性最優先

### R04 GraphRAG Local — composite 9 位 (67.86)
- 戦略: seed Deal から 1-hop 拡張 (Cluster/Customer/Industry)
- 強み: Q01 (89.6) と Q16 (90.0) でトップ、latency 13.7 秒
- 弱み: Q07/Q18/Q19 で hallucination 0.10 以上、global で弱い
- 推奨: 具体クエリで「関連 Deal を網羅」したいとき

### R05 GraphRAG Global — composite 3 位 (72.32)
- 戦略: 264 Cluster summary を全件 embed → 類似 Top-N Cluster の Deal 集約
- 強み: **retrieval 平均 0.68 (1 位)**、13 Q で retrieval トップ、Q20 (91.2) で苦手領域整理に最強
- 弱み: **Q10 で composite 6.7 / generation 0.00** という致命、hallucination 0.08 (最悪)、latency 32.6 秒
- 推奨: 概念整理・俯瞰要約、苦手領域抽出 (Q20 型)。Q10 のような「逆方向結論」リスクは要監視

### R06 LightRAG Hybrid — composite 6 位 (70.81)
- 戦略: Vector + Lucene Fulltext + Cluster 相関のハイブリッドスコア
- 強み: **latency 9.0 秒で最速級**、Q13/Q14/Q18 でトップ — global で意外に強い
- 弱み: Q02 で composite 51.9 / retrieval 0.40 / hallucination 0.29 — Fulltext が外すと致命
- 推奨: 「キーワード明確な global クエリ」、低レイテンシ要件

### R07 Contextual Retrieval — composite 12 位 (65.78)
- 戦略: Deal 文脈 (Customer/Industry/Cluster) を prepend した embed + fulltext を RRF 融合
- 強み: Q09 でトップ (85.3)、latency 14.3 秒、hallucination 0.01
- 弱み: Q11/Q15/Q17/Q19 で composite 50 台、global で弱い
- 推奨: specific クエリで「文脈付加」が効くもの

### R08 Agentic RAG — composite 13 位 (64.81)
- 戦略: LLM が tool 自律呼び出し (vector_search → graph_traverse → cluster_summary → fulltext)
- 強み: Q10 で 2 位 (81.3)、tool 多面探索の柔軟性
- 弱み: composite 最下位、Q11 で both_weak、hallucination 0.03、latency 18.3 秒
- 推奨: 個別 Deal の深掘り調査 (一括クエリには不向き)

### R09 RAPTOR — composite 2 位 (73.79)
- 戦略: Level0 (Deal Vector) + Level1 (Cluster summary) + Level2 (Industry summary) の階層集約
- 強み: **keyword_coverage 0.746 (1 位)**、latency 10.0 秒、Q04 Q15 でトップ、hallucination 0.02、安定
- 弱み: Q07 で 73.1 (retrieval 0.33)、特定タスクで他に譲る
- 推奨: **本番デフォルト最有力**。コスパ最強

### R10 Self-RAG — composite 10 位 (67.83)
- 戦略: 検索 yes/no 判定 → Vector → 自己評価 (supported / partially_supported / not_supported)
- 強み: **hallucination 0.00**、Q04 でトップ
- 弱み: Q11/Q14/Q18 で retrieval 0.00 — need_retrieval=False と判定して外す
- 推奨: 説明責任、不確実性を回答に明示したい場合

### R11 Corrective RAG — composite **1 位 (73.93)**
- 戦略: Vector → 関連度評価 (1-5) → 低品質なら fulltext_subquery で補強
- 強み: **composite 1 位**、**generation 0.89 (1 位)**、Q03 Q06 Q08 Q10 で 4 Q トップ、faithfulness 0.91 (1 位)、Q10 で唯一 90 超
- 弱み: Q09 で composite 55 / hallucination 0.20、keyword 平均 0.596 (下位)
- 推奨: 「品質最優先」の本番、retrieval が振るわなくても compensation が効く

### R12 RAG-Fusion — composite 11 位 (66.27)
- 戦略: 4 バリエーション生成 + RRF 融合
- 強み: Q16 でトップ (92.0)
- 弱み: retrieval 平均 0.45 で最下位、4 バリエーション生成が intent を曖昧化
- 推奨: 「複数の問いを束ねたい」横断質問。単発 specific では不利

### R13 Adaptive Ensemble — composite 5 位 (71.33)
- 戦略: LLM がクエリ分類 → STRATEGY_MAP で 2-3 手法を選択 → 結果合議
- 強み: Q02 Q18 でトップ、global で安定
- 弱み: latency 22.5 秒、selected_methods が固定化されると ensemble の意味が薄れる
- 推奨: 「クエリの性質が不明な汎用エージェント」

---

## 9. 横断的考察

### 9.1 specific vs global の難易度差

| type | クエリ平均 composite | クエリ平均 retrieval | クエリ平均 generation |
|---|---:|---:|---:|
| specific (Q01-Q10) | **76.3** | **0.57** | **0.86** |
| global (Q11-Q20) | **64.6** | **0.41** | **0.80** |

- global は retrieval が 16 pt 低い → 「データに直接答えがない/広域横断要求」が困難の本質
- generation は global で 6 pt 下がるのみ → LLM は global でもそれなりの回答を作る (ハルシネーションリスク)

### 9.2 改善前 (OLD) vs 改善後 (NEW) の比較

OLD ベースライン (`output/before_improvement/`) との composite 差:

| 手法 | OLD | NEW | Δ |
|---|---:|---:|---:|
| R11 Corrective RAG | 66.14 | **73.93** | **+7.79** |
| R08 Agentic RAG | 56.31 | 64.81 | **+8.50** |
| R06 LightRAG Hybrid | 63.60 | 70.81 | **+7.21** |
| R03 HyDE | 68.07 | 71.76 | +3.69 |
| R09 RAPTOR | 70.64 | 73.79 | +3.15 |
| R12 RAG-Fusion | 64.42 | 66.27 | +1.85 |
| R04 GraphRAG Local | 64.51 | 67.86 | +3.35 |
| R07 Contextual Retrieval | 64.32 | 65.78 | +1.46 |
| R10 Self-RAG | 68.81 | 67.83 | -0.98 |
| R02 Vector + Reranker | 65.23 | 68.06 | +2.83 |
| R01 Naive Vector RAG | 65.64 | 68.16 | +2.52 |
| R13 Adaptive Ensemble | 74.01 | 71.33 | -2.68 |
| R05 GraphRAG Global | **75.97** | 72.32 | **-3.65** |

- 11 手法が改善、2 手法 (R05 / R13 / R10) が悪化
- R05 悪化は Q10 致命的失敗 (composite 6.7) が原因
- 全体差が縮小 (改善前差 19.66 → 改善後差 9.12)
- 改善幅トップは R08 (+8.50)、R11 (+7.79)、R06 (+7.21)

### 9.3 手法カテゴリ別の強み

| カテゴリ | 該当 | 強み Q | 弱み Q |
|---|---|---|---|
| 単純検索系 | R01, R02 | specific 多数 | global Q14/Q18 |
| Query 変換系 | R03 HyDE, R12 RAG-Fusion | R03 が global 4 連覇 | R12 は retrieval 最下位 |
| Graph 集約 | R04 Local, R05 Global | R05 retrieval トップ、R04 Q01/Q16 | R05 Q10 致命 |
| Hybrid | R06, R07 | R06 global Q13/Q14/Q18 で強い | R07 Q15 で 20.0 |
| 階層集約 | R09 RAPTOR | Q15 圧勝 + 安定上位 | (突出した弱みなし) |
| Self-evaluation | R10 Self-RAG, R11 Corrective | R11 composite 1 位 | R10 Q11/Q14/Q18 で 0 retrieval |
| Agent/Ensemble | R08 Agentic, R13 Ensemble | R13 Q02/Q18 トップ | R08 最下位 |

### 9.4 R10 Q10 (EtherNet/IP の致命的失敗)

- R05 GraphRAG Global で composite 6.7、retrieval 0.00、generation 0.00
- 原因: community summary が OK 寄りの deal で埋まり「成約傾向あり」と OK 方向に結論
- 真の答え (NG 傾向) と真逆 → answer_relevancy = 0、completeness = 0
- 同じ Q10 を R11 (93.1) / R10 (77.3) は正しく NG 傾向と回答
- **示唆**: community summary に依存する手法は OK/NG バランスが偏った話題で逆方向リスクあり

### 9.5 hallucination の発生源

| 手法 | hall_rate ≥ 0.10 の Q 数 | 該当 Q |
|---|---:|---|
| R05 GraphRAG Global | 8 | Q02, Q03, Q05, Q08, Q09, Q11, Q12, Q19, Q20 |
| R04 GraphRAG Local | 2 | Q08 (0.33), Q18 |
| R01 Naive Vector | 2 | Q06, Q10, Q15 (0.40) |
| R08 Agentic RAG | 2 | Q10, Q12, Q19 |
| その他 | ≤ 1 | — |

- Community / cluster summary 依存手法 (R05) でハルシネーション集中
- R03 HyDE / R10 Self-RAG は完璧 (0.00 全 Q)

### 9.6 速度と品質のトレードオフ

| latency 層 | 手法 | 平均 composite |
|---|---|---:|
| 高速 (< 10 秒) | R01 (8.0s), R06 (9.0s), R09 (10.0s) | **70.9** (3 手法平均) |
| 中速 (10-20 秒) | R03/R04/R07/R10/R11/R02/R08 | 68.6 |
| 低速 (> 20 秒) | R13 (22.5s), R05 (32.6s) | 71.8 |

- R09 RAPTOR が **「高速 + composite 73.79」** で唯一突出
- 速度を犠牲にして品質を狙う R05 が R09 とほぼ同等 (差 1.5 pt) → コスパで R09 圧勝

---

## 10. シナリオ別推奨マトリクス

| 用途 | 第一推奨 | 第二推奨 | 理由 |
|---|---|---|---|
| 本番デフォルト (チャットボット) | **R09 RAPTOR** | R11 Corrective RAG | 高速 (10s) + composite 2 位 + hallucination 0.02 |
| 品質最優先 (オフライン KPI 算出) | **R11 Corrective RAG** | R09 RAPTOR | composite 1 位、generation 0.89、Q10 で唯一 90 超 |
| 説明責任重視 (法務・監査) | **R03 HyDE** | R10 Self-RAG | hallucination 0.00 (全 Q)、faithfulness 0.90 / 0.88 |
| 概念整理・俯瞰要約 | **R05 GraphRAG Global** | R09 RAPTOR | retrieval 0.68 (1 位)、Q20 で 91.2、Community summary が効く |
| 苦手領域・NG 抽出 (Q20 型) | **R05** または **R06** | R03 | R06 Q20 で 91.5 / R05 Q20 で 91.2 |
| 業界別比較 (Q18 型) | **R13 Adaptive Ensemble** または **R06** | R09 | 他は 0 点台、R13/R06 のみ 75 点 |
| 推奨提示 (Q19 型) | **R03 HyDE** | R05 | HyDE が 88.7 で唯一突出 |
| 低レイテンシ要件 | **R01 Naive Vector** または **R06** | R09 | 8-10 秒 |
| 業務クエリの自動振り分け | **R13 Adaptive Ensemble** | R09 | LLM が手法を選ぶ |

**避けるべき組み合わせ**:
- 「具体性必要」× R05 GraphRAG Global (community summary は具体 Deal を返さない)
- 「OK/NG 偏った話題で逆方向結論を求める」× R05 (Q10 で実証された致命)
- 「速度重視」× R05 / R13 (20 秒超)
- 「コスト感度高」× R08 Agentic RAG (LLM tool call 反復)

---

## 11. 実装上の主要発見

1. **OK/NG フィルタ + Context Compression が効いた**
   - 11 手法で composite 改善、改善幅トップは R08 (+8.50)
   - R05 / R13 / R10 は微減 (community / ensemble は context 削減でかえって精度低下のことも)

2. **R09 RAPTOR の階層集約が「素」で強い**
   - Level0/1/2 の重み付け合算で specific/global 両方をバランスよくカバー
   - 追加チューニング不要で本番デフォルトに最適

3. **R11 Corrective RAG の補強検索 (fulltext_subquery) が安定**
   - 関連度が ambiguous なときに発動 → faithfulness 0.91 (1 位)
   - generation 0.89 と高いのは「補強で正しい情報が取れているから」

4. **R03 HyDE は global に強い**
   - 仮想回答経由で「概念的に近い deal」を取れる
   - Q11 (OK 共通パターン)、Q12 (NG 失注理由)、Q17 (訴求ポイント)、Q19 (推奨) の 4 連覇

5. **R05 GraphRAG Global の弱点**
   - retrieval は最強だが、community summary が OK/NG 偏りで逆方向結論を生む
   - Q10 のように真逆を答えると composite 6.7 という致命
   - 単独運用ではなく R13 ensemble の一部として使うのが安全

6. **Q18 業界別比較の構造的困難**
   - 7 手法で retrieval = 0.00 — データに業界比較情報が薄い
   - R06 (75.0) と R13 (75.0) のみ 70 点超

7. **ファイル名規約の不備を修正済み**
   - main.py の `_METHOD_FILE_SUFFIX` に R12/R13 を追加
   - 旧バージョンでは `R12_r12.json` / `R13_r13.json` のフォールバック名になっていた

---

## 12. 残課題と次のアクション

| 優先 | タスク | 理由 |
|---|---|---|
| **高** | R05 GraphRAG Global の「逆方向結論」対策 | Q10 致命の根本対応 (community summary に OK/NG balance 制約を追加) |
| **高** | R12 RAG-Fusion の retrieval 改善 | バリエーション生成が intent を曖昧化、4 → 2 縮減も検討 |
| 中 | R10 Self-RAG の need_retrieval False 問題 | Q11/Q14/Q18 で retrieval 0、フォールバック必須化 |
| 中 | R08 Agentic RAG の tool 呼び出し最適化 | composite 最下位 (64.81)、重複排除 + 早期停止条件追加 |
| 中 | R06 LightRAG Hybrid の Fulltext sanitize | Q02 で composite 51.9 / hall 0.29、外すと致命 |
| 中 | クエリ難易度に応じた手法自動切替 (R13 強化) | R13 が global 一部で振るわず、STRATEGY_MAP 拡充 |
| 低 | Q18 業界別比較のためのデータ拡充 | KG に業界比較情報が薄い、Deal の industry tag 拡張 |
| 低 | evaluator_v2 の hallucination 検出精度向上 | R05 で 0.08、ジョブ間ばらつき大 |

---

## 13. Claude への依頼

本資料を元に **「ナレッジグラフベース RAG 13 手法 比較 技術検討書」** を作成してほしい。

想定読者: 社内技術評価会議 (マネージャ + エンジニア)、約 25-30 ページ想定

含めるべきセクション:
1. **エグゼクティブサマリ** — 推奨手法 + 主要根拠 + 残課題 (1 ページ)
2. **背景と目的** — KG ベース RAG 導入動機、13 手法選定理由
3. **評価方法** — v2 RAGAS の 3 軸設計、composite 重み (§2)
4. **全体ランキングと総合考察** — §3 を表、§9 を文章
5. **クエリ別ケーススタディ** — Q01-Q20 をベスト/ワースト/原因で論じる (§4-§7 のヒートマップを掲載)
6. **手法別プロファイル** — §8 をベースに各手法 1 ページ
7. **横断分析** — §9 (specific/global 差、改善前後、カテゴリ、Q10 致命、hallucination)
8. **シナリオ別推奨** — §10 を採用判断フローチャート化
9. **実装上の発見** — §11 を改善 KPT に
10. **残課題と次のアクション** — §12 をリスク評価表に
11. **付録** — 全 13 手法の生スコア、ヒートマップ、20 クエリ詳細

スタイル:
- 数値は本資料から引用 (再採点しない)
- 推奨は §10 の表を尊重し、§9 から根拠を引用
- 「LLM 評価には主観性がある」という限界を明示
- 改善前後の差は §9.2 を引用 (OLD = `output/before_improvement/`)
- 図表は ASCII テーブル可、必要なら mermaid

---

## 14. 補足: 参考データソース

| 参照先 | 内容 |
|---|---|
| `output/evaluation_v2_summary.csv` | ジョブ別 v2 全スコア (260 行) |
| `output/evaluation_v2_ranking.csv` | 手法別 v2 平均ランキング |
| `output/evaluation_v2_diagnosis.csv` | composite 昇順失敗分析 |
| `output/evaluation_v2_results.json` | hallucinated_claims 含む詳細 |
| `output/results/R*_*.json` | NEW 改善版 retrieval + generation 全 20 Q |
| `output/all_results.csv` | ベンチマーク横断集計 |
| `output/_aggregate_all.txt` | 本資料生成用テキスト集計 |
| `output/before_improvement/` | OLD ベースライン (改善前比較用) |
| `output/bench_run.log` / `eval_v2_run.log` | 実行ログ |
| `README.md` | プロジェクト全体概要 + 実行方法 |

---

## 15. アルゴリズム詳細 (実装ベース)

各プロセスの内部アルゴリズムと、`config.RETRIEVER_CONFIGS` で外部公開しているパラメータを記す。
コード本体は `retrievers/r*.py`, `utils/*.py`, `evaluation/evaluator_v2.py`, `tools/search_tools.py`。

### 15.0 共通基盤

#### 15.0.1 LLM クライアント (`utils/llm_client.py`)

- Azure OpenAI gpt-4o (deployment 名は `.env` の `AZURE_OPENAI_DEPLOYMENT_CHAT`)
- 主要メソッド: `chat(system, user, temperature, max_tokens, response_format)`, `embed(text)`, `embed_batch(texts)`, `chat_with_tools_loop(...)`
- リトライ: 3 回 / 指数バックオフ (2s → 4s → 8s) — Rate Limit 429 / 500 系で自動再試行
- タイムアウト: 60 秒
- すべての評価器・LLM 検索系は `temperature=0.0` + `response_format={"type":"json_object"}` を使い、再現性と JSON 構文を保証

#### 15.0.2 Neo4j クライアント (`utils/neo4j_client.py`)

- 接続: `bolt://localhost:7687` (`.env` の `NEO4J_URI`)
- 読み取り専用: `session.execute_read(...)` のみ使用 (書き込みは API レベルで禁止)
- クエリタイムアウト 30 秒
- 共有 Driver (シングルトン) でスレッドセーフ

#### 15.0.3 トークン管理 (`utils/token_counter.py`)

| 関数 | 役割 |
|---|---|
| `count_tokens(text)` | `tiktoken` (cl100k_base) で正確にカウント。失敗時は「文字数 / 2」で近似 |
| `pack_contexts_within_budget(contexts, max_tokens)` | 先頭から `CONTEXT_MAX_TOKENS=6000` 以内に詰める。区切り文字 `\n\n---\n\n` のトークンも加算 |

#### 15.0.4 OK/NG フィルタ (`utils/query_analyzer.py`)

`analyze_query_intent(llm, query)` — LLM で質問の OK/NG 意図を判定する 1 段階。

- 入力: 質問テキスト 1 つ
- LLM 呼び出し: 1 回 (`temperature=0.0`, JSON mode)
- 出力: `{"okng_filter": "OK"|"NG"|"BOTH"|null, "reason": "..."}`
- ルール（プロンプト記載）:
  - 「OK 案件の〜」「成功パターン」「成約傾向」→ `OK`
  - 「NG 案件の〜」「失注理由」「苦手な〜」→ `NG`
  - 「OK と NG の違い」「境界条件」→ `BOTH`
  - 上記以外 (個別事例・条件確認・推奨) → `null`
- 適用先: R01, R04, R07, R09, R12 (Vector 検索ステップで Cypher `WHERE node.okng = $okng` を追加)
- 適用判定: `config.ENABLE_OKNG_FILTER = True` がトリガー、`BOTH` / `null` の場合はフィルタを適用しない

#### 15.0.5 Context Compression (`utils/context_compressor.py`)

トークン予算を超えたコンテキストを LLM で圧縮する共通レイヤー。`main.py` で全 Retriever の retrieve 結果に適用される。

- トリガ条件: `context_token_count > CONTEXT_MAX_TOKENS × COMPRESSION_THRESHOLD_RATIO` = `6000 × 0.8 = 4800 tokens`
- 圧縮先: `COMPRESSION_MAX_CHARS = 3000 文字` 以内
- LLM 呼び出し: 1 回 (`temperature=0.1`, `max_tokens=max(512, 3000)`)
- プロンプト要件: 各 Deal を 1-3 行に圧縮 / Deal#ID と OK/NG 保持 / 数値と固有名詞 (機器名・工程名) 保持 / 不要な挨拶・日程調整・重複削除
- 入力長上限: 結合済み context が 12,000 文字を超える場合は先頭を切る (gpt-4o コンテキスト窓配慮)
- 戻り値メタ: `{"applied": bool, "before_tokens": int, "after_tokens": int, "llm_input_tokens": int, "llm_output_tokens": int}`

#### 15.0.6 RRF (`utils/rrf.py`)

Reciprocal Rank Fusion (Cormack 2009)。複数ランキングを統合する手法。

```python
score(d) = Σ_i  1 / (k + rank_i(d) + 1)
```

- `k = 60` がデフォルト (経験的に堅牢)
- R07, R12 で使用
- 同一文書が複数ランキングで上位にあるほど合算スコアが高くなる

#### 15.0.7 Lucene サニタイザ (`utils/lucene.py`)

`sanitize_lucene(text)`:

- Lucene 予約文字 ``+-&|!(){}[]^"~*?:\/`` を空白へ置換
- 空白で分割し 1 文字以下のトークンを除外
- 残りを空白区切り (Lucene の暗黙 OR) で結合
- 例: `"EtherNet/IP通信"` → `"EtherNet IP通信"`

#### 15.0.8 同義語辞書 (`utils/synonym_dict.py`)

`coverage_with_synonyms(keywords, answer, contexts)` — v2 評価の `keyword_coverage` 計算用。

- `SYNONYMS` 辞書: 70 語以上 (例: `"高温": ["200度", "200℃", "耐熱", ...]`)
- マッチ判定: キーワード本体 + 同義語のいずれかが answer に部分一致すれば match
- `only_in_context`: answer にはないが context には出現する語 → Generation 側の取りこぼし判定
- 戻り値: `CoverageDetail(coverage, matched, missed, only_in_context)`

#### 15.0.9 回答生成器 (`generator/answer_generator.py`)

`generate_answer(llm, query, contexts, temperature=0.2)`:

- システムプロンプト: 「コンテキスト情報のみを根拠に」「コンテキストにない情報は『情報が不足しています』と明示」
- 出力構造を強制: 1. 結論 → 2. 根拠 (箇条書き) → 3. 補足事項
- 温度 0.2 (わずかな多様性を許容)
- Self-RAG (R10) は `pre_generated_answer` を返すのでこのステップをスキップ

---

### 15.1 R01 Naive Vector RAG

```
質問 → [OK/NG フィルタ判定 (任意)] → 質問 embedding
     → Neo4j vector index Top-K → contexts
     → [Context Compressor]
     → generate_answer
```

- 検索クエリ: `CALL db.index.vector.queryNodes('deal_embedding_index', $k, $q) YIELD node, score`
- OK/NG フィルタ ON: `top_k * 3` でオーバーサンプル → Cypher `WHERE node.okng = $okng` → 上位 `top_k` 件
- OK/NG フィルタ OFF: 単純 Top-K
- LLM call 数: 1 (Generation) + 1 (OK/NG 判定、フィルタ ON 時)

| パラメータ | 値 | 役割 |
|---|---|---|
| `top_k` | 15 | 取得件数 |
| `ENABLE_OKNG_FILTER` | `True` (グローバル) | フィルタ要否 |

### 15.2 R02 Vector + Reranker

```
質問 embedding → Vector Top-50 → バッチで LLM Rerank (0-10) → スコア降順 Top-K
```

- Step 1: Vector で粗く `initial_top_k=50` 件取得
- Step 2: `rerank_batch_size=10` 件ずつに分割 → 各バッチを LLM に渡し JSON で `{"id": <doc_id>, "score": <0-10>}` のリストを得る
- Step 3: スコア降順で `rerank_top_k=8` 件を採用
- LLM call 数: ⌈50/10⌉ + 1 = 6 (Rerank 5 回 + Generation)
- OK/NG フィルタ: なし (Rerank が暗黙的に絞ると見なす)

| パラメータ | 値 | 役割 |
|---|---|---|
| `initial_top_k` | 50 | 粗取得件数 |
| `rerank_top_k` | 8 | 最終採用件数 |
| `rerank_batch_size` | 10 | 1 LLM call あたりの候補数 |

### 15.3 R03 HyDE (Hypothetical Document Embeddings)

```
質問 → LLM で 200-300 字の仮想商談レポート生成 → そのテキストを embedding
     → Vector Top-K で実際の Deal 検索
```

- 仮想回答生成プロンプト: 「商談分析レポート形式、ZP-L 等のセンサ名、工程名、ワーク種別、OK/NG 判定理由を含む 150-250 字」
- 仮想回答温度: 0.3 (バリエーション許容)
- `max_tokens=hyde_max_tokens=300` で生成を打ち切り → レイテンシ削減
- 仮想回答テキストを 1 つの大きな擬似クエリとして embedding → Vector 検索
- LLM call 数: 1 (HyDE) + 1 (Generation) = 2
- OK/NG フィルタ: なし (仮想回答が OK/NG どちらに寄るかを LLM 任せ)

| パラメータ | 値 | 役割 |
|---|---|---|
| `hyde_max_tokens` | 300 | 仮想回答の生成長上限 |
| `search_top_k` | 15 | Vector 検索の取得件数 |

### 15.4 R04 GraphRAG Local

```
質問 → [OK/NG フィルタ] → 質問 embedding
     → Vector で seed Deal (sim > min_score) を seed_k 件
     → 各 seed から 1-hop 拡張 (Cluster / Segment / OKTendency / NGTendency / Boundary
                              / Process / Equipment / Workpiece / sibling Deal)
     → 6 種の優先度 bucket に格納
     → bucket 順 (p1 → p6) で context を詰める
```

- bucket 優先度:
  1. **p1_seed**: seed Deal 本体 (`okng_reason` + 内容 1500 字)
  2. **p2_cluster**: Cluster の `objective` + `challenge`
  3. **p3_tendency**: `OKTendency.deal_level` + `NGTendency.deal_level`
  4. **p4_boundary**: `Boundary.okng_boundary`
  5. **p5_sibling**: 同クラスタの他 Deal 抜粋 (各 400 字)、最大 `sibling_per_seed` 件
  6. **p6_horizontal**: Process / Equipment / Workpiece の name 列挙
- Cypher: `_Q_EXPAND` (R04 ファイル内、1 seed あたり 1 クエリ)
- LLM call 数: 1 (Generation) + 1 (OK/NG 判定)

| パラメータ | 値 | 役割 |
|---|---|---|
| `seed_k` | 8 | seed Deal 数 |
| `min_score` | 0.3 | seed の cosine 類似度下限 |
| `max_hops` | 3 | 名目値 (実装は 1-hop ベース) |
| `sibling_per_seed` | 3 | seed 1 件あたりの兄弟 Deal 数 |

### 15.5 R05 GraphRAG Global (Map-Reduce on Communities)

```
全 Cluster (catchall 除外) を Cluster Embedding キャッシュから取得
  → 質問 embedding と cosine で上位 max_communities 件 (Vector 事前フィルタ)
  → bulk_map_size 件ずつまとめ、map_concurrency 並列で LLM に投げる (Bulk Map)
  → 各 Community に { relevance: 0-100, summary: 200 字 } を返させる
  → relevance >= threshold をフィルタ
  → Reduce: relevance 降順で contexts に詰める
```

- **Cluster Embedding キャッシュ** (`output/cluster_embeddings_cache.json`):
  - クラス変数 + ファイル永続化、プロセス内全インスタンス共有
  - キャッシュにない Cluster のみ `embed_batch(texts, batch=100)` で差分計算
  - 264 Cluster の embedding を毎回計算しない → latency 25% 削減
- **Bulk Map** の効果:
  - 60 Cluster を 15 件/call → 4 LLM call に圧縮 (元実装比 1/15)
  - `map_concurrency=3` で 4 call を 2 ラウンドで並列実行
- **Reduce**: relevance 降順で context に詰め、`relevance_threshold=30` 未満は捨てる
- Cluster summary には個別 Deal の deal_id は含まれない → `source_deal_ids` は空 (R05 の特徴)
- LLM call 数: 4 (Bulk Map) + 1 (Generation) = 5

| パラメータ | 値 | 役割 |
|---|---|---|
| `max_communities` | 60 | Vector で絞った後の候補数 |
| `bulk_map_size` | 15 | 1 LLM call で評価する Community 数 |
| `map_concurrency` | 3 | Bulk Map の並列度 |
| `relevance_threshold` | 30 | 採用する relevance 下限 (0-100) |

### 15.6 R06 LightRAG Hybrid

```
質問 → LLM で 2 種類のキーワード抽出
       - low_level_keywords: 具体名詞 (機器/センサ/ワーク/工程)
       - high_level_keywords: 抽象テーマ (傾向/条件/課題)
     → Low-level: Equipment/Process/Workpiece fulltext index → Cluster → Deal
     → High-level: cluster_objective fulltext → Cluster + Deal
     → Merge (high をやや強め: 1.5x、両ヒットには +2.0 ボーナス)
     → 出現スコア降順で contexts 配置
```

- キーワード抽出 LLM 1 回 → low/high 各 8 件まで
- Low-level Cypher (`_Q_LOW_LEVEL`): `fulltext_min_score > 1.0` で `max_entities_per_keyword=8` エンティティ → 各エンティティから `max_deals_per_entity=5` Deal
- High-level Cypher (`_Q_HIGH_LEVEL`): `cluster_objective_fulltext` で関連 Cluster → 配下 Deal + OK/NG 傾向 + Boundary を取得
- Merge ルール:
  ```python
  merged[d] = low_score[d] + high_score[d] * 1.5
  if d ∈ low ∩ high: merged[d] += 2.0
  ```
- Vector を一切使わない (LightRAG の特徴) → 純粋に Fulltext と Graph のみ
- LLM call 数: 1 (キーワード抽出) + 1 (Generation) = 2

| パラメータ | 値 | 役割 |
|---|---|---|
| `fulltext_min_score` | 1.0 | Lucene スコア下限 |
| `max_entities_per_keyword` | 8 | keyword あたりのエンティティ取得上限 |
| `max_deals_per_entity` | 5 | エンティティあたりの Deal 取得上限 |

### 15.7 R07 Contextual Retrieval

```
質問 → [OK/NG フィルタ] → 並列で
       (a) Vector Top-20 → ranking_v
       (b) Fulltext (deal_content_fulltext) Top-20 → ranking_f
     → RRF(k=60) で統合 → Top-15
     → 各 Deal に Cluster 文脈 (objective / process / okng) を prepend
```

- Vector ステップ: OK/NG フィルタ ON 時はオーバーサンプル + フィルタ
- Fulltext ステップ: 質問を `_sanitize_lucene` で安全化 → `deal_content_fulltext` で検索
- RRF: `score(d) = Σ 1/(60 + rank + 1)` で順位融合
- 文脈付加 Cypher: 各 Deal について `MATCH (d)-[:BELONGS_TO_CLUSTER]->(c)` → `objective` と `process` を context 先頭に prepend
- LLM call 数: 1 (Generation) + 1 (OK/NG 判定)

| パラメータ | 値 | 役割 |
|---|---|---|
| `vector_top_k` | 20 | Vector 取得件数 |
| `fulltext_top_k` | 20 | Fulltext 取得件数 |
| `rrf_k` | 60 | RRF 定数 |
| `final_top_k` | 15 | 最終採用件数 |

### 15.8 R08 Agentic RAG

```
LLM (gpt-4o function-calling) → tool_call ループ (最大 max_tool_calls=7)
   tools: vector_search / fulltext_search / graph_traverse / get_cluster_summary / finish
処理過程で SearchToolHandler が collected_deal_ids + collected_contexts に蓄積
ループ終了後、Deal ID で dedup → contexts として返す
```

- tool 定義 (`tools/search_tools.py`):
  | tool | 引数 | 動作 |
  |---|---|---|
  | `vector_search` | `query_text`, `top_k=10` | Deal vector index 検索、プレビュー 300 字 |
  | `fulltext_search` | `keyword`, `index_name` (5 つの fulltext index から選択) | Lucene 全文検索、Top-10 |
  | `graph_traverse` | `start_node_label`, `key_field`, `key_value`, `max_hops=2` | 起点ノードから 1-2 ホップ展開 |
  | `get_cluster_summary` | `cluster_id` | Cluster の目的・工程・OK/NG 傾向 |
  | `finish` | `final_answer` | ループ脱出 + 最終回答テキスト |
- `chat_with_tools_loop`: gpt-4o の `tool_calls` を解釈し、handler が JSON で結果を返す → LLM が次の tool を選ぶ
- LLM call 数: tool 呼び出し数 + Generation (最大 8 call)、平均 4-5 call

| パラメータ | 値 | 役割 |
|---|---|---|
| `max_tool_calls` | 7 | tool ループの上限 |
| `tool_timeout_sec` | 10 | 1 tool あたりの timeout |

### 15.9 R09 RAPTOR (Recursive Abstractive Processing)

ナレッジグラフが既に 3 階層 (Deal → Cluster → Segment) を持つため、構築フェーズなしで各レベルを並列検索する。

```
Level 0 (Deal):    Vector Top-k0 (任意で OK/NG フィルタ)
Level 1 (Cluster): cluster_objective_fulltext Top-k1 (catchall 除外)
                   + OKTendency / NGTendency / Boundary を JOIN
Level 2 (Segment): Segment ごとに cluster_objective_fulltext のヒットを集計
                   → total_score 降順 Top-k2

各 Level のスコアを min-max 正規化 → 重み合算
最終 context: Level 2 → Level 1 → Level 0 の階層構造で並べる
```

- 重み: `w0=0.5, w1=0.3, w2=0.2` (Leaf 重視)
- Level 1 Cypher: 1 つの fulltext query で Cluster とその傾向情報を一括取得
- Level 2 Cypher: 全 Segment に対し Cluster fulltext の合計スコアを集計 (N+1 query パターン)
- LLM call 数: 1 (Generation) + 1 (OK/NG 判定)

| パラメータ | 値 | 役割 |
|---|---|---|
| `top_k_level0` | 8 | Leaf Deal 取得件数 |
| `top_k_level1` | 5 | Cluster 取得件数 |
| `top_k_level2` | 3 | Segment 取得件数 |
| `weight_level0` | 0.5 | Leaf 重み |
| `weight_level1` | 0.3 | Cluster 重み |
| `weight_level2` | 0.2 | Segment 重み |
| `context_structure` | `"hierarchical"` | root → mid → leaf 順で配置 |

### 15.10 R10 Self-RAG (Self-Reflective)

```
1. Retrieve 判定 (LLM): need_retrieval = true/false
   - false: safety_top_k_when_no_retrieve=3 件だけ取って直接 generate
2. Vector 検索 Top-initial_top_k (=15)
3. Relevance 判定 (LLM 1 call で全件): relevant / partially_relevant / irrelevant
4. relevance >= relevance_threshold (=partially_relevant) を kept
5. 内部で回答生成 (generate_answer プロンプト相当を直接呼ぶ)
6. Support 判定 (LLM): fully_supported / partially_supported / not_supported
7. support < support_threshold (=partially_supported) なら
   - Rephrase クエリ (LLM) → Step 2 へ戻る
   - 最大 max_reflection_loops=2 回
8. 最終回答に "※一部推測を含みます (Self-RAG: partially_supported)" を付加するケースあり
```

- 全 4 種類の LLM 呼び出しが連続するため latency が他より高め
- `pre_generated_answer` を返すので `generate_answer` をスキップ
- LLM call 数: 最良 3 (Retrieve判定 + Relevance + Generation + Support = 4)、最悪 7 (リフレーズ 2 回 × 3)

| パラメータ | 値 | 役割 |
|---|---|---|
| `initial_top_k` | 15 | Vector 取得件数 |
| `max_reflection_loops` | 2 | 反省ループ上限 |
| `relevance_threshold` | `"partially_relevant"` | 関連性下限 |
| `support_threshold` | `"partially_supported"` | 支持度下限 |
| `rephrase_on_failure` | `True` | リフレーズ実施 |
| `safety_top_k_when_no_retrieve` | 3 | need_retrieval=false 時の保険検索 |

### 15.11 R11 Corrective RAG (CRAG)

```
1. Vector Top-initial_top_k (=8) で取得
2. Quality 評価 (LLM): correct / ambiguous / incorrect + confidence (0-1)
3. 分岐:
   - correct (confidence >= 0.6): Knowledge Refinement のみ
   - ambiguous: Knowledge Refinement + Sub-query 生成 (LLM) + Fulltext 追加検索 → 結合
   - incorrect: Strategy Selector (LLM) で A/B/C 選択 → 再検索 → 再評価
       A: Fulltext search (deal_content_fulltext)
       B: Graph search (Equipment/Process/Workpiece fulltext → Cluster → Deal)
       C: Vector rephrase (revised query で再 Vector)
4. ループ最大 max_correction_loops=2 回
5. context 構造:
   [CRAG Knowledge Refinement (quality=...)]   ← 先頭
   [CRAG Sub-query 追加検索結果]              ← 任意
   各 Deal の元 context (Deal#ID origin=...)  ← 順次
```

- Knowledge Refinement: `refinement_max_chars=400` 字以内に LLM で要約
- ambiguous は Refinement で確定 (再ループしない)
- LLM call 数:
  - correct: 1 (Quality) + 1 (Refinement) + 1 (Generation) = 3
  - ambiguous: 1 + 1 + 1 (subquery) + 1 (Generation) = 4
  - incorrect: 1 + 1 (Strategy) × loops + 1 (Generation) = 最大 5

| パラメータ | 値 | 役割 |
|---|---|---|
| `initial_top_k` | 8 | 初回 Vector 取得件数 |
| `max_correction_loops` | 2 | incorrect 時の修正ループ上限 |
| `quality_confidence_threshold` | 0.6 | correct 採用の confidence 下限 |
| `refinement_enabled` | `True` | Knowledge Refinement 有無 |
| `refinement_max_chars` | 400 | Refinement 出力上限 |
| `fallback_strategies` | `["fulltext","graph","rephrase"]` | (将来用) |

### 15.12 R12 RAG-Fusion (Multi-Query + RRF)

```
1. LLM で元クエリから 4 バリエーション生成 (temperature=0.5)
2. 元 + 4 バリエーション = 5 クエリ × 各 Vector Top-per_query_top_k (=10)
3. RRF(rrf_k=60) で 5 ランキングを統合
4. final_top_k=15 件採用
5. Deal 詳細を Cypher で取得 (content / okng / okng_reason)
```

- バリエーション生成プロンプト: 「異なる語彙 / 異なる側面 (具体例 / 抽象傾向 / 条件 / 反対視点) にフォーカス」
- 例 (Q01「OK 条件」に対するバリエーション):
  1. 合格と判断される基準は？
  2. どんな条件が OK とみなされるか？
  3. 許容範囲や基準値の設定は？
  4. NG になるのはどんなケースか？ (反対視点)
- OK/NG フィルタ ON 時は 5 クエリ全てに適用
- LLM call 数: 1 (多角化) + 5 (embedding は LLM call にカウントしない) + 1 (Generation) = 2

| パラメータ | 値 | 役割 |
|---|---|---|
| `num_variants` | 4 | バリエーション数 (元クエリ + 4 = 5 検索) |
| `per_query_top_k` | 10 | 各クエリの Vector 取得件数 |
| `rrf_k` | 60 | RRF 定数 |
| `final_top_k` | 15 | 最終採用件数 |

### 15.13 R13 Adaptive Ensemble

```
1. クエリ分類 (LLM):
     type:       specific / global / hybrid
     complexity: simple / moderate / complex
     okng_filter: OK / NG / BOTH / null
2. STRATEGY_MAP[(type, complexity)] から 2-3 手法を選択
3. 各 sub method を順次 (または並列) 実行
4. 結果を Deal ID で dedup、出現回数でブースト
   → 多手法ヒット deal を context 先頭に置く
5. supplementary contexts (Cluster summary 等) は末尾に最大 5 件
```

- STRATEGY_MAP (経験的に最適化済み):
  | (type, complexity) | 選択手法 |
  |---|---|
  | (specific, simple) | R07, R01 |
  | (specific, moderate) | R07, R04 |
  | (specific, complex) | R11, R04, R07 |
  | (global, simple) | R09, R06 |
  | (global, moderate / complex) | R09, R06, R05 |
  | (hybrid, simple) | R09, R07 |
  | (hybrid, moderate) | R09, R07, R04 |
  | (hybrid, complex) | R09, R04, R06 |
- 自己参照禁止: STRATEGY_MAP に R13 を含めない (無限ループ防止)
- LLM call 数: 1 (分類) + 各 sub method の LLM call + 1 (Generation)
- 並列実行 (`parallel_execution`) はレート制限の懸念で OFF (`False`) がデフォルト

| パラメータ | 値 | 役割 |
|---|---|---|
| `max_sub_methods` | 3 | 同時実行する sub method の上限 |
| `ensemble_strategy` | `"frequency_boost"` | dedup 方式 |
| `parallel_execution` | `False` | 並列実行フラグ |
| `fallback_methods` | `["R09", "R07"]` | 分類失敗時のフォールバック |

---

### 15.14 評価アルゴリズム (`evaluation/evaluator_v2.py`)

評価は 1 ジョブ (1 クエリ × 1 手法) あたり最大 3 つの LLM call。

#### Retrieval 評価 (`evaluate_retrieval`)

- 入力: 質問 + 期待方向 + 期待キーワード + コンテキスト群 (各 1500 字に切り詰め)
- LLM プロンプト: 「**回答は提示されません。コンテキストのみを評価**」「コンテキスト外の知識で『正しい』と判断しない」
- 出力:
  - `context_precision` (0-1): 関連コンテキストの割合
  - `context_recall` (0-1): 必要情報の被覆度
  - `context_relevancy` (0-1): 質問適合度
  - `precision_reason / recall_gaps / noise_examples` (各 100 字)
- `retrieval_score = (precision + recall + relevancy) / 3`

#### Generation 評価 (`evaluate_generation`)

- 入力: 質問 + コンテキスト + 回答
- LLM プロンプト: 「コンテキストに含まれる情報のみを根拠として評価」
- 出力:
  - `faithfulness` (0-1): 主張のコンテキスト裏付け度
  - `answer_relevancy` (0-1): 質問への直接性
  - `answer_completeness` (0-1): 期待観点の網羅度
  - `hallucinated_claims` (最大 5 件)
  - `missing_aspects` (最大 5 件)
- `generation_score = (faithfulness + answer_relevancy + answer_completeness) / 3`

#### Hallucination 検出 (`detect_hallucinations`)

- 入力: 回答 + コンテキスト
- LLM プロンプト: 「回答に含まれる『事実の主張』を最大 10 個列挙し、各主張を 3 段階で判定」
- 出力:
  - `claims`: `[{claim, status, evidence}, ...]` (各 80 字)
  - `status`: `supported` / `partially_supported` / `not_supported`
- `hallucination_rate = not_supported 数 / 全主張数`
- `--skip-hallucination` で省略可能 (LLM call 3 → 2)

#### Composite Score

```
composite = (retrieval_score × 0.4
           + generation_score × 0.5
           + keyword_coverage × 0.1) × 100
```

- 重み `DEFAULT_WEIGHTS = {"retrieval":0.4, "generation":0.5, "keyword":0.1}`
- latency は composite に含めず、別カラム `avg_latency_ms` で表示
- `keyword_coverage` は同義語辞書込み (§15.0.8)

#### 失敗診断 (`diagnose`)

| ラベル | 条件 |
|---|---|
| `retrieval_failure` | retrieval < 0.4 AND generation > 0.6 |
| `generation_failure` | retrieval > 0.6 AND generation < 0.4 |
| `both_weak` | retrieval < 0.5 AND generation < 0.5 |
| `both_good` | retrieval > 0.7 AND generation > 0.7 |
| `mixed` | 上記以外 |

#### 評価 CLI (`evaluation/evaluate_main_v2.py`)

```powershell
python -m rag_benchmark.evaluation.evaluate_main_v2 [options]
```

| オプション | 用途 |
|---|---|
| `--methods R09 R11` | 評価する手法 ID (省略時は全 13) |
| `--queries Q01 Q15` | 評価するクエリ ID (省略時は全 20) |
| `--concurrency 8` | LLM 評価の並列度 (デフォルト 5) |
| `--skip-hallucination` | Hallucination 検出を省略 (call 数 3→2) |
| `--diagnosis-only` | 既存 JSON から `evaluation_v2_diagnosis.csv` のみ再生成 |
| `--compare-v1` | v1 (`evaluation_results.json`) との Pearson 相関を計算 |
| `--log-file PATH` | ログ出力先 |

出力:

| ファイル | 内容 |
|---|---|
| `output/evaluation_v2_results.json` | 全ジョブの詳細 (hallucinated_claims, missing_aspects 含む) |
| `output/evaluation_v2_summary.csv` | ジョブ別 全スコア + diagnosis (260 行) |
| `output/evaluation_v2_ranking.csv` | 手法別 平均スコア (composite 降順) |
| `output/evaluation_v2_diagnosis.csv` | composite 昇順失敗分析 |

---

### 15.15 LLM 呼び出し回数まとめ (1 クエリあたり)

通常実行 (`generate_answer` 込み)。`embed` は別 API なのでカウント外。

| 手法 | OK/NG 判定 | 検索系 LLM | Generation | 合計 |
|---|--:|--:|--:|--:|
| R01 | 1 | 0 | 1 | **2** |
| R02 | 0 | 5 (rerank) | 1 | **6** |
| R03 | 0 | 1 (HyDE) | 1 | **2** |
| R04 | 1 | 0 | 1 | **2** |
| R05 | 0 | 4 (bulk map) | 1 | **5** |
| R06 | 0 | 1 (キーワード抽出) | 1 | **2** |
| R07 | 1 | 0 | 1 | **2** |
| R08 | 0 | 4-7 (tool ループ) | 1 (finish 内) | **5-8** |
| R09 | 1 | 0 | 1 | **2** |
| R10 | 0 | 3-4 (Retrieve/Relevance/Support[/Rephrase]) | 1 (内部生成) | **4-7** |
| R11 | 0 | 2-4 (Quality/Refinement/Subquery or Strategy) | 1 | **3-5** |
| R12 | 1 | 1 (多角化) | 1 | **3** |
| R13 | 1 (分類) | sub method 群 | 1 | **6-10** |

加えて v2 評価で各ジョブ 3 LLM call (Retrieval / Generation / Hallucination)。
全 260 ジョブ実行で実測 LLM call 数は **2,500-3,000 程度**。

### 15.16 ハードコード値の早見表

| 場所 | 名前 | 値 | 意味 |
|---|---|---|---|
| `config.py` | `NEO4J_QUERY_TIMEOUT_SEC` | 30 | Cypher タイムアウト |
| `config.py` | `LLM_TIMEOUT_SEC` | 60 | LLM call タイムアウト |
| `config.py` | `LLM_MAX_RETRIES` | 3 | リトライ回数 |
| `config.py` | `LLM_RETRY_INITIAL_WAIT` | 2.0 | リトライ初期待機 (s) → 2, 4, 8 |
| `config.py` | `CONTEXT_MAX_TOKENS` | 6000 | 全手法共通の context 上限 |
| `config.py` | `EMBEDDING_DIMENSIONS` | 3072 | text-embedding-3-large |
| `config.py` | `COMPRESSION_THRESHOLD_RATIO` | 0.8 | 圧縮トリガ閾値 (6000 × 0.8 = 4800) |
| `config.py` | `COMPRESSION_MAX_CHARS` | 3000 | 圧縮先の文字数上限 |
| `context_compressor.py` | LLM 入力上限 | 12000 文字 | gpt-4o コンテキスト窓配慮 |
| `evaluator_v2.py` | `_format_contexts` | 1500 字/context | 評価器入力の各 context 上限 |
| `evaluator_v2.py` | `DEFAULT_WEIGHTS` | `{0.4, 0.5, 0.1}` | composite 重み |
| `rrf.py` | `k` (デフォルト引数) | 60 | RRF 定数 |
| `query_analyzer.py` | reason 切り詰め | 100 字 | OK/NG 判定 reason 上限 |
| `synonym_dict.py` | `SYNONYMS` | 約 70 語 | 同義語辞書 |

---

これらのアルゴリズム情報は、Claude が技術検討書の付録「手法詳細仕様」「評価方法詳細」「パラメータ参照表」を書くのに十分。**実装の正確な記述には必ず本セクション §15 を参照**すること (口頭再現や記憶ベース説明は禁止)。

