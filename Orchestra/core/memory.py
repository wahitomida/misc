"""会話メモリとコンテキストウィンドウ管理。

設計書: ``doc/08_memory_context.md`` 全体, ``doc/06_agent.md`` §6.4
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .data_models import RoundLog, TokenCount, Utterance

if TYPE_CHECKING:
    from .api_client import ResilientAPIClient

logger = logging.getLogger(__name__)

# Constants
DEFAULT_MAX_CONTEXT_TOKENS = 5000
DEFAULT_SUMMARY_MODEL = "gpt-4.1"
DEFAULT_SUMMARY_TEMPERATURE = 0.0
DEFAULT_SUMMARY_MAX_TOKENS = 150

# 禁止例抽出 (extract_forbidden_examples) 用の定数
MAX_FORBIDDEN_EXAMPLES = 15
MAX_UTTERANCES_FOR_EXTRACTION = 40
FORBIDDEN_EXAMPLES_MAX_TOKENS = 500

# 会話の流れ (extract_recent_flow) 用の定数
RECENT_FLOW_COUNT = 3
FLOW_CONTENT_MAX_CHARS = 200

# Token 推定 (日本語と英語で異なる係数)
JP_TOKEN_PER_CHAR = 1.5
EN_TOKEN_PER_CHAR = 0.3

# Layer 3 (過去サマリ) を削るときに先頭から残す比率
TRUNCATE_TAIL_RATIO = 0.3


FORBIDDEN_EXAMPLES_PROMPT = """\
以下の議論ログを読み、これまでに既に登場した「具体例・固有名詞・シナリオ」および
「議論の方向性・枠組み」を合計最大 15 個列挙してください。
次のラウンドではこれらを繰り返さないためのリスト化です。

【議論ログ】
{log_text}

【出力形式 (JSON のみ、前後に説明文を付けない)】
{{
  "examples": ["例1", "例2", "例3"]
}}

【抽出のルール】
- 対象 A (具体例): 具体的な企業名、商品名、業界名、ユースケース、シナリオ、
  テクノロジー固有名、数字を含む具体表現、複合語 (例: "失敗ログ台帳"、"差分保存")
- 対象 B (議論の方向性・枠組み): 抽象度が中レベルの表現 (例: "事務作業の効率化"、
  "検証器の差し替え"、"境界案件の人戻し"、"社会受容性フレームワーク" など、
  今後もそこに引き寄せられ得る発想の枠)
- 除外: 「顧客」「品質」「AI」「精度」など一般的すぎる単語
- 重要度の高いもの上位 15 個まで (具体例 10 + 枠組み 5 が目安)
"""


class ContextBudget:
    """1 回の API 呼び出しの token 予算を管理する。

    Attributes:
        max_input: モデルの入力 token 上限。
        output_reserve: 出力用に確保する token 数 (level 別)。
        available_input: 実際に入力に使える上限 (``max_input - output_reserve``)。
    """

    # 各モデルの入力 token 上限 (doc/06_agent.md §6.4.2)
    MODEL_LIMITS: dict[str, int] = {
        "gpt-4.1": 128_000,
        "gpt-4.1-mini": 128_000,
        "gpt-5-mini": 400_000,
        "gpt-5": 400_000,
        "gpt-5.1": 400_000,
        "gpt-5.2": 400_000,
        "gpt-5.4": 1_000_000,
        "claude-sonnet-4": 200_000,
        "claude-sonnet-4-5": 200_000,
        "claude-opus-4-1": 200_000,
        "o1": 200_000,
        "o3-mini": 200_000,
        "o4-mini": 200_000,
    }

    # level → 出力 token 予約量
    OUTPUT_RESERVE: dict[str, int] = {
        "minimal": 200,
        "low": 500,
        "medium": 1_000,
        "high": 2_000,
    }

    DEFAULT_MODEL_LIMIT = 128_000
    DEFAULT_OUTPUT_RESERVE = 1_000

    def __init__(self, model: str, level: str) -> None:
        """Args:
            model: モデル名。未知の場合は ``DEFAULT_MODEL_LIMIT`` を使う。
            level: 発言レベル。未知の場合は ``DEFAULT_OUTPUT_RESERVE``。
        """
        self.max_input = self.MODEL_LIMITS.get(model, self.DEFAULT_MODEL_LIMIT)
        self.output_reserve = self.OUTPUT_RESERVE.get(level, self.DEFAULT_OUTPUT_RESERVE)
        self.available_input = self.max_input - self.output_reserve

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """テキストの token 数を推定する (高速な近似)。

        Args:
            text: 推定対象。

        Returns:
            推定 token 数 (int)。日本語 1 文字 ≈ 1.5 token、英語 1 文字 ≈ 0.3 token。
        """
        if not text:
            return 0
        jp_chars = sum(1 for c in text if ord(c) > 127)
        en_chars = len(text) - jp_chars
        return int(jp_chars * JP_TOKEN_PER_CHAR + en_chars * EN_TOKEN_PER_CHAR)

    def fits(self, system_prompt: str, user_message: str) -> bool:
        """``system + user`` が ``available_input`` に収まるか判定する。"""
        total = self.estimate_tokens(system_prompt) + self.estimate_tokens(user_message)
        return total < self.available_input

    def trim_to_fit(self, system_prompt: str, user_message: str) -> str:
        """``user_message`` を ``available_input`` に収まるように削減する。

        現状の実装は単純な末尾切り詰めで、Layer 4 (直近全文) の保持を最低限
        保証する目的では完璧ではないが、Phase C の範囲では十分。

        Args:
            system_prompt: 削らないシステムプロンプト。
            user_message: 削る対象のユーザーメッセージ。

        Returns:
            ``available_input`` 以内に収まるように調整した ``user_message``。
            既に収まっている場合は元の文字列を返す。
        """
        if self.fits(system_prompt, user_message):
            return user_message

        system_tokens = self.estimate_tokens(system_prompt)
        available_for_user = max(0, self.available_input - system_tokens)
        if available_for_user <= 0:
            return ""

        # 推定 token と文字数の比から、許容文字数を逆算 (安全側に倒す)
        estimated = self.estimate_tokens(user_message)
        if estimated == 0:
            return user_message
        ratio = available_for_user / estimated
        keep_chars = max(0, int(len(user_message) * ratio * 0.95))  # 5% 安全マージン
        return user_message[:keep_chars]


class ConversationMemory:
    """議論の共有メモリ。会話ログと中間要約を保持する。

    Attributes:
        api_client: 要約生成用の API クライアント。
        max_context_tokens: コンテキストとして渡せる token の目安。
        summary_model: 要約生成に使うモデル名。
        full_log: 全発言の構造化ログ (出力 JSON 用)。
        round_summaries: 各ラウンドの要約文字列。
        total_tokens: 累積 token 数。
        total_requests: 累積 API リクエスト数 (本クラスが行ったもの)。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        summary_model: str = DEFAULT_SUMMARY_MODEL,
    ) -> None:
        self.api_client = api_client
        self.max_context_tokens = max_context_tokens
        self.summary_model = summary_model

        self.full_log: list[dict[str, Any]] = []
        self.round_summaries: list[str] = []
        self.total_tokens = TokenCount()
        self.total_requests: int = 0

        # 内部: ラウンドごとのインデックス
        self._rounds: dict[int, list[dict[str, Any]]] = {}
        self._system_events: list[dict[str, Any]] = []
        # 禁止例リストのキャッシュ (ラウンド番号 → 具体例のリスト)。
        # 各ラウンド開始時に extract_forbidden_examples が 1 回だけ埋める。
        self._forbidden_examples_cache: dict[int, list[str]] = {}

    # ------------------------------------------------------------------
    # ログ追加
    # ------------------------------------------------------------------

    def add_utterance(self, utterance: Utterance, round_num: int) -> None:
        """発言をログに追加し、トークン累計を更新する。

        Args:
            utterance: 追加する ``Utterance``。
            round_num: ラウンド番号。
        """
        entry = {
            "round": round_num,
            "sequence": utterance.sequence,
            "speaker": utterance.speaker,
            "speaker_display": utterance.speaker_display,
            "type": utterance.type,
            "content": utterance.content,
            "model": utterance.model,
            "level": utterance.level,
            "tokens_used": {
                "input": int(utterance.tokens_used.get("input", 0)),
                "output": int(utterance.tokens_used.get("output", 0)),
            },
            "duration_sec": utterance.duration_sec,
            "timestamp": datetime.now().isoformat(),
        }

        self.full_log.append(entry)
        self._rounds.setdefault(round_num, []).append(entry)

        self.total_tokens.input += entry["tokens_used"]["input"]
        self.total_tokens.output += entry["tokens_used"]["output"]
        self.total_tokens.total = self.total_tokens.input + self.total_tokens.output
        self.total_requests += 1

    def add_system_event(self, event: str, round_num: int = -1) -> None:
        """システムイベント (堂々巡り検知、時間調整等) を記録する。"""
        self._system_events.append(
            {
                "round": round_num,
                "event": event,
                "timestamp": datetime.now().isoformat(),
            }
        )

    # ------------------------------------------------------------------
    # 取得
    # ------------------------------------------------------------------

    def get_round_utterances(self, round_num: int) -> list[dict[str, Any]]:
        """指定ラウンドの全発言を返す。"""
        return list(self._rounds.get(round_num, []))

    def get_own_recent_utterances(
        self,
        role_id: str,
        current_round: int,
        n: int = 2,
    ) -> list[dict[str, Any]]:
        """指定 role_id の直近 n 発言を返す (問題 P3-B 対策)。

        Agent に「前回の自分の発言」を参照させ、同じ切り出し方を避けさせるため、
        現ラウンド + 過去ラウンドの発言から末尾 n 件を返す。

        Args:
            role_id: 対象エージェントの ``role_id``。
            current_round: 現在のラウンド番号。
            n: 取得する発言数。

        Returns:
            ``[{speaker_display, content, round}]`` のリスト。末尾が最新。
            該当発言が無ければ空リスト。
        """
        if n <= 0:
            return []
        # full_log を末尾から走査して role_id 一致を n 件収集
        matching: list[dict[str, Any]] = []
        for entry in reversed(self.full_log):
            if entry.get("round", 0) > current_round:
                continue
            if entry.get("speaker") != role_id:
                continue
            matching.append(entry)
            if len(matching) >= n:
                break
        matching.reverse()  # 古い順に並べ直す
        return matching

    def get_last_utterance(self, round_num: int) -> dict[str, Any] | None:
        """指定ラウンドの最後の発言を返す。なければ ``None``。"""
        utterances = self._rounds.get(round_num)
        return utterances[-1] if utterances else None

    def get_context_for_agent(
        self,
        current_round: int,
        agent_role_id: str,
        context_budget: ContextBudget,
    ) -> dict[str, Any]:
        """各エージェントに渡すコンテキストを生成する。

        Args:
            current_round: 現在のラウンド番号。
            agent_role_id: 呼び出し元エージェントの ``role_id``。
                ``own_recent_utterances`` の抽出に使用する。
            context_budget: token 予算。

        Returns:
            ``previous_summary``, ``current_round_utterances``,
            ``last_utterance``, ``system_events``, ``forbidden_examples``,
            ``recent_flow``, ``own_recent_utterances`` を含む辞書。
            ``forbidden_examples`` は事前に ``extract_forbidden_examples`` が
            呼ばれていなければ空リスト。
        """
        current_utterances = self.get_round_utterances(current_round)
        all_previous = self._get_all_previous_utterances(current_round)
        previous_text = self._format_utterances(all_previous)

        total_estimate = context_budget.estimate_tokens(previous_text)
        if total_estimate < self.max_context_tokens:
            previous_summary = previous_text
        else:
            previous_summary = "\n".join(self.round_summaries[:current_round])

        own_recent = (
            self.get_own_recent_utterances(agent_role_id, current_round, n=2)
            if agent_role_id
            else []
        )

        return {
            "previous_summary": previous_summary,
            "current_round_utterances": current_utterances,
            "last_utterance": self.get_last_utterance(current_round),
            "system_events": [
                e for e in self._system_events if e["round"] == current_round
            ],
            "forbidden_examples": list(
                self._forbidden_examples_cache.get(current_round, [])
            ),
            "recent_flow": self.extract_recent_flow(current_round, n=RECENT_FLOW_COUNT),
            "own_recent_utterances": own_recent,
        }

    def extract_recent_flow(
        self, current_round: int, n: int = 3
    ) -> list[dict[str, Any]]:
        """直近 n 発言を「会話の流れ」として返す (問題4対策)。

        現ラウンドに発言があれば末尾 n 件、無ければ (現ラウンド最初)
        前ラウンドの末尾 n 件を返す。

        Args:
            current_round: 現在のラウンド番号。
            n: 取得する発言数。

        Returns:
            ``[{speaker_display, content}]`` のリスト。末尾が最新。
        """
        current = self.get_round_utterances(current_round)
        if current:
            source = current[-n:]
        else:
            all_prev = self._get_all_previous_utterances(current_round)
            source = all_prev[-n:]
        return [
            {
                "speaker_display": u["speaker_display"],
                "content": str(u["content"])[:FLOW_CONTENT_MAX_CHARS],
            }
            for u in source
        ]

    async def extract_forbidden_examples(
        self,
        current_round: int,
        model: str | None = None,
    ) -> list[str]:
        """過去ラウンドで既に登場した具体例を LLM で抽出しキャッシュする。

        次のラウンドで同じ例が繰り返されないようにするため、
        Conductor がラウンド開始時に一度だけ呼ぶ想定 (問題2対策)。

        Args:
            current_round: これから開始するラウンドの番号。
            model: 抽出用モデル (未指定なら ``summary_model``)。

        Returns:
            具体例のリスト (最大 ``MAX_FORBIDDEN_EXAMPLES`` 件)。
            前ラウンドの発言がなければ空リスト。
        """
        if current_round <= 1:
            self._forbidden_examples_cache[current_round] = []
            return []

        if current_round in self._forbidden_examples_cache:
            return list(self._forbidden_examples_cache[current_round])

        previous = self._get_all_previous_utterances(current_round)
        if not previous:
            self._forbidden_examples_cache[current_round] = []
            return []

        # 極端に長い履歴は末尾側 (直近ラウンド) だけに絞る
        if len(previous) > MAX_UTTERANCES_FOR_EXTRACTION:
            previous = previous[-MAX_UTTERANCES_FOR_EXTRACTION:]

        log_text = self._format_utterances(previous)
        prompt = FORBIDDEN_EXAMPLES_PROMPT.format(log_text=log_text)

        try:
            response = await self.api_client.call(
                model=model or self.summary_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=FORBIDDEN_EXAMPLES_MAX_TOKENS,
            )
            self.total_requests += 1
            content = str(response.get("content") or "")
            examples = self._parse_forbidden_examples(content)
        except Exception as e:  # noqa: BLE001
            logger.warning("extract_forbidden_examples failed: %s", e)
            examples = []

        self._forbidden_examples_cache[current_round] = examples
        return list(examples)

    @staticmethod
    def _parse_forbidden_examples(content: str) -> list[str]:
        """LLM 応答から具体例リストを抜き出す。パース失敗時は空リスト。"""
        import json
        import re

        text = (content or "").strip()
        if not text:
            return []
        # コードフェンス除去
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence:
            payload = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            payload = text[start : end + 1] if 0 <= start < end else text
        try:
            data = json.loads(payload)
        except (ValueError, json.JSONDecodeError):
            return []
        raw = data.get("examples") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        seen: set[str] = set()
        result: list[str] = []
        for item in raw:
            s = str(item).strip()
            if s and s not in seen:
                seen.add(s)
                result.append(s)
        return result[:MAX_FORBIDDEN_EXAMPLES]

    def get_full_log_text(self) -> str:
        """全ログを Phase 3 用にテキスト化する。"""
        lines: list[str] = []
        current_round = -1
        for entry in self.full_log:
            if entry["round"] != current_round:
                current_round = entry["round"]
                lines.append(f"\n--- Round {current_round} ---")
            lines.append(f"{entry['speaker_display']}: {entry['content']}")
        return "\n".join(lines)

    def get_context_summary(self) -> str:
        """議論全体の短い要約 (介入チェック等で使用)。"""
        if self.round_summaries:
            return "\n".join(self.round_summaries)
        recent = self.full_log[-5:]
        return "\n".join(
            f"{e['speaker_display']}: {e['content'][:50]}..." for e in recent
        )

    # ------------------------------------------------------------------
    # 要約生成
    # ------------------------------------------------------------------

    async def summarize_round(self, round_log: RoundLog) -> None:
        """ラウンド終了時に要約を生成して ``round_summaries`` に追加する。

        Args:
            round_log: 要約対象のラウンドログ。
                ``public_utterances`` / ``phase_name`` / ``goal`` /
                ``convergence_check`` (任意) を参照する。
        """
        utterances_text = "\n".join(
            f"{u.speaker_display}: {u.content}" for u in round_log.public_utterances
        )

        # convergence_check は Phase D で詳細化されるため、存在チェックだけ
        convergence_line = ""
        check = round_log.convergence_check
        if check is not None and hasattr(check, "score"):
            convergence_line = f"収束度: {check.score}\n"

        prompt = (
            "以下の議論ラウンドを3行以内で要約してください。\n"
            "要点・結論・重要な合意/対立のみ。会話調は不要。\n\n"
            f"【Round {round_log.round}: {round_log.phase_name}】\n"
            f"目標: {round_log.goal}\n"
            f"{convergence_line}\n"
            f"{utterances_text}\n\n"
            "要約（3行以内）:"
        )

        response = await self.api_client.call(
            model=self.summary_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_SUMMARY_TEMPERATURE,
            max_tokens=DEFAULT_SUMMARY_MAX_TOKENS,
        )
        summary_text = str(response.get("content", "")).strip()
        self.round_summaries.append(
            f"[R{round_log.round} {round_log.phase_name}] {summary_text}"
        )
        self.total_requests += 1

    # ------------------------------------------------------------------
    # エクスポート
    # ------------------------------------------------------------------

    def export_json(self) -> dict[str, Any]:
        """``discussion.json`` 用のデータをまとめて返す。"""
        return {
            "full_log": list(self.full_log),
            "round_summaries": list(self.round_summaries),
            "system_events": list(self._system_events),
            "statistics": {
                "total_requests": self.total_requests,
                "total_tokens": {
                    "input": self.total_tokens.input,
                    "output": self.total_tokens.output,
                    "total": self.total_tokens.total,
                },
            },
        }

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _get_all_previous_utterances(self, current_round: int) -> list[dict[str, Any]]:
        return [e for e in self.full_log if e["round"] < current_round]

    @staticmethod
    def _format_utterances(utterances: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"{u['speaker_display']}: {u['content']}" for u in utterances
        )


__all__ = [
    "ContextBudget",
    "ConversationMemory",
    "TokenCount",
    "DEFAULT_MAX_CONTEXT_TOKENS",
    "DEFAULT_SUMMARY_MODEL",
]
