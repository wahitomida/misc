"""Phase 3: 議論の評価統合と最終出力を担う ``Synthesizer``。

責務:
    - 全エージェントの自己 + 他者評価を並列実行 (D-4 前半)
    - 指揮者による総合評価 (MVP / ODSC 達成度 / 個別フィードバック) 取得
    - ``report.md`` / ``full_conversation.md`` / ``evaluation.md`` /
      ``summary.txt`` の生成 (D-4 後半、テンプレートベース)
    - ``session_meta`` 生成
    - ``_extract_hypotheses`` で議論ログから仮説を抽出

レポート生成は LLM を経由せず、構造化済みの ``OrchestratorEvaluation`` /
``AgentEvaluations`` から決定的にマークダウンを組み立てる。``vibe_coding_prompt.md``
(機能②) は Phase F-2 で実装する。

設計書: ``doc/09_evaluation_feedback.md`` §9.3, ``doc/14_output_format.md`` §14.4-14.7
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .data_models import (
    AgentEvaluations,
    AgentFeedback,
    DiscussionLog,
    ODSCAchievement,
    OrchestraPlan,
    OrchestratorEvaluation,
    PeerEvaluation,
    SynthesisResult,
)
from .evaluator import Evaluator

if TYPE_CHECKING:
    from .agent import Agent
    from .api_client import ResilientAPIClient
    from .config_loader import Settings
    from .memory import ConversationMemory

logger = logging.getLogger(__name__)

# Constants
DEFAULT_SYNTHESIZER_MODEL_KEY = "synthesizer"
DEFAULT_SYNTHESIZER_MODEL = "claude-sonnet-4-5"
DEFAULT_SYNTHESIZER_LEVEL = "medium"
ORCHESTRATOR_EVAL_MAX_TOKENS = 2000
ORCHESTRATOR_EVAL_TEMPERATURE = 0.3
SESSION_ID_TIME_FORMAT = "%Y%m%d_%H%M%S"

# レポート整形
TOOL_VERSION = "AI Orchestra v1.0"
SUMMARY_DIVIDER = "━" * 40
MAX_INSIGHTS_FOR_SUMMARY = 5
MAX_HYPOTHESES = 10

# 仮説抽出パターン (LLM 抽出が失敗した場合のフォールバック用)
HYPOTHESIS_ID_PATTERN = re.compile(r"\b(H\d{1,2})\b")
# 「仮説:」「と仮定」「と仮説」を含む発言を補助的に拾う
HYPOTHESIS_KEYWORDS = ("仮説", "hypothesis")
# 参考文献抽出: (Author+YYYY) または (Author+YYYY, arXiv)
CITATION_PATTERN = re.compile(r"\([A-Z][\w\-\u00C0-\u024F]+\+(?:19|20)\d{2}(?:,\s*arXiv)?\)")

# LLM 仮説抽出のパラメータ
HYPOTHESIS_EXTRACTION_TEMPERATURE = 0.0
HYPOTHESIS_EXTRACTION_MAX_TOKENS = 1500
HYPOTHESIS_MIN_COUNT = 3

# レポート・タイトル生成のパラメータ
REPORT_GENERATION_TEMPERATURE = 0.3
REPORT_GENERATION_MAX_TOKENS = 2500
TITLE_GENERATION_TEMPERATURE = 0.4
TITLE_GENERATION_MAX_TOKENS = 100

# P0-A: レポート/仮説生成のロバスト化パラメータ
MAX_LOG_CHARS_FOR_REPORT = 8000       # LLM に渡す議論ログの最大文字数
MAX_LOG_CHARS_FOR_HYPOTHESIS = 6000   # 仮説抽出用のログ最大文字数
REPORT_MIN_USABLE_LEN = 100           # LLM 生成レポートの最小長 (これ未満は fallback)
HYPOTHESIS_RETRY_PROMPT_PREFIX = (
    "以下のプロンプトに JSON オブジェクトのみで応答してください。"
    "コードフェンス、前置き、末尾説明は一切禁止です。\n\n"
)
# 因果パターン (LLM 抽出も regex fallback 両方失敗した時の最終手段)
CAUSAL_HYPOTHESIS_PATTERN = re.compile(
    r"[^。\n]{5,80}(?:すれば|すると|なら|であれば)[^。\n]{5,80}"
    r"(?:なる|できる|見える|生む|上がる|下がる|効く|進む|安定|向上|改善|失敗|生じる|につながる)"
)


# ----------------------------------------------------------------------
# プロンプト
# ----------------------------------------------------------------------


ORCHESTRATOR_EVALUATION_PROMPT = """\
議論全体を評価し、総合フィードバックを生成してください。

【ODSC】
{odsc}

【議論ログ全文】
{full_discussion_log}

【各AIの自己評価】
{self_evaluations_formatted}

【各AIの他者評価】
{peer_evaluations_formatted}

【あなたの評価タスク】

1. MVP選出:
- 議論に最も貢献したAIを1体選ぶ
- 選出理由を具体的に（どの発言がどう議論を動かしたか）

2. ODSC達成度:
- Objective は達成されたか
- Success Criteria はどの程度満たされたか
- 達成/未達成の根拠を具体的に

3. 各AIへの個別フィードバック:
- 良かった点 (strengths_noted): 具体的に2-3個
- 改善すべき点 (improvements_noted): 具体的に1-2個
- 次回への期待 (orchestrator_feedback): 1文で

【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
  "overall_discussion_quality": <1.0-5.0 小数点1桁>,
  "mvp": {{
    "role_id": "<MVP の role_id>",
    "reason": "<選出理由>"
  }},
  "odsc_achievement": {{
    "achieved": true,
    "detail": "<達成度の説明>",
    "objective_met": true,
    "deliverable_met": true,
    "criteria_met": true
  }},
  "per_agent_feedback": {{
{per_agent_template}
  }}
}}
"""


# ----------------------------------------------------------------------
# 仮説抽出プロンプト (問題4対策 — 従来の正規表現版はフォールバック)
# ----------------------------------------------------------------------

HYPOTHESIS_EXTRACTION_PROMPT = """\
以下の議論ログから、仮説として扱える主張を抽出してください。

【議論の全ログ】
{full_log}

【仮説として抽出すべきもの】
明示的に「仮説」と書かれていなくても、以下は全て仮説として扱う:
- 因果関係の主張:  「〜すれば〜になる」
- 効果の主張:      「〜は〜に効く」「〜が改善する」
- 価値仮説:        「〜なら〜が嬉しい」「〜のニーズがある」
- リスク仮説:      「〜が障壁になる」「〜が失敗の原因になりうる」

【抽出ルール】
- 最低 3 件、最大 7 件 (議論内容から必ずこの範囲で抽出する)
- 0 件では返さない。議論から抽出しづらい場合でも、含意された仮説を明文化する
- 各仮説には ID (H1, H2, ...) を振る
- ``hypothesis`` は 1 文で仮説内容を書く (会議で口頭で言える言葉遣い、疑似変数禁止)
- ``status`` は "unverified" 固定
- ``verification`` は仮説を検証する方法を 1 文で書く
  (Idea 議論: PoC / ヒアリング / 市場調査 など。Review 議論: A/B テスト / 計測 など)

【必須】回答は必ず有効な JSON オブジェクトのみ。前後に説明文を付けない。

【出力形式】
{{
  "hypotheses": [
    {{"id": "H1", "hypothesis": "...", "status": "unverified", "verification": "..."}},
    {{"id": "H2", "hypothesis": "...", "status": "unverified", "verification": "..."}},
    {{"id": "H3", "hypothesis": "...", "status": "unverified", "verification": "..."}}
  ]
}}
"""


# ----------------------------------------------------------------------
# レポート生成プロンプト (問題4対策 — 新構造 + LLM ベース。旧テンプレは fallback)
# ----------------------------------------------------------------------

REPORT_GENERATION_PROMPT = """\
以下の議論ログをもとに、読者が議論に参加していなくても内容が理解できる
自己完結したレポートを Markdown で生成してください。

【議論テーマ (Objective)】
{objective}

【成果物 (Deliverable)】
{deliverable}

【成功基準 (Success Criteria)】
{success_criteria}

【セッション情報】
- Session ID: {session_id}
- 参加AI: {n_agents}体
- 所要時間: {duration_str}
- 収束度: {convergence:.2f}

【議論の全ログ】
{full_log}

【指揮者の総合評価】
{orchestrator_summary}

## レポート構造 (以下の順序で必ず作る)

# [テーマを端的に表す 20〜40 文字のタイトル]
Session ID / 参加AI / 所要時間 / 収束度 を 1 行で示す

## エグゼクティブサマリー
3〜5 文で議論の結論と最も重要な提案をまとめる。読者がここだけ読んでも価値がある内容にする。

## 議論で得られた主要アイデア
各アイデアを番号付きで列挙 (3〜5 件)。各アイデアに:
- 概要 (2 文)
- 長所
- 懸念点
- 適用領域

## 最有望な提案
議論で最も合意が得られた提案を 1 つ選び、詳細に記述する:
- **何が (What)**:        提案の具体的内容
- **なぜ (Why)**:         他の案より有望な理由
- **どうやって (How)**:   実現ステップ (3〜5 段階)
- **誰が嬉しいか (Who)**: ターゲットユーザーと提供価値
- **どこから (Where)**:   最初に適用すべき領域

## リスクと対策
主要リスクを 3 つ以内で列挙。各リスクに対する具体的な回避策を添える。

## {verification_section_title}
{verification_section_intro}

## 未解決の論点
今後検討が必要な論点を 3 つ以内。各論点に「なぜ未解決か」の 1 文説明を添える。

## 次のアクション
具体的な次のステップを 3 つ以内。各ステップに「誰が / 何を / いつまでに」を含める。

## 書き方のルール (絶対遵守)
- タイトルに「技術検討レポート」「議論まとめ」のような平凡な名前は禁止。テーマと最有望案の両方が読み取れる固有のタイトルにする
- ラウンドの結論をそのままコピーしない。全体を再構成する
- 【結論】【合意点】【相違点】【次論点】のようなフォーマットタグを使わない
- 疑似変数 (τ=0.8、ε=0.1、+3pt、≤0.5% など) や単位の羅列は禁止。実際の会議で口頭で言える言葉に置き換える
- 専門用語を使う場合は初出時に簡単な説明を添える
- 議論に参加していない人が読んで理解できることが最優先
- 出力は Markdown 本文のみ。前後に説明文・コードフェンスを付けない
"""

# Idea 議論と Review 議論で「検証方法」/「実験計画」を切り替える
IDEA_VERIFICATION_SECTION_TITLE = "検証方法"
IDEA_VERIFICATION_SECTION_INTRO = (
    "この提案を検証するために効果的な方法を 3 つ提案する。各方法に:"
    "\n- 方法の概要\n- 必要なリソース\n- 期待される結果\n- 判断基準\n"
    "PoC / ヒアリング / 市場調査 など、ビジネス的な検証も含めて良い。"
)
REVIEW_EXPERIMENT_SECTION_TITLE = "実験計画"
REVIEW_EXPERIMENT_SECTION_INTRO = (
    "提案の妥当性を検証する実験計画を 3 つ提案する。各計画に:"
    "\n- 実験設計 (対照群・独立変数)\n- データセット / 計測方法\n- 評価指標\n- 期待される結果"
)


# ----------------------------------------------------------------------
# Synthesizer
# ----------------------------------------------------------------------


class Synthesizer:
    """Phase 3 の統合・評価・レポート生成を担う Synthesizer。

    ``_generate_*`` は D-4 後半で実装する。

    Attributes:
        api_client: 軽量〜重量モデル両対応の API クライアント。
        feedback_manager: ロール YAML への蓄積を担当する ``FeedbackManager``
            (E-1 で実装)。``None`` 可。
        settings: 全体設定。
        model: 統合に使うモデル。
        evaluator: 評価依頼を行うサービス。
    """

    def __init__(
        self,
        api_client: "ResilientAPIClient",
        feedback_manager: Any | None,
        settings: "Settings",
        model: str | None = None,
        evaluator: Evaluator | None = None,
    ) -> None:
        self.api_client = api_client
        self.feedback_manager = feedback_manager
        self.settings = settings
        self.model = model or settings.models.get(
            DEFAULT_SYNTHESIZER_MODEL_KEY, DEFAULT_SYNTHESIZER_MODEL
        )
        self.evaluator = evaluator or Evaluator(api_client=api_client, settings=settings)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        plan: OrchestraPlan,
        discussion_log: DiscussionLog,
        memory: "ConversationMemory | None" = None,
        agents: dict[str, "Agent"] | None = None,
        model: str | None = None,
        expertise: str = "intermediate",
        follow_up_context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> SynthesisResult:
        """Phase 3 の全体フロー。

        評価統合 → 指揮者総合評価 → ``session_meta`` 生成 → レポート生成
        の順で実行し、すべてが揃った ``SynthesisResult`` を返す。

        Args:
            plan: ``Orchestrator.plan()`` の出力。
            discussion_log: ``Conductor.run_discussion()`` の出力。
            memory: 共有メモリ (``full_conversation.md`` の補助情報源)。
            agents: ``role_id`` → ``Agent`` のマッピング。
            model: モデル名を CLI から上書きする場合。
            expertise: ``beginner`` / ``intermediate`` / ``expert``。
            follow_up_context: フォローアップ情報 (任意、現状未使用)。
            session_id: 出力ファイル用のセッション ID。未指定なら自動生成。

        Returns:
            評価データ + ``session_meta`` + 4 つのレポート文字列が埋まった
            ``SynthesisResult``。``vibe_coding_prompt_md`` は機能② で
            Phase F-2 が埋める。
        """
        del follow_up_context  # 後続フェーズ (follow-up 連鎖更新) で使用

        agents = agents or {}
        agent_list = self._resolve_agent_list(plan, agents)

        # 1. 各エージェントの自己 + 他者評価を並列実行
        agent_evaluations = await self._run_evaluations(
            agent_list, discussion_log, plan
        )

        # 2. 指揮者総合評価
        orchestrator_eval = await self._generate_orchestrator_evaluation(
            agent_evaluations, plan, discussion_log,
            model_override=model,
        )

        # 3. セッションメタデータ
        session_meta = self._generate_session_meta(
            plan=plan,
            log=discussion_log,
            evaluations=agent_evaluations,
            expertise=expertise,
            session_id=session_id,
        )

        # 4. レポート生成 (テンプレートベース、LLM 非経由)
        report_md = await self._generate_report(
            plan, discussion_log, agent_evaluations, orchestrator_eval, expertise
        )
        full_conversation_md = await self._generate_full_conversation(
            plan, discussion_log, memory,
            evaluations=agent_evaluations,
            orchestrator_eval=orchestrator_eval,
        )
        evaluation_md = await self._generate_evaluation_md(
            agent_evaluations, orchestrator_eval
        )
        summary_txt = await self._generate_summary(
            plan, discussion_log, agent_evaluations, orchestrator_eval
        )

        return SynthesisResult(
            report_md=report_md,
            full_conversation_md=full_conversation_md,
            evaluation_md=evaluation_md,
            summary_txt=summary_txt,
            vibe_coding_prompt_md=None,  # 機能② のみ。Phase F-2 で実装
            agent_evaluations=agent_evaluations,
            orchestrator_evaluation=orchestrator_eval,
            feedback_updates={},
            session_meta=session_meta,
        )

    # ------------------------------------------------------------------
    # 評価統合
    # ------------------------------------------------------------------

    async def _run_evaluations(
        self,
        agents: list["Agent"],
        discussion_log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> dict[str, AgentEvaluations]:
        """全エージェントの自己 + 他者評価を並列実行する。

        Args:
            agents: 議論に参加した ``Agent`` のリスト。
            discussion_log: ``Conductor`` 出力。
            plan: ``Orchestrator`` 出力。

        Returns:
            ``role_id`` → ``AgentEvaluations``。失敗した agent はキーから除外。
        """
        if not agents:
            return {}

        async def _eval_one(agent: "Agent") -> tuple[str, AgentEvaluations | None]:
            try:
                result = await self.evaluator.request_combined_evaluation(
                    agent=agent,
                    other_agents=agents,
                    discussion_log=discussion_log,
                    plan=plan,
                )
                return agent.role_id, result
            except Exception as e:  # noqa: BLE001 - 評価失敗で全体を止めない
                logger.warning(
                    "Evaluation failed for agent %r: %s", agent.role_id, e
                )
                return agent.role_id, None

        results = await asyncio.gather(*(_eval_one(a) for a in agents))
        return {role_id: ev for role_id, ev in results if ev is not None}

    async def _generate_orchestrator_evaluation(
        self,
        evaluations: dict[str, AgentEvaluations],
        plan: OrchestraPlan,
        log: DiscussionLog,
        model_override: str | None = None,
    ) -> OrchestratorEvaluation:
        """指揮者総合評価を取得する。"""
        prompt = self._build_orchestrator_eval_prompt(evaluations, plan, log)
        response = await self.api_client.call(
            model=model_override or self.model,
            messages=[{"role": "user", "content": prompt}],
            level=DEFAULT_SYNTHESIZER_LEVEL,
            temperature=ORCHESTRATOR_EVAL_TEMPERATURE,
            max_tokens=ORCHESTRATOR_EVAL_MAX_TOKENS,
        )
        content = str(response.get("content") or "")
        return self._parse_orchestrator_evaluation(content, log)

    # ------------------------------------------------------------------
    # セッションメタデータ
    # ------------------------------------------------------------------

    def _generate_session_meta(
        self,
        plan: OrchestraPlan,
        log: DiscussionLog,
        evaluations: dict[str, AgentEvaluations],
        expertise: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """``session_meta.json`` 用の辞書を生成する。"""
        now = datetime.now()
        sid = session_id or now.strftime(SESSION_ID_TIME_FORMAT) + "_idea"
        total_duration = sum(r.duration_sec for r in log.rounds)
        total_utterances = sum(len(r.public_utterances) for r in log.rounds)

        # created_at: セッション開始時刻 (議論開始 = now - duration)
        created_at = datetime.fromtimestamp(
            now.timestamp() - total_duration
        ).isoformat()
        completed_at = now.isoformat()

        return {
            "session_id": sid,
            "started_at": created_at,
            "ended_at": completed_at,
            "duration_sec": total_duration,
            "expertise": expertise,
            "plan_summary": {
                "objective": plan.odsc.objective,
                "convergence_threshold": plan.odsc.convergence_threshold,
                "estimated_rounds": (
                    plan.discussion_plan.estimated_rounds
                    if plan.discussion_plan
                    else 0
                ),
            },
            "statistics": {
                "total_rounds": len(log.rounds),
                "total_utterances": total_utterances,
                "total_requests": log.total_requests,
                "final_convergence_score": log.final_convergence_score,
                "early_termination": log.early_termination,
                "score_history": list(log.score_history),
                "participating_agents": sorted(evaluations.keys()),
            },
        }

    # ------------------------------------------------------------------
    # レポート生成 (テンプレートベース、LLM 非経由)
    # ------------------------------------------------------------------

    async def _generate_report(
        self,
        plan: OrchestraPlan,
        log: DiscussionLog,
        evaluations: dict[str, AgentEvaluations],
        orchestrator_eval: OrchestratorEvaluation,
        expertise: str,
        session_id: str | None = None,
    ) -> str:
        """``report.md`` 本文を生成する (問題4対策 — LLM ベース + テンプレ fallback)。

        LLM でエグゼクティブサマリー〜次のアクションまでを含む自己完結レポートを
        生成する。LLM 呼び出しが失敗するか出力が短すぎる場合は、旧来のテンプレ
        ベース実装 (``_generate_report_template``) にフォールバックする。

        Args:
            plan: 議論計画。
            log: 議論ログ。
            evaluations: 各エージェントの評価結果。
            orchestrator_eval: 指揮者総合評価。
            expertise: 発言 tone レベル (現状レポート生成では未使用)。
            session_id: セッション ID。``_review`` サフィックスなら
                「実験計画」セクション、それ以外は「検証方法」セクションを生成。

        Returns:
            Markdown 形式のレポート本文。
        """
        del expertise  # 将来の LLM 強化点で使用予定

        resolved_session_id = (
            session_id or self._derive_session_id_from_meta(log, plan)
        )
        is_review = "_review" in (resolved_session_id or "")
        if is_review:
            section_title = REVIEW_EXPERIMENT_SECTION_TITLE
            section_intro = REVIEW_EXPERIMENT_SECTION_INTRO
        else:
            section_title = IDEA_VERIFICATION_SECTION_TITLE
            section_intro = IDEA_VERIFICATION_SECTION_INTRO

        duration_sec = sum(r.duration_sec for r in log.rounds)
        n_agents = len(plan.selected_agents)
        convergence = log.final_convergence_score
        duration_str = self._format_duration(duration_sec)

        full_log = self._truncate_log_for_prompt(log, MAX_LOG_CHARS_FOR_REPORT)
        orchestrator_summary = self._format_orchestrator_summary(orchestrator_eval)

        prompt = REPORT_GENERATION_PROMPT.format(
            objective=plan.odsc.objective or "(未定義)",
            deliverable=plan.odsc.deliverable or "(未定義)",
            success_criteria=plan.odsc.success_criteria or "(未定義)",
            session_id=resolved_session_id,
            n_agents=n_agents,
            duration_str=duration_str,
            convergence=convergence,
            full_log=full_log or "(議論ログなし)",
            orchestrator_summary=orchestrator_summary or "(評価未実施)",
            verification_section_title=section_title,
            verification_section_intro=section_intro,
        )
        prompt_chars = len(prompt)

        content = ""
        fallback_reason = ""
        try:
            response = await self.api_client.call(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=REPORT_GENERATION_TEMPERATURE,
                max_tokens=REPORT_GENERATION_MAX_TOKENS,
            )
            raw = str(response.get("content") or "").strip()
            content = self._clean_llm_report_response(raw)
            if not content:
                fallback_reason = f"empty_after_clean (raw_len={len(raw)})"
        except Exception as e:  # noqa: BLE001 - 失敗時はテンプレ fallback
            fallback_reason = f"exception: {type(e).__name__}: {e}"
            content = ""

        if self._is_llm_report_usable(content):
            logger.info(
                "LLM report generated (len=%d, prompt_chars=%d, log_chars=%d)",
                len(content), prompt_chars, len(full_log),
            )
            return self._append_report_footer(content)

        # フォールバック: 旧来のテンプレベースレポート
        if not fallback_reason:
            has_heading = "##" in content or content.startswith("# ")
            fallback_reason = (
                f"usable_check_failed "
                f"(len={len(content)}, has_heading={has_heading})"
            )
        logger.error(
            "LLM report generation fell back to template. "
            "reason=%s | prompt_chars=%d | log_chars=%d | response_preview=%r",
            fallback_reason, prompt_chars, len(full_log),
            (content or "")[:200],
        )
        return await self._generate_report_template(
            plan, log, evaluations, orchestrator_eval, resolved_session_id
        )

    @staticmethod
    def _is_llm_report_usable(content: str) -> bool:
        """LLM 生成レポートが十分な体裁を保っているか簡易チェック。

        条件: ``len >= REPORT_MIN_USABLE_LEN`` AND (``"##"`` OR 先頭が ``"# "``)。
        以前は 200 文字 + ``"##"`` のみだったが、Claude が h1 (``# `` )のみで
        返す場合を許容するため緩和した。
        """
        if not content or len(content) < REPORT_MIN_USABLE_LEN:
            return False
        return "##" in content or content.startswith("# ")

    @staticmethod
    def _clean_llm_report_response(content: str) -> str:
        """LLM 生成レポートから余計な装飾を除去する。

        除去対象:
            - Markdown コードフェンス (``` ... ```)
            - 先頭の説明文 (「以下にレポートを生成します:」等)
            - 末尾の余計な補足説明
        """
        if not content:
            return ""
        text = content.strip()

        # ケース 1: 全体がコードフェンスで囲まれている
        fence_match = re.search(
            r"```(?:markdown|md)?\s*\n(.*?)\n\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            text = fence_match.group(1).strip()

        # ケース 2: 先頭に説明文があり、その後に見出しが続く
        # 最初の "# " または "## " を探し、その手前が説明文っぽければ削除する
        preamble_keywords = ("レポート", "以下", "生成", "作成", "Markdown", "です")
        earliest_heading = -1
        for marker in ("\n# ", "\n## "):
            idx = text.find(marker)
            if idx >= 0 and (earliest_heading < 0 or idx < earliest_heading):
                earliest_heading = idx + 1  # \n の次から
        if 0 < earliest_heading < 300:
            preamble = text[:earliest_heading].strip()
            if any(k in preamble for k in preamble_keywords):
                text = text[earliest_heading:]

        return text.strip()

    def _truncate_log_for_prompt(
        self,
        log: DiscussionLog,
        max_chars: int,
    ) -> str:
        """議論ログを ``max_chars`` に収まるよう段階的に圧縮する。

        段階:
            1. 全ログをそのまま返す (収まる場合)
            2. 各ラウンドで先頭 2 発言 + conclusion のみ残す
            3. それでも超過する場合、末尾切り詰め + 省略記号

        Args:
            log: 議論ログ。
            max_chars: 最大文字数。

        Returns:
            ``max_chars`` 以下に収まった議論ログ文字列。
        """
        full = self._format_log_for_extraction(log)
        if len(full) <= max_chars:
            return full

        # 圧縮版: 各ラウンドから先頭 2 発言 + conclusion を残す
        lines: list[str] = []
        for round_log in log.rounds:
            lines.append(f"[Round {round_log.round}: {round_log.phase_name}]")
            head = list(round_log.public_utterances[:2])
            conclusion = [
                u for u in round_log.public_utterances
                if getattr(u, "type", "") == "conclusion"
            ]
            picked = head + [c for c in conclusion if c not in head]
            for u in picked:
                lines.append(f"{u.speaker_display}: {u.content}")
        compressed = "\n".join(lines)
        if len(compressed) <= max_chars:
            return compressed

        # 最終手段: 末尾切り詰め
        return compressed[: max_chars - 20].rstrip() + "\n...(以下省略)"

    @staticmethod
    def _append_report_footer(body: str) -> str:
        """LLM 生成レポート末尾にツール名フッタを付ける (自動出力の目印)。"""
        footer = (
            f"\n\n---\n*{TOOL_VERSION} | "
            f"{datetime.now().strftime('%Y-%m-%d')}*\n"
        )
        return body.rstrip() + footer

    @staticmethod
    def _format_orchestrator_summary(orch_eval: OrchestratorEvaluation) -> str:
        """指揮者総合評価をレポートプロンプト用に短く整形する。"""
        if not orch_eval:
            return ""
        parts: list[str] = []
        if orch_eval.overall_discussion_quality:
            parts.append(
                f"議論品質: {orch_eval.overall_discussion_quality:.1f}/5"
            )
        if orch_eval.mvp_role_id:
            parts.append(
                f"MVP: {orch_eval.mvp_role_id} ({orch_eval.mvp_reason})"
            )
        odsc = orch_eval.odsc_achievement
        if odsc:
            parts.append(
                f"ODSC 達成: {'○' if odsc.achieved else '×'} — {odsc.detail}"
            )
        return " / ".join(p for p in parts if p)

    async def _generate_report_template(
        self,
        plan: OrchestraPlan,
        log: DiscussionLog,
        evaluations: dict[str, AgentEvaluations],
        orchestrator_eval: OrchestratorEvaluation,
        session_id: str,
    ) -> str:
        """旧来のテンプレベース ``report.md`` 生成 (LLM fallback 用)。

        LLM 呼び出しが失敗した場合の safety net。7 セクション構造
        (問題設定 / 洞察 / 骨格 / 仮説 / 実験計画 / 未解決 / 参考文献)
        を保持し、テストの互換性も担保する。
        """
        del evaluations  # 現状は未使用 (将来の要約強化点)

        duration_sec = sum(r.duration_sec for r in log.rounds)
        n_agents = len(plan.selected_agents)
        convergence = log.final_convergence_score

        hypotheses = await self._extract_hypotheses(log)
        insights = self._extract_insights(log)
        citations = self._extract_citations(log)
        unresolved = self._collect_unresolved_issues(log, orchestrator_eval)

        lines: list[str] = []
        lines.append("# 🔬 AI Orchestra 技術検討レポート")
        lines.append("")
        lines.append(f"> **Session**: {session_id}")
        lines.append(f"> **テーマ**: {plan.odsc.objective}")
        lines.append(
            f"> **所要時間**: {self._format_duration(duration_sec)} | "
            f"**参加AI**: {n_agents}体 | "
            f"**収束度**: {convergence:.2f}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        lines.append("## 1. 問題設定")
        lines.append("")
        lines.append(plan.odsc.objective or "(未定義)")
        lines.append("")

        lines.append("## 2. 技術的洞察")
        lines.append("")
        if insights:
            for i, ins in enumerate(insights, start=1):
                lines.append(f"{i}. {ins}")
        else:
            lines.append("(議論ログから抽出可能な洞察はありませんでした)")
        lines.append("")

        lines.append("## 3. 提案手法の骨格")
        lines.append("")
        lines.append(plan.odsc.deliverable or "(議論で具体化されていません)")
        lines.append("")

        lines.append("## 4. 仮説テーブル")
        lines.append("")
        lines.append(self._format_hypothesis_table(hypotheses))
        lines.append("")

        lines.append("## 5. 実験計画")
        lines.append("")
        lines.append(
            "実験設計の詳細は議論ログ (full_conversation.md) を参照してください。"
        )
        lines.append("")

        lines.append("## 6. 未解決問題")
        lines.append("")
        if unresolved:
            for i, item in enumerate(unresolved, start=1):
                lines.append(f"{i}. {item}")
        else:
            lines.append("(主要な未解決問題は残っていません)")
        lines.append("")

        lines.append("## 7. 参考文献")
        lines.append("")
        if citations:
            for c in citations:
                arxiv_note = " [要確認]" if "arXiv" in c else ""
                lines.append(f"- {c}{arxiv_note}")
        else:
            lines.append("(議論中で引用された文献はありませんでした)")
        lines.append("")

        lines.append("---")
        lines.append(
            f"*{TOOL_VERSION} | Research Mode | "
            f"{datetime.now().strftime('%Y-%m-%d')}*"
        )
        return "\n".join(lines)

    async def _generate_full_conversation(
        self,
        plan: OrchestraPlan,
        log: DiscussionLog,
        memory: "ConversationMemory | None",
        evaluations: dict[str, "AgentEvaluations"] | None = None,
        orchestrator_eval: "OrchestratorEvaluation | None" = None,
    ) -> str:
        """``full_conversation.md`` 本文を生成する (設計書 §14.4)。"""
        del memory  # 現状はラウンドログから直接生成

        duration_sec = sum(r.duration_sec for r in log.rounds)
        agent_emojis = " ".join(
            self._extract_emoji(cfg.role_id, plan) for cfg in plan.selected_agents
        )

        lines: list[str] = []
        lines.append("# 🎭 AI Orchestra — 会話ログ")
        lines.append("")
        lines.append(f"> テーマ: {plan.odsc.objective}")
        lines.append(f"> 参加: {agent_emojis}")
        lines.append(
            f"> 時間: {self._format_duration(duration_sec)} | "
            f"収束: {log.final_convergence_score:.2f}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # 舞台裏: 計画フェーズ
        lines.append("## 🎼 舞台裏: 計画フェーズ")
        lines.append("")
        lines.append("```")
        lines.append(f"🎼 [内心] {plan.odsc.objective}")
        estimated_rounds = (
            plan.discussion_plan.estimated_rounds if plan.discussion_plan else 0
        )
        lines.append(
            f"🎼 [内心] {len(plan.selected_agents)}体参加、"
            f"{estimated_rounds}ラウンド計画、"
            f"収束閾値={plan.odsc.convergence_threshold}"
        )
        lines.append("```")
        lines.append("")

        # private_instructions の表示
        if plan.private_instructions:
            for role_id, pi in plan.private_instructions.items():
                emoji = self._extract_emoji(role_id, plan)
                instruction = pi.expected_contribution or "(指示なし)"
                lines.append(f"**🎼→{emoji}** {instruction}")
            lines.append("")

        # 各ラウンド
        for round_log in log.rounds:
            lines.append("---")
            lines.append("")
            lines.append(
                f"## 💬 Round {round_log.round}: "
                f"{round_log.phase_name or '(無題)'}"
            )
            lines.append("")
            if round_log.goal:
                lines.append(f"> **目標**: {round_log.goal}")
                lines.append("")
            for u in round_log.public_utterances:
                emoji = self._extract_emoji_from_display(u.speaker_display)
                content = self._strip_conclusion_tags(u.content)
                if u.type == "conclusion":
                    lines.append(f"> **🎯 {emoji} 結論** {content}")
                else:
                    lines.append(f"**{emoji}** {content}")
                lines.append("")
            check = round_log.convergence_check
            if check is not None:
                lines.append("```")
                lines.append(
                    f"🎼 [収束: {check.score:.2f}] "
                    f"{check.reasoning or '(理由なし)'}"
                )
                if check.remaining_disagreements:
                    lines.append(
                        f"🎼 [未解決] {', '.join(check.remaining_disagreements)}"
                    )
                lines.append(
                    f"🎼 [判断] recommendation = {check.recommendation}"
                )
                lines.append("```")
                lines.append("")

        if log.early_termination:
            lines.append("---")
            lines.append("")
            lines.append("```")
            lines.append(f"🎼 [早期終了] reason = {log.early_termination}")
            if log.termination_detail:
                lines.append(f"🎼 [詳細] {log.termination_detail}")
            lines.append("```")
            lines.append("")

        # 評価セクション
        lines.append("---")
        lines.append("")
        lines.append("## 📊 評価タイム")
        lines.append("")

        if evaluations and orchestrator_eval:
            # 総合スコアランキング
            ranking = self._build_score_ranking(evaluations)
            if ranking:
                lines.append("### 🏆 ランキング")
                lines.append("")
                lines.append("| 順位 | AI | 自己評価 | 他者評価 | 総合 |")
                lines.append("|---|---|---|---|---|")
                medals = ["🥇", "🥈", "🥉"]
                for i, (role_id, self_avg, peer_avg, total) in enumerate(ranking):
                    medal = medals[i] if i < len(medals) else f"{i + 1}"
                    emoji = self._extract_emoji(role_id, plan)
                    lines.append(
                        f"| {medal} | {emoji} ({role_id}) | "
                        f"{self_avg:.1f} | {peer_avg:.1f} | "
                        f"**{total:.1f}** |"
                    )
                lines.append("")

            # MVP
            if orchestrator_eval.mvp_role_id:
                mvp_emoji = self._extract_emoji(
                    orchestrator_eval.mvp_role_id, plan
                )
                lines.append(
                    f"### 🏆 MVP: {mvp_emoji} ({orchestrator_eval.mvp_role_id})"
                )
                lines.append("")
                if orchestrator_eval.mvp_reason:
                    lines.append(f"> {orchestrator_eval.mvp_reason}")
                    lines.append("")

            # 議論品質
            lines.append("### 📈 議論品質")
            lines.append("")
            lines.append(
                f"- 全体品質: **{orchestrator_eval.overall_discussion_quality:.1f}**/5.0"
            )
            ach = orchestrator_eval.odsc_achievement
            lines.append(
                f"- ODSC達成: {'✅ 達成' if ach.achieved else '❌ 未達成'}"
            )
            lines.append(f"- 最終収束度: {ach.convergence_final:.2f}")
            lines.append("")
        else:
            lines.append("評価: 未実施")
            lines.append("")

        lines.append("---")
        lines.append(
            f"*{TOOL_VERSION} | {datetime.now().strftime('%Y-%m-%d')}*"
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_emoji_from_display(speaker_display: str) -> str:
        """``speaker_display`` (例: '🧮 理論屋') から絵文字部分を取り出す。"""
        if speaker_display and len(speaker_display) >= 1:
            # 先頭文字が絵文字ならそれを使う
            first_char = speaker_display[0]
            if ord(first_char) > 0x2600:
                return first_char
        return speaker_display

    @staticmethod
    def _strip_conclusion_tags(content: str) -> str:
        """結論発言から旧フォーマットタグを除去する (P1: フォーマットタグ廃止)。

        ROUND_CONCLUSION_INSTRUCTION の書き換え後も、LLM が慣性で
        「【結論】〜【合意点】〜【相違点】〜【次論点】」を出す場合がある。
        出力段で機械的に除去して自然な文章に戻す。
        """
        if not content:
            return content
        # タグを空文字に置換 (前後の空白は保持し、複数タグの連続を吸収)
        cleaned = content
        for tag in ("【最終結論】", "【結論】", "【合意点】", "【相違点】", "【次論点】"):
            cleaned = cleaned.replace(tag, "")
        # タグ削除で残った連続空白・改行を整える
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\s*\n\s*", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _extract_emoji(role_id: str, plan: OrchestraPlan) -> str:
        """``role_id`` から絵文字を推定する。

        参照優先順位:
            1. ``plan.selected_agents`` の ``display_name`` 先頭が絵文字ならそれを返す
               (実行時に role_manager から読み込まれた最新の display_name を使う)
            2. ハードコードマップ ``_KNOWN_EMOJIS`` で fallback
            3. 未知ロールは ``🎭`` (汎用マスク)
        """
        # 1. plan.selected_agents から display_name 経由で絵文字を取得
        for agent_cfg in getattr(plan, "selected_agents", []) or []:
            if getattr(agent_cfg, "role_id", None) != role_id:
                continue
            display = getattr(agent_cfg, "display_name", "") or ""
            if display and ord(display[0]) > 0x2600:
                return display[0]
            break

        # 2. ハードコードマップ (全 10 ロール + 旧コード互換)
        _known = {
            "theorist": "🧮",
            "experimentalist": "🔬",
            "implementer": "🤖",
            "literature": "📚",
            "devil": "😈",
            "bird_eye": "🎯",
            "son_masayoshi": "🐑",
            "matushita_kounosuke": "🍿",
            "code_architect": "📐",
            "code_reviewer": "📝",
            # 旧コード互換 (エイリアス)
            "designer": "📐",
            "ethicist": "⚖️",
            "scribe": "📝",
        }
        if role_id in _known:
            return _known[role_id]
        return "🎭"

    async def _generate_evaluation_md(
        self,
        evaluations: dict[str, AgentEvaluations],
        orchestrator_eval: OrchestratorEvaluation,
    ) -> str:
        """``evaluation.md`` 本文を生成する (設計書 §14.6)。"""
        lines: list[str] = []
        lines.append("# 📊 AI 評価レポート")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 総合スコアランキング
        lines.append("## 🏆 総合スコアランキング")
        lines.append("")
        ranking = self._build_score_ranking(evaluations)
        if ranking:
            lines.append("| 順位 | AI | 自己評価 | 他者評価 | 総合 |")
            lines.append("|---|---|---|---|---|")
            medals = ["🥇", "🥈", "🥉"]
            for i, (role_id, self_avg, peer_avg, total) in enumerate(ranking):
                medal = medals[i] if i < len(medals) else f"{i + 1}"
                lines.append(
                    f"| {medal} | {role_id} | {self_avg:.2f} | {peer_avg:.2f} | "
                    f"**{total:.2f}** |"
                )
        else:
            lines.append("(評価データなし)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 個別評価詳細
        lines.append("## 📝 個別評価詳細")
        lines.append("")
        if not evaluations:
            lines.append("評価: Phase 3 で実施されませんでした")
            lines.append("")
        for role_id, ev in evaluations.items():
            lines.append(f"### {role_id}")
            lines.append("")
            lines.append("#### 自己評価")
            lines.append("")
            self_eval = ev.self_eval
            if self_eval.scores:
                lines.append("| 基準 | スコア |")
                lines.append("|---|---|")
                for name, score in self_eval.scores.items():
                    stars = "⭐" * score + "☆" * (5 - score)
                    lines.append(f"| {name} | {stars} ({score}/5) |")
                lines.append(f"| **平均** | **{self_eval.avg_score:.2f}** |")
            else:
                lines.append("(自己評価スコアなし)")
            lines.append("")

            if self_eval.reasoning:
                lines.append("**自己振り返り:**")
                lines.append(f"> {self_eval.reasoning}")
                lines.append("")

            if self_eval.key_contributions:
                lines.append("**主な貢献:**")
                for k in self_eval.key_contributions:
                    lines.append(f"- {k}")
                lines.append("")

            if self_eval.missed_opportunities:
                lines.append("**やり残し:**")
                for m in self_eval.missed_opportunities:
                    lines.append(f"- {m}")
                lines.append("")

            # 他者からの評価 (この role_id を peer 評価対象とした他 agent を集める)
            received = self._collect_peer_received(role_id, evaluations)
            if received:
                lines.append("#### 他者からの評価")
                lines.append("")
                lines.append("| 評価者 | スコア | コメント |")
                lines.append("|---|---|---|")
                for evaluator_id, pe in received.items():
                    lines.append(
                        f"| {evaluator_id} | {pe.score}/5 | {pe.comment} |"
                    )
                lines.append("")

            # 指揮者フィードバック
            fb = orchestrator_eval.per_agent_feedback.get(role_id)
            if fb:
                lines.append("#### 🎵 指揮者からのフィードバック")
                lines.append("")
                if fb.strengths_noted:
                    lines.append("**良かった点:**")
                    for s in fb.strengths_noted:
                        lines.append(f"- {s}")
                    lines.append("")
                if fb.improvements_noted:
                    lines.append("**改善すべき点:**")
                    for s in fb.improvements_noted:
                        lines.append(f"- {s}")
                    lines.append("")
                if fb.orchestrator_feedback:
                    lines.append(f"> {fb.orchestrator_feedback}")
                    lines.append("")
            lines.append("---")
            lines.append("")

        # 議論品質の指標
        lines.append("## 📈 議論品質の指標")
        lines.append("")
        ach = orchestrator_eval.odsc_achievement
        lines.append("| 指標 | 値 | 判定 |")
        lines.append("|---|---|---|")
        lines.append(
            f"| 議論品質 | {orchestrator_eval.overall_discussion_quality:.1f}/5.0 | "
            f"{'✅' if orchestrator_eval.overall_discussion_quality >= 4.0 else '⚠️'} |"
        )
        lines.append(
            f"| ODSC 達成 | {'達成' if ach.achieved else '未達成'} | "
            f"{'✅' if ach.achieved else '❌'} |"
        )
        lines.append(
            f"| 最終収束度 | {ach.convergence_final:.2f} | "
            f"{'✅' if ach.convergence_final >= 0.8 else '⚠️'} |"
        )
        if orchestrator_eval.mvp_role_id:
            lines.append(
                f"| MVP | {orchestrator_eval.mvp_role_id} | 🏆 |"
            )
        lines.append("")

        lines.append("---")
        lines.append(
            f"*{TOOL_VERSION} | {datetime.now().strftime('%Y-%m-%d')}*"
        )
        return "\n".join(lines)

    async def _generate_summary(
        self,
        plan: OrchestraPlan,
        log: DiscussionLog,
        evaluations: dict[str, AgentEvaluations],
        orchestrator_eval: OrchestratorEvaluation,
    ) -> str:
        """``summary.txt`` 本文を生成する (設計書 §14.7、プレーンテキスト)。"""
        del evaluations  # 統計値は orchestrator_eval から取れる

        hypotheses = await self._extract_hypotheses(log)
        duration = self._format_duration(sum(r.duration_sec for r in log.rounds))
        agents_summary = ", ".join(
            f"{self._extract_emoji(cfg.role_id, plan)} {cfg.role_id}"
            for cfg in plan.selected_agents
        ) or "(なし)"

        lines: list[str] = []
        lines.append(SUMMARY_DIVIDER)
        lines.append("🔬 AI Orchestra 結果サマリ")
        lines.append(SUMMARY_DIVIDER)
        lines.append("")
        lines.append(f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M')} ({duration})")
        lines.append(f"テーマ: {plan.odsc.objective}")
        lines.append(f"参加AI: {agents_summary}")
        lines.append(f"最終収束度: {log.final_convergence_score:.2f}")
        lines.append("")
        lines.append("━━ 結論 ━━")
        lines.append("")
        ach = orchestrator_eval.odsc_achievement
        if ach.detail:
            lines.append(ach.detail)
        else:
            lines.append(plan.odsc.deliverable or "(結論は議論ログを参照)")
        lines.append("")

        lines.append("━━ 主要洞察 ━━")
        lines.append("")
        insights = self._extract_insights(log, limit=MAX_INSIGHTS_FOR_SUMMARY)
        if insights:
            for i, ins in enumerate(insights, start=1):
                lines.append(f"{i}. {ins}")
        else:
            lines.append("(洞察抽出なし)")
        lines.append("")

        lines.append(f"━━ 仮説 ({len(hypotheses)}個) ━━")
        lines.append("")
        if hypotheses:
            for h in hypotheses:
                marker = "🔲"
                lines.append(f"{h['id']}{marker} {h['hypothesis']}")
        else:
            lines.append("(仮説抽出なし)")
        lines.append("")

        lines.append("━━ 統計 ━━")
        lines.append("")
        lines.append(
            f"収束: {log.final_convergence_score:.2f} | "
            f"品質: {orchestrator_eval.overall_discussion_quality:.1f}/5 | "
            f"MVP: {orchestrator_eval.mvp_role_id or '(未選出)'}"
        )
        lines.append("")
        lines.append(SUMMARY_DIVIDER)
        return "\n".join(lines)

    async def _generate_vibe_prompt(
        self,
        findings: dict[str, Any],
        scan_result: dict[str, Any],
    ) -> str:
        """``vibe_coding_prompt.md`` を生成する (機能②、Phase F-2)。"""
        del findings, scan_result
        return ""

    # ------------------------------------------------------------------
    # 仮説 / 洞察 / 文献の抽出
    # ------------------------------------------------------------------

    async def _extract_hypotheses(
        self,
        log: DiscussionLog,
    ) -> list[dict[str, str]]:
        """議論ログから仮説を抽出する (LLM ベース + 正規表現フォールバック)。

        4 種の仮説 (因果 / 効果 / 価値 / リスク) を LLM で抽出する。
        LLM 呼び出しが失敗した場合、または JSON パースに失敗した場合は
        1 回だけ「JSON のみ返してください」を prepend して再送信し、
        それでも失敗すれば ``_extract_hypotheses_regex`` にフォールバックする。

        Args:
            log: ``DiscussionLog``。

        Returns:
            ``[{"id", "hypothesis", "status", "verification"}]`` のリスト。
            最大 ``MAX_HYPOTHESES`` 件。空ログの場合は空リスト。
        """
        log_text = self._truncate_log_for_prompt(log, MAX_LOG_CHARS_FOR_HYPOTHESIS)
        if not log_text.strip():
            return []

        base_prompt = HYPOTHESIS_EXTRACTION_PROMPT.format(full_log=log_text)
        parsed: list[dict[str, str]] = []

        # 1 回目: 通常呼び出し
        try:
            response = await self.api_client.call(
                model=self.model,
                messages=[{"role": "user", "content": base_prompt}],
                temperature=HYPOTHESIS_EXTRACTION_TEMPERATURE,
                max_tokens=HYPOTHESIS_EXTRACTION_MAX_TOKENS,
            )
            content = str(response.get("content") or "")
            parsed = self._parse_hypothesis_extraction(content)
        except Exception as e:  # noqa: BLE001 - 抽出失敗で全体を止めない
            logger.warning(
                "LLM hypothesis extraction failed (1st attempt): %s", e
            )

        # 2 回目: JSON 強制プレフィックスを付けて再試行
        if not parsed:
            try:
                retry_prompt = HYPOTHESIS_RETRY_PROMPT_PREFIX + base_prompt
                response = await self.api_client.call(
                    model=self.model,
                    messages=[{"role": "user", "content": retry_prompt}],
                    temperature=HYPOTHESIS_EXTRACTION_TEMPERATURE,
                    max_tokens=HYPOTHESIS_EXTRACTION_MAX_TOKENS,
                )
                content = str(response.get("content") or "")
                parsed = self._parse_hypothesis_extraction(content)
                if parsed:
                    logger.info(
                        "hypothesis extraction succeeded on retry (%d items)",
                        len(parsed),
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "LLM hypothesis extraction retry failed: %s", e
                )

        if parsed:
            return parsed[:MAX_HYPOTHESES]

        # フォールバック: 正規表現ベース
        fallback = self._extract_hypotheses_regex(log)
        logger.warning(
            "hypothesis extraction fell back to regex (returned %d items)",
            len(fallback),
        )
        return fallback

    @staticmethod
    def _format_log_for_extraction(log: DiscussionLog) -> str:
        """全ラウンドの発言を ``speaker: content`` 形式で連結する。"""
        lines: list[str] = []
        for round_log in log.rounds:
            lines.append(f"[Round {round_log.round}: {round_log.phase_name}]")
            for u in round_log.public_utterances:
                lines.append(f"{u.speaker_display}: {u.content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_hypothesis_extraction(content: str) -> list[dict[str, str]]:
        """LLM 応答 JSON を仮説リストにパースする。失敗時は空リスト。"""
        import json as _json
        import re as _re

        text = (content or "").strip()
        if not text:
            return []
        fence = _re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL | _re.IGNORECASE
        )
        if fence:
            payload = fence.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return []
            payload = text[start : end + 1]
        try:
            data = _json.loads(payload)
        except (_json.JSONDecodeError, ValueError):
            return []
        raw_list = data.get("hypotheses") if isinstance(data, dict) else None
        if not isinstance(raw_list, list):
            return []
        result: list[dict[str, str]] = []
        for i, item in enumerate(raw_list, start=1):
            if not isinstance(item, dict):
                continue
            hid = str(item.get("id") or f"H{i}").strip() or f"H{i}"
            hypothesis = str(item.get("hypothesis") or "").strip()
            if not hypothesis:
                continue
            result.append(
                {
                    "id": hid,
                    "hypothesis": hypothesis,
                    "status": str(item.get("status") or "unverified").strip()
                    or "unverified",
                    "verification": str(item.get("verification") or "").strip(),
                }
            )
        return result

    def _extract_hypotheses_regex(
        self,
        log: DiscussionLog,
    ) -> list[dict[str, str]]:
        """従来の正規表現ベースの仮説抽出 (LLM 抽出失敗時のフォールバック)。

        検出ロジック:
            - 発言中の ``H1``/``H2``/... 形式の ID をキーに集める
            - ID 周辺の文 (前後 80 字程度) を ``hypothesis`` 文として保存
            - ID が出ない場合、「仮説」「hypothesis」を含む発言を補助的に拾う

        Args:
            log: ``DiscussionLog``。

        Returns:
            ``[{"id", "hypothesis", "status", "verification"}]`` のリスト。
            重複 ID は最初の出現を採用。最大 ``MAX_HYPOTHESES`` 件。
        """
        seen_ids: dict[str, dict[str, str]] = {}
        keyword_hits: list[dict[str, str]] = []

        for round_log in log.rounds:
            for u in round_log.public_utterances:
                content = u.content or ""
                for match in HYPOTHESIS_ID_PATTERN.finditer(content):
                    hid = match.group(1).upper()
                    if hid in seen_ids:
                        continue
                    seen_ids[hid] = {
                        "id": hid,
                        "hypothesis": self._trim_around(content, match.start()),
                        "status": "unverified",
                        "verification": "",
                    }
                    if len(seen_ids) >= MAX_HYPOTHESES:
                        break
                else:
                    if any(k in content for k in HYPOTHESIS_KEYWORDS):
                        keyword_hits.append(
                            {
                                "id": "",
                                "hypothesis": content.strip(),
                                "status": "unverified",
                                "verification": "",
                            }
                        )
                if len(seen_ids) >= MAX_HYPOTHESES:
                    break
            if len(seen_ids) >= MAX_HYPOTHESES:
                break

        # ID 付き仮説を優先
        result = sorted(seen_ids.values(), key=lambda h: int(h["id"][1:]))
        if not result:
            # ID なし: キーワード一致を最大件数まで採用 (連番 ID を振る)
            for i, hit in enumerate(keyword_hits[:MAX_HYPOTHESES], start=1):
                hit["id"] = f"H{i}"
                result.append(hit)
        return result

    @staticmethod
    def _trim_around(content: str, position: int, span: int = 80) -> str:
        """``position`` を中心に前後 ``span`` 文字を抜き出して整形する。"""
        start = max(0, position - span // 4)
        end = min(len(content), position + span)
        snippet = content[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    @staticmethod
    def _extract_insights(log: DiscussionLog, limit: int = 5) -> list[str]:
        """各ラウンドの最終発言を「洞察」として取り出す (簡易版)。"""
        insights: list[str] = []
        for round_log in log.rounds:
            if not round_log.public_utterances:
                continue
            last = round_log.public_utterances[-1].content.strip()
            if last:
                insights.append(last)
            if len(insights) >= limit:
                break
        return insights

    @staticmethod
    def _extract_citations(log: DiscussionLog) -> list[str]:
        """発言から ``(Author+YYYY)`` 形式の引用を抽出する (重複除外、順序保持)。"""
        seen: set[str] = set()
        ordered: list[str] = []
        for round_log in log.rounds:
            for u in round_log.public_utterances:
                for match in CITATION_PATTERN.finditer(u.content or ""):
                    citation = match.group(0)
                    if citation not in seen:
                        seen.add(citation)
                        ordered.append(citation)
        return ordered

    @staticmethod
    def _collect_unresolved_issues(
        log: DiscussionLog,
        orchestrator_eval: OrchestratorEvaluation,
    ) -> list[str]:
        """最終収束結果と総合評価から未解決問題リストを構築する。"""
        issues: list[str] = []
        # 最終ラウンドの remaining_disagreements
        if log.rounds:
            last_check = log.rounds[-1].convergence_check
            if last_check is not None:
                issues.extend(last_check.remaining_disagreements or [])
        # 指揮者の ODSC 達成度詳細から「未達」要素を補完
        ach = orchestrator_eval.odsc_achievement
        if ach and ach.detail and not ach.achieved:
            issues.append(ach.detail)
        return issues

    # ------------------------------------------------------------------
    # 整形ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _format_hypothesis_table(hypotheses: list[dict[str, str]]) -> str:
        """マークダウン表で仮説テーブルを描画する。"""
        if not hypotheses:
            return "(議論ログから仮説を抽出できませんでした)"
        lines = ["| ID | 仮説 | 状態 | 検証方法 |", "|---|---|---|---|"]
        for h in hypotheses:
            lines.append(
                f"| {h['id']} | {h['hypothesis']} | "
                f"{h.get('status', 'unverified')} | "
                f"{h.get('verification', '')} |"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_duration(sec: float) -> str:
        """秒数を「Xm Ys」または「Xs」形式に整形する。"""
        if sec < 60:
            return f"{sec:.0f}秒"
        minutes = int(sec // 60)
        seconds = int(sec % 60)
        return f"{minutes}分{seconds:02d}秒"

    @staticmethod
    def _build_score_ranking(
        evaluations: dict[str, AgentEvaluations],
    ) -> list[tuple[str, float, float, float]]:
        """``(role_id, self_avg, peer_avg, total)`` のリストを総合降順で返す。"""

        # 各 role が受けた peer スコアを集計
        received: dict[str, list[int]] = {}
        for evaluator_id, ev in evaluations.items():
            for target_id, pe in ev.peer_evals.items():
                received.setdefault(target_id, []).append(pe.score)

        ranking: list[tuple[str, float, float, float]] = []
        for role_id, ev in evaluations.items():
            self_avg = float(ev.self_eval.avg_score or 0.0)
            peer_scores = received.get(role_id, [])
            peer_avg = sum(peer_scores) / len(peer_scores) if peer_scores else 0.0
            total = (self_avg + peer_avg) / 2 if (self_avg or peer_avg) else 0.0
            ranking.append((role_id, self_avg, peer_avg, total))
        ranking.sort(key=lambda x: x[3], reverse=True)
        return ranking

    @staticmethod
    def _collect_peer_received(
        role_id: str,
        evaluations: dict[str, AgentEvaluations],
    ) -> dict[str, PeerEvaluation]:
        """ある ``role_id`` が他者から受けた評価を ``evaluator_id`` → ``PeerEvaluation`` で返す。"""
        received: dict[str, PeerEvaluation] = {}
        for evaluator_id, ev in evaluations.items():
            if evaluator_id == role_id:
                continue
            pe = ev.peer_evals.get(role_id)
            if pe is not None:
                received[evaluator_id] = pe
        return received

    @staticmethod
    def _derive_session_id_from_meta(
        log: DiscussionLog,
        plan: OrchestraPlan,
    ) -> str:
        """``session_meta`` 未生成時の暫定 ID。"""
        del log, plan
        return datetime.now().strftime(SESSION_ID_TIME_FORMAT) + "_idea"

    # ------------------------------------------------------------------
    # プロンプト構築 + パース
    # ------------------------------------------------------------------

    def _build_orchestrator_eval_prompt(
        self,
        evaluations: dict[str, AgentEvaluations],
        plan: OrchestraPlan,
        log: DiscussionLog,
    ) -> str:
        return ORCHESTRATOR_EVALUATION_PROMPT.format(
            odsc=self._format_odsc(plan),
            full_discussion_log=self._format_full_log(log),
            self_evaluations_formatted=self._format_self_evaluations(evaluations),
            peer_evaluations_formatted=self._format_peer_evaluations(evaluations),
            per_agent_template=self._build_per_agent_template(evaluations),
        )

    @staticmethod
    def _format_odsc(plan: OrchestraPlan) -> str:
        return (
            f"- Objective: {plan.odsc.objective}\n"
            f"- Deliverable: {plan.odsc.deliverable}\n"
            f"- Success Criteria: {plan.odsc.success_criteria}\n"
            f"- Convergence Threshold: {plan.odsc.convergence_threshold}"
        )

    @staticmethod
    def _format_full_log(log: DiscussionLog) -> str:
        if not log.rounds:
            return "(ログなし)"
        lines: list[str] = []
        for r in log.rounds:
            lines.append(f"\n--- Round {r.round}: {r.phase_name} ---")
            for u in r.public_utterances:
                lines.append(f"{u.speaker_display}: {u.content}")
        return "\n".join(lines)

    @staticmethod
    def _format_self_evaluations(
        evaluations: dict[str, AgentEvaluations],
    ) -> str:
        if not evaluations:
            return "(評価なし)"
        lines: list[str] = []
        for role_id, ev in evaluations.items():
            s = ev.self_eval
            lines.append(
                f"- {role_id}: avg={s.avg_score}, scores={s.scores}, "
                f"reasoning={s.reasoning[:80]}..."
            )
        return "\n".join(lines)

    @staticmethod
    def _format_peer_evaluations(
        evaluations: dict[str, AgentEvaluations],
    ) -> str:
        if not evaluations:
            return "(評価なし)"
        lines: list[str] = []
        for evaluator_id, ev in evaluations.items():
            if not ev.peer_evals:
                continue
            peer_summary = ", ".join(
                f"{target_id}={pe.score}" for target_id, pe in ev.peer_evals.items()
            )
            lines.append(f"- {evaluator_id} → {peer_summary}")
        return "\n".join(lines) if lines else "(他者評価なし)"

    @staticmethod
    def _build_per_agent_template(
        evaluations: dict[str, AgentEvaluations],
    ) -> str:
        if not evaluations:
            return ""
        items: list[str] = []
        for role_id in evaluations.keys():
            items.append(
                f'    "{role_id}": {{\n'
                f'      "strengths_noted": ["<良かった点1>", "<良かった点2>"],\n'
                f'      "improvements_noted": ["<改善点1>"],\n'
                f'      "orchestrator_feedback": "<次回への期待（1文）>"\n'
                f"    }}"
            )
        return ",\n".join(items)

    @classmethod
    def _parse_orchestrator_evaluation(
        cls,
        content: str,
        log: DiscussionLog,
    ) -> OrchestratorEvaluation:
        """LLM 応答から ``OrchestratorEvaluation`` を構築する。

        パース失敗時は ``final_convergence_score`` だけ埋めたデフォルトを返す。
        """
        data = cls._extract_json_dict(content)
        if not data:
            return OrchestratorEvaluation(
                odsc_achievement=ODSCAchievement(
                    convergence_final=log.final_convergence_score
                )
            )

        try:
            quality = float(data.get("overall_discussion_quality", 0.0))
        except (TypeError, ValueError):
            quality = 0.0
        quality = max(0.0, min(5.0, quality))

        mvp_raw = data.get("mvp") or {}
        if not isinstance(mvp_raw, dict):
            mvp_raw = {}
        mvp_role_id = str(mvp_raw.get("role_id", ""))
        mvp_reason = str(mvp_raw.get("reason", ""))

        achievement = cls._parse_odsc_achievement(
            data.get("odsc_achievement"), log.final_convergence_score
        )

        per_agent = cls._parse_per_agent_feedback(data.get("per_agent_feedback"))

        return OrchestratorEvaluation(
            overall_discussion_quality=round(quality, 1),
            mvp_role_id=mvp_role_id,
            mvp_reason=mvp_reason,
            odsc_achievement=achievement,
            per_agent_feedback=per_agent,
        )

    @staticmethod
    def _parse_odsc_achievement(
        raw: Any, convergence_final: float
    ) -> ODSCAchievement:
        if not isinstance(raw, dict):
            return ODSCAchievement(convergence_final=convergence_final)
        return ODSCAchievement(
            achieved=bool(raw.get("achieved", False)),
            detail=str(raw.get("detail", "")),
            objective_met=bool(raw.get("objective_met", False)),
            deliverable_met=bool(raw.get("deliverable_met", False)),
            criteria_met=bool(raw.get("criteria_met", False)),
            convergence_final=float(
                raw.get("convergence_final", convergence_final) or convergence_final
            ),
        )

    @classmethod
    def _parse_per_agent_feedback(
        cls,
        raw: Any,
    ) -> dict[str, AgentFeedback]:
        if not isinstance(raw, dict):
            return {}
        result: dict[str, AgentFeedback] = {}
        for role_id, item in raw.items():
            if not isinstance(item, dict):
                continue
            result[str(role_id)] = AgentFeedback(
                strengths_noted=cls._coerce_string_list(item.get("strengths_noted")),
                improvements_noted=cls._coerce_string_list(
                    item.get("improvements_noted")
                ),
                orchestrator_feedback=str(item.get("orchestrator_feedback", "")),
            )
        return result

    # ------------------------------------------------------------------
    # 共通ヘルパー
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_dict(content: str) -> dict[str, Any]:
        """Markdown フェンス・前後説明文を許容して JSON を取り出す。"""
        if not content or not content.strip():
            return {}
        text = content.strip()
        fence_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            payload = fence_match.group(1)
        else:
            start = text.find("{")
            if start == -1:
                return {}
            end = text.rfind("}")
            payload = text[start : end + 1] if end > start else text[start:]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.warning("Synthesizer: failed to parse JSON: %s", e)
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(v) for v in value if v is not None]

    @staticmethod
    def _resolve_agent_list(
        plan: OrchestraPlan,
        agents: dict[str, "Agent"],
    ) -> list["Agent"]:
        """``plan.selected_agents`` の順序で ``Agent`` を取り出す。"""
        result: list["Agent"] = []
        for cfg in plan.selected_agents:
            agent = agents.get(cfg.role_id)
            if agent is not None:
                result.append(agent)
            else:
                logger.warning(
                    "Synthesizer: agent %r not provided; skipping", cfg.role_id
                )
        return result


__all__ = [
    "Synthesizer",
    "ORCHESTRATOR_EVALUATION_PROMPT",
    "DEFAULT_SYNTHESIZER_MODEL",
]
