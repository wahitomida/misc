"""コードレビュー: 共有定数 (LLM 非経由)。

- ``FOCUS_PRESETS``: ``--focus`` ごとの観点重み (§12.2.4)
- ``CONCERN_TO_ROLE`` / ``CONCERN_TO_MODEL``: 観点 → ロール ID / モデル名 (§12.2.4)
- ``FolderScanner`` / ``PartLeaderAssigner`` のデフォルト閾値

設計書: ``doc/12_code_review.md`` §12.2
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# FolderScanner デフォルト
# ----------------------------------------------------------------------


DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "__pycache__",
    "__pycache__/*",
    ".git",
    ".git/*",
    ".gitignore",
    "node_modules",
    "node_modules/*",
    "*.egg-info",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    "env",
    "env/*",
)
DEFAULT_MAX_FILE_SIZE_BYTES = 1_048_576  # 1MB
DEFAULT_HEADER_LINES = 50


# ----------------------------------------------------------------------
# PartLeaderAssigner: weight → level / minor file 判定
# ----------------------------------------------------------------------


LEVEL_HIGH_THRESHOLD = 1.5
LEVEL_MEDIUM_THRESHOLD = 1.0
WEIGHT_SKIP_THRESHOLD = 0.3
WEIGHT_FULL_COVERAGE_THRESHOLD = 1.0

MINOR_FILE_FRAGMENTS: tuple[str, ...] = (
    "tests/",
    "test_",
    "__init__.py",
    "conftest.py",
    "setup.py",
)


# ----------------------------------------------------------------------
# --focus プリセット (§12.2.4)
# ----------------------------------------------------------------------


FOCUS_PRESETS: dict[str, dict[str, float]] = {
    "all": {
        "algorithm": 1.0,
        "reproducibility": 1.0,
        "performance": 1.0,
        "structure": 1.0,
        "readability": 1.0,
        "results": 1.0,
    },
    "pre_submission": {
        "algorithm": 1.5,
        "reproducibility": 1.5,
        "results": 1.5,
        "structure": 0.5,
        "readability": 0.5,
        "performance": 0.8,
    },
    "performance": {
        "performance": 2.0,
        "structure": 1.0,
        "algorithm": 0.5,
        "reproducibility": 0.3,
        "readability": 0.3,
        "results": 0.5,
    },
    "structure": {
        "structure": 2.0,
        "readability": 1.5,
        "algorithm": 0.3,
        "reproducibility": 0.5,
        "performance": 0.5,
        "results": 0.3,
    },
    "handover": {
        "readability": 2.0,
        "reproducibility": 1.5,
        "structure": 1.5,
        "algorithm": 0.3,
        "performance": 0.3,
        "results": 0.5,
    },
    "algorithm": {
        "algorithm": 2.0,
        "results": 1.5,
        "structure": 0.3,
        "readability": 0.3,
        "performance": 0.5,
        "reproducibility": 0.5,
    },
}


CONCERN_TO_ROLE: dict[str, str] = {
    "algorithm": "theorist",
    "reproducibility": "experimentalist",
    "performance": "implementer",
    "structure": "code_architect",
    "readability": "code_reviewer",
    "results": "experimentalist",
}


CONCERN_TO_MODEL: dict[str, str] = {
    "algorithm": "gpt-5.4",
    "reproducibility": "gpt-5",
    "performance": "gpt-5.4",
    "structure": "gpt-4.1",
    "readability": "gpt-4.1-mini",
    "results": "gpt-5",
}


__all__ = [
    "DEFAULT_IGNORE_PATTERNS",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_HEADER_LINES",
    "LEVEL_HIGH_THRESHOLD",
    "LEVEL_MEDIUM_THRESHOLD",
    "WEIGHT_SKIP_THRESHOLD",
    "WEIGHT_FULL_COVERAGE_THRESHOLD",
    "MINOR_FILE_FRAGMENTS",
    "FOCUS_PRESETS",
    "CONCERN_TO_ROLE",
    "CONCERN_TO_MODEL",
]
