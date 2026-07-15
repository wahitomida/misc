# Web Search Grounding Test

このプロジェクトは、Google Vertex AI の生成モデルとWeb検索グラウンディングを使って、企業情報や業界動向を調査する試作ツールです。製造業向けの情報収集パイプラインとして、検索結果の根拠と出力形式を明示する構成になっています。

## できること

- 企業名を入力すると、Web検索ベースで企業概要・事業内容を生成
- 検索クエリ・ソースURLのデバッグ出力をサポート
- Vertex AI の grounding 機能で検索結果を参照しながら回答

## セットアップ

```powershell
cd web_search\web_search\grounding-test
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`GCP_PROJECT_ID` を含む `.env` ファイルを配置してください。

例:

```text
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
MODEL_NAME=gemini-2.5-flash
```

## 実行

```powershell
python main.py "企業名"
```

対話モードで実行する場合は引数なしで起動します。

```powershell
python main.py
```

詳細表示を有効にするには `--verbose` または `-v` を利用します。

```powershell
python main.py "企業名" --verbose
```

## 知見・ポートフォリオ訴求ポイント

- LLM と検索グラウンディングを組み合わせた調査パイプライン
- 出力フォーマット設計と検証用デバッグ情報の提供
- Vertex AI を使った実装例
