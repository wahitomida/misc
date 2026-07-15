# AI Orchestra — Idea Discussion 現状分析ドキュメント

> **目的**: このドキュメントは、AI Orchestra の Idea Discussion 機能（複数 AI がテーマについて議論しレポートを生成する機能）の
> 現状の実装と、依然として残っている課題を Claude に解析してもらい、
> 次の改善方針を決めるために作成されたものです。
>
> **作成日**: 2026-07-13
> **対象コード**: `misc_26/Orchestra/`
> **対象機能**: `features/idea_discussion.py` 経由で提供される「idea」モード
> **ユニットテスト**: 603/603 pass (2026-07-13 時点)

---

## 目次

- [§1 全体像](#1-全体像)
  - 1.1 3 フェーズ構造
  - 1.2 モジュール依存とレイヤ
  - 1.3 データフロー (1 セッション分)
  - 1.4 主要な LLM 呼び出し箇所と担当モデル
- [§2 現状の実装詳細](#2-現状の実装詳細)
  - 2.1 Orchestrator (Phase 1 計画)
  - 2.2 Conductor (Phase 2 議論進行)
  - 2.3 Agent (発言生成)
  - 2.4 ConvergenceChecker / RepetitionDetector / AgreementDetector
  - 2.5 Synthesizer (Phase 3 統合)
  - 2.6 ConversationMemory
- [§3 プロンプト一覧](#3-プロンプト一覧)
  - 3.1 計画立案 (Planner)
  - 3.2 ラウンド末尾の結論
  - 3.3 収束スコア判定
  - 3.4 狭まりすぎ検知 + ピボット
  - 3.5 堂々巡り検知 / 同意過多検知
  - 3.6 Goal 達成度チェック
  - 3.7 Bonus round goal 生成
  - 3.8 禁止例抽出
  - 3.9 仮説抽出
  - 3.10 レポート生成
  - 3.11 自己 / 他者 / 総合評価
- [§4 ロール定義の現状](#4-ロール定義の現状)
- [§5 現状の問題点](#5-現状の問題点)
- [§6 改善候補と Claude への質問](#6-改善候補と-claude-への質問)

---

## 1. 全体像

### 1.1 3 フェーズ構造

Idea Discussion は 3 つの Phase で構成される。ユーザー入力 → 計画 → 議論 → レポートの流れ。

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Phase 0      │   │ Phase 1      │   │ Phase 2      │   │ Phase 3      │
│ Input Valid. │──▶│ Orchestrator │──▶│  Conductor   │──▶│ Synthesizer  │
│ + Scenario検 │   │ (計画立案)   │   │ (議論進行)   │   │ (統合・出力) │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                          │                   │                   │
                     1 LLM call         N × Agent.speak      評価 M 並列
                     (Planner)          + 収束/停滞判定       + 総合評価
                                         + goal 補完          + レポート生成
```

各 Phase の入出力:

| Phase | 入力 | 出力 | 主体 |
|---|---|---|---|
| 0 | user_input (str) | 検証済み文字列 + scenario | `IdeaDiscussion` |
| 1 | user_input + scenario + roles | `OrchestraPlan` (ODSC + agents + rounds + private_instructions) | `Orchestrator` |
| 2 | `OrchestraPlan` | `DiscussionLog` (rounds[].utterances[]) | `Conductor` + `Agent[]` |
| 3 | `Plan` + `DiscussionLog` | `SynthesisResult` (report.md, full_conv.md, evaluation.md, summary.txt) | `Synthesizer` |

### 1.2 モジュール依存とレイヤ

```
Interface Layer   : main.py / serve.py (FastAPI) / cli_runner.py / display/
Feature Layer     : features/idea_discussion.py                    ← エントリ
Core Layer        : orchestrator, conductor, agent, synthesizer,
                    convergence, memory, evaluator, feedback,
                    conductor_prompts, speaking_order, follow_up,
                    time_keeper, turn_calculator, intervention
Infrastructure    : api_client (KotoBuddy API wrapper), rate_tracker,
                    config_loader, exceptions
Config            : config/settings.yaml, config/roles/*.yaml (10),
                    config/prompts/planning_prompt.txt,
                    config/role_base_template.txt,
                    config/scenarios/*.yaml (3)
```

**依存の方向は Interface → Feature → Core → Infrastructure → Config の一方向のみ**。
循環 import を避けるため、Feedback は Protocol インターフェース経由でのみ Orchestrator から参照される。

### 1.3 データフロー (1 セッション分)

```
User Input
  │
  ▼
IdeaDiscussion.run(user_input, time_limit=300)
  │
  ├─ 1. _validate_input   (5 <= len <= 5000)
  ├─ 2. _load_follow_up   (follow_up_id あれば過去セッション読込)
  ├─ 3. _detect_scenario  (キーワード検出: algorithm_design/experiment_planning/paper_discussion)
  │
  ├─ 4. Orchestrator.plan()
  │     ├─ _build_planning_prompt(roles, follow_up, scenario, preferred_roles)
  │     ├─ api_client.call(model=gpt-5.4, level=medium) — 1 回
  │     └─ _parse_plan_response → _validate_plan → OrchestraPlan
  │
  ├─ 5. confirm_callback(plan) — ユーザー確認 (Web UI では待受)
  │
  ├─ 6. _initialize_agents(plan) — role_id → Agent マッピング
  │
  ├─ 7. Conductor.run_discussion(plan)
  │     ├─ _notify_kickoff_briefing (指揮者ブリーフィング SSE)
  │     ├─ for each round in plan.round_config:
  │     │   ├─ _handle_time_pressure (残時間で早期終了判定)
  │     │   ├─ memory.extract_forbidden_examples (前ラウンド具体例抽出、1 LLM)
  │     │   ├─ _dispatch_pattern → _run_one_shot / _run_ping_pong / _run_free_talk
  │     │   │   └─ 各発言で Agent.speak() (N LLM)
  │     │   ├─ _run_round_conclusion  (leader が結論、1 LLM)
  │     │   ├─ _check_and_complete_goal (goal 達成判定、未達なら補足 1-2 LLM)
  │     │   ├─ convergence_checker.check (収束スコア、1 LLM)
  │     │   ├─ _handle_early_convergence → 停滞なら pivot 生成 (1 LLM)
  │     │   └─ _detect_narrowing (最終ラウンド以外) — 狭まりすぎ判定 (1 LLM)
  │     └─ _run_bonus_rounds_if_time_remains — 時間余ってれば追加 goal 生成 + ラウンド実行
  │
  └─ 8. Synthesizer.synthesize(plan, discussion_log)
        ├─ _run_evaluations (agent 数 × 並列。各 agent 内で self+peer combined 1 LLM)
        ├─ _generate_orchestrator_evaluation (MVP / ODSC 達成度、1 LLM)
        ├─ _generate_session_meta (LLM 非経由)
        ├─ _generate_report (LLM ベース、失敗時テンプレ fallback、1 LLM)
        │   └─ 内部で _extract_hypotheses (LLM ベース、失敗時 regex fallback、1 LLM)
        ├─ _generate_full_conversation (LLM 非経由)
        ├─ _generate_evaluation_md (LLM 非経由)
        └─ _generate_summary (LLM 非経由、内部で _extract_hypotheses 1 LLM)
```

### 1.4 主要な LLM 呼び出し箇所と担当モデル

| 呼び出し元 | 用途 | デフォルトモデル | Temperature | Max Tokens |
|---|---|---|---|---|
| Orchestrator | 計画立案 | `gpt-5.4` | — (level=medium) | reasoning_effort=medium |
| Agent.speak | 発言生成 | 各ロール指定 (`gpt-4.1` / `gpt-5` / `gpt-5.4` / `claude-sonnet-4-5`) | 0.7 | 300 (or verbosity=low) |
| Agent._request_shorter | 発言短縮 | `gpt-4.1` | 0.3 | 200 |
| ConvergenceChecker | 収束判定 | `gpt-4.1` | 0.0 | 200 |
| RepetitionDetector | 堂々巡り判定 | `gpt-4.1` | 0.0 | 150 |
| AgreementDetector | 同意過多判定 | `gpt-4.1` | 0.0 | 10 |
| Conductor._handle_stagnation | pivot 指示 | conductor.model (`gpt-4.1`) | 0.3 | 100 |
| Conductor._detect_narrowing | 狭まりすぎ判定 | convergence_checker.model (`gpt-4.1`) | 0.0 | 120 |
| Conductor._check_goal_achievement | goal 達成判定 | convergence_checker.model (`gpt-4.1`) | 0.0 | 200 |
| Conductor bonus round goal | 追加ラウンド goal 生成 | conductor.model (`gpt-4.1`) | 0.4 | 150 |
| ConversationMemory.extract_forbidden_examples | 具体例抽出 | `gpt-4.1` | 0.0 | 400 |
| ConversationMemory.summarize_round | ラウンド要約 | `gpt-4.1` | 0.0 | 150 |
| DynamicOrder (free_talk) | 次発言者選定 + 振り文言 | `gpt-4.1` | 0.0 | 20–200 |
| Evaluator (自己+他者) | 評価 | `gpt-4.1` | 0.0 | 1200 |
| Synthesizer._generate_orchestrator_evaluation | 総合評価 | `claude-sonnet-4-5` | 0.3 | 2000 |
| Synthesizer._extract_hypotheses | 仮説抽出 | `claude-sonnet-4-5` | 0.0 | 900 |
| Synthesizer._generate_report | レポート生成 | `claude-sonnet-4-5` | 0.3 | 2500 |

**1 セッション (5 ロール × 5 ラウンド × ~300 秒) の総 LLM 呼び出し目安**: 60-100 回

---

## 2. 現状の実装詳細

### 2.1 Orchestrator (Phase 1 計画)

**ファイル**: `core/orchestrator.py`
**責務**: ユーザー入力から ODSC・参加エージェント・ラウンド構成・個別指示を生成し `OrchestraPlan` を返す。

**構造**:
- 1 回の LLM 呼び出しで JSON 形式の計画を取得
- プロンプトは `config/prompts/planning_prompt.txt` を優先し、無ければモジュール内定数 `PLANNING_PROMPT` にフォールバック (両方に同じ内容が入っている dual-sourcing パターン)
- LLM が生成しがちなパターン名 (`brainstorm`、`socratic`、`sprint` など) は `_PATTERN_ALIASES` で正規 3 種 (`one_shot` / `ping_pong` / `free_talk`) にマップ

**OrchestraPlan の構造** (最終的に `Conductor` に渡されるデータ):
```python
@dataclass
class OrchestraPlan:
    odsc: ODSC                              # {objective, deliverable, success_criteria, convergence_threshold}
    selected_agents: list[AgentConfig]      # [{role_id, model, level, reason, expected_contribution}, ...]
    discussion_plan: DiscussionPlan         # {estimated_rounds, round_config, total_estimated_time_sec, total_estimated_requests}
    private_instructions: dict[str, PrivateInstruction]  # role_id → {expected_contribution, focus_points, constraints, ...}
```

**プランナが従うべき原則** (planning_prompt.txt から抜粋):
- **最優先: Objective の中心性** — Deliverable/Success Criteria は形式指定にすぎず、各 Round の goal は Objective の分解であること
- **議論フェーズ 4 段構造 (絶対遵守)** — 発散 / 比較評価 / 選択と具体化 / 統合とまとめ。途中で急に絞り込まない。
- **goal は「動詞+具体成果物+数字」の形** — 数字必須。「議論する」「検討する」は禁止。
- **数値過剰の抑制** — 疑似変数 (τ=0.8 等) や単位の羅列は禁止、口頭で言える範囲に
- **speakers 最低 3 名**、Round 1 は必ず `one_shot`、Round 2 以降は `one_shot` 禁止
- ビジネス系ロール参加時は 1 ラウンド以上を `ping_pong: [技術, ビジネス]` に

**弱点として認識されている点**:
- LLM が「切り口 5 案を出す」といった goal を書いても、実際の発言はそのラウンド内で 5 案未達になることがある (Conductor の `_check_and_complete_goal` が補完役として動く)
- ラウンド 3 以降で「特定業務の詳細に閉じる」現象は Orchestrator では検知できない (Conductor 側の `_detect_narrowing` が事後補正)

### 2.2 Conductor (Phase 2 議論進行)

**ファイル**: `core/conductor.py`
**責務**: `OrchestraPlan` に従って全ラウンドを実行、各ラウンドで発言者を順に呼び、収束・停滞・狭まりすぎを検知して次ラウンドに介入する。

**主要メソッド**:

| メソッド | 責務 | LLM 呼び出し |
|---|---|---|
| `run_discussion(plan)` | 全ラウンドをループ実行、bonus round も | — |
| `run_round(round_config, plan)` | 1 ラウンド実行 (発言 → 結論 → goal 補完 → 収束判定) | 4-8 |
| `_dispatch_pattern` | pattern に応じて `_run_one_shot` / `_run_ping_pong` / `_run_free_talk` | — |
| `_run_one_shot` | 各 speaker が固定順で 1 回発言 | N (speakers 数) |
| `_run_ping_pong` | 対立ペアが `max_exchanges=3` 回交互応答 (計 6 発言) | 6 |
| `_run_free_talk` | `DynamicOrder` で次発言者を都度選定、最大 8 発言 | 8-16 |
| `_run_round_conclusion` | speakers[0] (leader) が結論を出す | 1 |
| `_check_and_complete_goal` | goal 達成判定 (LLM) + 未達なら leader に補足発言要求 | 1-2 |
| `_handle_early_convergence` | 収束スコアと threshold で terminate/pivot/continue 判定 | — |
| `_handle_stagnation` | 停滞時に pivot 指示を LLM で生成 | 1 |
| `_detect_narrowing` | ラウンド末で LLM に「狭まりすぎか?」判定させ、狭まっていれば次ラウンドの pivot 指示に「視野拡大指示」を追加 | 1 |
| `_run_bonus_rounds_if_time_remains` | 全ラウンド後に時間が余っていれば追加ラウンド (bonus round) を実行 | 1 (goal 生成) + ラウンド分 |

**pivot 指示の伝播メカニズム**:
- `self._pivot_instruction: str` — 次ラウンドに注入する文字列 (空文字なら注入なし)
- `_handle_stagnation` と `_detect_narrowing` の両方が書き込む (`_detect_narrowing` は既存 pivot に追記)
- `run_round` 冒頭で `_consume_pivot_instruction()` が読み出し、`additional_instruction` として最初の発言者に注入

**時間管理**:
- `TimeKeeper` が残時間を管理し、`TimePressure` (NORMAL / URGENT / CRITICAL) を返す
- URGENT で次ラウンドが入りきらないなら terminate、CRITICAL でも terminate
- bonus round は残時間 >= `BONUS_ROUND_MIN_REMAINING_SEC (30s)` の間、最大 `BONUS_ROUND_MAX_COUNT (3)` 回

**収束による早期終了は無効化済み** — スコア記録と pivot 指示のみ維持、制限時間まで議論を継続する方針 (ユーザー指定の時間を使い切るため)。

### 2.3 Agent (発言生成)

**ファイル**: `core/agent.py`
**責務**: ロール定義 + 指揮者指示 + フィードバックを統合した system prompt を組み立てて発言を生成する。

**System Prompt の構造** (`_build_system_prompt`):
```
[base_template]                         ← config/role_base_template.txt (会話の態度)
[role_specific system_prompt]           ← ロール YAML の system_prompt (プレースホルダー除去済み)

【指揮者からの指示】
[private_instruction]                   ← Orchestrator が role 毎に生成した focus_points

【過去のフィードバック（改善を期待しています）】
[feedback_context]                      ← FeedbackManager が過去セッションから生成

【発言ルール】
[speaking_rules]                        ← settings.yaml の common + expertise 別

[DIVERSITY_RULE]                        ← 全 role 共通で末尾に付与 (多様性強制)
```

**Layer 構造の user message** (`_build_context_message`):
Agent は 10 層のコンテキストを組み立ててから API に投げる。

| Layer | 内容 | 目的 |
|---|---|---|
| 1 | **Objective (最優先)** | 議論の唯一の判断軸。Objective 外の発言を防止。 |
| 2 | Phase 状態 (Round N / 総 M) + phase hint | 今どの段階か認識 |
| 3 | Round Goal | このラウンドで達成すべきこと |
| 4 | ODSC 参考項目 (Deliverable / Success Criteria) | 二の次扱い |
| 5 | Previous summary | 過去ラウンドの要約 |
| 6 | **Forbidden examples** | 過去ラウンドで登場した具体例 (再利用禁止) |
| 7 | Current round utterances | このラウンドこれまでの発言 |
| 8 | Recent flow (直近 3 発言) | 引用強制の代替。会話の流れ |
| 9 | Additional instruction | 指揮者からの追加指示 (pivot / handoff など) |
| 10 | Last utterance | 直前発言に自然に反応 |

**発言長制御 (3 段防衛)**:
1. system prompt で「50〜150 文字」と指示
2. API パラメータで `max_tokens=300` (or GPT-5 系は `verbosity=low`)
3. 事後判定で `MAX_UTTERANCE_CHARS=200` 超なら `_request_shorter` で LLM に短縮依頼 (`gpt-4.1`)

**モデル別 API パラメータの分岐**:
- **GPT-5 系**: `temperature` / `max_tokens` 禁止。`reasoning_effort` (=level) + `verbosity=low` のみ
- **Claude thinking 系**: `thinking={budget_tokens=CLAUDE_THINKING_BUDGET[level]}` を追加
- **標準**: `temperature=0.7` + `max_tokens=300`

### 2.4 ConvergenceChecker / RepetitionDetector / AgreementDetector

**ファイル**: `core/convergence.py`
すべて `gpt-4.1` + `temperature=0.0` で JSON 出力を要求する軽量判定器。

**ConvergenceChecker**:
- ラウンド末で `check()` を呼び、`ConvergenceResult(score, reasoning, remaining_disagreements, recommendation)` を返す
- スコアは 0.0-1.0、`recommendation` は `continue` / `conclude` / `pivot`
- **stagnation 検出**: `is_stagnating()` は直近 window=3 ラウンドの max-min < tolerance=0.05 なら True
- **収束スコア変化ルール** (最近追加): プロンプト内で「前回スコアが存在する場合、必ず変化理由を明記」「前進なら +0.05 以上、後退なら -0.05 以上変化」「安易に同値を返すな」を強制

**RepetitionDetector**:
- 直近 window=4 発言に堂々巡りがあるかを判定
- `is_repeating=True` なら `_build_repetition_instruction` で次発言に「別角度・具体例・そもそもの問い」を提示する指示を注入
- free_talk 内で `free_talk_repetition_check_interval=3` 発言ごとに呼ばれる

**AgreementDetector**:
- 直近 window=3 発言が全て同意的か判定 (true/false のみ返す)
- 現状 `Conductor` から呼ばれていない (`EXCESSIVE_AGREEMENT_INSTRUCTION` は定義されているが未使用)

### 2.5 Synthesizer (Phase 3 統合)

**ファイル**: `core/synthesizer.py`
**責務**: 各エージェント評価の並列実行 → 指揮者総合評価 → 4 種類の出力ファイル (report.md / full_conversation.md / evaluation.md / summary.txt) の生成。

**主要フロー**:
```python
async def synthesize(plan, discussion_log, memory, agents, ...):
    agent_evaluations = await self._run_evaluations(agent_list, discussion_log, plan)
        # 各 agent に対し Evaluator.evaluate_combined を並列実行
        # (自己 + 他者を 1 回の LLM で取得)
    orchestrator_eval = await self._generate_orchestrator_evaluation(...)
        # MVP選出 + ODSC達成度 + 各 agent への個別フィードバック
    session_meta = self._generate_session_meta(...)  # LLM 非経由
    report_md = await self._generate_report(...)
    full_conversation_md = await self._generate_full_conversation(...)  # LLM 非経由
    evaluation_md = await self._generate_evaluation_md(...)              # LLM 非経由
    summary_txt = await self._generate_summary(...)                       # LLM 非経由 (仮説抽出 1 LLM)
    return SynthesisResult(...)
```

**`_generate_report` の実装** (問題4 対策として LLM ベース化済み):
- LLM (`claude-sonnet-4-5`) にプロンプト `REPORT_GENERATION_PROMPT` を渡し、Markdown レポートを生成
- 生成成功判定: `_is_llm_report_usable(content)` = `len >= 200 AND "##" in content`
- 失敗時は `_generate_report_template` (旧 7 セクション構造) にフォールバック
- **Idea モード vs Review モード切り替え**: `session_id` に `_review` が含まれるかで `verification_section_title` を「実験計画」/「検証方法」に切り替える

**`_extract_hypotheses` の実装** (問題4 対策として LLM ベース化済み):
- LLM に 4 種の仮説 (因果/効果/価値/リスク) を最低 3、最大 7 件抽出させる
- 失敗時は `_extract_hypotheses_regex` (H1、H2 パターンや「仮説」キーワードマッチ) にフォールバック

**評価集約 (`_run_evaluations`)**:
- `Evaluator.evaluate_combined` を各 agent 並列実行
- 各 agent は自分の視点で「自己評価 + 他者評価 (自分以外全員)」を 1 回の LLM で返す
- 集約後、`AgentEvaluations(self_eval, peer_evals)` を各 role_id にマップ

### 2.6 ConversationMemory

**ファイル**: `core/memory.py`
**責務**: 発言ログ・ラウンド要約・system events・token 統計・禁止例キャッシュを保持し、Agent が使うコンテキストを構築する。

**主要データ**:
- `full_log`: 全発言の構造化辞書リスト (`round`, `sequence`, `speaker`, `content`, `type`, `tokens_used`, `duration_sec`, `timestamp`)
- `round_summaries`: 各ラウンドの 3 行要約 (`summarize_round` で LLM 生成、現状使われていない場合が多い)
- `_forbidden_examples_cache`: ラウンド番号 → 具体例リスト (最大 10 件)
- `total_tokens` / `total_requests`: 累積統計

**`extract_forbidden_examples(current_round)`**:
- 過去ラウンドの発言を LLM で解析し「具体的な企業名、商品名、業界名、ユースケース、シナリオ、テクノロジー固有名、数字を含む具体表現」を最大 10 件抽出
- 一般語 (「顧客」「AI」「精度」など) は除外
- 各ラウンド開始時に Conductor が 1 回だけ呼び、結果をキャッシュ
- Agent の `_layer_forbidden_examples` (Layer 6) がこれを取り出して「これらは再利用禁止」と指示

**`get_context_for_agent`**:
- 現在のラウンド番号と `ContextBudget` を受け取り、Layer 5-8 用の材料を返す
- 履歴が `max_context_tokens=5000` を超えたら `round_summaries` に切り替える (現状は稀)

**弱点**:
- `round_summaries` は生成されているが Agent のプロンプトで積極活用されていない
- `_forbidden_examples_cache` は文字列マッチなので、LLM が抽出しなかった具体例 (同義表現) は防げない

---

## 3. プロンプト一覧

以下、実際に本番で使用されている全プロンプトを原文または要約で示す。プレースホルダは `{}` で示す。

### 3.1 計画立案 (Planner)

**呼び出し元**: `Orchestrator.plan()` — 1 セッションで 1 回のみ
**モデル**: `gpt-5.4` (`level=medium`)
**ファイル**: `config/prompts/planning_prompt.txt` (外部) + `core/orchestrator.py` `PLANNING_PROMPT` (フォールバック定数)

```
あなたはAI Orchestraの指揮者です。制限時間 {time_limit_sec:.0f} 秒で
アイデアを発展・深化させる議論の計画を立ててください。
目的は合意形成ではなくアイデアの深化。時間まで継続し早期終了はしません。

【ブレインストーミングの性格】
- 40% 創造的発想 / 30% 実現可能性 / 20% ユーザー・ビジネス視点 / 10% 技術裏付け
- 論文調・研究調の goal は禁止。口語的で具体的に。

【★ 最優先: Objective の中心性 ★】
Objective が議論全体の唯一の判断軸です。Deliverable / Success Criteria は
成果物のフォーマット指定にすぎず、内容は Objective に沿っているかで評価
されます。各ラウンドの goal は Objective の分解であること。

【★ 議論フェーズ構造 (絶対遵守) ★】
議論は以下 4 段構造で組み立てる。各段階を跳ばさず、途中で急に絞り込まない。

段階 1 (Round 1) 発散 / 持ち寄り: pattern="one_shot" 必須、全員 speakers に入れる。
  goal 例「各 AI が Objective に対する切り口を 1 つ提示 (合計 N 案)」。
  制約: 数値・実装詳細・製品名に踏み込まない。切り口タイトルレベル。
  goal に「特定業務・特定製品に踏み込まない」を必ず含める。

段階 2 (中間 Round) 比較評価: pattern="free_talk" or "ping_pong"。
  goal 例「Phase 1 の各案に長所 1 + 懸念 1 を指摘し比較する」。
  【絶対禁止】この段階で 1 案に絞り込む goal を書いてはいけない。
  複数の案を並行して比較する。goal に「特定 1 案の深掘りに入り込まない」を必ず含める。

段階 3 (最終前 Round、総 3 以上のとき) 選択と具体化: pattern="ping_pong"。
  goal 例「最有望案 1 つに合意し、実現方法の骨子を描く」。
  ここで初めて絞り込みに入る。

段階 4 (最終 Round) 統合とまとめ: pattern="free_talk"。
  goal 例「選ばれた案の MVP・KPI・リスク要素を具体化し、全体像と未解決課題を振り返る」。

総ラウンド 2 → 段階 1+4 統合可。総 3 → 段階 1+2+3/4 統合。

【★ goal の書き方 (絶対遵守) ★】
「動詞 + 具体成果物 + 数字」の形。数字必須。
良い例: 「切り口 5 案を出す」「主要リスク 3 つと回避策」「MVP 機能 3 つを決める」。
悪い例: 「議論する」「検討する」「分析する」「体験ストーリーを描く」(数字なし)。

【★ 会議の自然さ (数値過剰の抑制) ★】
実際の会議では、口頭で自然に言える範囲の数字しか扱いません。goal や発言では
以下のレベルに留めてください:
- 疑似変数 (τ=0.8、ε=0.1、δ、σ 等) を並べない
- 単位や接頭子を過剰に付けない (bps、+3pt、≤10ms などの羅列は禁止)
- パーセンテージは代表となる 1 – 2 個に絞り、それ以外は言葉で描写する
- 数字は「意思決定に直接影響する値」だけ (例: 想定 ARR、ターゲットユーザー数)

悪い例 (実際の会議でこんな発言はしない):
  「MVP は ①担当 ID 付き返却表 ②τ=0.8 未満は保留 ③全件に版番号＋理由ログ。
   KPI は誤返却率 ≤0.5%、翌営業日解決率 ≥95%。
   主リスクは保留 24h 超過 5% と、月次ドリフトで誤停止 +3pt」
良い例 (同じ内容を会議で口頭で言う):
  「MVP は 3 つ。担当者 ID を返却情報に付ける仕組み、
   自信度が低いときの自動保留、履歴を全部残す仕組みです。
   KPI は誤返却率と翌営業日解決率。目標値は事業サイドと調整。
   リスクは保留が長期化することと、モデル精度がじわじわ落ちること」

→ 「同僚に口頭で 3 分で説明できるレベル」を基準にする。
→ goal や結論でも同様に、口頭で交わされない疑似数式は禁止。

【計画原則】
- 時間 {time_limit_sec:.0f} 秒の 90-100% を使い切る計画にする
- 各ラウンドの time_budget_sec は 60-180 秒
- 最低ラウンド数: 制限時間 ≤300s → 3, 300-600s → 4, >600s → 5
- level は minimal / low / medium のみ (high 禁止 = タイムアウト原因)
- 進行 3 秒 + 結論 10 秒 /ラウンド、Phase 3 (統合) 25 秒
- 合計が制限時間の 95% 以内に収まる計画にすること

【制約】
- 参加可能 AI 数: 最大 {max_agents} 体
- expertise レベル: {expertise}
- level 別推定時間: minimal=3秒, low=5秒, medium=10秒

【ユーザー入力】
{user_input}

【利用可能ロール】
{roles_section}    ← 10 ロールの role_id / display_name / description / perspective /
                     expertise / domain_tags / feedback_stats を列挙

【★ role_id ルール (絶対遵守) ★】
role_id は上記【利用可能ロール】各行先頭の「role_id: xxx」の値
(英小文字・アンダースコアのみ) をそのまま使う。絵文字・日本語名は禁止。
  OK: "theorist"    NG: "🧮"    NG: "理論屋"    NG: "🧮 理論屋"

【speakers 設計】
- speakers[0] はそのラウンドの主導者。ラウンド末で結論を出す
- **各ラウンドの speakers は必ず 3 名以上** 含めること (絶対遵守)。
  ping_pong の場合も、主な話者 2 名に加えて働聴・補足役を 1 名以上入れる。
  free_talk の深掘りでも、単独発言者のラウンドは作らない。
  → 実際の会議でも 1 対 1 のモノローグは会議にならないため。
- ビジネス系ロール (matushita_kounosuke / son_masayoshi など domain に
  business_* / management_* を含む) 参加時:
  1 ラウンド以上を ping_pong: [技術系, ビジネス系] にする。
  one_shot の speakers 順序は「技術系 → ビジネス系」の交互配置
- 個性派カスタムロール (bird_eye / devil 以外) を 1 ラウンド以上の
  主導者 (speakers[0]) にも配置する

【pattern】
- "one_shot"  : 各 speaker が順に 1 回発言 (発散/概観)
- "ping_pong" : 2 人が交互に応答 (深掘り/反論)
- "free_talk" : 主導者中心の自由発言 (拡張/創発)
- Round 1 は "one_shot" のみ。Round 2 以降は "one_shot" 禁止。
- 対立が予想される議題: ping_pong 優先。拡散重視: free_talk 優先。

【private_instructions のロール別 focus_points】
- ビジネス系: 事業規模 (想定 ARR/TAM)、初期顧客セグメント、競合との差別化
- 現場系: 現場の困り事、導入抵抗、教育・体制整備
- 技術系 (theorist / implementer / experimentalist): 実装ボトルネック、
  代替アーキテクチャ、性能の数値目標
- 全ロール共通の constraints: 「他者と同じ具体例・言い回しを繰り返さない」
{preferred_roles_section}{follow_up_section}{scenario_section}
【出力形式 (JSON のみ。前後に説明文を付けない)】
{{ "odsc": {...}, "selected_agents": [...], "discussion_plan": {...},
   "private_instructions": {...} }}
```

**このプロンプトの特徴**:
- 「4 段構造絶対遵守」を **★ で囲んで強調** している
- 数値過剰の抑制について悪例/良例をペアで示している (LLM が模倣しやすい)
- 「収束閾値」はもう機能上ほぼ意味を持たない (収束による早期終了は無効化済み) が、プロンプトには残っている

### 3.2 ラウンド末尾の結論

**呼び出し元**: `Conductor._run_round_conclusion` — 毎ラウンド 1 回、speakers[0] (leader) が発言
**モデル**: leader agent 自身のモデル (ロール指定)
**種類**: 中間ラウンド用 (`ROUND_CONCLUSION_INSTRUCTION`) と最終ラウンド用 (`FINAL_ROUND_CONCLUSION_INSTRUCTION`) の 2 種

**中間ラウンド用** (`conductor_prompts.py`):
```
🎯 このラウンドの結論を出してください。

【★全体議題 (Objective) ★】
{objective}
→ この結論は必ず上記 Objective に直接貢献するものにする。
  Objective から外れた一般論・テーマ外の方向への拡張は一切含めない。

【あなたの役割】
あなたはこのラウンドの主導者です。これまでの他の参加者の発言を踏まえて、
このラウンドで何が見えたのかを結論としてまとめてください。

【ラウンドの目標】
{round_goal}

【目標達成への強い役割 (問題5対策)】
- 上記目標を必ず達成する結論を書くこと。
- 目標に「N 案出す」とあり、議論で N 案未達なら、あなたが不足分を提示して埋める。
- 目標に「〜を決める」とあり、議論が発散したままなら、あなたが仮決めして提示する。
- 目標に「〜を描く」とあり、具体化不足なら、あなたが具体例・シナリオで埋める。

【会議の自然さ (数値過剰の抑制)】
- 数字は代表となる 1〜2 個に絞る。疑似変数 (τ=0.8、ε=0.1、δ 等) や
  単位の羅列 (bps、+3pt、≤10ms、≤95% など) は一切使わない。
- リスクや目標値を述べるときは、実際の会議で口頭で交わす言葉
  (「事業サイドと調整」「じわじわ落ちる」など) に置き換える。

【まとめ方】
- 冒頭に「【結論】」と付ける
- 他者の発言を取り込んだ統合的な結論にする (引用形式は問わない。
  「《内容》について合意」のように自然に述べる)
- 【合意点】と【相違点】を分けて明記する (それぞれ最低 1 つ)
- 最後に【次論点】として、次のラウンドで扱うべき論点を 1 つ具体的に提示する
  (ここも Objective に不可欠な論点に限る)

【禁止事項】
- 自分の意見だけを述べる (単独の発表になる)
- 「みなさん良い議論でした」のような空虚な総括
- 議論に登場していない内容をひねり出す
- Objective と直接関係のない論点を含める

【文字数】
150〜250 文字。「【結論】〜【合意点】〜【相違点】〜【次論点】」の順で。
```

**最終ラウンド用は**:
- 冒頭が「【最終結論】」に変わる
- 【次論点】は書かない
- 「セッション全体を統合した結論に」と指示

**このプロンプトの現状の問題**:
- 「【結論】〜【合意点】〜【相違点】〜【次論点】」のテンプレートタグを強制することで、
  出力ログ (`full_conversation.md`) が定型化して読みにくい (§5 で詳述)
- 「みなさん良い議論でした」のような空虚な総括を禁止しているが、実際には
  leader が「AIの進化は、単体性能より、反復検証で安定化し…」のような
  空虚な総括を書きがち

### 3.3 収束スコア判定

**呼び出し元**: `ConvergenceChecker.check()` — 毎ラウンド 1 回
**モデル**: `gpt-4.1` (`temperature=0.0`, `max_tokens=200`)
**ファイル**: `core/convergence.py` `CONVERGENCE_CHECK_PROMPT`

```
以下の議論ログを分析し、参加者間の合意度を評価してください。

【必須】回答は必ず有効な JSON オブジェクトのみ。前後の説明文・前置き・
コードフェンスの内側以外に何も付けないこと。

【ODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【このラウンドの目標】
{round_goal}

【直近の議論（このラウンド全文）】
{round_utterances}

【これまでの収束スコア推移】
{previous_scores}

【スコア変化ルール（絶対遵守）】
- 前回スコアが存在する場合、今回は必ず「前進した理由」または「後退した理由」を
  reasoning に明記すること。
- 前回と同じ値を安易に返すのは禁止。停滞に見えても、微細な進展/後退を
  観察して差分を出すこと。
- 前進していれば +0.05 以上、後退していれば -0.05 以上変化させる。
- どうしても同じスコアにする場合は reasoning に「完全に同水準である理由」を
  1 文で明示する。

【評価の観点】
1. アイデアが十分に膨らんだか（新しい切り口・展開が出尽くしたか）
2. 反対意見や死角が指摘され、それに対する代替案が出たか
3. 具体的な次のアクションや実験が提案されたか
4. Success Criteria の達成度はどの程度か
5. まだ深掘りできる未探索の方向性が残っていないか

【重要】
- 単に「方向性が合っている」だけでは収束とみなさない
- 「まだこういう展開もありえる」が残っている限り、スコアを高くしない
- 全員が同意しているだけの状態は 0.5 程度（深掘り不足の可能性）

【出力形式 (JSON のみ)】
{{
  "score": 0.75,
  "reasoning": "合意度の根拠（1-2文）",
  "remaining_disagreements": ["未解決の論点1", "論点2"],
  "recommendation": "continue"
}}

score の目安:
- 0.0-0.3: 方向性すら定まっていない
- 0.3-0.5: 方向性は見えるが、アイデアの広がりが不十分
- 0.5-0.65: 複数の切り口が出たが、深掘り・具体化が足りない
- 0.65-0.8: 主要な方向性が探索され、具体的アクションも一部出た
- 0.8-0.9: アイデアが十分に発展し、次のステップが明確
- 0.9-1.0: 完全に議論し尽くした（稀）

recommendation:
- "continue": まだ深掘りや新しい切り口の余地がある
- "conclude": アイデアが十分に発展し、次のアクションが明確になった
- "pivot": 議論が行き詰まっている。別の角度から攻める必要がある
```

**このプロンプトの現状の問題**:
- スコア変化ルールを強調しても、実運用では 0.70 → 0.75 → 0.75 → 0.75 → 0.75 のように停滞しがち
  (§5.2 の `20260710_172837_idea/full_conversation.md` 参照)
- 「単に方向性が合っているだけでは収束としない」と書いても、実際には合意過多を高スコア扱いにする傾向

### 3.4 狭まりすぎ検知 + ピボット

**呼び出し元**: `Conductor._detect_narrowing()` — 毎ラウンド末 (最終ラウンド除く) 1 回
**モデル**: `gpt-4.1` (`temperature=0.0`, `max_tokens=120`)
**ファイル**: `core/conductor_prompts.py` `NARROWING_CHECK_PROMPT`

判定プロンプト:
```
以下のラウンド結論を分析し、議論が「特定の 1 業務・1 製品・1 シナリオの改善策」に閉じ気味かを判定してください。

【元テーマ (Objective)】
{objective}

【直近ラウンドの結論と主要発言】
{utterances_text}

【判定基準】
- narrowed=true: 議論が具体的な 1 業務 (例: 経費精算 / FAQ チャット) や 1 シナリオの改善策の詳細に入り込んでいる
- narrowed=false: 複数の切り口・業界・視点が並行して議論されている

【必須】回答は必ず有効な JSON オブジェクトのみ。前後に説明文を付けない。

【出力形式】
{{
  "narrowed": true,
  "focused_topic": "閉じている場合、その業務や具体例名 (最大 20 字)"
}}
```

判定が `narrowed=true` の場合、次ラウンドの Agent に注入される指示:
```
【視野拡大の指示】
前のラウンドの結論は「{focused_topic}」の改善策に閉じ気味です。
ここで視野を広げます。元のテーマ「{objective}」に立ち戻り、
別の切り口や別の業界への展開・別の観点 (技術/ビジネス/社会/倫理) から発言してください。
```

**この機構の現状の問題**:
- 判定 LLM は「経費精算」「FAQ チャット」など明示的な単語に反応するが、より微妙な狭まり (例: 「見直し型」「線引き型」の 3 案の中で 1 案の細部に閉じる) は検知できない
- 検知しても、次ラウンドの Agent への「視野拡大指示」は 1 文なので、直前 2-3 発言の吸引力に負けて元テーマに戻れないことがある
- `_detect_narrowing` は最終ラウンドで skip する仕様のため、5 ラウンド構成なら最後の 4→5 ラウンド遷移では働かない

### 3.5 堂々巡り検知 / 同意過多検知

**RepetitionDetector** (`REPETITION_CHECK_PROMPT`):
```
以下の直近{window}発言を分析し、堂々巡りが起きているか判定してください。

【必須】回答は必ず有効な JSON オブジェクトのみ。前後の説明文は不要。

【直近の発言】
{utterances_text}

【判定基準】
- 同じ論点が2回以上繰り返されている → 堂々巡り
- 新しい情報・視点が追加されず、同じ主張の言い換え → 堂々巡り
- 前の発言を踏まえて深まっている → 堂々巡りではない

【出力形式 (JSON のみ)】
{{
  "is_repeating": true,
  "repeated_topic": "繰り返されている論点（なければ空文字）",
  "suggestion": "議論を前に進めるための提案"
}}
```

`is_repeating=True` の場合、Conductor は `_build_repetition_instruction` で次発言者に以下を注入する:
```
⚠️ 議論が堂々巡りしています。

【繰り返されている論点】
{repeated_topic}

【あなたへの指示】
上記の論点は一旦横に置いてください。代わりに以下のいずれかを行ってください：
1. まったく別の角度から問題を見る
2. 具体的な数値例や反例を出して議論を動かす
3. 「そもそも」の問いに立ち返る
4. この論点を「未解決」として明示し、次に進む

普通に会話するトーンで、50〜150文字で発言してください。
```

**現状の呼ばれ方**:
- `_run_free_talk` 内で `free_talk_repetition_check_interval=3` 発言ごとに呼ばれる
- `_run_one_shot` と `_run_ping_pong` では呼ばれない (ラウンド全体で堂々巡りしても検知しない)

**AgreementDetector** (`AGREEMENT_CHECK_PROMPT`):
```
以下の直近{window}発言を分析してください。

{utterances_text}

全員が同じ方向に同意しているだけで、新しい視点や批判が出ていない場合は true を返してください。
出力: true または false のみ
```

**現状の呼ばれ方**:
- **どこからも呼ばれていない** (定義済みだが未使用)
- 対応する `EXCESSIVE_AGREEMENT_INSTRUCTION` も定義済みだが未使用

### 3.6 Goal 達成度チェック

**呼び出し元**: `Conductor._check_and_complete_goal` — 毎ラウンド末 (結論後) 1 回
**モデル**: `gpt-4.1` (`temperature=0.0`, `max_tokens=200`)
**ファイル**: `core/conductor_prompts.py` `GOAL_COMPLETION_CHECK_PROMPT`

判定プロンプト:
```
以下は 1 ラウンドの議論ログです。「ラウンド目標」に対する達成度を評価してください。

【必須】回答は必ず有効な JSON オブジェクトのみ。前後の説明文は不要。

【ラウンド目標】
{round_goal}

【議論ログ (結論も含む)】
{utterances_text}

【判定基準】
- 目標が「N 個出す」なら、N 個の具体的候補が明示されているかチェック
- 目標が「〜を決める」なら、明確な決定・優先順位が示されているかチェック
- 目標が「〜を描く」なら、具体的なシナリオ・数字・エピソードが十分か
- 単に議論されただけで成果物が出ていない場合は achieved=false

【出力形式 (JSON のみ)】
{{
  "achieved": true,
  "missing": "不足している要素があれば 1 文で、なければ空文字"
}}
```

`achieved=false` の場合、leader (speakers[0]) に補足発言を要求:
```
⚠️ このラウンドの目標がまだ達成されていません。あなたが埋めてください。

【ラウンド目標】
{round_goal}

【不足している要素】
{missing}

【あなたへの指示】
（以下、この後 leader が発言）
```

**この機構の現状の問題**:
- 補足発言も leader (speakers[0]) が行うため、leader の視点だけで埋まる (多様性が損なわれる)
- 「未達なら埋める」がプロンプト補完で行われるので、実際に議論で不足していた案の中身は空虚な列挙になりやすい

### 3.7 Bonus round goal 生成

**呼び出し元**: `Conductor._run_bonus_rounds_if_time_remains` — 全計画ラウンド後に時間が余っていれば
**モデル**: `gpt-4.1` (`temperature=0.4`, `max_tokens=150`)
**ファイル**: `core/conductor_prompts.py` `BONUS_ROUND_GOAL_PROMPT`

```
時間が余っているので、もう 1 ラウンド追加で議論します。
【重要】追加ラウンドが「同じ具体例をさらに掘る」形になっては元テーマから逸れます。
以下の 4 択から目的を 1 つ選んで goal を作ってください:

  A. まだ触れていない角度 (技術 / ビジネス / 社会 / 倫理) から議論する
  B. これまでの議論を元テーマに接続し直し、全体像をまとめる
  C. 異なる業界・文脈への適用を検討する
  D. まだ議論されていない有望案を掘り起こす

【当初の Objective】
{objective}

【これまでのラウンドのゴール】
{previous_goals}

【最新の収束スコア】 {last_score}

【未解決の論点】
{disagreements}

【禁止】
- 直前ラウンドと同じ具体例 (同一業務・同一製品・同一シナリオ) をさらに掘る goal は書かない
- 「〜をさらに深掘りする」「〜の詳細を詰める」形は禁止

【出力形式】
前置きなしで、以下 1 行だけ (60 文字以内、「動詞 + 具体成果物」の形を守る):
goal: <ラウンドの目標>
```

**Pivot 生成** (`PIVOT_PROMPT`、停滞時に `_handle_stagnation` から呼ばれる):
```
議論が停滞しています。方向転換の指示を生成してください。

【停滞の状況】
- 直近の収束度: {recent_scores}
- 未解決の対立点: {disagreements}

【方向転換の方法（いずれかを選択）】
1. 未解決の対立点を「仮に〇〇とする」で暫定合意し、別の論点に移る
2. 抽象度を上げて「そもそも」の問いに立ち返る
3. 具体例を1つ設定し、その例に絞って議論する
4. 対立点を「未解決問題」として残し、解決可能な部分から進める

次のラウンドの冒頭で全AIに伝える指示（100文字以内）:
```

**この機構の現状の問題**:
- Bonus round goal は「4 択から選ぶ」形式にした結果、A/B/C/D どれも「一般論」寄りになる傾向 (§5.2 参照)
- Pivot 指示は 100 文字以内なので、Agent への説得力が弱く、次発言者がまた元の論点に戻ることがある

### 3.8 禁止例抽出

**呼び出し元**: `ConversationMemory.extract_forbidden_examples` — 毎ラウンド開始時 1 回
**モデル**: `gpt-4.1` (`temperature=0.0`, `max_tokens=400`)
**ファイル**: `core/memory.py` `FORBIDDEN_EXAMPLES_PROMPT`

```
以下の議論ログを読み、これまでに既に登場した「具体例・固有名詞・シナリオ」を最大 10 個列挙してください。
次のラウンドではこれらを繰り返さないため、リスト化します。

【議論ログ】
{log_text}

【出力形式 (JSON のみ、前後に説明文を付けない)】
{{
  "examples": ["例1", "例2", "例3"]
}}

【抽出のルール】
- 対象: 具体的な企業名、商品名、業界名、ユースケース、シナリオ、テクノロジー固有名、数字を含む具体表現
- 除外: 「顧客」「品質」「AI」「精度」など一般的な単語
- 重要度の高いもの上位 10 個まで
```

**結果の使われ方**:
Agent の Layer 6 `_layer_forbidden_examples` で以下の形で表示:
```
【今回避けるべき既出の具体例】
- 経費精算
- 通関書類
- 契約書チェック
→ これらは既に議論で登場しています。同じ例を繰り返さず、
   新しい具体例・業界・シナリオを持ち出してください。
```

**現状の問題**:
- 具体例名は防げるが、その具体例に紐づいた「発想の枠組み」(例:「事務作業の自動化」) は防げない
- 抽出漏れが多い (例:「失敗ログ台帳」「差分保存」など複合語は取りこぼしがち)

### 3.9 仮説抽出

**呼び出し元**: `Synthesizer._extract_hypotheses` — レポート生成時 1 回、Summary 生成時 1 回 (計 2 回)
**モデル**: `claude-sonnet-4-5` (`temperature=0.0`, `max_tokens=900`)
**ファイル**: `core/synthesizer.py` `HYPOTHESIS_EXTRACTION_PROMPT`

```
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
```

**フォールバック**: LLM 呼び出しか JSON パースが失敗した場合、`_extract_hypotheses_regex` を使う。
regex 版は `H\d+` パターンや「仮説」「hypothesis」キーワードを検索するが、正規表現マッチは
ほぼ空になるため、旧テンプレート版レポートでは「仮説抽出なし」が頻発していた (これが問題4対策の背景)。

**現状の問題**:
- LLM 抽出でも実運用では `(仮説抽出なし)` になることがある (§5.2 の summary.txt 参照)
- 抽出成功時も、原文のフレーズをそのまま `hypothesis` に入れるだけで、
  「因果」「効果」「価値」「リスク」の分類がされない

### 3.10 レポート生成

**呼び出し元**: `Synthesizer._generate_report` — 1 セッションで 1 回
**モデル**: `claude-sonnet-4-5` (`temperature=0.3`, `max_tokens=2500`)
**ファイル**: `core/synthesizer.py` `REPORT_GENERATION_PROMPT`

```
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

## {verification_section_title}   ← Idea モード: 「検証方法」 / Review モード: 「実験計画」
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
```

Idea モード用の「検証方法」セクション導入:
```
この提案を検証するために効果的な方法を 3 つ提案する。各方法に:
- 方法の概要
- 必要なリソース
- 期待される結果
- 判断基準
PoC / ヒアリング / 市場調査 など、ビジネス的な検証も含めて良い。
```

Review モード用の「実験計画」セクション導入:
```
提案の妥当性を検証する実験計画を 3 つ提案する。各計画に:
- 実験設計 (対照群・独立変数)
- データセット / 計測方法
- 評価指標
- 期待される結果
```

**フォールバック**: 生成失敗 or `len < 200` or `"##"` が含まれない場合、旧テンプレ実装
`_generate_report_template` に fall back (7 セクション: 問題設定 / 洞察 / 骨格 / 仮説 / 実験計画 / 未解決 / 参考文献)。

**現状の問題**:
- LLM は指示に従うが、`full_log` に「【結論】〜」タグが大量に含まれるため、そのままコピーしがち (§5.2)
- タイトル固定禁止と書いても、「AI 進化のロードマップ」のような平凡なタイトルになる
- 「議論で得られた主要アイデア」の 3-5 件が、実際の議論の 5 切り口をそのまま並べるだけになる (集約されない)

### 3.11 自己 / 他者 / 総合評価

3 種類のプロンプトが `core/evaluator.py` と `core/synthesizer.py` に定義されている。

**COMBINED_EVALUATION_PROMPT** (自己 + 他者を 1 回で取る、`Evaluator.evaluate_combined`):
```
議論が完了しました。自己評価と他者評価をまとめて行ってください。

【あなたの役割】
{role_display_name} ({role_id})

【あなたに期待されていたこと】
{expected_contribution}

【あなたの評価基準（自己評価用）】
{evaluation_criteria_formatted}  ← ロール YAML の evaluation_criteria から自動生成

【他の参加者（他者評価対象）】
{other_agents_list}

【議論のODSC】
- Objective: {objective}
- Success Criteria: {success_criteria}

【議論ログ（あなたの発言は ** で囲んでハイライトしています）】
{discussion_log_with_highlights}

【出力形式 (JSON のみ。前後に説明文を付けない)】
{{
  "self_evaluation": {{
    "scores": {{ ...ロール別評価基準ごとに 1-5 のスコア... }},
    "avg_score": <平均値 小数点1桁>,
    "reasoning": "<3-5文で振り返り>",
    "key_contributions": ["<主な貢献1>", "<主な貢献2>"],
    "missed_opportunities": ["<やるべきだったがやらなかったこと>"]
  }},
  "peer_evaluations": {{
    "<other_role_id>": {{"score": 1-5, "comment": "..."}}
  }}
}}

【注意】
- 自分自身は peer_evaluations に含めない
- 自己評価は厳しく、他者評価は具体的に
- スコアは 1〜5 の整数
```

**ORCHESTRATOR_EVALUATION_PROMPT** (`Synthesizer._generate_orchestrator_evaluation`):
```
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
  "mvp": {{ "role_id": "...", "reason": "..." }},
  "odsc_achievement": {{
    "achieved": true, "detail": "...",
    "objective_met": true, "deliverable_met": true, "criteria_met": true
  }},
  "per_agent_feedback": {{
    <role_id>: {{
      "strengths_noted": [...],
      "improvements_noted": [...],
      "orchestrator_feedback": "..."
    }}
  }}
}}
```

**現状の問題**:
- 各 Agent は自分の視点で他者を評価するが、
  実際には自己評価 4.5 + 他者評価 5.0 で全員が高得点になりがち (同調圧力)
- `orchestrator_evaluation` の `odsc_achievement.detail` が長くなり、summary.txt の「結論」欄で
  「ObjectiveとDeliverableは概ね達成された...一方でSuccess Criteriaは完全達成までは至っていない...」
  のような超長文になる (§5.2 の summary.txt 参照)
- 各 Agent の evaluation_criteria がロール YAML にハードコードされており、動的な議論に合った基準になっていない

---

## 4. ロール定義の現状

10 ロールが `config/roles/*.yaml` に定義されている。Idea 議論では通常 4-5 ロールが選ばれる。

### 4.0 共通のシステムプロンプト前後 (role_base_template.txt)

全ロール共通で先頭に注入:
```
【会話の態度】
- 自然な会話として話す。テンプレートや定型文は使わない。
- 前の人の発言を踏まえて話を展開する。ただし「〇〇さんの『〜』について、」のような形式的な引用や名前の明示は不要。会話の流れに乗ることの方が重要。
- 1回の発言は50〜200文字。内容があれば短くて良い。冗長な前置きや締めのフレーズは書かない。
- 評論家にならない。抽象的な感想より、具体的なアイデア・提案・エピソードを1つ出す。
- 数字は「実際の会議で口頭で自然に言える範囲」に限る。τ=0.8、ε=0.1、+3pt、≤0.5%、24h超過5% のような疑似変数・単位の羅列は禁止。数値を出すなら代表となる 1〜2 個までに絞り、それ以上は「事業サイドと相談」「じわじわ落ちる」など言葉で述べる。
- 前の発言に反応するか、新しい切り口を出す。文脈と無関係な発言はしない。
- 前の発言と同じ構文・同じ切り口・同じ結び方を繰り返さない。毎回違う言い回しで話す。
- 直前 2 回の自分の発言と同じ文頭 (例:「そもそも」「ちょっと待って」「一歩引くと」など) は避ける。
- 「整理すると」「まとめると」「俯瞰すると」等のメタ発言は 3 回に 1 回まで。中身のあるアイデア・具体例・反例を優先する。

{orchestrator_instruction}

{feedback_context}
```

さらに全ロール共通で末尾に DIVERSITY_RULE を付与:
```
【多様性ルール】
- 直前の発言者と同じ出だし・同じ論理展開・同じ結び方を使ってはいけない
- あなたの発言が定型化していたら、途中でも書き直す。毎回違う切り口で発言する
- 疑似変数 (τ=0.8、ε=0.1、σ、δ 等) や単位の羅列 (bps、+3pt、≤0.5%、24h超過5% 等) を並べない。実際の会議で口頭で自然に言えるレベルの表現に留める
```

### 4.1 bird_eye 🎯 鳥の目 (`gpt-5.4`)

- **description**: 俯瞰視点でメタ整理を行うファシリテーター。論点を再フレーミングして地図を作る。
- **perspective**: 問題設定の構造分析、分野横断的なアナロジー、研究の意義・新規性の評価
- **evaluation_criteria**: 俯瞰力 / リフレーミング / アナロジーの質 / 介入タイミング

**system_prompt の要点**:
- 【あなたの独自価値】: 「あなたは単なる司会者・整理役ではない。参加者が気付いていない『構造的な問題』を指摘するのが独自の価値」「発言を要約するだけの回は禁止」
- 【発言スタイル】: 「文頭固定禁止 (「一歩引くと」「別の見方をすると」「そもそも」を毎回使うな。3 回連続で同じ文頭を使うな)」
- 【禁止事項】: 「毎ターン発言する」「細部の技術議論に踏み込みすぎる」「具体的提案なしの「もっと考えよう」」

**feedback_history の現状** (2026-07-13 時点):
- self_avg 4.43, peer_avg 4.67
- 改善点として繰り返し指摘されるのは「数値閾値や意思決定ルールを明示して議論をさらに強く収束させる余地があった」

### 4.2 devil 😈 穴探し (`gpt-5.4`)

- **description**: あえて逆張りを担う悪魔の代弁者。仮定の穴やリスクを指摘して議論を締める。
- **perspective**: エッジケース分析、反例構築、前提条件の検証、failure mode 分析
- **evaluation_criteria**: 穴の発見力 / 反例の具体性 / 修復案の提示 / 致命度の判断

**system_prompt の要点**:
- 【反論の 3 パターン (毎回どれか一つを明示的に選ぶ)】:
  1. 前提崩し
  2. エッジケース (N=1 / empty / 密度ゼロ / 想定外分布 など極端例)
  3. スケール問題 (100 倍 / 1000 倍にした時に破綻する構造上の理由)
- 【発言スタイル】: 「文頭固定禁止: 3 回連続で「ちょっと待って」から始めない。感嘆の連発 (「あ、壊れた」「致命的じゃない？」「面白い穴だね」) も禁止」
- 【心がけ】: 「全部否定しない。良い点は「それは筋いい、ただし…」と認めてから指摘」
- 【禁止事項】: 「穴の指摘だけして修復案を出さない (最も重要なルール)」

**feedback_history の現状**:
- self_avg 4.6, peer_avg 4.42
- 改善点: 「どの失敗モードが本当に優先対処対象かの順位づけをもう少し明示すると、収束への貢献がさらに増します」
- 「守りの観点が中心だったため、どの条件なら積極導入できるかという『攻めの許容条件』も併記できるとバランスが良くなります」

### 4.3 theorist 🧮 理論屋 (`gpt-5.4`)

- **description**: 理論と数式で議論を支える研究者。計算量や収束性の観点から発言を裏付ける。
- **perspective**: 数理モデリング、計算量解析、最適化理論、収束証明、情報理論
- **evaluation_criteria**: 定式化の的確さ / 理論的根拠の提示 / 計算量の意識 / 議論の深化

**system_prompt の要点**:
- 【役割】: 議論中のアイデアを数学的に定式化、計算量オーダーを明示、理論的な限界を指摘
- 【発言スタイル】: 「数式はテキスト表現で自然に混ぜる (例: O(N log N), ∑, ∈, ≤, ∀)」「結論→条件の順で話す」「他の人の直感的な発言を「それを定式化すると…」と引き取る」「文頭固定禁止: 3 回連続で同じ文頭を使わない。感嘆の連発 (「それ筋いいね」「美しい」「エレガント」) も禁止」
- 【禁止事項】: 「長い数式の羅列」「ビジネス的観点への言及」「他の人を見下すような態度」

**feedback_history の現状**:
- self_avg 1.5, peer_avg 1.67 (前回の 1 セッションだけの数字。過去大セッションでは 4.5/5.0)
- 改善点: 「後半は通知最適化など新しい枝を伸ばし過ぎて、経費精算 MVP の最終像との接続がやや薄くなった」

### 4.4 implementer 🤖 実装屋 (`gpt-5.4`)

- **description**: 実装可能性を最優先で判断する現場のエンジニア。MVP と現実的なスコープに敏感。
- **perspective**: PyTorch / PyTorch Geometric / JAX、CUDA最適化、メモリ効率設計、分散学習
- **evaluation_criteria**: 実装可能性の判断 / ボトルネック特定 / 代替手段の提示 / ツール・ライブラリ知識

**system_prompt の要点**:
- 【発言スタイル】: 「フレームワーク名・関数名を具体的に出す」「「それO(N²)のnaive実装だけど、〇〇使えばO(N log N)に落ちる」のように代替を示す」「短いコード片(1-2行)を`バッククォート`で引用してもOK」「文頭固定禁止: 3 回連続で同じ文頭を使わない。感嘆の連発 (「それGPU乗るね」「メモリ死ぬぞ」) も禁止」
- 【禁止事項】: 「長いコードブロック (会話が止まる。3行以上はNG)」

**feedback_history の現状**:
- self_avg 4.8, peer_avg 5.0 (2026-07-10 idea session、MVP 選出あり)
- 改善点: 「品質非劣化の業務別評価設計については『保留にしてMVP先行』の場面が多く、精度検証フレームをもう一段先回りして提案できるとさらに強い」

### 4.5 experimentalist 🔬 実験屋 (`gpt-5`)

- **description**: 手を動かして検証するタイプ。仮説を素早く実験に落とし込むことに強い。
- **perspective**: 実験設計 (DoE)、統計的仮説検定、再現性保証、ベンチマーク選定
- **evaluation_criteria**: 実験設計の妥当性 / 具体性 / ベースラインの適切さ / 現実的制約の意識

**system_prompt の要点**:
- 【役割】: 提案手法を検証する実験計画を設計、公正なベースライン選定、ablation study 条件を提案
- 【発言スタイル】: 「「それ何のデータセットで試す？」「seed何個回す？」のように具体的に」「「再現できなきゃ意味ない」が信条」「文頭固定禁止: 3 回連続で同じ文頭を使わない。感嘆の連発 (「cleanだね」「それfairな比較だ」) も禁止」

**feedback_history の現状**:
- 大セッションでは self/peer_avg 4.5 前後
- 改善点: 「一部の設定は負荷やメモリ条件がやや楽観的だったため、容量見積もりや段階的ロールアウト条件もセットで示せると運用接続がより強くなる」

### 4.6 literature 📚 文献屋 (`gpt-5.4`)

- **description**: 先行研究に精通する文献屋。既存の知見や事例で議論を補強する。
- **perspective**: 論文サーベイ、手法比較・系譜整理、ベンチマーク結果の把握
- **evaluation_criteria**: 引用の適切さ / 正確性 / 系譜の整理 / 差分の明確化

**system_prompt の要点**:
- 【重要ルール】: 「存在が不確かな論文には必ず [要確認] をつける」「知らない分野・手法については「そこは詳しくない」と正直に言う」「arXiv preprint は「(Author+年, arXiv)」と区別する」
- 【発言スタイル】: 「引用形式: (著者+年) で簡潔に」「文頭固定禁止: 3 回連続で同じ文頭を使わない。感嘆の連発 (「お、それ新しいね」「あ、それ(XX+20XX)と同じ発想では」) も禁止」
- 【禁止事項】: 「架空の論文の引用 (最も重大な違反)」

### 4.7 code_architect 📐 設計リーダー (`gpt-4.1`)

- **description**: アーキテクチャと設計の一貫性を守るソフトウェア設計者。責務分割と拡張性に着目する。
- **perspective**: SOLID原則、デザインパターン、モジュール分割、依存関係管理、テスタビリティ設計
- **evaluation_criteria**: 構造問題の発見 / 改善案の実用性 / 優先度の適切さ / 段階的改善の提案

**Idea 議論での参加は稀** (主に code_review 用)。system_prompt は「【調査観点】」「【発言スタイル】」で
コードレビュー向けに最適化されている (「ファイル名 L行番号: 〇〇 → △△に変更推奨」形式)。

### 4.8 code_reviewer 📝 可読性リーダー (`gpt-4.1-mini`)

- **description**: 可読性・保守性を重視するコードレビュー担当。命名やコメントの粒度まで踏み込む。
- **perspective**: PEP 8 / PEP 257、命名規則、docstring、型ヒント、コードフォーマッタ
- **evaluation_criteria**: 可読性問題の発見 / 命名の妥当性 / スタイル一貫性 / 段階的改善の提案

**Idea 議論では通常参加しない**。

### 4.9 son_masayoshi 🐑 孫正義 (`gpt-4.1`)

- **description**: 孫正義。ビジネスの才能が高い
- **domain_tags**: business_strategy / innovation / corporate_management / investment / entrepreneurship

**system_prompt の要点**:
- 【あなたの語り方】: 「技術を「事業としてスケールさせる方法」で語る」「「1000万ユーザーに広がったら何が起きるか」「10 年後どうなっているか」を毎回問う」「数字と比喩を使う」
- 【数字を出す時の絶対ルール】:
  - 「数字は必ず 2〜3 ステップの導出ロジックを添える。単独の値だけ言うのは禁止」
  - 悪例: 「ARR 100 億」「これは 10 兆円市場」— 根拠なしの単独数字は使わない
  - 良例: 「対象市場は 3000 億円、浸透率 3% と見て 90 億」「日本の中小 400 万社、月 1 万円で年 4800 億の TAM」
- 【発言スタイル】: 「大胆な仮説を 1 つ提示し、数字と根拠 (2〜3 ステップ) を添える」「他者の同意と同じ中味に入らない。新しい切り口を一つ出す」

**feedback_history の現状**:
- self_avg 1.57, peer_avg 1.58 (直近セッション)
- 改善点: 「スケール構想は魅力的だった一方、初期MVPからどの条件でその規模へ伸ばすか、段階的な事業計画や単位経済の接続がやや粗かった」

### 4.10 matushita_kounosuke 🍿 松下幸之助 (`gpt-4.1`)

- **description**: 松下幸之助。ビジネス観点で議論できる
- **domain_tags**: business_management / corporate_strategy / organizational_development / innovation / customer_experience

**system_prompt の要点**:
- 【あなたの語り方】: 「技術の詳細ではなく「どう届けるか」「現場でどう使われるか」を語る」「抽象論より、現場での小さなエピソードや具体例で語る」「「使う人にとってどうか？」「教育も含めた導入は？」を毎回考える」「穏やかで親しみやすい語り口、時折大阪弁を混ぜる (「〜やと思います」「〜やないですか」)」
- 【発言スタイル】: 「具体の人・場面・数字をひとつ入れる」「強い同意・非難はしない。隣にいる者に追加の問いを投げる」

**feedback_history の現状**:
- self_avg 1.43, peer_avg 1.42 (直近セッション)
- 改善点: 「提案の実務妥当性は高かったが、運用コスト削減幅や定着率改善など、効果を測る定量化がもう一歩あると説得力が増す」

### 4.11 ロールの現状の問題

1. **10 ロールのうち Idea 議論で活用されるのは 6-7 ロール** (theorist / bird_eye / devil / implementer / experimentalist / literature / son_masayoshi / matushita_kounosuke)
2. **code_architect と code_reviewer は Idea 議論ではほぼ使われない** が role_manager には登録されている
3. **feedback_history が肥大化している** — 各ロールの YAML に 10+ セッション分の履歴が蓄積 (最新 10 件だけ保持、それ以前は圧縮ロジックがあるが機能しているかは要確認)
4. **observed_weaknesses が繰り返される** — feedback_context にプロンプト注入されるが、実際の発言改善に繋がる証拠はない
5. **口癖固定は解除済み** だが、代わりの「発言の起点」が明示されておらず、LLM がテンプレ的に対処する場合がある
6. **son_masayoshi の「数字は 2-3 ステップ」ルールは追加済み** だが、実運用ではまだ「ARR 100 億」のような単独数字が散見される (実際の実行時に守られているか要検証)
7. **matushita_kounosuke の大阪弁指示** が全ラウンドで繰り返されるため、他ロールとのトーン差が過度になる場面あり
8. **evaluation_criteria がロール毎に固定** で、動的な議論の質評価に使いにくい

---

## 5. 現状の問題点

### 5.1 これまで対策した 4 問題 (対策の詳細と、それでも残る症状)

#### 問題 1 (系): 議論が 1 つの具体例に落ちて戻れない

**対策 1A: PLANNING_PROMPT に 4 段構造を絶対遵守として書いた**
- 段階 1 (発散) / 段階 2 (比較評価) / 段階 3 (選択と具体化) / 段階 4 (統合とまとめ)
- 段階 2 で「1 案に絞り込む goal を書いてはいけない」と明示
- 「特定業務・特定製品に踏み込まない」を goal に必ず含めるよう指示
- **結果**: Planner の生成 goal 自体は「切り口 5 案」「長所 1 + 懸念 1」形式になったが、実行時に発言側で 1 案に閉じるのは防げていない

**対策 1B: BONUS_ROUND_GOAL_PROMPT に 4 択方式を導入**
- A: まだ触れていない角度 / B: 元テーマ接続 / C: 別業界展開 / D: 未議論案
- 「同じ具体例をさらに掘る goal は書かない」「〜をさらに深掘りする形は禁止」
- **結果**: bonus round の goal は多様になったが、実際の bonus round 発言では前のラウンドの流れを引きずる (§5.2 の Round 6-7 参照)

**対策 1C: Conductor._detect_narrowing の実装 (2026-07-13)**
- LLM で「1 業務・1 製品・1 シナリオ」への収束を判定
- narrowed=true なら NARROWING_PIVOT_INSTRUCTION を次ラウンドの pivot に注入
- **現状の不明点**:
  - 実運用のログで narrowing 判定が実際に発火しているか未検証
  - 発火しても、Agent が視野拡大指示を無視する場合があるのでは
  - 最終ラウンドで skip 仕様のため、5 ラウンド構成なら最後の遷移では働かない

#### 問題 2 (系): ロールの発言パターンが固定化

**対策 2A: 全ロールから感嘆 (「あ、壊れた」「それGPU乗るね」等) を削除**
- devil / theorist / implementer / experimentalist / literature の 5 ロールから 感嘆リスト行を削除

**対策 2B: 文頭固定禁止ルールを role_base_template.txt に共通追加**
- 「直前 2 回の自分の発言と同じ文頭 (例:「そもそも」「ちょっと待って」「一歩引くと」など) は避ける」
- 「「整理すると」「まとめると」「俯瞰すると」等のメタ発言は 3 回に 1 回まで。中身のあるアイデア・具体例・反例を優先する」

**対策 2C: 独自価値の明示**
- bird_eye: 「あなたは単なる司会者・整理役ではない。参加者が気付いていない『構造的な問題』を指摘するのが独自の価値」
- devil: 「反論の 3 パターン (前提崩し / エッジケース / スケール問題) — 毎回どれか一つを明示的に選ぶ」
- son_masayoshi: 「数字は必ず 2〜3 ステップの導出ロジックを添える」+ 悪例/良例

**現状の不明点**:
- 実運用ログで文頭が本当に多様化しているか未検証 (§5.2 では bird_eye の「一歩引くと」が Round 2, 4, 5 で 3 回出ている)
- devil の 3 パターン明示は実現しているか未検証 (§5.2 では「ちょっと待って」で 5 回始まっている)
- son_masayoshi の 2-3 ステップ導出ロジックは §5.2 では Round 3-5 で 3-4 ステップに従っている印象だが、Round 6-7 では「1兆円規模の事業群」「ARR1000億円級」のような単独数字が復活している

#### 問題 3: 収束判定が 0.75 で停滞

**対策 3A: CONVERGENCE_CHECK_PROMPT にスコア変化ルール強化**
- 「前回スコアが存在する場合、必ず前進 or 後退の理由を明記」
- 「前進なら +0.05 以上、後退なら -0.05 以上変化させる」
- 「安易に同じ値を返さない」「同じ値にする場合は理由を 1 文で明示」

**現状の不明点**:
- §5.2 の実運用ログでは Round 2-7 で **7 ラウンド連続で score=0.75** が続いている (2026-07-10 のログ、対策 3A 導入前のはずだが確認要)
- スコア変化ルールを追加しても、LLM が「安易に同じ値を返す」を無視しない保証がない
- 収束による早期終了はもう無効化済みのため、スコア自体の意味が薄い

#### 問題 4 (系): レポートの品質が低い

**対策 4A: _extract_hypotheses を LLM ベース化**
- 4 種の仮説 (因果 / 効果 / 価値 / リスク) を最低 3、最大 7 件抽出
- 失敗時は regex fallback (旧実装を保持)

**対策 4B: _generate_report を LLM ベース化**
- claude-sonnet-4-5 で自己完結レポートを生成
- 7 セクション: エグゼクティブサマリー / 主要アイデア / 最有望提案 (What/Why/How/Who/Where) / リスクと対策 / 検証方法 (or 実験計画) / 未解決 / 次のアクション
- 失敗時は旧テンプレ (7 セクション: 問題設定 / 洞察 / 骨格 / 仮説 / 実験計画 / 未解決 / 参考文献) に fallback

**対策 4C: Idea/Review 属性化**
- session_id に `_review` が含まれるかで verification_section_title を切り替え
- Idea = 「検証方法」 / Review = 「実験計画」

**現状の不明点**:
- §5.2 の実運用レポート (`20260710_172837_idea/report.md`) は **旧テンプレ形式** で出力されており、対策 4B の LLM ベースレポートが機能していない (fallback 発動している?)
- 仮説抽出も「(議論ログから仮説を抽出できませんでした)」で **fallback 経路** (Regex が空を返している)
- session_id の名称が不整合: report.md の Session は `20260710_172928_idea` だが、出力ディレクトリは `20260710_172837_idea`

### 5.2 実際の出力サンプル分析 (`output/20260710_172837_idea/`)

**セッション概要**:
- テーマ: 「今後 AI がビジネスでどのように進化するかについて、多様な視点からアイデアを発展・深化し、具体的な未来像の切り口を広げること」
- 参加: 🧮 theorist / 🎯 bird_eye / 😈 devil / 🍿 matushita_kounosuke / 🐑 son_masayoshi
- 5 ロール × 5 計画ラウンド + 2 bonus round (計 7 ラウンド)
- 所要時間: 8 分 14 秒 / 収束度: 0.75

**症状 A: 議論の狭まり (Round 2 → 4 で経費精算に急速に閉じている)**

```
Round 1 (発散): 5 切り口を出す (検証付き反復AI / AI組織化 / AI責任境界 / 現場密着型 / エコシステム)
Round 2 (比較): 5 案を 3 層に分類 (安定して動く / 安心して任せる / 広く伸ばす)
  - devil: 「夜間の返金処理」具体例
  - matushita: 「メーカー現場の品質異常」具体例
  - devil: 「個人情報漏えい」具体例
Round 3 (選択): 「検証付き反復AI」に合意
  - theorist: 「請求書と発注書の突合」具体例
  - theorist: 「広告入稿」具体例
  - theorist: 「通関書類」具体例
  - son_masayoshi: 「補助金審査」「与信管理」具体例
Round 4 (深掘り): 「経費精算 MVP」に絞る
  - devil: 「商品マスタの分類ルール」具体例
  - bird_eye: 「失敗ログ台帳」提案
  - devil: 「領収書の日付誤読」具体例
Round 5 (まとめ): 「記録先行でまず 1 部署を回す」
  - theorist: 「月末の在庫引当みたいなレア事故」具体例
  - theorist: 「一次はルールで即決、境界だけ 2 人合議」
Bonus Round 6 (goal: 社会受容性フレームワーク設計):
  - devil: 「駅ナカの動的値付けで通勤客だけ毎朝高くなる」具体例
  - devil: 「採用面接の日程」具体例
  - matushita: 「炊飯器の保温機能」具体例
Bonus Round 7 (goal: 個別通知切替基準ガイドライン策定):
  - (Round 6 の続きで通知設計の詳細に閉じる)
```

**発見**: Round 3 以降、「経費精算」→「失敗ログ台帳」→「差分保存・理由 3 択・週次表示」→「境界案件の人戻し」と、細部に細部を重ねる形で狭まっている。Round 6-7 は bonus round の goal が「社会受容性フレームワーク」と別テーマだったにもかかわらず、「通知の粒度」に閉じてしまっている。

**症状 B: 収束スコアが 0.75 で 6 ラウンド連続で貼り付き**

```
Round 1: 0.70
Round 2: 0.75  ← +0.05
Round 3: 0.75
Round 4: 0.75
Round 5: 0.75
Round 6: 0.75  ← bonus round
Round 7: 0.75  ← bonus round
```

Round 3-7 で **完全に同値**。CONVERGENCE_CHECK_PROMPT に強化したルール導入前のログだが、
仮に導入しても LLM が「合意はできている、まだ完全ではない」を機械的に返し続ける可能性が高い。

**症状 C: ロール発言パターンの固定化**

- **bird_eye**: 「別の見方をすると/一歩引くと/そもそも」の 3 パターンで文頭を回している。Round 2 で「一歩引くと 5 案は…」、Round 4 で「一歩引くと 意見箱より…」、Round 5 で「別の見方をすると、今日は…」→ 文頭固定禁止ルール導入後でも解消しない可能性
- **devil**: 全 6-7 発言で「ちょっと待って、それ〇〇の場合どうなる？」で始まっている。感嘆「あ、壊れた」も Round 4, 7 で復活
- **son_masayoshi**: 「ARR 100 億円級」「1 兆円規模」「ARR 1000 億円級」「10 兆円市場」を根拠なしで連発 (2-3 ステップ導出ルール導入前のログ)
- **matushita_kounosuke**: 全発言で「〜ですわ」「〜やと思います」の大阪弁で語尾固定

**症状 D: レポートの品質不足**

`report.md` は **旧テンプレの 7 セクション形式**で出力されている:
```
# 🔬 AI Orchestra 技術検討レポート  ← 平凡タイトル (対策 4B で禁止したはず)
## 1. 問題設定
## 2. 技術的洞察   ← 各ラウンドの結論を丸ごとコピー (対策 4B で禁止)
## 3. 提案手法の骨格   ← plan.odsc.deliverable の丸出し
## 4. 仮説テーブル
(議論ログから仮説を抽出できませんでした)   ← 仮説抽出失敗
## 5. 実験計画
実験設計の詳細は議論ログ (full_conversation.md) を参照してください。 ← 実質空欄
## 6. 未解決問題
1. 夕方通知上限を固定するか現場ごとに可変にするか  ← 詳細不明
...
## 7. 参考文献
(議論中で引用された文献はありませんでした)
```

洞察欄が「【結論】切り口は 5 案で出そろった…【合意点】…【相違点】…【次論点】…」と、
ラウンド結論のフォーマットタグをそのまま含んでいる。これは REPORT_GENERATION_PROMPT で
「【結論】【合意点】【相違点】【次論点】のようなフォーマットタグを使わない」と禁止したが、
実際には旧テンプレ経由で出ているためタグが露出している。

**症状 E: summary.txt の「結論」欄が超長文**

```
━━ 結論 ━━

ObjectiveとDeliverableは概ね達成された。5つの切り口から出発し、相互フィードバックを通じて
「検証付き反復AI」に収束し、経費精算を初手業務とするMVP、失敗ログ台帳、差分保存・理由3択・
同種ミス週次表示、手修正率・再発防止率など、実装と運用に踏み込んだ議論ができている。
一方でSuccess Criteriaは完全達成までは至っていない。ビジネス規模はARR100億円級などの示唆は
出たが、1部署MVPからどの条件でその規模に伸ばすかの一貫した事業計画にまで接続し切れていない。
加えて、人戻し基準、レア案件の基準線、失敗ログ責任者などが未決のまま残り、
最終ラウンドでは通知最適化の設計に焦点が移って、単一案の最終統合像がやや拡散した。
したがって、収束度は高いが、成功条件を厳密に見ると『概ね達成・最終統合は未完』という評価が妥当である。
```

これは `orchestrator_eval.odsc_achievement.detail` をそのまま貼っているため。
summary.txt (プレーンテキスト) の想定用途 (「一目で結論がわかる」) に合っていない。

**症状 F: 表示名の破損**

`full_conversation.md` のヘッダ:
```
> 参加: 🧮 bird_eye 😈 matushita_kounosuke son_masayoshi
```

これは `_extract_emoji` の実装が正しく動いていない (bird_eye の絵文字が 🎯 でなく 🧮 になっている、
matushita_kounosuke に絵文字が付いていない)。表示バグ。

### 5.3 依然として残る課題 (対策済みだが未検証 or 未対策)

1. **議論の狭まりを実行時に本当に検知できているか未検証** (`_detect_narrowing` のログ確認が必要)
2. **収束スコアの停滞は §5.2 で明確** — 対策 3A で完全解消するか懐疑的
3. **ロール発言パターンの固定化は「口癖を消した」だけで、代替の起点が明示されていない** — 「文頭を固定するな」だけでは LLM は別のパターンに固定するだけ
4. **レポート生成が LLM 経路でなく fallback (旧テンプレ) に落ちている可能性** — なぜ fallback するのか原因調査が必要
5. **仮説抽出が高頻度で失敗** — LLM 経路で 0 件が返る、あるいはパース失敗している
6. **summary.txt の「結論」が超長文** — orchestrator_eval.detail を短くする、または要約プロンプトを分離する必要
7. **表示名破損** — bird_eye が 🧮 と表示されるなど、絵文字マッピングのバグ
8. **AgreementDetector と EXCESSIVE_AGREEMENT_INSTRUCTION が定義済みだが未使用** — 実装漏れ
9. **round_summaries が生成されているが Agent プロンプトで積極活用されていない** — Layer 5 で使うが、`total_estimate < max_context_tokens` の間は生の履歴が優先されるため
10. **Bonus round の goal がテーマから逸脱** (§5.2 の Round 6 「社会受容性」は元テーマ「AI がビジネスでどう進化するか」と接続薄い)
11. **feedback_context がプロンプトで注入されるが、実際の発言改善に繋がる証拠なし** — 「改善点」を書いても、それをどう体現するかを Agent は理解しない
12. **evaluation の同調圧力** — 全員が 4.5-5.0 になり、実質的な差別化が peer_evaluation で起きていない
13. **session_id の不整合** — Idea Discussion 内で session_id が 2 回生成されているのでは (report.md と ディレクトリ名がずれている)
14. **Idea モードで code_architect / code_reviewer が候補に入ってしまう可能性** — role_manager の domain フィルタが未実装 or 弱い

---

## 6. 改善候補と Claude への質問

### 6.1 優先度別の質問リスト

**優先度 1 (最重要)**:

Q1. §5.2 の症状 D (レポート出力が LLM 経路でなく旧テンプレ経路になっている件) について、
考えられる原因を挙げてください。特に、以下 3 点を確認したい:
   - `Synthesizer._generate_report` の `_is_llm_report_usable(content)` が false になる典型パターンは?
   - `claude-sonnet-4-5` に max_tokens=2500 で REPORT_GENERATION_PROMPT (log ~3000 tokens 込み) を渡した時に、
     完全な Markdown レポートが返ってこない状況はどんな時か
   - 旧テンプレ経路の出力にどうして「【結論】...【合意点】...」タグが露出しているか

Q2. §5.2 の症状 A (議論の狭まり) について、
`_detect_narrowing` の判定プロンプト (§3.4) が本当に「経費精算に閉じている」を
narrowed=true と判定するか、以下ラウンド末発言で判定してみてください。
判定精度が不十分ならプロンプト改良案を提示してください:
```
theorist: 仮決めなら見直し型かな。請求書と発注書の突合みたいに検証器を置ける業務だと...
son_masayoshi: 見直し型は導入初年度からコスト削減効果が見えるのが強い。例えば契約書チェックや広告入稿の承認業務に展開すれば...
theorist: 横展開するなら、生成器は共通で検証器だけ差し替える形が美しい...
```

Q3. §5.2 の症状 B (収束スコア停滞) について、
CONVERGENCE_CHECK_PROMPT (§3.3) に「+0.05 以上変化」を強制しても、
LLM が「同水準の理由」欄を毎回書いてスコア維持することはあり得るか?
根本的にスコアではなく「議論の進み方の性質」を出力させるプロンプト設計に切り替える提案があるか?

**優先度 2 (品質改善)**:

Q4. §5.2 の症状 C (ロール発言パターンの固定化) について、
「文頭を固定するな」というネガティブ指示だけで解決するか?
以下代替案の妥当性を評価してほしい:
  - (a) 発言の冒頭タイプ (質問 / 主張 / 反論 / 具体例 / 数字 / 引用) を毎回ランダムに指定する
  - (b) 直近の自分の発言 2 件を参照して「同じ冒頭タイプを避ける」と Agent 内部で判定
  - (c) 「口癖」自体は残すが、その頻度を Conductor が監視して過剰時のみ介入

Q5. Ideaディスカッションでのロール構成として、現状の 10 ロール (theorist / bird_eye / devil / implementer / experimentalist / literature / son_masayoshi / matushita_kounosuke + code_architect / code_reviewer)
は、5 人の議論に対して過剰か / 不足か? 何ロールがあれば十分か?
論点別に (技術 / ビジネス / 現場 / 反論者 / 俯瞰 / ...) のロール要件を提案してほしい。

Q6. §5.2 の症状 E (summary.txt 結論が超長文) について、
`_generate_summary` の中に「結論を 100 字以内で要約する」LLM 呼び出しを追加すべきか、
それとも `orchestrator_evaluation` の detail 自体を短くすべきか?

**優先度 3 (アーキテクチャ)**:

Q7. Agent の Layer 1-10 構造 (§2.3) は 10 層で肥大している。
特に Layer 4 (ODSC extras) / Layer 5 (previous summary) / Layer 6 (forbidden examples) / Layer 8 (recent flow) は
情報の重複がある。整理案を提案してほしい。

Q8. Conductor から LLM 呼び出しが 1 ラウンドあたり最低でも 5 回発生する
(発言 N + 結論 1 + 収束判定 1 + goal 判定 1 + 狭まり判定 1 + 禁止例抽出 1 (次ラウンド用) = N+5)。
7 ラウンドで 100 回近い LLM 呼び出しが 1 セッションで発生する。
以下観点で削減 or 統合の余地はあるか:
  - 収束判定 + goal 判定 + 狭まり判定を 1 プロンプトに統合
  - 禁止例抽出は Round 3 以降のみ (Round 2 では前ラウンドが 1 つしかない)
  - Bonus round はスキップして、代わりに Round 数を Planner に多めに書かせる

Q9. `_run_free_talk` は最大 8 発言だが、次発言者選定 (`DynamicOrder.decide_next_speaker_with_handoff`) が
1 発言あたり 1 LLM 呼び出しになっている。8 発言なら選定だけで 8 LLM。これは削減できるか?

**優先度 4 (将来検討)**:

Q10. 「同じテーマを 2 回目に議論する」ケース (follow_up_id 指定時) では、
前回の未解決問題を強く意識するプロンプト設計が必要。現状の実装 (§2.5 の `follow_up_context`) は
Orchestrator の Planner にしか渡らず、Agent には反映されていない。改善案は?

Q11. 議論結果の「良さ」を客観的に測る指標は何か? 現状は
    - 収束スコア (自己申告的、あてにならない)
    - orchestrator_evaluation.overall_discussion_quality (1-5 の自己評価)
    - per_agent の self/peer_avg (同調圧力で高得点になりがち)
これらに代わる、または追加する指標があるか?
(例: 議論ログ内での固有名詞・具体例の多様性 / 反例の数 / 数字の根拠付き比率など)

Q12. 現状の 5 ロール × 5 ラウンドで生成される議論ログは 3000-6000 tokens。
これを Claude に「良い / 悪い」評価してもらう自動評価パイプラインを作れば、
プロンプト改良の効果を数値化できる。実装優先度は?

### 6.2 特に見てほしい観点

1. **プロンプトの階層構造**: PLANNING_PROMPT が 4 段構造を書き、ROUND_CONCLUSION_INSTRUCTION がフォーマットタグを強制し、REPORT_GENERATION_PROMPT がフォーマットタグを禁止する — 相互に矛盾していないか?
2. **Agent の Layer 構造の情報密度**: Layer が増えるほど後段 (Layer 9-10) の指示が薄れないか? 特に Layer 9 (additional_instruction) の pivot 指示が Agent に届く割合は?
3. **収束スコアと goal 達成度の関係**: 収束スコアと goal 達成度は独立の指標だが、実装上は互いに影響しあっている。どちらか一方に統合できないか?
4. **フォールバック経路の存在感**: `_extract_hypotheses` と `_generate_report` は fallback を持つが、
   fallback が動いた時のログ出力が warning レベルで、実運用で気付きにくい。可視化の改善は?

### 6.3 実際に修正するファイル (改善方針決定後の作業対象)

- **プロンプト系** (影響大、テスト影響あり):
  - `config/prompts/planning_prompt.txt` + `core/orchestrator.py` `PLANNING_PROMPT`
  - `core/conductor_prompts.py` (ROUND_CONCLUSION / NARROWING / PIVOT / BONUS_ROUND / GOAL_COMPLETION)
  - `core/convergence.py` (CONVERGENCE_CHECK / REPETITION_CHECK / AGREEMENT_CHECK)
  - `core/synthesizer.py` (REPORT_GENERATION / HYPOTHESIS_EXTRACTION / ORCHESTRATOR_EVALUATION)
  - `core/memory.py` (FORBIDDEN_EXAMPLES)
  - `core/agent.py` (AGENT_BASE_ATTITUDE / DIVERSITY_RULE)

- **ロール系** (影響中、feedback_history 圧縮に注意):
  - `config/roles/*.yaml` × 10
  - `config/role_base_template.txt`

- **ロジック系** (影響小〜中、テスト 603 個の影響あり):
  - `core/conductor.py` (`_detect_narrowing` / `_check_and_complete_goal` / bonus round loop)
  - `core/synthesizer.py` (`_generate_report` / `_extract_hypotheses` / `_generate_summary`)
  - `core/evaluator.py` (evaluate_combined)

- **設定系** (影響小):
  - `config/settings.yaml` (convergence.default_threshold / stagnation_window / speaking_rules)

### 6.4 参照すべき既存ドキュメント

- `doc/architecture.md` — レイヤ構造・依存関係
- `doc/patterns.md` — 実装パターン集
- `doc/api-reference.md` — API 呼び出し規約
- `doc/data-models.md` — dataclass 定義
- `doc/prompts-catalog.md` — プロンプト一覧
- `doc/design/*` — 詳細設計書

---

*このドキュメントは 2026-07-13 時点の実装をもとに作成されました。
改善方針が決まったら、`doc/proposals/idea_discussion_v2.md` として次期改善案を記述する想定です。*

