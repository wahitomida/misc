"""接続設定・カラムマッピング・ノードラベル定数を集約.

実際の `05_analysis.csv` は仕様書とカラム名が異なる箇所があるため、
ここでマッピングを一元管理する（csv_loader が参照）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# =============================================================================
# Neo4j 接続設定
# =============================================================================


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls) -> "Neo4jSettings":
        return cls(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            user=(
                os.environ.get("NEO4J_USER")
                or os.environ.get("NEO4J_USERNAME", "neo4j")
            ),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )


# =============================================================================
# 入出力デフォルト
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV_CANDIDATES: List[Path] = [
    PROJECT_ROOT / "data" / "05_analysis.csv",
    PROJECT_ROOT.parent.parent / "workdir_v6" / "05_analysis.csv",
    PROJECT_ROOT.parent.parent / "workdir" / "05_analysis.csv",
]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

MAX_PROPERTY_LENGTH = 5000
TRUNCATE_HEAD_LENGTH = 3000
BATCH_SIZE = 500

# catchall (受け皿) クラスタ判定閾値
#  - segment が unknown / 無し
#  - cluster 内 Deal 件数が全体の CATCHALL_THRESHOLD_RATIO を超える
# のいずれかで True
CATCHALL_THRESHOLD_RATIO: float = 0.10
CATCHALL_SEGMENT_NAMES = {"unknown", "無し"}

# Embedding 設定 (OpenAI text-embedding-3-small 等)
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS: int = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
EMBEDDING_BATCH_SIZE: int = int(os.environ.get("EMBEDDING_BATCH_SIZE", "100"))
EMBEDDING_MAX_TOKENS: int = int(os.environ.get("EMBEDDING_MAX_TOKENS", "8191"))
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")

# Azure OpenAI Embedding 設定 (GUI_kabe と同じ命名規則)
# AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_KEY / AZURE_OPENAI_EMBED_DEPLOYMENT が
# すべて設定されている場合は Azure バックエンドを優先使用する。
AZURE_OPENAI_ENDPOINT: str = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY: str = (
    os.environ.get("AZURE_OPENAI_KEY")
    or os.environ.get("AZURE_OPENAI_API_KEY", "")
)
AZURE_OPENAI_EMBED_DEPLOYMENT: str = (
    os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT")
    or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    or "embedding"
)
AZURE_OPENAI_API_VERSION: str = os.environ.get("API_VERSION", "2024-12-01-preview")


def use_azure_openai() -> bool:
    """Azure OpenAI 経由で Embedding を呼ぶべきかを判定."""
    return bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY)


# =============================================================================
# カラムマッピング
#   key   = 内部論理名（プログラム側で使う名前）
#   value = 実 CSV カラム名（候補リストの先頭から探索）
# =============================================================================

COLUMN_MAP: Dict[str, List[str]] = {
    # ─── 基本情報 ──────────────────────────────────────────────
    "deal_id": ["id", "index"],
    "content": ["content", "コメント"],
    "score": ["score", "has_app_info"],
    "app_sort": ["app_sort", "application"],
    # ─── クラスタ情報 ─────────────────────────────────────────
    "cluster_id": ["cluster_id"],
    "cluster_process": ["cluster_process"],
    # 実データには installation はあるが equipment は無いので installation で代用
    "cluster_equipment": ["cluster_equipment", "cluster_installation"],
    "cluster_workpiece": ["cluster_workpiece"],
    "cluster_objective": ["cluster_objective"],
    # 実データの problem を challenge として扱う
    "cluster_challenge": ["cluster_challenge", "cluster_problem"],
    # 実データの existing_solution を current_method として扱う
    "cluster_current_method": ["cluster_current_method", "cluster_existing_solution"],
    # ─── OK/NG 判定 ───────────────────────────────────────────
    "okng": ["okng", "deal_result"],
    "okng_reason": ["okng_reason", "deal_result_reason"],
    "okng_detail_reason": ["okng_detail_reason", "deal_ok_reason", "deal_ng_reason"],
    "okng_confidence": ["okng_confidence", "deal_result_confidence"],
    # 以下はフィールド名と CSV 名が一致
    "okng_ok_tendency": ["okng_ok_tendency"],
    "okng_ng_tendency": ["okng_ng_tendency"],
    "okng_boundary": ["okng_boundary"],
    "okng_appeal_point": ["okng_appeal_point"],
    "okng_recommendation": ["okng_recommendation"],
    # ─── セグメント分析 ────────────────────────────────────────
    "analysis_segment_ok_tendency": ["analysis_segment_ok_tendency"],
    "analysis_segment_ng_tendency": ["analysis_segment_ng_tendency"],
    "analysis_segment_key_difference": ["analysis_segment_key_difference"],
    "analysis_segment_appeal_point": ["analysis_segment_appeal_point"],
    "analysis_segment_actionable_insight": ["analysis_segment_actionable_insight"],
    # ─── IL 置換分析 ──────────────────────────────────────────
    "analysis_il_ok_tendency": ["analysis_il_ok_tendency"],
    "analysis_il_ng_tendency": ["analysis_il_ng_tendency"],
    "analysis_il_boundary": ["analysis_il_boundary"],
    "analysis_il_recommendation": ["analysis_il_recommendation"],
    # 仕様書には「analysis_il_appeal_point」も含まれていないが念のため拾う
    "analysis_il_appeal_point": ["analysis_il_appeal_point"],
}


# =============================================================================
# ノード・リレーション定義
# =============================================================================

NODE_LABELS = [
    "Segment",
    "Cluster",
    "Deal",
    "AppCategory",
    "Process",
    "Equipment",
    "Workpiece",
    "OKTendency",
    "NGTendency",
    "Boundary",
    "AppealPoint",
    "Recommendation",
]

RELATIONSHIP_TYPES = [
    # 階層
    "IN_SEGMENT",
    "BELONGS_TO_CLUSTER",
    "CATEGORIZED_AS",
    # Cluster → 工程・機器・ワーク (横断検索軸)
    "HAS_PROCESS",
    "USES_EQUIPMENT",
    "TARGETS_WORKPIECE",
    # Deal レベル
    "HAS_OK_TENDENCY",
    "HAS_NG_TENDENCY",
    "HAS_BOUNDARY",
    "HAS_APPEAL",
    "HAS_RECOMMENDATION",
    # Cluster レベル
    "CLUSTER_OK_TENDENCY",
    "CLUSTER_NG_TENDENCY",
    "CLUSTER_BOUNDARY",
    "CLUSTER_APPEAL",
    "CLUSTER_RECOMMENDATION",
    # AppCategory レベル
    "APP_OK_TENDENCY",
    "APP_NG_TENDENCY",
]


# =============================================================================
# ノードカラーパレット（visualize で使用）
# =============================================================================

NODE_COLORS: Dict[str, str] = {
    "Segment": "#4A90D9",        # 青 (旧 Industry)
    "Cluster": "#7BC67E",        # 緑
    "Deal": "#F5D76E",           # 黄
    "AppCategory": "#F39C12",    # 橙
    "Process": "#48C9B0",        # ティール (新規)
    "Equipment": "#F7DC6F",      # ゴールド (新規)
    "Workpiece": "#E59866",      # コーラル (新規)
    "OKTendency": "#A9DFBF",     # 薄緑
    "NGTendency": "#F1948A",     # 薄赤
    "Boundary": "#BB8FCE",       # 紫
    "AppealPoint": "#85C1E9",    # 水色
    "Recommendation": "#BDC3C7", # グレー
}


# =============================================================================
# データ品質判定
# =============================================================================

INSUFFICIENT_DATA_PATTERNS: List[str] = [
    r"当クラスタは十分な要約データが未整備のため",
    r"要約データがないため",
    r"現時点では.*を定量的に抽出できません",
    r"データ欠落",
    r"データ不足",
    r"未分析",
]
