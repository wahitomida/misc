"""ファイルチャンク化ユーティリティ。

``FileChunker`` は Python ファイルは AST で関数/クラス単位に、それ以外は
行ベースで分割する。LLM トークン上限に収めることが目的。

設計書: ``doc/12_code_review.md`` §12.3.2
"""

from __future__ import annotations

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

DEFAULT_MAX_TOKENS_PER_CHUNK = 8_000
DEFAULT_LINES_PER_CHUNK = 200
DEFAULT_SUB_LINES_PER_CHUNK = 100

# トークン推定 (1 文字 ≈ 0.5 token の粗い近似)
TOKEN_PER_CHAR = 0.5


# ----------------------------------------------------------------------
# FileChunker
# ----------------------------------------------------------------------


class FileChunker:
    """ファイルを token 上限内のチャンクに分割する。"""

    def __init__(
        self,
        max_tokens_per_chunk: int = DEFAULT_MAX_TOKENS_PER_CHUNK,
    ) -> None:
        self.max_tokens = max_tokens_per_chunk

    def chunk_file(
        self,
        content: str,
        path: str,
    ) -> list[dict[str, Any]]:
        """ファイルを分割してチャンクのリストを返す。"""
        if not content:
            return [
                {"file": path, "type": "whole", "lines": "L1-1", "content": ""}
            ]
        if path.endswith(".py"):
            return self._chunk_by_ast(content, path)
        return self._chunk_by_lines(content, path)

    def _chunk_by_ast(
        self,
        content: str,
        path: str,
    ) -> list[dict[str, Any]]:
        """AST で関数/クラス単位に分割する。"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.info(
                "AST parse failed for %s; falling back to line chunks", path
            )
            return self._chunk_by_lines(content, path)

        lines = content.split("\n")
        chunks: list[dict[str, Any]] = []
        for node in tree.body:
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            start = (node.lineno or 1) - 1
            end = node.end_lineno or (start + 1)
            chunk_content = "\n".join(lines[start:end])
            chunk_meta: dict[str, Any] = {
                "file": path,
                "type": type(node).__name__,
                "name": node.name,
                "lines": f"L{start + 1}-{end}",
            }
            if self._estimate_tokens(chunk_content) <= self.max_tokens:
                chunk_meta["content"] = chunk_content
                chunks.append(chunk_meta)
            else:
                sub_chunks = self._chunk_by_lines(
                    chunk_content,
                    path,
                    lines_per_chunk=DEFAULT_SUB_LINES_PER_CHUNK,
                    base_line=start + 1,
                )
                for sc in sub_chunks:
                    sc["parent_type"] = type(node).__name__
                    sc["parent_name"] = node.name
                chunks.extend(sub_chunks)

        if chunks:
            return chunks
        return [
            {
                "file": path,
                "type": "module",
                "lines": f"L1-{len(lines)}",
                "content": content,
            }
        ]

    def _chunk_by_lines(
        self,
        content: str,
        path: str,
        lines_per_chunk: int = DEFAULT_LINES_PER_CHUNK,
        base_line: int = 1,
    ) -> list[dict[str, Any]]:
        lines = content.split("\n")
        chunks: list[dict[str, Any]] = []
        for start_idx in range(0, len(lines), lines_per_chunk):
            end_idx = min(start_idx + lines_per_chunk, len(lines))
            chunk_content = "\n".join(lines[start_idx:end_idx])
            chunks.append(
                {
                    "file": path,
                    "type": "lines",
                    "lines": (
                        f"L{base_line + start_idx}-{base_line + end_idx - 1}"
                    ),
                    "content": chunk_content,
                }
            )
        return chunks

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return int(len(text) * TOKEN_PER_CHAR)


__all__ = [
    "FileChunker",
    "DEFAULT_MAX_TOKENS_PER_CHUNK",
    "DEFAULT_LINES_PER_CHUNK",
    "DEFAULT_SUB_LINES_PER_CHUNK",
    "TOKEN_PER_CHAR",
]
