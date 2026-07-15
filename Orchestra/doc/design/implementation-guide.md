# AI Orchestra — Implementation Guide

> この文書は GitHub Copilot がコーディングを進めるための実行指示書です。
> 設計の詳細は `Orchestra/doc/` 配下の設計書を参照してください。

---

## 設計書の参照マップ

実装時に参照すべき設計書の対応表:

| 実装対象 | 参照する設計書 | 特に見るべきセクション |
|---|---|---|
| `core/exceptions.py` | なし（シンプルな定義） | — |
| `core/config_loader.py` | `17_settings.md` | 全体 |
| `core/api_client.py` | `02_api_specification.md` | §2.1-2.7 |
| `core/rate_tracker.py` | `15_error_handling.md` | §15.4 |
| `core/time_keeper.py` | `10_turn_management.md` | §10.2 |
| `core/turn_calculator.py` | `10_turn_management.md` | §10.1, §10.3 |
| `core/role_manager.py` | `07_role_definitions.md` | §7.1, §7.4 |
| `core/agent.py` | `06_agent.md` | 全体 |
| `core/memory.py` | `08_memory_context.md` | 全体 |
| `core/orchestrator.py` | `04_orchestrator.md` | 全体 |
| `core/conductor.py` | `05_conductor.md` | 全体 |
| `core/evaluator.py` | `09_evaluation_feedback.md` | §9.1, §9.2 |
| `core/synthesizer.py` | `09_evaluation_feedback.md` + `14_output_format.md` | §9.3 + §14.4-14.7 |
| `core/feedback.py` | `09_evaluation_feedback.md` | §9.4, §9.5 |
| `core/follow_up.py` | `13_follow_up.md` | 全体 |
| `core/output_generator.py` | `14_output_format.md` | 全体 |
| `core/intervention.py` | `05_conductor.md` | §5.7 |
| `features/idea_discussion.py` | `11_idea_discussion.md` | 全体 |
| `features/code_review.py` | `12_code_review.md` | 全体 |
| `display/*.py` | `16_cli_interface.md` | §16.4, §16.5 |
| `main.py` | `16_cli_interface.md` | §16.1, §16.2 |
| `config/settings.yaml` | `17_settings.md` | 全体（そのまま使う） |
| `config/roles/*.yaml` | `99_appendix.md` | 付録A（そのまま使う） |
| `config/scenarios/*.yaml` | `99_appendix.md` | 付録I（そのまま使う） |
| `tests/mocks/mock_api.py` | `18_roadmap.md` | §18.5 |

---

## 実装順序（依存関係に基づく）

以下の順番で実装すること。各タスクは前のタスクに依存する。

```
Phase A: 基盤（他の全てが依存）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A-1. core/exceptions.py
A-2. config/settings.yaml
A-3. core/config_loader.py
A-4. tests/mocks/mock_api.py

Phase B: API + 時間管理
━━━━━━━━━━━━━━━━━━━━━━
B-1. core/rate_tracker.py
B-2. core/api_client.py
B-3. core/time_keeper.py
B-4. core/turn_calculator.py

Phase C: エージェント基盤
━━━━━━━━━━━━━━━━━━━━━━━━
C-1. core/role_manager.py
C-2. config/roles/*.yaml (8ファイル)
C-3. core/memory.py
C-4. core/agent.py

Phase D: 3フェーズエンジン
━━━━━━━━━━━━━━━━━━━━━━━━━
D-1. core/orchestrator.py
D-2. core/conductor.py
D-3. core/evaluator.py
D-4. core/synthesizer.py

Phase E: 統合 + 出力
━━━━━━━━━━━━━━━━━━━
E-1. core/feedback.py
E-2. core/output_generator.py
E-3. core/intervention.py
E-4. features/idea_discussion.py

Phase F: 追加機能
━━━━━━━━━━━━━━━━
F-1. core/follow_up.py
F-2. features/code_review.py
F-3. config/scenarios/*.yaml

Phase G: CLI + 表示
━━━━━━━━━━━━━━━━━━
G-1. display/plan_display.py
G-2. display/discussion_display.py
G-3. display/progress_display.py
G-4. display/completion_display.py
G-5. main.py
```

---

## 各タスクの実装指示

### A-1. core/exceptions.py

**参照**: なし（独自定義）
**依存**: なし
**テスト**: 不要（定義のみ）

```
実装内容:
- OrchestraError (基底例外)
- OrchestraAPIError(OrchestraError)
- ModelNotFoundError(OrchestraAPIError) — model: str 属性
- AuthenticationError(OrchestraAPIError) — is_rate_limit: bool 属性
- RateLimitExhaustedError(OrchestraAPIError)
- EmptyResponseError(OrchestraAPIError)
- MaxRetriesExceededError(OrchestraAPIError)
- TimeoutError(OrchestraAPIError)
- ServerError(OrchestraAPIError) — status_code: int, retryable: bool
- RoleNotFoundError(OrchestraError)
- RoleValidationError(OrchestraError)
- SessionNotFoundError(OrchestraError)
- InputTooShortError(OrchestraError)
- InputTooLongError(OrchestraError)
- ChainTooDeepError(OrchestraError)
- ConfigLoadError(OrchestraError)
```

---

### A-2. config/settings.yaml

**参照**: `Orchestra/doc/17_settings.md` をそのまま使う
**依存**: なし
**テスト**: 不要

```
実装内容:
- 17章の完全版 settings.yaml をそのままコピー
```

---

### A-3. core/config_loader.py

**参照**: `Orchestra/doc/17_settings.md`, `Orchestra/doc/02_api_specification.md` §2.7
**依存**: A-2 (settings.yaml)
**テスト**: tests/unit/test_config_loader.py

```
実装内容:
- Settings dataclass (各セクションを属性として持つ)
- Settings.load(config_dir: Path) クラスメソッド
- .env ファイルパーサー（python-dotenv不要、独自実装）
- 環境変数の読み込み（KOTOBUDDY_*, AZURE_OPENAI_* フォールバック）
- 優先順位: CLI引数 > .env > 環境変数 > settings.yaml デフォルト
- get_timeout(model: str) → int
- get_level_time(level: str, model: str) → float
- get_expertise_config(level: str) → dict
```

---

### A-4. tests/mocks/mock_api.py

**参照**: `Orchestra/doc/18_roadmap.md` §18.5
**依存**: なし
**テスト**: 不要（テスト用ユーティリティ）

```
実装内容:
- MockAPIClient クラス
  - __init__(responses: list[dict] | None)
  - async call(model, messages, **kwargs) → dict
  - call_log: list[dict]
  - call_count: int (property)
  - mode: str = "openai"
  - assert_called_with_model(model)
  - assert_call_count(expected)
  - assert_no_temperature()
  - assert_no_max_tokens()
```

---

### B-1. core/rate_tracker.py

**参照**: `Orchestra/doc/15_error_handling.md` §15.4
**依存**: A-1 (exceptions)
**テスト**: tests/unit/test_rate_tracker.py

```
実装内容:
- RateLimitTracker dataclass
  - daily_limit: int = 10000
  - safety_margin: float = 0.9
  - request_count: int
  - last_reset: date
  - persistence_path: Path
  - __post_init__() → ファイルから復元
  - increment(n: int = 1)
  - remaining() → int
  - can_proceed(estimated_requests: int) → bool
  - utilization() → float
  - _check_reset() → 日付変わりでリセット
  - _save() / _load() → JSON永続化
```

---

### B-2. core/api_client.py

**参照**: `Orchestra/doc/02_api_specification.md` 全体, `Orchestra/doc/15_error_handling.md` §15.1-15.3
**依存**: A-1, A-3, B-1
**テスト**: tests/unit/test_api_client.py

```
実装内容:
- detect_mode(endpoint: str, explicit_mode: str | None) → str
- RetryConfig dataclass
- RetryHandler クラス
  - execute_with_retry(func, *args, **kwargs)
  - _calculate_delay(attempt) → exponential backoff + jitter
- FallbackManager クラス
  - FALLBACK_CHAIN 定義
  - get_fallback(model) → str | None
  - call_with_fallback(api_client, model, **kwargs)
- EmptyResponseHandler クラス
  - handle_empty_response(params, api_client)
- ResilientAPIClient クラス
  - __init__(base_client, rate_tracker, retry_config, fallback_manager)
  - mode: str (自動判定)
  - async call(model, messages, **kwargs) → dict
  - async call_raw(model, messages, **kwargs) → dict (フォールバックなし)
  - _build_params(model, messages, **kwargs) → dict
  - _is_gpt5_series(model) → bool
  - _is_claude_thinking(model) → bool
  - _classify_error(exception, model) → 適切な例外型
```

---

### B-3. core/time_keeper.py

**参照**: `Orchestra/doc/10_turn_management.md` §10.2
**依存**: A-1
**テスト**: tests/unit/test_time_keeper.py

```
実装内容:
- TimePressure Enum (RELAXED, MODERATE, URGENT, CRITICAL)
- TimeKeeper dataclass
  - time_limit_sec, phase1_actual_sec, phase3_reserve_sec, safety_margin
  - start_time, round_times
  - elapsed → float (property)
  - discussion_budget → float (property)
  - discussion_elapsed → float (property)
  - remaining → float (property)
  - pressure → TimePressure (property)
  - can_start_next_round(estimated_round_sec) → bool
  - record_round(duration_sec)
  - get_moving_average(window=3) → float
  - force_conclude() → bool
```

---

### B-4. core/turn_calculator.py

**参照**: `Orchestra/doc/10_turn_management.md` §10.1, §10.3
**依存**: A-3 (settings)
**テスト**: tests/unit/test_turn_calculator.py

```
実装内容:
- LEVEL_TIME_MAP 定数
- CONDUCTOR_OVERHEAD_PER_ROUND 定数
- CONVERGENCE_CHECK_TIME 定数
- TurnCalculator クラス
  - calculate_round_time(round_config: RoundConfig) → float
  - calculate_total_time(plan: DiscussionPlan) → float
  - fits_in_budget(plan, time_limit) → bool
  - estimate_utterance_time(model, level) → float
- DynamicPlanAdjuster クラス
  - adjust_for_time_overrun(plan, completed_rounds, time_keeper) → list[RoundConfig]
  - _downgrade_level(level) → str
  - _recalculate_budget(rc, new_level, remaining_time, remaining_rounds) → float
```

---

### C-1. core/role_manager.py

**参照**: `Orchestra/doc/07_role_definitions.md` §7.1, §7.4
**依存**: A-1, A-3
**テスト**: tests/unit/test_role_manager.py

```
実装内容:
- RoleManager クラス
  - __init__(roles_dir: Path)
  - _cache: dict[str, dict]
  - load_role(role_id: str) → dict
  - list_available_roles() → list[dict] (サマリ)
  - _validate_role(role: dict) → None or raise
  - REQUIRED_FIELDS 定数
```

---

### C-2. config/roles/*.yaml

**参照**: `Orchestra/doc/99_appendix.md` 付録A をそのまま使う
**依存**: なし
**テスト**: 不要

```
作成ファイル:
- theorist.yaml
- experimentalist.yaml
- implementer.yaml
- literature.yaml
- devil.yaml
- bird_eye.yaml
- code_architect.yaml
- code_reviewer.yaml
```

---

### C-3. core/memory.py

**参照**: `Orchestra/doc/08_memory_context.md` 全体
**依存**: A-1, B-2 (api_client)
**テスト**: tests/unit/test_memory.py

```
実装内容:
- ConversationMemory クラス
  - __init__(api_client, max_context_tokens=5000, summary_model="gpt-4.1")
  - full_log: list[dict]
  - round_summaries: list[str]
  - total_tokens, total_requests
  - add_utterance(utterance, round_num)
  - add_system_event(event, round_num)
  - get_round_utterances(round_num) → list[dict]
  - get_last_utterance(round_num) → dict | None
  - get_context_for_agent(current_round, agent_role_id, context_budget) → dict
  - get_full_log_text() → str
  - get_context_summary() → str
  - async summarize_round(round_log)
  - export_json() → dict
- ContextBudget クラス
  - MODEL_LIMITS 定数
  - __init__(model, level)
  - estimate_tokens(text) → int
  - fits(system_prompt, user_message) → bool
  - trim_to_fit(system_prompt, user_message) → str
```

---

### C-4. core/agent.py

**参照**: `Orchestra/doc/06_agent.md` 全体
**依存**: A-1, B-2, C-1, C-3
**テスト**: tests/unit/test_agent.py

```
実装内容:
- AgentConfig dataclass (docs/data-models.md 参照)
- Utterance dataclass (docs/data-models.md 参照)
- Agent クラス
  - __init__(config, role_definition, api_client, memory, settings)
  - async speak(round_context, additional_instruction="") → Utterance
  - async evaluate(discussion_log, all_agents) → dict
  - set_private_instruction(instruction)
  - set_feedback_context(context)
  - set_speaking_rules(rules)
  - _build_system_prompt() → str
  - _build_context_message(round_context, additional_instruction) → str
  - _build_api_params(system_prompt, user_message) → dict
  - _build_api_params_gpt5(system_prompt, user_message) → dict
  - _build_api_params_claude_thinking(system_prompt, user_message) → dict
  - _build_api_params_standard(system_prompt, user_message) → dict
  - _is_too_long(content) → bool
  - async _request_shorter(original_content, round_context) → str
  - _is_gpt5_series(model) → bool
  - _is_claude_thinking_model(model) → bool
- MAX_UTTERANCE_CHARS 定数
- CLAUDE_THINKING_BUDGET 定数
```

---

### D-1. core/orchestrator.py

**参照**: `Orchestra/doc/04_orchestrator.md` 全体
**依存**: A-1, B-2, B-4, C-1, E-1(feedback — 循環を避けるためインターフェースのみ参照)
**テスト**: tests/unit/test_orchestrator.py

```
実装内容:
- OrchestraPlan, ODSC, DiscussionPlan, RoundConfig, PrivateInstruction dataclass
- Orchestrator クラス
  - __init__(api_client, role_manager, feedback_manager, settings)
  - async plan(user_input, model, level, time_limit_sec, max_agents, expertise, follow_up_context, scenario) → OrchestraPlan
  - _build_planning_prompt(user_input, roles, settings, follow_up, scenario) → str
  - _parse_plan_response(response_content) → OrchestraPlan
  - _validate_plan(plan, time_limit) → OrchestraPlan (時間内か検証)
- PLANNING_PROMPT テンプレート文字列
```

---

### D-2. core/conductor.py

**参照**: `Orchestra/doc/05_conductor.md` 全体, `Orchestra/doc/10_turn_management.md` §10.4
**依存**: A-1, B-2, B-3, C-3, C-4, D-1(型定義)
**テスト**: tests/unit/test_conductor.py

```
実装内容:
- DiscussionLog, RoundLog, ConvergenceResult dataclass
- ConvergenceChecker クラス
  - async check(round_log, plan, memory) → ConvergenceResult
  - should_terminate(result, threshold) → bool
  - is_stagnating(window=3, tolerance=0.05) → bool
- RepetitionDetector クラス
  - async check_repetition(recent_utterances, window=4) → dict
- AgreementDetector クラス
  - async check_excessive_agreement(recent_utterances, window=3) → bool
- SpeakingOrder (Fixed, Dialectic, Shuffle, Dynamic)
- Conductor クラス
  - __init__(api_client, agents, memory, time_keeper, intervention, settings, model)
  - async run_discussion(plan) → DiscussionLog
  - async run_round(round_config, plan) → RoundLog
  - async _run_one_shot(round_config, plan) → list[Utterance]
  - async _run_ping_pong(round_config, plan) → list[Utterance]
  - async _run_free_talk(round_config, plan) → list[Utterance]
  - async _decide_next_speaker(speakers, context, counts) → str
  - async _handle_time_pressure(time_keeper, plan, current_round)
  - async _handle_early_convergence(score, threshold, current_round, plan)
  - async _handle_stagnation(plan, discussion_log)
  - async _force_new_topic(detection_result, next_speaker, context) → str
  - async _handle_excessive_agreement(speakers, context) → str
  - _estimate_round_time(round_config) → float
```

---

### D-3. core/evaluator.py

**参照**: `Orchestra/doc/09_evaluation_feedback.md` §9.1, §9.2
**依存**: A-1, B-2, C-4
**テスト**: tests/unit/test_evaluator.py

```
実装内容:
- Evaluator クラス
  - __init__(api_client, settings)
  - async request_self_evaluation(agent, discussion_log, plan) → dict
  - async request_peer_evaluation(agent, other_agents, discussion_log) → dict
  - async request_combined_evaluation(agent, other_agents, discussion_log, plan) → dict
  - _build_self_eval_prompt(agent, log, plan) → str
  - _build_peer_eval_prompt(agent, others, log) → str
  - _parse_evaluation_response(content) → dict
- SELF_EVALUATION_PROMPT テンプレート
- PEER_EVALUATION_PROMPT テンプレート
```

---

### D-4. core/synthesizer.py

**参照**: `Orchestra/doc/09_evaluation_feedback.md` §9.3, `Orchestra/doc/14_output_format.md`
**依存**: A-1, B-2, D-3, E-1(feedback)
**テスト**: tests/unit/test_synthesizer.py

```
実装内容:
- SynthesisResult dataclass
- Synthesizer クラス
  - __init__(api_client, feedback_manager, settings)
  - async synthesize(plan, discussion_log, memory, agents, model, expertise, follow_up_context) → SynthesisResult
  - async _run_evaluations(agents, discussion_log, plan) → dict
  - async _generate_orchestrator_evaluation(evaluations, plan, log) → dict
  - async _generate_report(plan, log, evaluations, expertise) → str
  - async _generate_full_conversation(plan, log, memory) → str
  - async _generate_evaluation_md(evaluations) → str
  - async _generate_summary(plan, log, evaluations) → str
  - async _generate_vibe_prompt(findings, scan_result) → str (code_review用)
  - async _extract_hypotheses(log) → list[dict]
  - _generate_session_meta(plan, log, evaluations) → dict
- ORCHESTRATOR_EVALUATION_PROMPT テンプレート
- REPORT_GENERATION_PROMPT テンプレート
- HYPOTHESIS_EXTRACTION_PROMPT テンプレート
```

---

### E-1. core/feedback.py

**参照**: `Orchestra/doc/09_evaluation_feedback.md` §9.4, §9.5
**依存**: A-1, C-1 (role_manager)
**テスト**: tests/unit/test_feedback.py

```
実装内容:
- FeedbackManager クラス
  - __init__(roles_dir: Path, max_history: int = 10)
  - generate_feedback_context(role_id) → str
  - update_role_feedback(role_id, session_id, date, topic, self_eval, peer_avg, orchestrator_feedback)
  - should_reinforce_rules(role_id) → bool
  - _calculate_stats(history) → dict
  - _calculate_trend(scores) → str
  - _compress_old_entries(history) → list[dict]
  - _most_common_theme(items) → str
```

---

### E-2. core/output_generator.py

**参照**: `Orchestra/doc/14_output_format.md` 全体
**依存**: A-1
**テスト**: tests/unit/test_output_generator.py

```
実装内容:
- OutputGenerator クラス
  - __init__(output_dir: Path)
  - generate(session_id, plan, discussion_log, synthesis, memory) → Path
  - _write_session_meta(session_dir, meta)
  - _write_discussion_json(session_dir, plan, log, evaluations, synthesis)
  - _write_full_conversation(session_dir, content)
  - _write_report(session_dir, content)
  - _write_evaluation(session_dir, content)
  - _write_summary(session_dir, content)
  - _write_vibe_prompt(session_dir, content) — code_review時のみ
  - _generate_session_id(type: str) → str
```

---

### E-3. core/intervention.py

**参照**: `Orchestra/doc/05_conductor.md` §5.7
**依存**: なし
**テスト**: 不要（ABC + NoIntervention のみ）

```
実装内容:
- InterventionHandler (ABC)
  - check_intervention(round_num, context) → str | None
  - notify_progress(event, data) → None
- NoIntervention(InterventionHandler)
  - check_intervention → always None
  - notify_progress → pass
```

---

### E-4. features/idea_discussion.py

**参照**: `Orchestra/doc/11_idea_discussion.md` 全体
**依存**: core/ 全体
**テスト**: tests/integration/test_idea_discussion.py

```
実装内容:
- IdeaDiscussion クラス
  - __init__(api_client, role_manager, feedback_manager, settings)
  - async run(user_input, planner_model, conductor_model, synth_model, time_limit, max_agents, expertise, follow_up_id, attached_files, focus_hypotheses, output_dir) → Path
  - _validate_input(user_input) → str
  - _load_follow_up(session_id, attached_files, focus_hypotheses) → FollowUpContext | None
  - _detect_scenario(user_input) → dict | None
  - _confirm_execution(plan) → bool
  - _initialize_agents(plan) → dict[str, Agent]
  - _write_output(plan, log, synthesis, memory, output_dir) → Path
```

---

### F-1. core/follow_up.py

**参照**: `Orchestra/doc/13_follow_up.md` 全体
**依存**: A-1, B-2
**テスト**: tests/unit/test_follow_up.py

```
実装内容:
- FollowUpContext dataclass
- FollowUpManager クラス
  - __init__(output_dir: Path, api_client)
  - load_previous_session(session_id) → FollowUpContext
  - _extract_conclusion(session_dir) → str
  - _extract_hypotheses(report_path) → list[dict]
  - _extract_unresolved(report_path) → list[str]
  - async _compress_discussion(session_dir) → str
  - _extract_agent_info(session_dir) → tuple
- HypothesisManager クラス
  - VALID_TRANSITIONS 定数
  - apply_updates(hypotheses, updates, new_hypotheses) → list[dict]
  - generate_table_markdown(hypotheses) → str
- AttachmentProcessor クラス
  - MAX_FILES, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
  - process(file_paths) → list[dict]
```

---

### F-2. features/code_review.py

**参照**: `Orchestra/doc/12_code_review.md` 全体
**依存**: core/ 全体
**テスト**: tests/integration/test_code_review.py

```
実装内容:
- CodeReview クラス
  - async run(target_path, focus, planner_model, conductor_model, synth_model, time_limit, max_agents, ignore_patterns, output_dir) → Path
  - async _phase1_scan(target_path, planner_model, ignore_patterns) → ScanResult
  - async _phase2_investigate(scan_result, focus) → dict[str, list[dict]]
  - async _phase3_cross_question(findings) → dict
  - async _phase4_meeting(findings, conductor_model) → DiscussionLog
  - async _phase5_report(scan_result, findings, discussion_log, synth_model, output_dir) → Path
- FolderScanner クラス
  - scan(target_path, extra_ignores) → ScanResult
  - _walk_files(path, ignores) → Iterator[Path]
  - _read_header(file_path) → str
- FileChunker クラス
  - chunk_file(content, path) → list[dict]
- PartLeaderAssigner クラス
  - assign(scan_result, focus) → list[PartLeaderConfig]
- CrossQuestioner クラス
  - async run(findings, leaders) → dict
- FOCUS_PRESETS 定数
- INVESTIGATION_PROMPTS 定数 (6種)
```

---

### F-3. config/scenarios/*.yaml

**参照**: `Orchestra/doc/99_appendix.md` 付録I をそのまま使う
**依存**: なし

```
作成ファイル:
- algorithm_design.yaml
- experiment_planning.yaml
- paper_discussion.yaml
```

---

### G-1〜G-4. display/*.py

**参照**: `Orchestra/doc/16_cli_interface.md` §16.4, §16.5
**依存**: rich ライブラリ, core/ の型定義

```
G-1. display/plan_display.py
- PlanDisplay クラス
  - show(plan, rate_tracker)
  - confirm_execution() → bool

G-2. display/discussion_display.py
- DiscussionDisplay クラス
  - EMOJI_MAP
  - show_round_start(round_config, time_keeper)
  - show_utterance(utterance)
  - show_convergence(result)
  - show_orchestrator_memo(memo) — verbose時のみ

G-3. display/progress_display.py
- TimeDisplay クラス
  - start()
  - update(elapsed, remaining)
  - stop()

G-4. display/completion_display.py
- CompletionDisplay クラス
  - show_completion(output_path, statistics)
  - show_error(error, partial_output_path)
```

---

### G-5. main.py

**参照**: `Orchestra/doc/16_cli_interface.md` §16.1, §16.2
**依存**: features/, display/, core/config_loader

```
実装内容:
- typer app 定義
- idea コマンド (全オプション)
- review コマンド (全オプション)
- list-roles コマンド
- history コマンド
- replay コマンド
- role-stats コマンド
- _async_run_idea() 非同期ラッパー
- _async_run_review() 非同期ラッパー
```

---

## Copilot への指示テンプレート

各タスクを実装する際は、以下の形式で Copilot に指示してください:

### 新規モジュール作成時

```
@workspace
#file:docs/implementation-guide.md のタスク [タスクID] を実装してください。

設計の詳細は #file:Orchestra/doc/[該当章].md を参照してください。
データ型は #file:docs/data-models.md を参照してください。
実装パターンは #file:docs/patterns.md を参照してください。

まず Plan（実装するクラスとメソッドの一覧）を示し、確認後に実装してください。
```

### テスト作成時

```
@workspace
#file:core/[モジュール名].py のユニットテストを作成してください。

テスト方針は #file:docs/test-strategy.md を参照してください。
MockAPIClient は #file:tests/mocks/mock_api.py を使用してください。

Arrange / Act / Assert パターンで、各公開メソッドに少なくとも2ケース
（正常系 + エラー系）を書いてください。
```

### バグ修正時

```
@workspace
以下のエラーが発生しています:
[エラー内容]

#file:Orchestra/doc/15_error_handling.md を参照して、
適切なエラーハンドリングを実装してください。
```

---

## 完了基準

各タスクは以下を全て満たした時に「完了」とする:

```
□ 型ヒントが全 public メソッドに付いている
□ Google Style docstring が全 public メソッドに書かれている
□ 対応するユニットテストが存在しパスする
□ 既存テストが全てパスする (pytest tests/unit/)
□ 循環 import がない
□ 1ファイル300行以下
□ 1関数50行以下
□ マジックナンバーが存在しない
□ print() が使われていない
