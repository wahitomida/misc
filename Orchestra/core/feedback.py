"""ロール YAML へのフィードバック蓄積と次回プロンプト用テキスト生成。

責務:
    - ``feedback_history`` への追記 (§9.4.1)
    - ``feedback_stats`` の自動再計算 (§9.4.2)
    - 古いエントリの圧縮 (§9.4.3)
    - 次回セッション時の ``feedback_context`` 生成 (§9.5.1)
    - 下降傾向時のルール強化判定 (§9.5.2)

設計書: ``doc/09_evaluation_feedback.md`` §9.4-9.5
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .exceptions import RoleNotFoundError

logger = logging.getLogger(__name__)

# Constants (§9.4-9.5)
DEFAULT_MAX_HISTORY = 10
TREND_RECENT_WINDOW = 3
TREND_IMPROVING_THRESHOLD = 0.3
TREND_DECLINING_THRESHOLD = -0.3
EXCEPTIONAL_HIGH_SCORE = 4.8
EXCEPTIONAL_LOW_SCORE = 1.5
MAX_EXCEPTIONAL_KEEP = 2
RECENT_TOPICS_COUNT = 5
MAX_IMPROVEMENTS_IN_CONTEXT = 3
MAX_FEEDBACK_IN_CONTEXT = 2

TREND_IMPROVING = "improving"
TREND_DECLINING = "declining"
TREND_STABLE = "stable"
TREND_INSUFFICIENT = "insufficient_data"


class FeedbackManager:
    """ロール YAML へ評価結果を蓄積し、次回利用のコンテキストを生成する。

    Attributes:
        roles_dir: ロール YAML を格納するディレクトリ。
        max_history: ``feedback_history`` の最大保持件数。これを超えると
            ``_compress_old_entries`` で圧縮される。
    """

    def __init__(
        self,
        roles_dir: Path,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self.roles_dir = Path(roles_dir)
        self.max_history = max_history

    # ------------------------------------------------------------------
    # public API: 書き込み
    # ------------------------------------------------------------------

    def update_role_feedback(
        self,
        role_id: str,
        session_id: str,
        date: str,
        topic: str,
        self_eval: dict[str, Any],
        peer_avg: float,
        orchestrator_feedback: dict[str, Any],
        is_mvp: bool = False,
    ) -> None:
        """セッション結果をロール YAML に追記する。

        Args:
            role_id: ロール識別子。
            session_id: セッション ID。
            date: ``YYYY-MM-DD`` 形式の日付。
            topic: 議論テーマ。
            self_eval: ``{"avg_score": float}`` を含む自己評価辞書。
            peer_avg: 他者評価の平均スコア。
            orchestrator_feedback: ``{"strengths_noted", "improvements_noted",
                "orchestrator_feedback"}`` を含む指揮者フィードバック辞書。
            is_mvp: そのセッションで MVP に選出されたか。
        """
        role = self._load_role(role_id)

        history = role.setdefault("feedback_history", [])
        if not isinstance(history, list):
            logger.warning(
                "feedback_history of %r is not a list; resetting", role_id
            )
            history = []
            role["feedback_history"] = history

        entry = {
            "session_id": session_id,
            "date": date,
            "topic": topic,
            "self_score_avg": float(self_eval.get("avg_score", 0.0) or 0.0),
            "peer_score_avg": float(peer_avg or 0.0),
            "is_mvp": bool(is_mvp),
            "strengths_noted": list(orchestrator_feedback.get("strengths_noted") or []),
            "improvements_noted": list(
                orchestrator_feedback.get("improvements_noted") or []
            ),
            "orchestrator_feedback": str(
                orchestrator_feedback.get("orchestrator_feedback", "")
            ),
        }
        history.append(entry)

        if len(history) > self.max_history:
            role["feedback_history"] = self._compress_old_entries(history)

        role["feedback_stats"] = self._calculate_stats(role["feedback_history"])
        self._apply_auto_weakness(role, date)
        self._save_role(role_id, role)

    # ------------------------------------------------------------------
    # public API: 読み出し
    # ------------------------------------------------------------------

    def generate_feedback_context(self, role_id: str) -> str:
        """次回セッションで ``system_prompt`` に注入するテキストを生成する。

        Args:
            role_id: 対象ロール。

        Returns:
            注入用テキスト。履歴がなければ空文字列。
        """
        try:
            role = self._load_role(role_id)
        except RoleNotFoundError:
            return ""

        history = role.get("feedback_history") or []
        stats = role.get("feedback_stats") or {}
        if not history:
            return ""

        parts: list[str] = []

        # 直近スコアの提示 (自己評価・他者評価・指揮者の期待を統合するプロンプト強化)
        recent_self = stats.get("recent_self_avg")
        recent_peer = stats.get("recent_peer_avg")
        if recent_self or recent_peer:
            parts.append(
                f"【あなたの直近スコア】自己評価 {float(recent_self or 0):.1f} / "
                f"他者評価 {float(recent_peer or 0):.1f} (5点満点)"
            )

        trend = stats.get("trend", TREND_INSUFFICIENT)
        if trend == TREND_IMPROVING:
            parts.append(
                "📈 あなたの評価は改善傾向にあります。この調子を維持してください。"
            )
        elif trend == TREND_DECLINING:
            parts.append(
                "📉 あなたの評価が下降傾向です。以下の改善点を特に意識してください。"
            )

        # 直近セッションで反復して指摘された弱点 (プロンプト改善の中心テーマ)
        recent_top_weakness = stats.get("recent_top_weakness")
        if recent_top_weakness:
            parts.append(
                f"【今回こそ改善すべき主要テーマ】{recent_top_weakness}"
            )

        recent = history[-TREND_RECENT_WINDOW:]
        improvements: list[str] = []
        feedbacks: list[str] = []
        for h in recent:
            for imp in h.get("improvements_noted") or []:
                if imp not in improvements:
                    improvements.append(str(imp))
            fb = h.get("orchestrator_feedback", "")
            if fb and fb not in feedbacks:
                feedbacks.append(str(fb))

        if improvements:
            parts.append("【過去に指摘された改善点】")
            for imp in improvements[-MAX_IMPROVEMENTS_IN_CONTEXT:]:
                parts.append(f"- {imp}")

        if feedbacks:
            parts.append("【指揮者からの継続的な期待】")
            for fb in feedbacks[-MAX_FEEDBACK_IN_CONTEXT:]:
                parts.append(f"- {fb}")

        top_strength = stats.get("top_strength")
        if top_strength:
            parts.append(
                f"【あなたの強み】{top_strength} — これを活かしてください。"
            )

        return "\n".join(parts)

    # FeedbackProtocol (D-1 Orchestrator) との互換エイリアス
    def generate_context_from_history(self, role_id: str) -> str:
        """``Orchestrator.FeedbackProtocol`` インターフェース互換エイリアス。"""
        return self.generate_feedback_context(role_id)

    def should_reinforce_rules(self, role_id: str) -> bool:
        """直近トレンドが ``declining`` ならルール強化が必要と判定する。"""
        try:
            role = self._load_role(role_id)
        except RoleNotFoundError:
            return False
        stats = role.get("feedback_stats") or {}
        return stats.get("trend") == TREND_DECLINING

    # ------------------------------------------------------------------
    # personality への自動反映 (§9.5 プロンプト改善)
    # ------------------------------------------------------------------

    def _apply_auto_weakness(self, role: dict[str, Any], date: str) -> None:
        """直近セッションから観測された弱点を ``personality`` に自動反映する。

        ユーザーが手動編集する ``personality.weakness`` は書き換えず、
        別フィールド ``personality.observed_weaknesses`` に蓄積する。
        次回セッションでは ``generate_feedback_context`` 経由で
        ``system_prompt`` に注入されるため、ロールは自身の弱点を意識した
        応答を返せるようになる。
        """
        stats = role.get("feedback_stats") or {}
        recent_top_weakness = stats.get("recent_top_weakness")
        if not recent_top_weakness:
            return

        history = role.get("feedback_history") or []
        recent_improvements: list[str] = []
        for h in history[-TREND_RECENT_WINDOW:]:
            for imp in h.get("improvements_noted") or []:
                if imp and imp not in recent_improvements:
                    recent_improvements.append(str(imp))

        personality = role.get("personality")
        if not isinstance(personality, dict):
            personality = {}
            role["personality"] = personality

        personality["observed_weaknesses"] = {
            "top_theme": recent_top_weakness,
            "recent_improvements": recent_improvements[-MAX_IMPROVEMENTS_IN_CONTEXT:],
            "recent_self_avg": stats.get("recent_self_avg", 0.0),
            "recent_peer_avg": stats.get("recent_peer_avg", 0.0),
            "last_updated": date,
        }

    # ------------------------------------------------------------------
    # 統計
    # ------------------------------------------------------------------

    def _calculate_stats(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        """``feedback_history`` から統計辞書を計算する (§9.4.2)。"""
        if not history:
            return {}

        self_scores = [float(h.get("self_score_avg") or 0.0) for h in history]
        peer_scores = [float(h.get("peer_score_avg") or 0.0) for h in history]
        # 直近 N 件のスコアを別途集計 (プロンプト改善の主インプット)
        recent_self = self_scores[-TREND_RECENT_WINDOW:]
        recent_peer = peer_scores[-TREND_RECENT_WINDOW:]

        trend = self._calculate_trend(peer_scores)

        all_strengths: list[str] = []
        all_improvements: list[str] = []
        recent_improvements: list[str] = []
        recent_feedbacks: list[str] = []
        for h in history:
            all_strengths.extend(h.get("strengths_noted") or [])
            all_improvements.extend(h.get("improvements_noted") or [])
        for h in history[-TREND_RECENT_WINDOW:]:
            recent_improvements.extend(h.get("improvements_noted") or [])
            fb = h.get("orchestrator_feedback", "")
            if fb:
                recent_feedbacks.append(str(fb))

        return {
            "total_sessions": len(history),
            "avg_self_score": round(sum(self_scores) / len(self_scores), 2),
            "avg_peer_score": round(sum(peer_scores) / len(peer_scores), 2),
            "recent_self_avg": round(sum(recent_self) / len(recent_self), 2)
                if recent_self else 0.0,
            "recent_peer_avg": round(sum(recent_peer) / len(recent_peer), 2)
                if recent_peer else 0.0,
            "trend": trend,
            "top_strength": self._most_common_theme(all_strengths),
            "top_weakness": self._most_common_theme(all_improvements),
            "recent_top_weakness": self._most_common_theme(recent_improvements),
            "recent_topics": [
                str(h.get("topic", "")) for h in history[-RECENT_TOPICS_COUNT:]
            ],
        }

    @staticmethod
    def _calculate_trend(scores: list[float]) -> str:
        """スコア推移から ``improving`` / ``declining`` / ``stable`` を判定する。

        直近 ``TREND_RECENT_WINDOW`` 件とそれ以前の平均を比較。比較する
        サンプルがない場合は ``insufficient_data``。
        """
        if len(scores) < TREND_RECENT_WINDOW:
            return TREND_INSUFFICIENT

        recent = scores[-TREND_RECENT_WINDOW:]
        earlier = scores[:-TREND_RECENT_WINDOW]
        if not earlier:
            return TREND_INSUFFICIENT

        diff = (sum(recent) / len(recent)) - (sum(earlier) / len(earlier))
        if diff > TREND_IMPROVING_THRESHOLD:
            return TREND_IMPROVING
        if diff < TREND_DECLINING_THRESHOLD:
            return TREND_DECLINING
        return TREND_STABLE

    @staticmethod
    def _most_common_theme(items: list[str]) -> str:
        """テキストリストから最頻出テーマを返す。

        全テキストが完全一致しなければ「最新の項目」を返す (§9.4.2 簡易版)。
        """
        if not items:
            return ""
        counter = Counter(items)
        most_common, top_count = counter.most_common(1)[0]
        if top_count > 1:
            return most_common
        return items[-1]

    # ------------------------------------------------------------------
    # 圧縮
    # ------------------------------------------------------------------

    def _compress_old_entries(
        self,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """``max_history`` を超えた古いエントリを圧縮する (§9.4.3)。

        直近 ``max_history`` 件を保持しつつ、それ以前にあった例外的に
        重要なエントリ (``self_score_avg`` が ``EXCEPTIONAL_HIGH_SCORE``
        以上または ``EXCEPTIONAL_LOW_SCORE`` 以下) を最大
        ``MAX_EXCEPTIONAL_KEEP`` 件だけ先頭に残す。
        """
        if len(history) <= self.max_history:
            return list(history)

        keep = history[-self.max_history :]
        older = history[: -self.max_history]
        exceptional = [
            h
            for h in older
            if float(h.get("self_score_avg") or 3.0) >= EXCEPTIONAL_HIGH_SCORE
            or float(h.get("self_score_avg") or 3.0) <= EXCEPTIONAL_LOW_SCORE
        ]
        exceptional = exceptional[-MAX_EXCEPTIONAL_KEEP:]
        return exceptional + keep

    # ------------------------------------------------------------------
    # 内部 I/O
    # ------------------------------------------------------------------

    def _role_path(self, role_id: str) -> Path:
        return self.roles_dir / f"{role_id}.yaml"

    def _load_role(self, role_id: str) -> dict[str, Any]:
        path = self._role_path(role_id)
        if not path.exists():
            raise RoleNotFoundError(f"Role '{role_id}' not found at {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise RoleNotFoundError(
                f"Role file {path} must contain a mapping at top level"
            )
        return data

    def _save_role(self, role_id: str, data: dict[str, Any]) -> None:
        path = self._role_path(role_id)
        path.write_text(
            yaml.dump(
                data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


__all__ = [
    "FeedbackManager",
    "DEFAULT_MAX_HISTORY",
    "TREND_IMPROVING",
    "TREND_DECLINING",
    "TREND_STABLE",
    "TREND_INSUFFICIENT",
]
