"""機能②: コードレビュー パッケージ。

サブモジュール (内部実装):
    - ``constants``: FOCUS_PRESETS / CONCERN_TO_ROLE / CONCERN_TO_MODEL ほか
    - ``scanner``: FolderScanner (LLM 非経由)
    - ``chunker``: FileChunker (LLM 非経由)
    - ``assigner``: PartLeaderAssigner (LLM 非経由)
    - ``prompts``: 全プロンプト定数
    - ``cross_question``: CrossQuestioner (LLM 経由, Phase 3)
    - ``focus_detector``: focus 自動推定 (LLM 経由, §12.7)
    - ``code_review``: ``CodeReview`` 統合フロー (Phase 1-2 実装, 3-5 スタブ)

``from features.code_review import FolderScanner`` のような従来パスは
本 ``__init__`` で互換維持される。

設計書: ``doc/12_code_review.md`` 全体
"""

from features.code_review.assigner import PartLeaderAssigner
from features.code_review.chunker import (
    DEFAULT_MAX_TOKENS_PER_CHUNK,
    FileChunker,
)
from features.code_review.code_review import CodeReview
from features.code_review.constants import (
    CONCERN_TO_MODEL,
    CONCERN_TO_ROLE,
    DEFAULT_HEADER_LINES,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    FOCUS_PRESETS,
)
from features.code_review.cross_question import (
    DEFAULT_CROSS_QUESTION_MAX_ROUNDS,
    CrossQuestioner,
)
from features.code_review.prompts import (
    CODE_STATE_DETECTION_PROMPT,
    CROSS_QUESTION_PAIRS,
    INVESTIGATION_PROMPTS,
    STATE_TO_DEFAULT_FOCUS,
)
from features.code_review.scanner import FolderScanner

__all__ = [
    # 統合クラス
    "CodeReview",
    # スキャン系
    "FolderScanner",
    "FileChunker",
    "PartLeaderAssigner",
    # 相互質問
    "CrossQuestioner",
    # プロンプト定数
    "INVESTIGATION_PROMPTS",
    "CROSS_QUESTION_PAIRS",
    "CODE_STATE_DETECTION_PROMPT",
    "STATE_TO_DEFAULT_FOCUS",
    # 設定定数
    "FOCUS_PRESETS",
    "CONCERN_TO_ROLE",
    "CONCERN_TO_MODEL",
    "DEFAULT_IGNORE_PATTERNS",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_HEADER_LINES",
    "DEFAULT_MAX_TOKENS_PER_CHUNK",
    "DEFAULT_CROSS_QUESTION_MAX_ROUNDS",
]
