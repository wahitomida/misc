# 第11章 機能①: 技術議論（アイデアブラッシュアップ）

---

## 11.1 実行フロー全体図

機能①は「研究テーマやアルゴリズムのアイデアについて、複数AIが多角的に議論し、技術的洞察・仮説・実験計画を導出する」機能です。

```
[ユーザー]
python main.py idea "点群のGNNで特徴量抽出する設計指針"
│
▼
┌──────────────────────────────────────────────────────────┐
│ IdeaDiscussion.run()                                      │
│                                                           │
│  ① 入力バリデーション                                      │
│     - テーマテキストの検証                                  │
│     - follow-up情報の読み込み (該当時)                      │
│     - 添付ファイルの読み込み (該当時)                       │
│                                                           │
│  ② シナリオテンプレート選定                                 │
│     - テーマからシナリオを推定                              │
│     - 明示指定があればそれを使用                            │
│                                                           │
│  ③ Phase 1: 計画立案                                       │
│     → Orchestrator.plan()                                 │
│     → ユーザー確認 (計画表示 + [Y/n])                      │
│                                                           │
│  ④ Phase 2: 議論進行                                       │
│     → Conductor.run_discussion()                          │
│     → 各ラウンドの進行 (発言取得, 収束判定, 時間管理)       │
│                                                           │
│  ⑤ Phase 3: 統合・評価                                     │
│     → Synthesizer.synthesize()                            │
│     → 評価・フィードバック                                 │
│     → レポート生成                                        │
│                                                           │
│  ⑥ 出力                                                   │
│     → output/{timestamp}_idea/ にファイル群を書き出し       │
│     → YAML フィードバック更新                              │
│     → CLI に完了表示                                       │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

### 実装クラス

```python
class IdeaDiscussion:
"""機能①: 技術議論の統合フロー"""

def __init__(
self,
api_client: ResilientAPIClient,
role_manager: RoleManager,
feedback_manager: FeedbackManager,
settings: Settings,
):
self.api_client = api_client
self.role_manager = role_manager
self.feedback_manager = feedback_manager
self.settings = settings

async def run(
self,
user_input: str,
planner_model: str = "gpt-5.4",
conductor_model: str = "gpt-4.1",
synth_model: str = "claude-sonnet-4-5",
time_limit: float = 300,
max_agents: int = 5,
expertise: str = "intermediate",
follow_up_id: str | None = None,
attached_files: list[Path] | None = None,
focus_hypotheses: list[str] | None = None,
output_dir: Path = Path("./output"),
) -> Path:
"""機能①の完全実行フロー。出力ディレクトリのPathを返す。"""

# ① 入力バリデーション
validated_input = self._validate_input(user_input)
follow_up_context = self._load_follow_up(follow_up_id, attached_files, focus_hypotheses)

# ② シナリオテンプレート選定
scenario = self._detect_scenario(validated_input)

# ③ Phase 1: 計画立案
orchestrator = Orchestrator(self.api_client, self.role_manager, self.feedback_manager, self.settings)
plan = await orchestrator.plan(
user_input=validated_input,
model=planner_model,
level="high",
time_limit_sec=time_limit,
max_agents=max_agents,
expertise=expertise,
follow_up_context=follow_up_context,
scenario=scenario,
)

# ユーザー確認
if not self._confirm_execution(plan):
return None

# ④ Phase 2: 議論進行
time_keeper = TimeKeeper(time_limit_sec=time_limit, phase1_actual_sec=plan.duration_sec)
memory = ConversationMemory(self.api_client)
agents = self._initialize_agents(plan)
conductor = Conductor(
self.api_client, agents, memory, time_keeper,
NoIntervention(), self.settings, model=conductor_model,
)
discussion_log = await conductor.run_discussion(plan)

# ⑤ Phase 3: 統合・評価
synthesizer = Synthesizer(self.api_client, self.feedback_manager, self.settings)
synthesis = await synthesizer.synthesize(
plan=plan,
discussion_log=discussion_log,
memory=memory,
agents=agents,
model=synth_model,
expertise=expertise,
follow_up_context=follow_up_context,
)

# ⑥ 出力
output_path = self._write_output(plan, discussion_log, synthesis, memory, output_dir)
return output_path
```

---

## 11.2 入力の受け取りとバリデーション

### バリデーションルール

```python
class InputValidator:
"""ユーザー入力の検証"""

MIN_LENGTH = 5        # 最低5文字
MAX_LENGTH = 5000     # 最大5000文字（あまりに長いとPhase1で非効率）
BLOCKED_PATTERNS = [
# Confidential A に該当しそうなキーワード（簡易チェック）
# ※ セキュリティ判断はユーザー責任だが、明らかなものは警告
]

def validate(self, user_input: str) -> str:
"""入力を検証し、整形して返す"""

# 空白トリム
cleaned = user_input.strip()

# 長さチェック
if len(cleaned) < self.MIN_LENGTH:
raise InputTooShortError(
f"入力が短すぎます ({len(cleaned)}文字)。5文字以上で入力してください。"
)

if len(cleaned) > self.MAX_LENGTH:
raise InputTooLongError(
f"入力が長すぎます ({len(cleaned)}文字)。5000文字以内に収めてください。"
f"詳細情報は --attach でファイル添付することを推奨します。"
)

return cleaned
```

### follow-up 情報の読み込み

```python
def _load_follow_up(
self,
session_id: str | None,
attached_files: list[Path] | None,
focus_hypotheses: list[str] | None,
) -> FollowUpContext | None:
"""follow-up情報を読み込み"""

if session_id is None:
return None

follow_up_manager = FollowUpManager(self.settings.output_dir)
context = follow_up_manager.load_previous_session(session_id)

# 添付ファイルの読み込み
if attached_files:
for file_path in attached_files:
if not file_path.exists():
raise FileNotFoundError(f"添付ファイルが見つかりません: {file_path}")
content = file_path.read_text(encoding="utf-8")
context.attached_files.append({
"name": file_path.name,
"content": content[:10000],  # 最大10000文字
})

# フォーカス仮説の設定
if focus_hypotheses:
context.focus_hypotheses = focus_hypotheses

return context
```

---

## 11.3 シナリオテンプレートの活用

シナリオテンプレートは、テーマの性質に応じた**議論の流れのヒント**を指揮者に提供します。指揮者はこのヒントを参考にしつつ、独自の判断で計画をカスタマイズします。

### シナリオの自動検出

```python
def _detect_scenario(self, user_input: str) -> dict | None:
"""テーマからシナリオを自動推定"""

scenarios_dir = self.settings.config_dir / "scenarios"
available = {
"algorithm_design": ["設計", "アルゴリズム", "手法", "アプローチ", "方式"],
"experiment_planning": ["実験", "検証", "比較", "ベンチマーク", "評価"],
"paper_discussion": ["論文", "paper", "手法の理解", "読み会", "サーベイ"],
}

input_lower = user_input.lower()
best_match = None
best_score = 0

for scenario_name, keywords in available.items():
score = sum(1 for kw in keywords if kw in input_lower)
if score > best_score:
best_score = score
best_match = scenario_name

if best_match and best_score >= 1:
scenario_path = scenarios_dir / f"{best_match}.yaml"
if scenario_path.exists():
return yaml.safe_load(scenario_path.read_text(encoding="utf-8"))

return None  # マッチしない場合はシナリオなしで計画
```

---

### 11.3.1 algorithm_design

```yaml
# config/scenarios/algorithm_design.yaml
scenario_id: algorithm_design
display_name: "アルゴリズム設計"
description: "新しいアルゴリズムや手法の設計を議論する"

suggested_flow:
- phase: "問題の定式化"
description: "入出力の数学的定義、制約条件の明確化"
recommended_speakers: ["theorist", "literature"]
pattern: "one_shot"
level: "medium"

- phase: "先行研究の整理"
description: "既存手法の長短、SOTAとの差分"
recommended_speakers: ["literature", "implementer"]
pattern: "one_shot"
level: "medium"

- phase: "提案手法の穴探し"
description: "前提の検証、反例の構築、限界の特定"
recommended_speakers: ["devil", "theorist"]
pattern: "ping_pong"
level: "medium"

- phase: "統合・設計決定"
description: "全視点を統合して手法の骨格を固める"
recommended_speakers: ["all"]
pattern: "free_talk"
level: "high"

- phase: "実験計画"
description: "検証方法、ベースライン、データセットの設計"
recommended_speakers: ["experimentalist", "implementer"]
pattern: "one_shot"
level: "medium"

recommended_agents:
must_have: ["theorist", "devil"]
nice_to_have: ["literature", "experimentalist", "implementer"]
optional: ["bird_eye"]

deliverable_format: "提案手法の骨格 + 実験計画"

odsc_hint:
objective_template: "{topic}における最適な設計選択を技術的に評価する"
success_criteria_template: "手法の骨格が合意され、検証すべき仮説が3つ以上明確になっていること"
```

---

### 11.3.2 experiment_planning

```yaml
# config/scenarios/experiment_planning.yaml
scenario_id: experiment_planning
display_name: "実験計画"
description: "実験の設計・条件設定・ベースライン選定を議論する"

suggested_flow:
- phase: "実験目的の明確化"
description: "何を検証するのか、仮説の整理"
recommended_speakers: ["experimentalist", "theorist"]
pattern: "one_shot"
level: "medium"

- phase: "条件設計"
description: "比較条件、ablation条件、データセット選定"
recommended_speakers: ["experimentalist", "literature"]
pattern: "ping_pong"
level: "medium"

- phase: "実装・リソース確認"
description: "計算リソース、実装可能性、所要時間の見積もり"
recommended_speakers: ["implementer", "experimentalist"]
pattern: "ping_pong"
level: "medium"

- phase: "穴探し・リスク確認"
description: "実験設計の穴、統計的妥当性、再現性リスク"
recommended_speakers: ["devil", "experimentalist"]
pattern: "ping_pong"
level: "medium"

- phase: "最終確認"
description: "実験計画書としてのまとめ"
recommended_speakers: ["all"]
pattern: "one_shot"
level: "low"

recommended_agents:
must_have: ["experimentalist", "implementer"]
nice_to_have: ["theorist", "devil", "literature"]
optional: ["bird_eye"]

deliverable_format: "実験設計書（条件、データ、指標、リソース、再現性チェックリスト）"

odsc_hint:
objective_template: "{topic}を検証するための再現可能な実験計画を設計する"
success_criteria_template: "比較条件、評価指標、計算リソースが具体的に定まっていること"
```

---

### 11.3.3 paper_discussion

```yaml
# config/scenarios/paper_discussion.yaml
scenario_id: paper_discussion
display_name: "論文議論"
description: "論文の手法を理解し、応用可能性や限界を議論する"

suggested_flow:
- phase: "手法の整理"
description: "論文の核心アイデアの要約と位置づけ"
recommended_speakers: ["literature", "theorist"]
pattern: "one_shot"
level: "medium"

- phase: "強みの分析"
description: "なぜこの手法が機能するか、理論的根拠"
recommended_speakers: ["theorist", "implementer"]
pattern: "one_shot"
level: "medium"

- phase: "限界と弱点"
description: "手法が破綻するケース、仮定の脆さ"
recommended_speakers: ["devil", "experimentalist"]
pattern: "ping_pong"
level: "high"

- phase: "応用可能性"
description: "自分の研究への適用、拡張の方向性"
recommended_speakers: ["all"]
pattern: "free_talk"
level: "high"

recommended_agents:
must_have: ["literature", "devil"]
nice_to_have: ["theorist", "experimentalist", "implementer"]
optional: ["bird_eye"]

deliverable_format: "技術的洞察一覧 + 応用アイデア + 限界の明確化"

odsc_hint:
objective_template: "{topic}の技術的本質を理解し、応用可能性と限界を評価する"
success_criteria_template: "手法の強み・弱みが明確で、自研究への具体的な応用案が1つ以上出ていること"
```

---

### 指揮者プロンプトへのシナリオ注入

```
【シナリオテンプレート（参考）】
以下はテーマに適したシナリオテンプレートです。これを参考にしつつ、
テーマ固有の事情を踏まえて独自にカスタマイズしてください。

シナリオ: {scenario.display_name}
推奨フロー:
{scenario.suggested_flow のフォーマット}

推奨メンバー:
- 必須: {scenario.recommended_agents.must_have}
- 推奨: {scenario.recommended_agents.nice_to_have}

※ これはあくまで参考です。テーマに応じて自由に変更してください。
```

---

## 11.4 議論中の会話制御

### 11.4.1 研究者向けの自然な会話トーン

settings.yaml で定義された会話スタイルを、全エージェントの発言ルールに反映します。

```yaml
# config/settings.yaml
conversation_style:
tone: "lab_discussion"
rules:
- "箇条書き禁止。会話調で。"
- "1発言1論点。複数論点あるなら分けて発言。"
- "他者の発言に言及してから自分の意見を述べる。"
- "「たしかに」「でもさ」「ちょっと待って」等の接続詞を自然に使う。"
- "データ引用は1発言に1つまで。"
- "ビジネス的観点(ROI, 市場等)は言及しない。"
- "数式はテキスト表現で自然に混ぜる。"
- "論文引用は(著者+年)で簡潔に。"
```

**良い発言の例**:

```
🧮: それを定式化すると、kNNグラフ上のmessage passingは
各ノードの近傍k個の特徴を集約する操作で、計算量O(Nk)になるね。

😈: ちょっと待って。kが固定ってことは密度不均一データで
疎な領域のノードが遠い点まで繋がるよね。それ意図した動作？

🔬: 実際ModelNet40で試した時、点数N=1024の均一サンプリングだから
その問題出てない可能性あるよ。ScanObjectNNで試すと顕在化するかも。
```

**悪い発言の例（これを生成させない）**:

```
❌ 「以下に3つの観点から分析します。
1. 計算量の観点: ...
2. 実装の観点: ...
3. 理論的限界の観点: ...
まとめると、...」
→ 論文調。長すぎ。1発言で3論点入れている。
```

---

### 11.4.2 数式の表現ルール

```yaml
# 数式ルール（全ロール共通で注入）
math_expression_rules:
format: "text"  # LaTeX でなくテキスト表現
examples:
- "O(N²)" ← OK
- "$O(N^2)$" ← NG (LaTeX記法は使わない)
- "∑_{i=1}^{N} x_i" ← OK (Unicode記号)
- "\\sum_{i=1}^{N}" ← NG (LaTeX記法)
- "N×k" ← OK
- "≤, ≥, ∈, ∀, ∃" ← OK (Unicode)
allowed_symbols:
- "∑, ∏, ∫, ∂, ∇"
- "∈, ∉, ⊂, ⊃, ∪, ∩"
- "≤, ≥, ≠, ≈, →, ↦"
- "∀, ∃, ∞"
- "α, β, γ, θ, λ, σ, μ"
max_formula_length: 30  # 1行30文字以上の数式は分けて書く
```

**system prompt への注入文**:

```
【数式の書き方】
- テキスト表現で自然に混ぜる。LaTeX記法（$...$や\\sum等）は禁止。
- 例: O(N log N), ∑_i x_i, h ∈ R^d, ∀ε>0
- 長い数式は避ける。必要なら「つまり〇〇の条件で△△が成立」のように自然言語で。
```

---

### 11.4.3 文献引用の正確性保証

📚 文献屋に限らず、全 AI が論文を引用する可能性があります。架空論文の引用は研究者にとって致命的であるため、複数の対策を講じます。

**対策1: system prompt での明示的指示**

```
【文献引用ルール（全員共通）】
- 論文を引用する場合は (著者+年) の形式で。
- 存在に確信がない論文には必ず [要確認] をつける。
- 「〇〇という研究があったはず [要確認]」の形式。
- 架空の論文を作り上げることは最も重大な違反。
- 知らない場合は「そこは知らない」と正直に言う。
```

**対策2: 出力時の [要確認] タグ検出**

```python
class CitationChecker:
"""引用の信頼性をチェック"""

UNCERTAIN_MARKERS = ["[要確認]", "[未確認]", "[citation needed]", "[要検証]"]

def extract_uncertain_citations(self, text: str) -> list[str]:
"""[要確認]タグ付きの引用を抽出"""
uncertain = []
for marker in self.UNCERTAIN_MARKERS:
if marker in text:
# マーカー周辺のテキストを抽出
for line in text.split("\n"):
if marker in line:
uncertain.append(line.strip())
return uncertain

def generate_warning(self, uncertain_citations: list[str]) -> str:
"""レポートに付加する警告文を生成"""
if not uncertain_citations:
return ""

warning = "\n\n⚠️ **以下の引用は実在確認が必要です:**\n"
for citation in uncertain_citations:
warning += f"- {citation}\n"
warning += "\n実際に論文を検索して確認してください。"
return warning
```

**対策3: report.md の参考文献セクションに警告を付加**

```markdown
## 8. 参考文献

- (Qi+2017) PointNet: Deep Learning on Point Sets. CVPR 2017.
- (Wang+2019) DGCNN: Dynamic Graph CNN. ToG 2019.
- (Wu+2024) Point Transformer V3. CVPR 2024.
- ⚠️ Mamba3D (2024, arXiv) [要確認] ← **実在確認が必要**
```

---

## 11.5 仮説テーブルの管理

### 11.5.1 仮説の構造（ID / 内容 / 状態 / 検証方法）

議論中に出た「検証すべきこと」を構造化して管理します。

```python
@dataclass
class Hypothesis:
"""仮説の構造"""
id: str                    # "H1", "H2", ...
hypothesis: str            # 仮説の内容
status: str                # "unverified" | "confirmed" | "rejected" | "modified"
verification_method: str   # どうやって検証するか
proposed_by: str           # 提案した AI の role_id
round_proposed: int        # 提案されたラウンド番号
note: str = ""             # 補足（確認/棄却時の理由等）
```

**仮説の生成タイミング**:

仮説は Phase 3 の統合時に、議論ログから抽出されます。

```python
HYPOTHESIS_EXTRACTION_PROMPT = """以下の議論ログから、検証すべき仮説を抽出してください。

【議論ログ】
{full_discussion_log}

【仮説の定義】
- 議論中に出た「こうではないか？」「これが成り立つなら〇〇」という主張
- 実験や追加調査で検証可能なもの
- 既に全員が同意している「事実」は仮説ではない

【出力形式 (JSON)】
{{
"hypotheses": [
{{
"id": "H1",
"hypothesis": "仮説の内容（1文）",
"status": "unverified",
"verification_method": "検証方法（1-2文）",
"proposed_by": "role_id",
"round_proposed": 2
}}
]
}}

最低3つ、最大7つ抽出してください。"""
```

---

### 11.5.2 未検証 / 確認済み / 棄却 の状態遷移

```
┌──────────────┐
│  unverified  │ ← 初期状態（議論で出た直後）
│      🔲      │
└──────┬───────┘
│
├── 実験で確認 ──→ ┌──────────────┐
│                   │  confirmed   │
│                   │      ✅      │
│                   └──────────────┘
│
├── 実験で否定 ──→ ┌──────────────┐
│                   │  rejected    │
│                   │      ❌      │
│                   └──────────────┘
│
└── 修正が必要 ──→ ┌──────────────┐
│  modified    │ → 新しい仮説 H1' として再登録
│      🔄      │
└──────────────┘
```

**follow-up 時の状態更新**:

```python
class HypothesisManager:
"""仮説テーブルの管理"""

def update_from_follow_up(
self,
previous_hypotheses: list[dict],
new_input: str,
focus_hypotheses: list[str],
) -> list[dict]:
"""follow-up時の仮説更新"""

updated = []
for h in previous_hypotheses:
if h["id"] in focus_hypotheses:
# フォーカスされた仮説は更新候補
h["_focused"] = True
updated.append(h)

return updated

def apply_updates(
self,
hypotheses: list[dict],
updates: dict[str, dict],
) -> list[dict]:
"""指揮者が決定した更新を適用"""

for h in hypotheses:
if h["id"] in updates:
update = updates[h["id"]]
h["status"] = update["new_status"]
h["note"] = update.get("note", "")

return hypotheses

def add_new_hypotheses(
self,
existing: list[dict],
new_ones: list[dict],
) -> list[dict]:
"""新規仮説を追加"""

# ID の採番（既存の最大ID + 1から）
max_id = self._get_max_id(existing)
for i, h in enumerate(new_ones):
if not h.get("id"):
h["id"] = f"H{max_id + i + 1}"

return existing + new_ones
```

---

## 11.6 最終レポートの生成（研究者向け構成）

Phase 3 で `claude-sonnet-4-5` (extended thinking, budget=16000) を使用して生成します。

### レポート生成プロンプト

```python
REPORT_GENERATION_PROMPT = """以下の議論ログと評価結果を基に、研究者向けの最終レポートを生成してください。

【ODSC】
{odsc}

【議論ログ全文】
{full_discussion_log}

【抽出された仮説テーブル】
{hypotheses}

【評価結果サマリ】
{evaluation_summary}

【レポート構成（この順で出力）】
1. 問題設定: 入出力の定義、制約条件
2. 技術的洞察: 議論から得られた知見（番号付きで3-7個）
3. 提案手法の骨格: アルゴリズムの概要（疑似コード or フロー）
4. 仮説テーブル: 検証すべきことの一覧
5. 実験計画: 条件、データ、指標、リソース
6. 未解決問題: 議論で解決しなかった論点
7. 参考文献: 議論中に言及された文献

【書き方のルール】
- 研究者が読む文書。過不足なく。
- 数式はテキスト表現 (O記法, Unicode記号)
- 各セクションは独立して読めるように
- 「次に何をすべきか」が明確になる書き方
- [要確認]タグ付きの引用はそのまま残す

出力: Markdown形式"""
```

---

### 11.6.1 問題設定

```markdown
## 1. 問題設定

### 入力
- 点群 P = {p_i} ∈ R^{N×3}, N = 10,000〜100,000

### 出力
- 点ごとの特徴ベクトル h_i ∈ R^d（セグメンテーション用）
- またはグローバル特徴 h ∈ R^d（分類用）

### 求められる性質
- 置換不変/等変性（点の順序に依存しない）
- 局所幾何の捕捉（曲率、法線方向等）
- 密度不均一への頑健性
- 計算スケーラビリティ（N=10万でも実用時間内）
```

---

### 11.6.2 技術的洞察

```markdown
## 2. 技術的洞察（議論から得られた知見）

### 洞察①: kNN vs radius graph
kNNグラフの方がmanifold上の測地距離近似として理論的に自然。
密度不均一でもmanifold上で局所的に等距離な点を結ぶ性質を持つ。
radius graphは孤立ノードやdense接続の問題がある。

**ただし**: manifold仮定が成り立たない箇所（CADのエッジ・角）では
kNNも破綻する → multi-scale (k=10,20,40) で対応。

### 洞察②: WL-testの限界は実用上問題にならない
（内容...）

### 洞察③: Positional Encoding の選択はユースケース依存
（内容...）
```

---

### 11.6.3 提案手法の骨格

```markdown
## 3. 提案手法の骨格

```
Input: P ∈ R^{N×3}
│
├── Multi-scale kNN Graph Construction
│     k ∈ {10, 20, 40}
│     各スケールで独立にグラフ構築
│
├── 相対位置エンコーディング
│     e_ij = MLP(p_j - p_i || ||p_j - p_i||)
│
├── EdgeConv Layers (×4)
│     h_i = max_{j∈N(i)} MLP(h_j - h_i || h_i)
│     各スケールのメッセージを concat → MLP で統合
│
├── Global Pooling (分類) or Per-point MLP (セグメンテーション)
│
Output: h ∈ R^d or H ∈ R^{N×d}
```

**計算量**: O(Nk·L) where k=40(max), L=4(層数)
```

---

### 11.6.4 仮説テーブル

```markdown
## 4. 仮説テーブル

| ID | 仮説 | 状態 | 検証方法 |
|---|---|---|---|
| H1 | multi-scale kNNは単一kより密度不均一データで精度向上する | 🔲 未検証 | ScanObjectNNでk=20 vs multi-scale比較 |
| H2 | 相対位置PEはspectral PEと同等性能でリアルタイム処理可能 | 🔲 未検証 | ModelNet40でPE種別のablation |
| H3 | GNNはTransformerよりメモリ効率が良い（N>5万で顕著） | 🔲 未検証 | N=1万〜10万でメモリ・速度計測 |
| H4 | kの値に対する精度の感度は小さい（k±5で精度変化<0.5%） | 🔲 未検証 | k=15,20,25でablation |
| H5 | manifoldの角・エッジ部でmulti-scaleが単一scaleより効く | 🔲 未検証 | CADデータセットでの定性+定量評価 |
```

---

### 11.6.5 実験計画

```markdown
## 5. 実験計画

### 5.1 比較条件
| 因子 | 水準 |
|---|---|
| グラフ構築 | kNN(k=20) / radius(r=0.1) / multi-scale(k=10,20,40) |
| PE | なし / spectral(k=32) / random walk / 相対位置 |
| GNN層 | GCN / GAT / EdgeConv |

### 5.2 ベースライン
- PointNet++ (MSG)
- Point Transformer V3
- DGCNN

### 5.3 データセット
- ModelNet40（合成, 12,311サンプル）
- ScanObjectNN（実スキャン, 密度不均一）
- ShapeNetPart（パーツセグメンテーション用）

### 5.4 評価指標
- Overall Accuracy (OA)
- Mean Class Accuracy (mAcc)
- 推論 latency (ms/sample, batch=32)
- GPU メモリ使用量 (MB)

### 5.5 計算リソース見積もり
- 108 run × 約200epoch × 5min/epoch ≈ 37.5 GPU日
- A100 1枚: 約5-6週間 / A100 4枚: 約10日

### 5.6 再現性チェックリスト
- [ ] seed=42,123,456 の3回実行
- [ ] PyTorch 2.x, PyG 2.5+, FAISS-GPU
- [ ] Docker環境（Dockerfile同梱）
- [ ] Hydra config で全パラメータ管理
- [ ] W&B でメトリクス記録
```

---

### 11.6.6 未解決問題

```markdown
## 6. 未解決問題

1. **multi-scale統合の最適な方法**: concat→MLP? attention? 加重和?
→ 実験のablationで決定する（H1の追加条件として）

2. **kの適応的選択**: 密度に応じてkを変える手法の理論的裏付けが不十分
→ 今回は固定multi-scaleで進め、将来の研究課題とする

3. **動的点群への拡張**: フレーム間の時系列変化をグラフにどう反映するか
→ 今回のスコープ外。静的点群で手法を確立してから取り組む

4. **Explainability**: GNN出力のどのエッジ/ノードが判定に寄与したか
→ GNNExplainerの適用可能性を次のセッションで議論予定
```

---

### 11.6.7 参考文献

```markdown
## 7. 参考文献

議論中に言及された文献一覧:

- (Qi+2017) PointNet: Deep Learning on Point Sets. CVPR 2017.
- (Qi+2017b) PointNet++: Deep Hierarchical Feature Learning. NeurIPS 2017.
- (Wang+2019) Dynamic Graph CNN for Learning on Point Clouds. ToG 2019.
- (Wu+2024) Point Transformer V3: Simpler, Faster, Stronger. CVPR 2024.
- (Xiang+2021) Walk in the Cloud: Learning Curves for Point Clouds. ICML 2021.
- (Lim+2023) Sign and Basis Invariant Networks for Spectral GNNs. ICLR 2023.
- ⚠️ Mamba3D (2024) [要確認] — 実在確認が必要

---

*⚠️ [要確認]タグ付きの文献は、実在を確認してから引用してください。*
```

---

### 11章まとめ: 機能①の設計原則

| 原則 | 実現方法 |
|---|---|
| **研究者の思考を加速** | 壁打ちを自動化。5分で多角的な議論を回す |
| **構造化された出力** | 仮説テーブル、実験計画、再現性チェックリストまで一貫して生成 |
| **継続的な深掘り** | follow-up で実験結果を踏まえた再議論が可能 |
| **会話の自然さ** | 研究室のホワイトボード前の議論を再現する会話トーン |
| **引用の誠実さ** | [要確認]タグシステムで架空論文引用を防止 |
| **柔軟なシナリオ** | テーマに応じたテンプレート提供しつつ、指揮者の自由裁量を確保 |

---
