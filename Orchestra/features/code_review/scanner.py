"""フォルダスキャナ: 対象ディレクトリの全ファイル情報を集める。

設計書: ``doc/12_code_review.md`` §12.2.1
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from core.data_models import ScanResult
from features.code_review.constants import (
    DEFAULT_HEADER_LINES,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
)

if TYPE_CHECKING:
    from core.config_loader import Settings

logger = logging.getLogger(__name__)


class FolderScanner:
    """対象フォルダをスキャンして ``ScanResult`` を返す。"""

    def __init__(self, settings: "Settings | None" = None) -> None:
        cr_config: dict[str, Any] = (
            getattr(settings, "code_review", {}) or {} if settings else {}
        )
        self.ignore_patterns: list[str] = list(
            cr_config.get("ignore_patterns") or DEFAULT_IGNORE_PATTERNS
        )
        self.max_file_size: int = int(
            cr_config.get("max_file_size_bytes", DEFAULT_MAX_FILE_SIZE_BYTES)
        )
        self.header_lines: int = int(
            cr_config.get("header_lines", DEFAULT_HEADER_LINES)
        )

    def scan(
        self,
        target_path: Path,
        extra_ignores: list[str] | None = None,
    ) -> ScanResult:
        """対象フォルダをスキャンし、``ScanResult`` を返す。"""
        target_path = Path(target_path)
        if not target_path.exists():
            logger.warning("Scan target does not exist: %s", target_path)
            return ScanResult(target_path=target_path)

        ignores = self.ignore_patterns + list(extra_ignores or [])
        file_tree: list[dict[str, Any]] = []
        file_details: list[dict[str, Any]] = []

        for file_path in self._walk_files(target_path, ignores):
            try:
                stat = file_path.stat()
            except OSError as e:
                logger.warning("Failed to stat %s: %s", file_path, e)
                continue

            rel_path = file_path.relative_to(target_path)
            file_info: dict[str, Any] = {
                "path": str(rel_path).replace("\\", "/"),
                "size_bytes": stat.st_size,
                "extension": file_path.suffix,
                "lines": self._count_lines(file_path),
            }

            if stat.st_size <= self.max_file_size:
                file_info["header"] = self._read_header(file_path)
                file_tree.append(file_info)
                file_details.append(file_info)
            else:
                file_info["skipped"] = True
                file_info["skip_reason"] = (
                    f"ファイルサイズ超過 ({stat.st_size} bytes > "
                    f"{self.max_file_size})"
                )
                file_tree.append(file_info)

        return ScanResult(
            target_path=target_path,
            file_tree=file_tree,
            file_details=file_details,
            total_files=len(file_tree),
            total_lines=sum(f.get("lines", 0) for f in file_tree),
            skipped_files=[f for f in file_tree if f.get("skipped")],
        )

    def _walk_files(
        self,
        path: Path,
        ignores: list[str],
    ) -> Iterator[Path]:
        """ignore パターンを除外してファイルを列挙する。"""
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(path)).replace("\\", "/")
            if self._should_ignore(
                rel, file_path.name, file_path.parts, ignores
            ):
                continue
            yield file_path

    @staticmethod
    def _should_ignore(
        rel: str,
        name: str,
        parts: tuple[str, ...],
        ignores: list[str],
    ) -> bool:
        for pat in ignores:
            if fnmatch.fnmatch(rel, pat):
                return True
            if fnmatch.fnmatch(name, pat):
                return True
            if pat in parts:
                return True
        return False

    def _read_header(self, file_path: Path) -> str:
        """ファイル先頭 ``header_lines`` 行を返す (失敗時は空文字列)。"""
        try:
            with file_path.open(
                "r", encoding="utf-8", errors="replace"
            ) as f:
                lines: list[str] = []
                for i, line in enumerate(f):
                    if i >= self.header_lines:
                        break
                    lines.append(line)
                return "".join(lines)
        except OSError as e:
            logger.warning("Failed to read header from %s: %s", file_path, e)
            return ""

    @staticmethod
    def _count_lines(file_path: Path) -> int:
        """ファイルの行数を返す (失敗時は 0)。"""
        try:
            with file_path.open("rb") as f:
                return sum(1 for _ in f)
        except OSError as e:
            logger.warning("Failed to count lines in %s: %s", file_path, e)
            return 0


__all__ = ["FolderScanner"]
