"""コードレビュー関連のプロンプト定数。

- ``INVESTIGATION_PROMPTS``: Phase 2 個別調査 (6 観点別) — §12.3.1
- ``CROSS_QUESTION_PAIRS``: Phase 3 相互質問の典型ペア — §12.4.1
- ``CODE_STATE_DETECTION_PROMPT``: Phase 1 で focus 自動推定に使う — §12.7
- ``STATE_TO_DEFAULT_FOCUS``: 状態名 → focus プリセット名のマップ — §12.7

設計書: ``doc/12_code_review.md`` §12.3.1, §12.4, §12.7
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# Phase 2: 個別調査プロンプト (§12.3.1)
# ----------------------------------------------------------------------


INVESTIGATION_PROMPTS: dict[str, str] = {
    "algorithm": """\
以下のコードを「アルゴリズムの正しさ」の観点で調査してください。

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

【出力形式 (JSON のみ)】
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
}}
""",
    "reproducibility": """\
以下のコードを「再現性」の観点で調査してください。

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

【出力形式 (JSON のみ)】
{{"findings": [...]}}
""",
    "performance": """\
以下のコードを「計算効率」の観点で調査してください。

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

【出力形式 (JSON のみ)】
{{"findings": [...]}}
""",
    "structure": """\
以下のコードを「設計・構造」の観点で調査してください。

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

【出力形式 (JSON のみ)】
{{"findings": [...]}}
""",
    "readability": """\
以下のコードを「可読性」の観点で調査してください。

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

【出力形式 (JSON のみ)】
{{"findings": [...]}}
""",
    "results": """\
以下のコードを「結果の妥当性」の観点で調査してください。

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

【出力形式 (JSON のみ)】
{{"findings": [...]}}
""",
}


# ----------------------------------------------------------------------
# Phase 3: 相互質問 (§12.4)
# ----------------------------------------------------------------------


CROSS_QUESTION_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("algorithm", "results", "この正規化の有無で出力はどの程度変わる？テストある？"),
    ("results", "algorithm", "結果が論文と0.5%ずれてるが、式の実装どこか違う？"),
    ("performance", "algorithm", "この行列計算、数学的に等価でもっと速い書き方ある？"),
    ("algorithm", "performance", "対称行列だから固有値分解でO(N²)に落とせるはず"),
    ("structure", "performance", "この関数分割したら並列化しやすくなる？"),
    ("performance", "structure", "DataLoaderとModel間のインターフェースが密結合"),
    ("readability", "structure", "この変数名、構造整理すれば命名も自然に決まるのでは"),
    ("reproducibility", "readability", "configのパラメータ名とコード内変数名が不一致で危険"),
    ("results", "reproducibility", "この実験結果、seed変えたら再現する？"),
)


# 相互質問プロンプトテンプレート (§12.4)
CROSS_QUESTION_GENERATION_PROMPT = """\
あなたは {asker} 観点を担当するコードレビュアーです。
{answerer} 観点を担当する別のレビュアーに、コードレビューの過程で
質問を 1 つ投げかけてください。

【あなた ({asker}) が見つけた所見】
{asker_findings}

【相手 ({answerer}) が見つけた所見】
{answerer_findings}

【質問の方向性 (参考)】
{hint}

【ルール】
- 質問は 1 文〜2 文。短く、具体的に。
- 相手の所見と関連付けて聞く。
- 質問する価値がない場合は "特になし" とだけ返す。

質問:
"""


CROSS_QUESTION_ANSWER_PROMPT = """\
あなたは {answerer} 観点を担当するコードレビュアーです。
他の観点 ({asker}) のレビュアーから次の質問を受けました。

【質問】
{question}

【あなたがこれまでに見つけた所見 (参考)】
{answerer_findings}

【ルール】
- 1〜3 文で簡潔に回答する。
- あなたの観点 ({answerer}) から判断できる範囲で答える。
- 分からない場合は「そこは確認が必要」と正直に答える。

回答:
"""


# ----------------------------------------------------------------------
# Phase 1: コード状態判定 (§12.7)
# ----------------------------------------------------------------------


CODE_STATE_DETECTION_PROMPT = """\
プロジェクトの状態を判定してください。

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

出力: 状態名のみ
"""


STATE_TO_DEFAULT_FOCUS: dict[str, str] = {
    "prototype": "structure",
    "experimental": "all",
    "pre_publication": "pre_submission",
    "production": "handover",
    "optimization": "performance",
}


__all__ = [
    "INVESTIGATION_PROMPTS",
    "CROSS_QUESTION_PAIRS",
    "CROSS_QUESTION_GENERATION_PROMPT",
    "CROSS_QUESTION_ANSWER_PROMPT",
    "CODE_STATE_DETECTION_PROMPT",
    "STATE_TO_DEFAULT_FOCUS",
]
