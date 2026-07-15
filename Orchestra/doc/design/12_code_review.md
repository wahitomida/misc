# 第12章 機能②: コードレビュー

---

## 12.1 実行フロー全体図（5フェーズ）

機能②は「研究コードのフォルダを入力として、6つの観点から多角的にレビューし、修正指示書を生成する」機能です。機能①の3フェーズ構成とは異なり、**5フェーズ**で構成されます。

```
[ユーザー]
python main.py review --focus pre_submission ./src/
│
▼
┌──────────────────────────────────────────────────────────────────┐
│ CodeReview.run()                                                   │
│                                                                    │
│  Phase 1: 構造スキャン (~10秒)                                      │
│  ├── フォルダツリー取得                                             │
│  ├── 各ファイルのヘッダ(先頭50行)解析                               │
│  ├── 機能グループの推定                                             │
│  └── パートリーダー6体の割当・重み決定                              │
│                                                                    │
│  Phase 2: 個別調査 (~60-120秒)                                      │
│  ├── 🧮 アルゴリズム検証リーダー → 数式↔コード対応、数値安定性       │
│  ├── 🔬 再現性検証リーダー → seed固定、config管理、環境依存          │
│  ├── 🤖 性能分析リーダー → ボトルネック、メモリ、並列化              │
│  ├── 📐 設計リーダー → モジュール分割、DRY、SOLID                   │
│  ├── 📝 可読性リーダー → 命名、docstring、フォーマット               │
│  └── 📊 結果分析リーダー → 出力妥当性、論文整合、テスト             │
│                                                                    │
│  Phase 3: 相互質問 (~30-60秒)                                       │
│  ├── 🧮↔📊 アルゴリズム×結果の整合                                 │
│  ├── 🤖↔🧮 性能改善×数学的等価性                                   │
│  └── 📐↔🤖 構造改善×並列化可能性                                   │
│                                                                    │
│  Phase 4: 全体会議 (~60秒)                                          │
│  ├── 各リーダーの報告統合                                           │
│  ├── 課題の優先度付け議論                                           │
│  ├── 修正順序の決定 (Phase A/B/C)                                   │
│  └── 副作用の検討                                                   │
│                                                                    │
│  Phase 5: レポート生成 (~25秒)                                      │
│  ├── report.md (課題一覧+修正方針)                                  │
│  ├── vibe_coding_prompt.md (AI修正指示書)                           │
│  └── 他出力ファイル                                                 │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### 実装クラス

```python
class CodeReview:
    """機能②: コードレビューの統合フロー"""

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
        target_path: Path,
        focus: str = "all",
        planner_model: str = "gpt-5.4",
        conductor_model: str = "gpt-4.1",
        synth_model: str = "claude-sonnet-4-5",
        time_limit: float = 600,
        max_agents: int = 6,
        ignore_patterns: list[str] | None = None,
        output_dir: Path = Path("./output"),
    ) -> Path:
        """機能②の完全実行フロー"""

        # Phase 1: 構造スキャン
        scan_result = await self._phase1_scan(target_path, planner_model, ignore_patterns)

        # ユーザー確認
        if not self._confirm_execution(scan_result):
            return None

        # Phase 2: 個別調査
        findings = await self._phase2_investigate(scan_result, focus)

        # Phase 3: 相互質問
        enriched_findings = await self._phase3_cross_question(findings)

        # Phase 4: 全体会議
        discussion_log = await self._phase4_meeting(enriched_findings, conductor_model)

        # Phase 5: レポート生成
        output_path = await self._phase5_report(
            scan_result, enriched_findings, discussion_log, synth_model, output_dir
        )

        return output_path
```

---

## 12.2 Phase 1: 構造スキャン

### 12.2.1 フォルダツリーの取得

```python
class FolderScanner:
    """フォルダ構造のスキャン"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ignore_patterns = settings.code_review.ignore_patterns
        self.max_file_size = settings.code_review.max_file_size_bytes
        self.header_lines = settings.code_review.header_lines

    def scan(self, target_path: Path, extra_ignores: list[str] | None = None) -> ScanResult:
        """対象フォルダをスキャンし、構造情報を返す"""

        ignores = self.ignore_patterns + (extra_ignores or [])

        file_tree = []
        file_details = []

        for file_path in self._walk_files(target_path, ignores):
            rel_path = file_path.relative_to(target_path)
            stat = file_path.stat()

            file_info = {
                "path": str(rel_path),
                "size_bytes": stat.st_size,
                "extension": file_path.suffix,
                "lines": self._count_lines(file_path),
            }
            file_tree.append(file_info)

            # ヘッダ解析（先頭N行）
            if stat.st_size <= self.max_file_size:
                header = self._read_header(file_path)
                file_info["header"] = header
                file_details.append(file_info)
            else:
                file_info["skipped"] = True
                file_info["skip_reason"] = f"ファイルサイズ超過 ({stat.st_size} bytes)"

        return ScanResult(
            target_path=target_path,
            file_tree=file_tree,
            file_details=file_details,
            total_files=len(file_tree),
            total_lines=sum(f.get("lines", 0) for f in file_tree),
            skipped_files=[f for f in file_tree if f.get("skipped")],
        )

    def _walk_files(self, path: Path, ignores: list[str]) -> Iterator[Path]:
        """ignoreパターンを除外してファイルを列挙"""
        import fnmatch

        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(path))
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(file_path.name, pat) for pat in ignores):
                continue
            yield file_path

    def _read_header(self, file_path: Path) -> str:
        """ファイルの先頭N行を読み取り"""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= self.header_lines:
                        break
                    lines.append(line)
                return "".join(lines)
        except Exception:
            return ""
```

---

### 12.2.2 ファイルヘッダ解析

各ファイルの先頭50行から以下を抽出します:

```python
def _analyze_header(self, header: str, file_path: str) -> dict:
    """ヘッダからファイルの役割を推定"""
    return {
        "docstring": self._extract_docstring(header),
        "imports": self._extract_imports(header),
        "classes": self._extract_class_names(header),
        "functions": self._extract_function_names(header),
        "estimated_purpose": None,  # Phase 1 の LLM で推定
    }
```

---

### 12.2.3 機能グループ推定

指揮者（gpt-5.4, minimal）がフォルダ構造とヘッダ情報から機能グループを推定します。

```python
STRUCTURE_ANALYSIS_PROMPT = """以下のプロジェクト構造を分析し、機能グループに分類してください。

【フォルダツリー】
{file_tree_formatted}

【各ファイルのヘッダ（先頭50行）】
{headers_formatted}

【出力形式 (JSON)】
{{
    "project_summary": "このプロジェクトが何をするものかの1文説明",
    "functional_groups": [
        {{
            "group_name": "グループ名",
            "description": "このグループの役割",
            "files": ["path/to/file1.py", "path/to/file2.py"],
            "primary_concern": "algorithm|structure|performance|reproducibility"
        }}
    ],
    "entry_points": ["メインの実行ファイル"],
    "test_coverage": "tests有り/無し/部分的"
}}"""
```

---

### 12.2.4 パートリーダー割当

機能グループの特性と `--focus` 指定に基づいて、各パートリーダーの担当範囲と重みを決定します。

```python
FOCUS_PRESETS = {
    "all": {
        "algorithm": 1.0, "reproducibility": 1.0, "performance": 1.0,
        "structure": 1.0, "readability": 1.0, "results": 1.0,
    },
    "pre_submission": {
        "algorithm": 1.5, "reproducibility": 1.5, "results": 1.5,
        "structure": 0.5, "readability": 0.5, "performance": 0.8,
    },
    "performance": {
        "performance": 2.0, "structure": 1.0,
        "algorithm": 0.5, "reproducibility": 0.3, "readability": 0.3, "results": 0.5,
    },
    "structure": {
        "structure": 2.0, "readability": 1.5,
        "algorithm": 0.3, "reproducibility": 0.5, "performance": 0.5, "results": 0.3,
    },
    "handover": {
        "readability": 2.0, "reproducibility": 1.5, "structure": 1.5,
        "algorithm": 0.3, "performance": 0.3, "results": 0.5,
    },
    "algorithm": {
        "algorithm": 2.0, "results": 1.5,
        "structure": 0.3, "readability": 0.3, "performance": 0.5, "reproducibility": 0.5,
    },
}

class PartLeaderAssigner:
    """パートリーダーの割当と重み決定"""

    def assign(self, scan_result: ScanResult, focus: str) -> list[PartLeaderConfig]:
        weights = FOCUS_PRESETS.get(focus, FOCUS_PRESETS["all"])

        leaders = []
        for concern, weight in weights.items():
            if weight < 0.3:
                continue  # 重みが低すぎるリーダーはスキップ

            # 該当するファイル群を割当
            assigned_files = self._get_files_for_concern(scan_result, concern)

            leaders.append(PartLeaderConfig(
                concern=concern,
                weight=weight,
                assigned_files=assigned_files,
                role_id=CONCERN_TO_ROLE[concern],
                model=CONCERN_TO_MODEL[concern],
                level=self._weight_to_level(weight),
            ))

        return leaders

    def _weight_to_level(self, weight: float) -> str:
        if weight >= 1.5:
            return "high"
        elif weight >= 1.0:
            return "medium"
        else:
            return "low"

CONCERN_TO_ROLE = {
    "algorithm": "theorist",
    "reproducibility": "experimentalist",
    "performance": "implementer",
    "structure": "code_architect",
    "readability": "code_reviewer",
    "results": "experimentalist",  # 兼務
}

CONCERN_TO_MODEL = {
    "algorithm": "gpt-5.4",
    "reproducibility": "gpt-5",
    "performance": "claude-sonnet-4-5",
    "structure": "gpt-4.1",
    "readability": "gpt-4.1-mini",
    "results": "gpt-5",
}
```

---

## 12.3 Phase 2: 個別調査

### 12.3.1 パートリーダー6体制の調査項目

各パートリーダーはそれぞれ固有の調査プロンプトを持ち、担当ファイルを分析します。

```python
INVESTIGATION_PROMPTS = {
    "algorithm": """以下のコードを「アルゴリズムの正しさ」の観点で調査してください。

【調査項目】
□ 数式↔コードの対応が正しいか
□ インデックスの0/1始まり混同はないか
□ 総和・正規化の範囲は正しいか
□ 数値安定性 (log(0), div/0, overflow/underflow)
□ 境界条件 (N=0, N=1, 最大入力)
□ 確率的処理の正しさ (dropout, BN, sampling)
□ 損失関数がタスクに対して妥当か
□ 勾配の伝搬が意図通りか (detach, no_grad)

【コード】
{file_content}

【出力形式 (JSON)】
{{
    "findings": [
        {{
            "severity": "critical|warning|suggestion",
            "file": "ファイルパス",
            "line": "L42-58",
            "title": "課題タイトル",
            "current_code": "現状のコード（該当部分）",
            "problem": "何が問題か",
            "fix_suggestion": "修正方針",
            "impact": "影響範囲"
        }}
    ]
}}""",

    "reproducibility": """以下のコードを「再現性」の観点で調査してください。

【調査項目】
□ 乱数seed固定 (python, numpy, torch, cuda)
□ cudnn.deterministic / benchmark 設定
□ DataLoaderの worker_init_fn
□ ハイパーパラメータがconfigで管理されているか
□ データパスがハードコードされていないか
□ ライブラリバージョンが固定されているか
□ 実行環境情報のログ出力があるか
□ checkpoint保存・復元が正しく動くか

【コード】
{file_content}

【出力形式 (JSON)】
同上""",

    "performance": """以下のコードを「計算効率」の観点で調査してください。

【調査項目】
□ O(N²)以上のループがないか
□ 不要なCPU-GPU転送がないか
□ テンソルの不要コピー (.clone(), .detach() の濫用)
□ メモリリーク (計算グラフの意図しない保持)
□ バッチ処理で並列化できる逐次処理がないか
□ I/Oボトルネック (データロードが律速)
□ GPU utilizationを下げている箇所
□ 型変換 (float64→float32) の無駄

【コード】
{file_content}

【出力形式 (JSON)】
同上""",

    "structure": """以下のコードを「設計・構造」の観点で調査してください。

【調査項目】
□ 1ファイル/1クラスの責務が明確か
□ 関数が長すぎないか (50行超は分割検討)
□ モジュール間の依存が一方向か (循環import)
□ 設定と処理が分離されているか
□ テストが書きやすい構造か
□ 似た処理のコピペ (DRY原則違反)
□ マジックナンバーが定数化されているか
□ ディレクトリ構成が論理的か

【コード】
{file_content}

【出力形式 (JSON)】
同上""",

    "readability": """以下のコードを「可読性」の観点で調査してください。

【調査項目】
□ 変数名・関数名が意味を表しているか
□ 命名の表現揺れ (get_ vs fetch_, calc_ vs compute_)
□ docstringがあるか。内容は正確か
□ コメントが嘘をついていないか
□ 型ヒントがあるか
□ 不要なコメントアウトコード
□ importの整理 (未使用、順序)
□ 一貫したフォーマット

【コード】
{file_content}

【出力形式 (JSON)】
同上""",

    "results": """以下のコードを「結果の妥当性」の観点で調査してください。

【調査項目】
□ 出力値の範囲は妥当か (確率が0-1か等)
□ テストで期待値との比較がされているか
□ 既知入力に対する出力が論文報告値と一致するか
□ エラーメトリクスの計算方法は正しいか
□ 可視化コードが実データを正しく反映しているか
□ ログ出力から実験追跡が可能か
□ regression test (前回結果と今回の一致確認)

【コード】
{file_content}

【出力形式 (JSON)】
同上""",
}
```

---

### 12.3.2 token 制限内でのファイル分割戦略

大きなファイルは token 上限を超えるため、分割して渡します。

```python
class FileChunker:
    """ファイルをtoken上限内のチャンクに分割"""

    def __init__(self, max_tokens_per_chunk: int = 8000):
        self.max_tokens = max_tokens_per_chunk

    def chunk_file(self, file_content: str, file_path: str) -> list[dict]:
        """ファイルを関数/クラス単位で分割"""

        # 方法1: AST解析で関数/クラス単位に分割（Python限定）
        if file_path.endswith(".py"):
            return self._chunk_by_ast(file_content, file_path)

        # 方法2: 行数ベースで等分割（非Python）
        return self._chunk_by_lines(file_content, file_path, lines_per_chunk=200)

    def _chunk_by_ast(self, content: str, file_path: str) -> list[dict]:
        """ASTで関数/クラス単位に分割"""
        import ast

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._chunk_by_lines(content, file_path)

        chunks = []
        lines = content.split("\n")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno - 1
                end = node.end_lineno
                chunk_content = "\n".join(lines[start:end])

                if self._estimate_tokens(chunk_content) <= self.max_tokens:
                    chunks.append({
                        "file": file_path,
                        "type": type(node).__name__,
                        "name": node.name,
                        "lines": f"L{start+1}-{end}",
                        "content": chunk_content,
                    })
                else:
                    # 1関数/クラスが大きすぎる場合はさらに分割
                    sub_chunks = self._chunk_by_lines(chunk_content, file_path, lines_per_chunk=100)
                    chunks.extend(sub_chunks)

        return chunks if chunks else [{"file": file_path, "content": content}]
```

---

### 12.3.3 重点モード（--focus）による観点の重み付け

`--focus` で指定された重みに応じて、各パートリーダーの**調査の深さ**と**割当ファイル数**が変わります。

```
--focus pre_submission の場合:

🧮 アルゴリズム:  weight=1.5 → level=high,  全ファイル調査
🔬 再現性:       weight=1.5 → level=high,  全ファイル調査
📊 結果分析:     weight=1.5 → level=high,  全ファイル調査
🤖 性能:        weight=0.8 → level=medium, 主要ファイルのみ
📐 設計:        weight=0.5 → level=low,    サマリのみ
📝 可読性:      weight=0.5 → level=low,    サマリのみ
```

```
--focus performance の場合:

🤖 性能:        weight=2.0 → level=high,  全ファイル詳細調査
📐 設計:        weight=1.0 → level=medium, 構造的ボトルネック
🧮 アルゴリズム:  weight=0.5 → level=low,   計算量の確認のみ
📊 結果分析:     weight=0.5 → level=low,    性能指標のみ
🔬 再現性:       weight=0.3 → スキップ
📝 可読性:      weight=0.3 → スキップ
```

---

## 12.4 Phase 3: 相互質問

### 12.4.1 質問パターンの組み合わせ

パートリーダー間で相互に質問し合い、観点を横断的に検証します。

```python
# 相互質問の典型パターン
CROSS_QUESTION_PAIRS = [
    # (質問者, 回答者, 質問の観点)
    ("algorithm", "results", "この正規化の有無で出力はどの程度変わる？テストある？"),
    ("results", "algorithm", "結果が論文と0.5%ずれてるが、式の実装どこか違う？"),
    ("performance", "algorithm", "この行列計算、数学的に等価でもっと速い書き方ある？"),
    ("algorithm", "performance", "対称行列だから固有値分解でO(N²)に落とせるはず"),
    ("structure", "performance", "この関数分割したら並列化しやすくなる？"),
    ("performance", "structure", "DataLoaderとModel間のインターフェースが密結合"),
    ("readability", "structure", "この変数名、構造整理すれば命名も自然に決まるのでは"),
    ("reproducibility", "readability", "configのパラメータ名とコード内変数名が不一致で危険"),
    ("results", "reproducibility", "この実験結果、seed変えたら再現する？"),
]

class CrossQuestioner:
    """パートリーダー間の相互質問を管理"""

    def __init__(self, api_client: ResilientAPIClient, settings: Settings):
        self.api_client = api_client
        self.max_rounds = settings.code_review.cross_question_max_rounds

    async def run(
        self,
        findings: dict[str, list[dict]],
        leaders: list[PartLeaderConfig],
    ) -> dict[str, list[dict]]:
        """相互質問を実行し、findings を拡充して返す"""

        enriched = {k: list(v) for k, v in findings.items()}

        # 関連性のあるペアを選定
        pairs = self._select_relevant_pairs(findings)

        for asker_concern, answerer_concern, context_hint in pairs:
            # 質問生成
            question = await self._generate_question(
                asker_concern, answerer_concern,
                findings[asker_concern], findings[answerer_concern],
                context_hint,
            )

            if not question:
                continue

            # 回答取得
            answer = await self._get_answer(
                answerer_concern, question, findings[answerer_concern]
            )

            # 追加知見として記録
            if answer:
                enriched[asker_concern].append({
                    "severity": "info",
                    "title": f"[相互質問] {answerer_concern}への質問結果",
                    "question": question,
                    "answer": answer,
                    "source": f"cross_question_{asker_concern}→{answerer_concern}",
                })

        return enriched
```

---

### 12.4.2 最大5往復と収束判定

```python
async def _question_answer_loop(
    self,
    asker: str,
    answerer: str,
    initial_question: str,
    max_rounds: int = 5,
) -> list[dict]:
    """質問→回答のループ（最大5往復）"""

    exchanges = []
    current_question = initial_question

    for round_num in range(max_rounds):
        # 回答取得
        answer = await self._get_answer(answerer, current_question, context={})
        exchanges.append({"role": "answer", "from": answerer, "content": answer})

        # 質問者が満足したか確認
        satisfied = await self._check_satisfaction(asker, exchanges)
        if satisfied:
            break

        # フォローアップ質問の生成
        follow_up = await self._generate_follow_up(asker, exchanges)
        if not follow_up:
            break

        exchanges.append({"role": "question", "from": asker, "content": follow_up})
        current_question = follow_up

    return exchanges
```

---

## 12.5 Phase 4: 全体会議

Phase 4 は機能①の Phase 2 と同じ Conductor エンジンを使用しますが、コードレビュー固有のテーマ設定で議論を行います。

### 12.5.1 課題の優先度付け議論

```python
MEETING_PROMPT = """各パートリーダーの調査結果を基に、全体会議を行います。

【各リーダーの発見事項サマリ】
{findings_summary}

【全体会議の目標】
1. 発見された課題に優先度をつける (Critical / Warning / Suggestion)
2. 課題間の依存関係を特定する
3. 修正の順序を決定する
4. 修正時の副作用リスクを検討する

【参加者の役割】
- 各パートリーダーは自分の発見を報告し、他者の発見との関連を指摘
- 優先度について意見が分かれた場合は議論して合意する
- 「これを直すとここが壊れる」というリスクを指摘する
"""
```

**会話ログでの見え方**:

```
── 全体会議 ──

🎼 各リーダーの報告を聞いた。課題が合計23個。優先度つけよう。

🧮: 致命的なのはloss.pyのlog(0)とmulti_scale_knn.pyの正規化漏れ。今の実験結果に影響してる可能性ある。

📊: 実際ScanObjectNNでの精度が論文より1.2%低いんだよね。正規化漏れが原因かも。

📐: ただそこ直すならtrain.pyの構造も一緒に直したい。今の設計だと1箇所直すと3箇所に波及する。

📝: train.pyは600行ある。まず分割してから修正した方がバグ入りにくい。

🤖: 分割するなら、ついでにdata_loader.pyのI/Oボトルネックも一緒に直せる。

🔬: 待って。大きくリファクタすると前の実験結果との比較ができなくなる。まずregression test作ってから手を入れない？

🧮: それは正しい。順番としては①regression test→②正規化漏れ→③精度確認→④リファクタ。
```

---

### 12.5.2 修正順序の決定（Phase A/B/C 分類）

```python
PHASE_CLASSIFICATION = {
    "A": {
        "name": "精度直結・即時修正",
        "criteria": "修正しないと実験結果が信頼できない課題",
        "typical": ["アルゴリズムのバグ", "数値安定性", "結果の不整合"],
        "prerequisite": "Phase Aの前にregression testを作成",
    },
    "B": {
        "name": "構造改善・保守性向上",
        "criteria": "精度には直接影響しないが、今後の開発効率に影響",
        "typical": ["リファクタリング", "命名統一", "docstring追加"],
        "prerequisite": "Phase Aで精度が期待値に達したことを確認してから",
    },
    "C": {
        "name": "性能改善・最適化",
        "criteria": "動作は正しいが遅い、メモリを食う等の効率問題",
        "typical": ["GPU最適化", "I/Oパイプライン", "メモリ削減"],
        "prerequisite": "Phase Bで構造が整理されてから（不要な最適化を避ける）",
    },
}
```

---

### 12.5.3 副作用の検討

```python
SIDE_EFFECT_CHECK_PROMPT = """以下の修正タスクについて、副作用リスクを検討してください。

【修正タスク】
{task_description}

【関連ファイル】
{related_files}

【検討観点】
1. この修正で他のファイルが壊れないか？
2. 既存のテストが通らなくなる可能性は？
3. APIインターフェース(関数のシグネチャ)が変わるか？
4. 学習済みモデルとの互換性は保たれるか？
5. 実験結果の再現性に影響するか？

【出力形式 (JSON)】
{{
    "risk_level": "high|medium|low|none",
    "affected_files": ["影響を受けるファイル"],
    "breaking_changes": ["後方互換性を壊す変更"],
    "mitigation": "リスク軽減策"
}}"""
```

---

## 12.6 Phase 5: レポート生成

### 12.6.1 report.md（統合版: 研究+汎用）

```markdown
# 🔬 コードレビュー レポート

> **Session**: 20260625_150000_review
> **対象**: ./src/ (点群GNN特徴抽出)
> **Focus**: pre_submission
> **時間**: 6分18秒 | **パートリーダー**: 6体

---

## 概要

| 観点 | 課題数 | Critical | Warning | Suggestion |
|---|---|---|---|---|
| 🧮 アルゴリズム | 4 | 2 | 1 | 1 |
| 🔬 再現性 | 3 | 0 | 2 | 1 |
| 🤖 性能 | 5 | 0 | 3 | 2 |
| 📐 設計 | 6 | 1 | 3 | 2 |
| 📝 可読性 | 8 | 0 | 2 | 6 |
| 📊 結果分析 | 2 | 1 | 1 | 0 |
| **合計** | **28** | **4** | **12** | **12** |

---

## 修正方針（全体会議の結論）

```
Phase A (精度直結・即時修正):
  前提: regression test 作成
  1. multi_scale_knn.py L38 — 正規化漏れ [🧮]
  2. loss.py L15 — log(0) [🧮]
  3. 精度再確認 [📊]

Phase B (構造・可読性):
  前提: Phase A で精度が期待値に達したこと
  4. train.py 分割 (600行→3ファイル) [📐]
  5. 命名統一 (compute_ vs calc_) [📝]
  6. config-コード変数名の統一 [🔬📝]

Phase C (性能改善):
  前提: Phase B で構造が整理されてから
  7. DataLoader最適化 (GPU util 40%→推定75%) [🤖]
  8. 不要GPU-CPU転送除去 (3箇所) [🤖]
```

⚠️ **Phase B, C は Phase A で精度が期待値に達したことを確認してから着手すること**

---

## 🔴 Critical 課題

### [C-1] 🧮 multi_scale_knn.py L38 — 正規化漏れ

**論文の式(3):**
h_i = σ(Σ_{j∈N(i)} (h_j - h_i) / |N(i)| · W)

**現状のコード:**
```python
msg = self.mlp(x[edge_index[0]] - x[edge_index[1]])
out = scatter_add(msg, edge_index[1], dim=0)
```

**問題:** `/ |N(i)|` (近傍数での正規化) が抜けている

**影響:** 密度の高い領域のノードが不当に大きな特徴値を持つ。
ScanObjectNNでの精度-1.2%の原因と推定。

**修正:** `scatter_add` → `scatter_mean` に変更

**副作用:** 学習済みモデルは使用不可（再学習必要）

---

（以降のCritical/Warning/Suggestion課題が続く）
```

---

### 12.6.2 vibe_coding_prompt.md（AI修正指示書）

```python
VIBE_PROMPT_GENERATION = """以下の課題一覧と修正方針を基に、
コーディングAIに渡す修正指示書を生成してください。

【課題一覧と修正方針】
{prioritized_findings}

【プロジェクト構成】
{file_tree}

【指示書の要件】
- コーディングAIがそのまま作業を開始できる形式
- 各タスクに: 現状コード → 問題点 → 修正方針 → 期待する結果
- タスク間の依存関係を明示
- グローバル制約（コーディング規約）を末尾にまとめる
- 修正後はファイル全体を出力するよう指示

【フォーマット】
Markdown形式。セクション構成:
1. プロジェクトコンテキスト
2. 修正タスク一覧（優先度順）
3. グローバル制約
4. 議論で出た補足情報"""
```

**生成される vibe_coding_prompt.md の構造**:

```markdown
# 🤖 コード修正指示書（AI向け）

## プロジェクトコンテキスト
（プロジェクト概要、ディレクトリ構成、技術スタック）

## 修正タスク一覧（優先度順）

### 🔴 Task 1: [Critical] multi_scale_knn.py L38 — 正規化漏れ
**現状のコード:**（該当部分）
**問題点:**（具体的に）
**修正方針:**（どう直すか）
**期待する修正後:**（コード例）
**影響するファイル:**（依存関係）
**議論で出た補足:**（AI間議論からの追加情報）

### 🔴 Task 2: ...
### 🟡 Task 3: ...

## グローバル制約
1. テスト互換性
2. docstring: Google Style
3. 型ヒント必須
4. 命名: snake_case統一
...

## 議論で出た追加コンテキスト
（全体会議からの補足情報）
```

---

## 12.7 コードの状態に応じた観点自動調整

Phase 1 の構造スキャン結果から、指揮者がコードの「成熟度」を判断し、重点を自動調整します。

```python
CODE_STATE_DETECTION_PROMPT = """プロジェクトの状態を判定してください。

【プロジェクト情報】
- 総ファイル数: {total_files}
- 総行数: {total_lines}
- テストの有無: {test_coverage}
- docstring率: {docstring_ratio}
- 型ヒント率: {type_hint_ratio}

【判定】
以下の状態から最も近いものを選んでください:

1. prototype: 研究初期。動くが構造がカオス
2. experimental: 実験を回している段階。部分的に整理されている
3. pre_publication: 論文投稿前。正しさの保証が重要
4. production: 他者が使う段階。保守性・可読性が重要
5. optimization: 動作は正しいが速度/メモリ改善が必要

出力: 状態名のみ"""

# 状態に応じたデフォルト focus の自動設定
STATE_TO_DEFAULT_FOCUS = {
    "prototype": "structure",        # まず構造を整える
    "experimental": "all",           # バランスよく
    "pre_publication": "pre_submission",  # 正しさ重視
    "production": "handover",        # 可読性・再現性重視
    "optimization": "performance",   # 性能重視
}
```

**CLI で `--focus` が未指定の場合**:

```python
async def _auto_detect_focus(self, scan_result: ScanResult) -> str:
    """コードの状態から最適なfocusを自動推定"""

    if self.cli_focus:
        return self.cli_focus  # 明示指定があればそれを使う

    state = await self._detect_code_state(scan_result)
    auto_focus = STATE_TO_DEFAULT_FOCUS.get(state, "all")

    console.print(f"[dim]コード状態: {state} → 自動focus: {auto_focus}[/dim]")
    return auto_focus
```

**会話ログでの見え方**:

```
🎼 [Phase 1] コード状態を判定中...
🎼 [判定結果] 状態: pre_publication (テストあり、docstring率60%、型ヒント率30%)
🎼 [自動調整] focus=pre_submission を適用。アルゴリズム・再現性・結果を重点調査。
```

---

### 12章まとめ: コードレビュー設計の原則

| 原則 | 実現方法 |
|---|---|
| **多角的レビュー** | 6つの観点（アルゴリズム/再現性/性能/設計/可読性/結果）をパートリーダーが分担 |
| **横断的検証** | Phase 3 の相互質問で観点間の関連性を発見 |
| **合意形成** | Phase 4 の全体会議で修正順序と優先度を議論 |
| **実用的出力** | vibe_coding_prompt.md でそのままコーディング AI に渡せる |
| **適応的深度** | --focus と自動状態検知で調査の深さを最適化 |
| **副作用意識** | 修正の連鎖反応を事前に検討し、安全な修正順序を提示 |

---
