"""ベンチマーク全体の設定を集約."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # rag_benchmark/.env を優先、無ければ neo4j_knowledge_graph/.env を併用
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(
        Path(__file__).resolve().parent.parent / "neo4j_knowledge_graph" / ".env",
        override=False,
    )
except ImportError:
    pass


# =============================================================================
# Neo4j 接続
# =============================================================================
NEO4J_URI: str = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = (
    os.environ.get("NEO4J_USER")
    or os.environ.get("NEO4J_USERNAME", "neo4j")
)
NEO4J_PASSWORD: str = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE: str = os.environ.get("NEO4J_DATABASE", "neo4j")
NEO4J_QUERY_TIMEOUT_SEC: int = 30


# =============================================================================
# Azure OpenAI
# =============================================================================
AZURE_OPENAI_ENDPOINT: str = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY: str = (
    os.environ.get("AZURE_OPENAI_API_KEY")
    or os.environ.get("AZURE_OPENAI_KEY", "")
)
AZURE_OPENAI_API_VERSION: str = os.environ.get(
    "API_VERSION", os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
)
AZURE_OPENAI_DEPLOYMENT_CHAT: str = os.environ.get(
    "AZURE_OPENAI_DEPLOYMENT_CHAT",
    os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
)
AZURE_OPENAI_DEPLOYMENT_EMBEDDING: str = os.environ.get(
    "AZURE_OPENAI_DEPLOYMENT_EMBEDDING",
    os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "embedding"),
)

LLM_TIMEOUT_SEC: int = 60
LLM_MAX_RETRIES: int = 3
LLM_RETRY_INITIAL_WAIT: float = 2.0  # 指数バックオフ: 2, 4, 8


# =============================================================================
# 全手法共通
# =============================================================================
CONTEXT_MAX_TOKENS: int = 6000        # 公平比較のため統一
GENERATION_MODEL: str = AZURE_OPENAI_DEPLOYMENT_CHAT
EMBEDDING_MODEL: str = AZURE_OPENAI_DEPLOYMENT_EMBEDDING
EMBEDDING_DIMENSIONS: int = 3072


# =============================================================================
# 手法別パラメータ
# =============================================================================
RETRIEVER_CONFIGS: dict[str, dict] = {
    # R01: Top-K 10→15 で取得を厚くし global クエリでの情報不足を緩和
    "R01": {"top_k": 15},
    # R02: rerank で削りすぎを緩和 (5→8)
    "R02": {"initial_top_k": 50, "rerank_top_k": 8, "rerank_batch_size": 10},
    # R03: HyDE 生成を短縮 (400→300) + 検索 top_k 10→15
    "R03": {"hyde_max_tokens": 300, "search_top_k": 15},
    # R04: seed Deal を増やし (5→8)、ホップ範囲も 2→3 で関連 Deal を厚く
    "R04": {"seed_k": 8, "min_score": 0.3, "max_hops": 3, "sibling_per_seed": 3},
    # R05: bulk_map_size 10→15 で LLM call 数削減、map_concurrency 2→3 で並列化
    "R05": {
        "max_communities": 60,
        "bulk_map_size": 15,
        "map_concurrency": 3,
        "relevance_threshold": 30,
    },
    # R06: エンティティと Deal の取得上限を拡大
    "R06": {
        "fulltext_min_score": 1.0,
        "max_entities_per_keyword": 8,
        "max_deals_per_entity": 5,
    },
    # R07: final_top_k 10→15 で情報不足を緩和
    "R07": {
        "vector_top_k": 20,
        "fulltext_top_k": 20,
        "rrf_k": 60,
        "final_top_k": 15,
    },
    # R08: tool 呼び出し回数 5→7 で多面探索を許可
    "R08": {"max_tool_calls": 7, "tool_timeout_sec": 10},
    "R09": {  # RAPTOR: Level 0 Deal を増やし (5→8) 具体性を強化
        "top_k_level0": 8,
        "top_k_level1": 5,
        "top_k_level2": 3,
        "weight_level0": 0.5,
        "weight_level1": 0.3,
        "weight_level2": 0.2,
        "context_structure": "hierarchical",  # root → mid → leaf
    },
    "R10": {  # Self-RAG: 検索スキップ過多を抑制
        "initial_top_k": 15,                  # 10→15
        "max_reflection_loops": 2,
        "relevance_threshold": "partially_relevant",
        "support_threshold": "partially_supported",
        "rephrase_on_failure": True,
        "safety_top_k_when_no_retrieve": 3,   # need_retrieval=false でも保険として 3 件取得
    },
    "R11": {  # Corrective RAG: 初期検索を縮小し refinement 入力を軽量化
        "initial_top_k": 8,                   # 10→8
        "max_correction_loops": 2,
        "quality_confidence_threshold": 0.6,
        "refinement_enabled": True,
        "refinement_max_chars": 400,          # Knowledge Refinement 出力上限 (短縮)
        "fallback_strategies": ["fulltext", "graph", "rephrase"],
    },
    # ====================================================================
    # R12: RAG-Fusion (Multi-Query + RRF)
    # ====================================================================
    "R12": {
        "num_variants": 4,
        "per_query_top_k": 10,
        "rrf_k": 60,
        "final_top_k": 15,
    },
    # ====================================================================
    # R13: Adaptive Ensemble (動的手法選択)
    # ====================================================================
    "R13": {
        "max_sub_methods": 3,
        "ensemble_strategy": "frequency_boost",  # 出現回数でブースト
        "parallel_execution": False,             # True にすると並列実行 (レート制限注意)
        "fallback_methods": ["R09", "R07"],
    },
}


# =============================================================================
# 第 2 次改善: 共通機能フラグ
# =============================================================================
ENABLE_CONTEXT_COMPRESSION: bool = True   # main.py で全手法共通に適用
COMPRESSION_THRESHOLD_RATIO: float = 0.8  # CONTEXT_MAX_TOKENS のこの比率を超えたら圧縮
COMPRESSION_MAX_CHARS: int = 3000

ENABLE_OKNG_FILTER: bool = True            # R01/R04/R07/R09 で OK/NG フィルタを有効化
CLUSTER_EMBEDDING_CACHE_FILE: Path = (
    Path(__file__).resolve().parent / "output" / "cluster_embeddings_cache.json"
)


# =============================================================================
# パス
# =============================================================================
PROJECT_ROOT: Path = Path(__file__).resolve().parent
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
RESULTS_DIR: Path = OUTPUT_DIR / "results"
SUMMARY_CSV: Path = OUTPUT_DIR / "all_results.csv"
