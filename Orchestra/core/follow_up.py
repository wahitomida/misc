"""フォローアップセッションの引き継ぎ機構。

責務:
    - 過去 ``discussion.json`` / ``report.md`` から ``FollowUpContext`` を組み立てる
    - 仮説テーブルの状態遷移を管理する (``HypothesisManager``)
    - 添付ファイルの読み込み・検証を行う (``AttachmentProcessor``)

設計書: ``doc/13_follow_up.md`` 全体
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .data_models import FollowUpContext
from .exceptions import (
    FileTooLargeError,
    SessionNotFoundError,
    TooManyAttachmentsError,
    UnsupportedFileTypeError,
)

if TYPE_CHECKING:
    from .api_client import ResilientAPIClient

logger = logging.getLogger(__name__)

# Constants
DEFAULT_COMPRESSION_MODEL = "gpt-4.1"
DEFAULT_COMPRESSION_TEMPERATURE = 0.0
DEFAULT_COMPRESSION_MAX_TOKENS = 200
MAX_FALLBACK_LINES = 5

# 仮説テーブル状態の表記マッピング
STATUS_EMOJI: dict[str, str] = {
    "unverified": "🔲 未検証",
    "confirmed": "✅ 確認済み",
    "rejected": "❌ 棄却",
    "modified": "🔄 修正",
}

# Markdown テーブル parse 用
_HYPOTHESIS_TABLE_ROW = re.compile(r"^\|\s*H\d+\s*\|")
_HYPOTHESIS_TABLE_HEADER = re.compile(r"\|\s*ID\s*\|", re.IGNORECASE)
_HYPOTHESIS_ID_RE = re.compile(r"^H\d+", re.IGNORECASE)


# ======================================================================
# FollowUpManager
# ======================================================================


class FollowUpManager:
    """過去セッションから引き継ぎコンテキストを組み立てる。

    Attributes:
        output_dir: セッションディレクトリの親 (例: ``./output``)。
        api_client: 議論圧縮 (``_compress_discussion``) に使う API クライアント。
            ``None`` の場合はフォールバック (LLM 非経由) で要約する。
    """

    def __init__(
        self,
        output_dir: Path,
        api_client: "ResilientAPIClient | None" = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.api_client = api_client

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def load_previous_session(self, session_id: str) -> FollowUpContext:
        """過去セッションを読み込み ``FollowUpContext`` を返す。

        Args:
            session_id: 過去セッションの ID (出力ディレクトリ名)。

        Returns:
            前回の結論・仮説・未解決・参加者情報を含むコンテキスト。

        Raises:
            SessionNotFoundError: 指定セッションが存在しない、または必須
                ファイル (``discussion.json``) が無い。
        """
        session_dir = self.output_dir / session_id
        if not session_dir.exists():
            raise SessionNotFoundError(
                f"セッション '{session_id}' が見つかりません: {session_dir}"
            )

        report_path = session_dir / "report.md"
        meta_path = session_dir / "session_meta.json"

        conclusion = self._extract_conclusion(session_dir)
        hypotheses = (
            self._extract_hypotheses(report_path) if report_path.exists() else []
        )
        unresolved = (
            self._extract_unresolved(report_path) if report_path.exists() else []
        )
        agents, feedback = self._extract_agent_info(session_dir)
        discussion_summary = await self._compress_discussion(session_dir)

        chain = self._build_chain(meta_path, session_id)

        return FollowUpContext(
            parent_session_id=session_id,
            previous_conclusion=conclusion,
            previous_hypotheses=hypotheses,
            unresolved_issues=unresolved,
            discussion_summary=discussion_summary,
            previous_agents=agents,
            previous_feedback=feedback,
            chain=chain,
            chain_depth=len(chain),
        )

    # ------------------------------------------------------------------
    # 個別抽出
    # ------------------------------------------------------------------

    def _extract_conclusion(self, session_dir: Path) -> str:
        """``discussion.json`` から結論文字列を抽出する。

        ``synthesis.final_conclusion`` が存在しなければ
        ``orchestrator_evaluation.odsc_achievement.detail`` をフォールバックに使う。
        """
        data = self._load_discussion_json(session_dir)
        synthesis = data.get("synthesis") or {}
        final = synthesis.get("final_conclusion")
        if final:
            return str(final).strip()

        orch_eval = data.get("orchestrator_evaluation") or {}
        achievement = orch_eval.get("odsc_achievement") or {}
        detail = achievement.get("detail")
        if detail:
            return str(detail).strip()

        return ""

    def _extract_hypotheses(self, report_path: Path) -> list[dict[str, str]]:
        """``report.md`` の Markdown テーブルから仮説を抽出する。

        テーブル列の最低数 (ID/仮説/状態/検証方法) を満たす行のみ採用する。
        """
        try:
            content = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to read %s: %s", report_path, e)
            return []

        hypotheses: list[dict[str, str]] = []
        in_table = False
        for line in content.splitlines():
            if _HYPOTHESIS_TABLE_HEADER.search(line):
                in_table = True
                continue
            if not in_table:
                continue
            if not _HYPOTHESIS_TABLE_ROW.match(line):
                # テーブル終端を検知
                if line.strip() and not line.lstrip().startswith("|"):
                    in_table = False
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 4:
                continue
            hid = parts[0]
            if not _HYPOTHESIS_ID_RE.match(hid):
                continue
            hypotheses.append(
                {
                    "id": hid,
                    "hypothesis": parts[1],
                    "status": self._parse_status(parts[2]),
                    "verification_method": parts[3],
                }
            )
        return hypotheses

    def _extract_unresolved(self, report_path: Path) -> list[str]:
        """``report.md`` の「未解決問題」セクションからリストを抽出する。"""
        try:
            content = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Failed to read %s: %s", report_path, e)
            return []

        issues: list[str] = []
        in_section = False
        for line in content.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                if "未解決" in stripped:
                    in_section = True
                    continue
                if in_section:
                    # 別の見出しに到達 → セクション終了
                    break
                continue
            if not in_section:
                continue
            text = stripped.strip()
            if not text:
                continue
            # `- xxx` または `1. xxx` 形式
            cleaned = re.sub(r"^[\-\*\u30fb]\s+", "", text)
            cleaned = re.sub(r"^\d+\.\s*", "", cleaned)
            if cleaned and cleaned != text:
                issues.append(cleaned)
            elif cleaned.startswith("- "):
                # 念のため
                issues.append(cleaned[2:].strip())
        return [i for i in issues if i]

    async def _compress_discussion(self, session_dir: Path) -> str:
        """議論全体を 3〜5 行に圧縮する。

        ``api_client`` が無い場合は LLM 非経由のフォールバックで、
        各ラウンドの ``reasoning`` を直接連結する。
        """
        data = self._load_discussion_json(session_dir)
        discussion = data.get("discussion") or {}
        rounds = discussion.get("rounds") or []

        round_conclusions: list[str] = []
        for r in rounds:
            convergence = r.get("convergence_check") or {}
            reasoning = convergence.get("reasoning") or ""
            if reasoning:
                round_conclusions.append(f"R{r.get('round', '?')}: {reasoning}")

        if not round_conclusions:
            return ""

        full_text = "\n".join(round_conclusions)

        if self.api_client is None:
            return "\n".join(round_conclusions[:MAX_FALLBACK_LINES])

        prompt = (
            "以下の議論の流れを3-5行に圧縮してください。\n"
            "結論と重要な転換点のみ残す。詳細は不要。\n\n"
            f"{full_text}\n\n"
            "圧縮版（3-5行）:"
        )
        try:
            response = await self.api_client.call(
                model=DEFAULT_COMPRESSION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=DEFAULT_COMPRESSION_TEMPERATURE,
                max_tokens=DEFAULT_COMPRESSION_MAX_TOKENS,
            )
        except Exception as e:  # noqa: BLE001 - 圧縮失敗で全体停止させない
            logger.warning("Discussion compression failed: %s", e)
            return "\n".join(round_conclusions[:MAX_FALLBACK_LINES])
        return str(response.get("content", "")).strip()

    def _extract_agent_info(
        self,
        session_dir: Path,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """前回の参加者情報と評価を抽出する。

        Returns:
            ``(selected_agents, orchestrator_evaluation)`` のタプル。
        """
        data = self._load_discussion_json(session_dir)
        planning = data.get("planning") or {}
        agents = planning.get("selected_agents") or []
        if not isinstance(agents, list):
            agents = []

        # E-2 OutputGenerator のスキーマでは orchestrator_evaluation がトップ
        # レベルに格納される。設計書サンプルの ``evaluation.orchestrator_feedback``
        # 形式にもフォールバック。
        feedback: dict[str, Any] = {}
        orch_eval = data.get("orchestrator_evaluation")
        if isinstance(orch_eval, dict):
            feedback = orch_eval
        else:
            eval_section = data.get("evaluation") or {}
            if isinstance(eval_section, dict):
                fb = eval_section.get("orchestrator_feedback")
                if isinstance(fb, dict):
                    feedback = fb

        return agents, feedback

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _load_discussion_json(self, session_dir: Path) -> dict[str, Any]:
        path = session_dir / "discussion.json"
        if not path.exists():
            raise SessionNotFoundError(
                f"discussion.json が見つかりません: {path}"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse %s: %s", path, e)
            return {}

    @staticmethod
    def _parse_status(status_text: str) -> str:
        if "✅" in status_text or "確認" in status_text:
            return "confirmed"
        if "❌" in status_text or "棄却" in status_text:
            return "rejected"
        if "🔄" in status_text or "修正" in status_text:
            return "modified"
        return "unverified"

    def _build_chain(
        self,
        meta_path: Path,
        session_id: str,
    ) -> list[str]:
        """``session_meta.json`` からチェーンを構築する (失敗時は単一要素)。"""
        if not meta_path.exists():
            return [session_id]
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse %s: %s", meta_path, e)
            return [session_id]
        chain = (meta.get("follow_up") or {}).get("chain") or []
        if not isinstance(chain, list):
            return [session_id]
        # 既存チェーン + 自身 (重複除外)
        result = [str(s) for s in chain if isinstance(s, str)]
        if session_id not in result:
            result.append(session_id)
        return result


# ======================================================================
# HypothesisManager
# ======================================================================


class HypothesisManager:
    """仮説テーブルの状態遷移と Markdown 出力を管理する。

    設計書 §13.5 の状態遷移図に準拠:
        - ``unverified`` → ``confirmed`` / ``rejected`` / ``modified``
        - ``confirmed`` → (変更不可)
        - ``rejected`` → ``modified`` のみ
        - ``modified`` → ``confirmed`` / ``rejected``
    """

    VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
        "unverified": ("confirmed", "rejected", "modified"),
        "confirmed": (),
        "rejected": ("modified",),
        "modified": ("confirmed", "rejected"),
    }

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def apply_updates(
        self,
        hypotheses: list[dict[str, Any]],
        updates: dict[str, dict[str, Any]],
        new_hypotheses: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """既存仮説の状態を更新し、新規仮説を追加する。

        Args:
            hypotheses: 既存の仮説リスト。各要素は ``id``, ``hypothesis``,
                ``status``, ``verification_method`` を含む。
            updates: ``id`` → ``{"new_status", "note", "session_id"}`` の辞書。
            new_hypotheses: 新規追加する仮説のリスト (``id`` は未指定可)。

        Returns:
            更新後の仮説リスト。
        """
        updated: list[dict[str, Any]] = []
        for h in hypotheses:
            h_copy = dict(h)
            h_id = h_copy.get("id", "")
            current_status = h_copy.get("status", "unverified")
            if h_id in updates:
                update = updates[h_id]
                new_status = update.get("new_status", current_status)
                if new_status in self.VALID_TRANSITIONS.get(current_status, ()):
                    h_copy["status"] = new_status
                    h_copy["note"] = update.get("note", h_copy.get("note", ""))
                    h_copy["updated_session"] = update.get("session_id", "")
                else:
                    h_copy["_invalid_transition_attempted"] = new_status
                    logger.warning(
                        "Invalid transition for %s: %s -> %s",
                        h_id,
                        current_status,
                        new_status,
                    )
            updated.append(h_copy)

        if new_hypotheses:
            max_num = self._get_max_num(updated)
            for i, raw in enumerate(new_hypotheses, start=1):
                new_h = dict(raw)
                if not new_h.get("id"):
                    new_h["id"] = f"H{max_num + i}"
                new_h.setdefault("status", "unverified")
                new_h.setdefault("verification_method", "")
                updated.append(new_h)
        return updated

    def generate_table_markdown(self, hypotheses: list[dict[str, Any]]) -> str:
        """仮説リストを Markdown テーブルとして出力する。"""
        if not hypotheses:
            return "(仮説なし)"
        lines = ["| ID | 仮説 | 状態 | 検証方法 | 備考 |", "|---|---|---|---|---|"]
        for h in hypotheses:
            emoji = STATUS_EMOJI.get(h.get("status", "unverified"), "?")
            note = str(h.get("note", ""))
            lines.append(
                f"| {h.get('id', '?')} | {h.get('hypothesis', '')} | "
                f"{emoji} | {h.get('verification_method', '')} | {note} |"
            )
        return "\n".join(lines)

    @staticmethod
    def build_focus_context(
        hypotheses: list[dict[str, Any]],
        focus_ids: list[str],
    ) -> str:
        """``--focus-hypothesis`` 指定の仮説コンテキストを構築する (§13.2.3)。"""
        focus_set = set(focus_ids)
        targets = [h for h in hypotheses if h.get("id") in focus_set]
        if not targets:
            return ""

        emoji_map = {
            "unverified": "🔲",
            "confirmed": "✅",
            "rejected": "❌",
            "modified": "🔄",
        }
        parts: list[str] = [
            "【フォーカスする仮説】以下の仮説について重点的に議論してください:",
            "",
        ]
        for h in targets:
            status = h.get("status", "unverified")
            emoji = emoji_map.get(status, "?")
            parts.append(
                f"  ★ {h.get('id', '?')}: {h.get('hypothesis', '')} "
                f"[{emoji} {status}]"
            )
            verification = h.get("verification_method", "")
            if verification:
                parts.append(f"    検証方法: {verification}")
            note = h.get("note", "")
            if note:
                parts.append(f"    補足: {note}")
            parts.append("")
        parts.append(
            "上記以外の仮説にも触れてよいが、フォーカス仮説を優先すること。"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _get_max_num(hypotheses: list[dict[str, Any]]) -> int:
        """既存仮説 ID の最大番号を返す (見つからなければ 0)。"""
        nums: list[int] = []
        for h in hypotheses:
            h_id = str(h.get("id", ""))
            match = re.match(r"^H(\d+)", h_id, re.IGNORECASE)
            if match:
                try:
                    nums.append(int(match.group(1)))
                except ValueError:
                    pass
        return max(nums) if nums else 0


# ======================================================================
# AttachmentProcessor
# ======================================================================


class AttachmentProcessor:
    """添付ファイルの読み込みと前処理。

    制約 (§13.2.2):
        - 最大ファイル数: ``MAX_FILES``
        - 1 ファイル最大サイズ: ``MAX_FILE_SIZE`` バイト
        - 合計最大文字数: ``MAX_TOTAL_CHARS``
        - 対応拡張子: ``ALLOWED_EXTENSIONS``
    """

    MAX_FILES: int = 5
    MAX_FILE_SIZE: int = 50_000
    MAX_TOTAL_CHARS: int = 10_000
    ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
        {".txt", ".csv", ".md", ".json", ".yaml", ".yml", ".py", ".log"}
    )

    def process(self, file_paths: list[Path]) -> list[dict[str, Any]]:
        """添付ファイルリストを検証して内容を読み込む。

        Args:
            file_paths: 添付ファイルの ``Path`` リスト。

        Returns:
            ``[{"name", "path", "size_bytes", "content"}]`` のリスト。

        Raises:
            TooManyAttachmentsError: ``MAX_FILES`` 超過。
            FileNotFoundError: 存在しないパス。
            UnsupportedFileTypeError: 許容外拡張子。
            FileTooLargeError: ``MAX_FILE_SIZE`` 超過。
        """
        if len(file_paths) > self.MAX_FILES:
            raise TooManyAttachmentsError(
                f"添付ファイルは最大{self.MAX_FILES}個まで (指定: {len(file_paths)})"
            )

        attachments: list[dict[str, Any]] = []
        total_chars = 0

        for path in file_paths:
            if not path.exists():
                raise FileNotFoundError(f"ファイルが見つかりません: {path}")
            if path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
                raise UnsupportedFileTypeError(
                    f"非対応形式: {path.suffix} (許容: "
                    f"{sorted(self.ALLOWED_EXTENSIONS)})"
                )
            size = path.stat().st_size
            if size > self.MAX_FILE_SIZE:
                raise FileTooLargeError(
                    f"ファイルが大きすぎます ({size} bytes, 上限 "
                    f"{self.MAX_FILE_SIZE}): {path}"
                )

            content = path.read_text(encoding="utf-8", errors="replace")
            original_len = len(content)

            if total_chars + original_len > self.MAX_TOTAL_CHARS:
                remaining = max(0, self.MAX_TOTAL_CHARS - total_chars)
                if remaining <= 0:
                    content = (
                        f"(以降省略。前のファイルで合計上限 "
                        f"{self.MAX_TOTAL_CHARS} 文字に到達)"
                    )
                else:
                    content = (
                        content[:remaining]
                        + f"\n... (以降省略。全{original_len}文字中"
                        f"{remaining}文字を掲載)"
                    )

            total_chars += len(content)

            attachments.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": size,
                    "content": content,
                }
            )
        return attachments


__all__ = [
    "FollowUpManager",
    "HypothesisManager",
    "AttachmentProcessor",
    "STATUS_EMOJI",
]
