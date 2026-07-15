# AI Orchestra

複数の AI エージェントを並列に動かし、議論・評価・要約を行う実験的なマルチエージェント基盤です。アイデア発散からコードレビューまで、複数ステージで構成されたワークフローを実装しています。

## できること

- 複数エージェントによる議論の進行
- アイデアの深掘りと要約
- コードレビュー向けの観点別調査
- 会話ログや評価結果の出力

## 主な技術

- Python
- FastAPI / Jinja2 / Alpine.js
- OpenAI / Azure OpenAI 互換 API
- pytest

## ポートフォリオでの訴求ポイント

- マルチエージェントの設計と実装
- 複数ステップのワークフロー構築
- LLM を使った分析・評価・レポート生成の組み合わせ

## 公開前の注意

- API キーや認証情報は含めない
- 実行ログやセッション出力は公開対象から外す
| [doc/04_orchestrator.md](doc/04_orchestrator.md) | Phase 1 計画立案の仕様 |
| [doc/05_conductor.md](doc/05_conductor.md) | Phase 2 議論進行の仕様 |
| [doc/06_agent.md](doc/06_agent.md) | Agent の system_prompt 構造 |
| [doc/08_memory_context.md](doc/08_memory_context.md) | Layer 1-6 コンテキストと token 予算 |
| [doc/11_idea_discussion.md](doc/11_idea_discussion.md) | 機能①: Idea Discussion フロー |
| [doc/12_code_review.md](doc/12_code_review.md) | 機能②: Code Review 5 フェーズ |
| [doc/17_settings.md](doc/17_settings.md) | settings.yaml 全項目 |
| [doc/18_roadmap.md](doc/18_roadmap.md) | Phase A-G 実装ロードマップ |

---

## コーディング規約

プロジェクト全体で以下を厳守:

- **型ヒント**: 全 public メソッド・関数に付与 (Python 3.10+ の `|` 記法、`list[str]` 等の小文字)
- **Docstring**: Google Style (`Args:` / `Returns:` / `Raises:`)
- **命名**: PascalCase (クラス) / snake_case (関数・メソッド) / UPPER_SNAKE_CASE (定数)
- **ファイル長**: 目安 300 行、超えたら責務単位で分割
- **関数長**: 目安 50 行、超えたらヘルパー抽出
- **例外**: 具体的な例外型を指定 (`except Exception:` は禁止)
- **マジックナンバー**: モジュール先頭で定数化

詳細は リポジトリルートの [`.github/copilot-instructions.md`](../../.github/copilot-instructions.md) を参照。

---

## トラブルシューティング

### 計画立案がタイムアウトする

`config/settings.yaml` の `api.timeouts.gpt-5.4` は 180 秒に設定済み。それでもタイムアウトする場合は planner モデルを `gpt-4.1` に変更 (`config/settings.yaml` の `models.planner`)。

### Web UI で発言が止まる

`serve.py` を `--reload` なしで起動していないか確認。`--reload` がないと Python モジュール変更が反映されず CRUD/generate エンドポイントが古いままになる。

### 議論が Objective から逸れる

Layer 2 の Objective 強調と Phase フェーズヒントが働くようになっているが、Round 1 の goal が具体的すぎる場合は planning_prompt.txt の「Phase 1 (Round 1) 持ち寄り」制約を確認。goal 例通り「切り口タイトルレベル」に留められているか。

### `feedback_history` が肥大化する

`FeedbackManager.DEFAULT_MAX_HISTORY = 10` を超えると `_compress_old_entries` で自動的に例外的スコア (>=4.8 or <=1.5) 上位のみ残される。手動でロール YAML の `feedback_history` をリセットしたい場合は該当キーを YAML から削除。
