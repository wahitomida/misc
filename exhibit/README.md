# ExhibiReport

展示会前後の調査・レポート作成を支援する AI Web アプリケーションです。FastAPI と Jinja2 で構成し、LLM を活用した事前調査、事後分析、履歴管理をまとめて提供できます。

## できること

- 展示会前の関心テーマに基づく企業候補の提案
- 展示会後の訪問企業に対するレポート生成
- 分析ダッシュボードによる要点の可視化
- 履歴管理と再利用しやすい UI

## 主な技術

- FastAPI
- Jinja2 / Alpine.js
- Google Vertex AI / Gemini
- Web 検索グラウンディング

## セットアップ

```bash
cd exhibit/exhibit
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

環境変数は .env で定義します。サンプルは .env.example を参照してください。

## 実行

```bash
python main.py
```

## ポートフォリオでの訴求ポイント

- AI を使った業務フロー自動化
- Web アプリケーションの実装と UI 設計
- LLM と検索を組み合わせた情報収集パイプライン
