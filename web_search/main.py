# -*- coding: utf-8 -*-
"""企業情報・業界調査ツール (Vertex AI + Google検索グラウンディング)
営業向け: 製造業の自動化・省人化ソリューション導入可否を判断するための情報収集ツール
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv

import vertexai
from vertexai.generative_models import (
    GenerationConfig,
    GenerativeModel,
    Tool,
    grounding,
)

# Windowsコンソールでの文字化け対策
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass


def build_prompt(company_name: str) -> str:
    """モデルに送信するプロンプトを構築する"""
    return f"""あなたの作業は2段階です。

【第1段階：調査】
以下の企業について、徹底的に調査してください。
公式Webサイト、IR、採用ページ、ニュース、業界メディア、製品カタログ等を幅広く参照すること。

調査対象: {company_name}

調査する観点（これらは出力しないこと。内部的に調べるだけ）:
企業概要、全事業・全製品、製造工程、使用設備、拠点、自動化状況、塗装工程有無、環境対応、競合、新規事業

【第2段階：出力】
調査結果を、以下のフォーマット「のみ」で出力してください。
それ以外の情報、補足、前置き、まとめは一切出力しないでください。

■ 企業サマリー
- 正式名称:
- 業種:
- 本社所在地:
- 従業員数:（出典年を括弧書き）
- 売上高:（確定実績値のみ。出典年を括弧書き）

■ 事業内容
以下の5列の表形式で、見つかった主要事業をすべて（省略せず）記載すること。

| 主要事業 | 代表製品 | 主な製造工程 | 主要設備・装置 | 工程間ワーク |
|----------|----------|--------------|----------------|--------------|
| （名詞のみ） | （具体的な製品名） | （工程を→で接続） | （設備名を列挙） | （形態変化を→で接続） |

記載例:
| 塗装治具 | ハンガー治具、マスク治具、搬送治具 | 設計→切断→曲げ・穴あけ→溶接・組立→表面仕上げ→検査 | CAD/CAM、レーザー加工機、ベンダー、溶接機、測定器 | 丸棒・板金→切断材→加工部品→組立済み治具→完成品 |

【出力ルール】
- 出力は「■ 企業サマリー」から始めること。それ以前に文章を書かない。
- 出力は「■ 事業内容」の表で終わること。それ以降に文章を書かない。
- 事業は見つかったものをすべて行として記載する。省略しない。
- 不明な項目は「不明」と書く。推測しない。
- 数値には必ず出典年度を添える。予想値は使用しない。
- 主要事業の列は名詞のみ。動詞（製造、販売、開発等）を含めない。
  例: ×「各種スプリングの製造・販売」→ ○「各種スプリング」
- 製造工程は原材料投入から出荷までを「→」で接続する。
- 工程間ワークは形態の変化を「→」で接続する。
- 情報源が見つからない列は「不明」とし、行自体は省略しない。
"""


def init_vertexai() -> tuple[str, str, str]:
    """Vertex AI を初期化し、設定値を返す"""
    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    location = os.getenv("GCP_LOCATION", "us-central1")
    model_name = os.getenv("MODEL_NAME", "gemini-2.5-flash")

    if not project_id:
        raise RuntimeError(".env の GCP_PROJECT_ID が設定されていません。")

    vertexai.init(project=project_id, location=location)
    return project_id, location, model_name


def _extract_grounding_metadata(response) -> Optional[object]:
    """レスポンスからグラウンディングメタデータを安全に取得する"""
    try:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return None
        first = candidates[0]
        return getattr(first, "grounding_metadata", None)
    except Exception:
        return None


def _print_verbose(response, elapsed: float) -> None:
    """--verbose 時のみ表示する詳細情報"""
    print("\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    print("📋 デバッグ情報")
    print("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")

    # トークン情報
    usage = getattr(response, "usage_metadata", None)
    if usage:
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens = input_tokens + output_tokens
        print(f"  トークン: 入力 {input_tokens:,} / 出力 {output_tokens:,} / 合計 {total_tokens:,}")

        # 費用概算
        cost_usd = input_tokens / 1_000_000 * 0.075 + output_tokens / 1_000_000 * 0.30
        print(f"  推定費用: ${cost_usd:.6f} USD（約 {cost_usd * 150:.4f} 円）")

    # グラウンディングメタデータ
    metadata = _extract_grounding_metadata(response)
    if metadata:
        # 検索クエリ
        queries = []
        if hasattr(metadata, "web_search_queries"):
            queries = list(metadata.web_search_queries or [])
        if queries:
            print(f"\n  🔎 検索クエリ ({len(queries)}件):")
            for i, q in enumerate(queries, 1):
                print(f"     {i}. {q}")

        # ソースURL
        chunks = []
        if hasattr(metadata, "grounding_chunks"):
            chunks = list(metadata.grounding_chunks or [])
        if chunks:
            print(f"\n  🌐 ソース ({len(chunks)}件):")
            for i, chunk in enumerate(chunks, 1):
                web = getattr(chunk, "web", None)
                if web:
                    title = getattr(web, "title", "(不明)") or "(不明)"
                    uri = getattr(web, "uri", "(不明)") or "(不明)"
                    print(f"     [{i}] {title}")
                    print(f"         {uri}")

    print("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")


def investigate(company_name: str, model_name: str, verbose: bool = False) -> None:
    """企業調査を実行する"""
    print(f"\n🔍 調査中: {company_name} ...\n")

    # Google検索グラウンディングツール
    try:
        search_tool = Tool.from_dict({"google_search": {}})
    except Exception:
        search_tool = Tool.from_google_search_retrieval(
            grounding.GoogleSearchRetrieval()
        )

    # モデル初期化
    model = GenerativeModel(model_name=model_name, tools=[search_tool])

    # 生成設定
    generation_config = GenerationConfig(
        temperature=1.0,
        max_output_tokens=5000,
    )

    prompt = build_prompt(company_name)

    # API 呼び出し
    t_start = time.perf_counter()
    try:
        response = model.generate_content(
            prompt,
            generation_config=generation_config,
        )
    except Exception as exc:
        msg = str(exc)
        print(f"❌ API呼び出しに失敗しました。")
        print(f"   詳細: {msg}")
        lowered = msg.lower()
        if any(k in lowered for k in ("credential", "auth", "permission", "unauthenticated", "401", "403")):
            print("\n💡 認証エラーの可能性があります。次のコマンドを実行してください:")
            print("   gcloud auth application-default login")
        return

    elapsed = time.perf_counter() - t_start

    # レポート出力
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    try:
        print(response.text)
    except Exception as exc:
        print(f"(本文の取得に失敗しました: {exc})")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # グラウンディングステータス（1行）
    metadata = _extract_grounding_metadata(response)
    if metadata:
        print(f"✅ グラウンディング: 成功（処理時間: {elapsed:.1f}秒）")
    else:
        print(f"⚠️  グラウンディング: 失敗（処理時間: {elapsed:.1f}秒）")

    # verbose時のみ詳細表示
    if verbose:
        _print_verbose(response, elapsed)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(
        description="企業情報・業界調査ツール（Google検索グラウンディング）"
    )
    parser.add_argument(
        "company",
        nargs="*",
        help="調査対象の企業名（省略時はインタラクティブモード）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="検索クエリ・ソースURL・トークン情報を表示する",
    )
    return parser.parse_args()


def main() -> None:
    """メイン処理"""
    args = parse_args()

    try:
        _, _, model_name = init_vertexai()
    except Exception as exc:
        print(f"❌ 初期化エラー: {exc}")
        sys.exit(1)

    # コマンドライン引数で企業名が指定された場合
    if args.company:
        company_name = " ".join(args.company).strip()
        if company_name:
            investigate(company_name, model_name, verbose=args.verbose)
        return

    # インタラクティブモード
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🏢 企業調査ツール（製造業向け）")
    print("   終了: quit / 詳細表示: 企業名の後に --verbose")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    while True:
        try:
            user_input = input("\n企業名 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("終了します。")
            break

        # インタラクティブモードでも --verbose をサポート
        verbose = False
        if user_input.endswith("--verbose") or user_input.endswith("-v"):
            verbose = True
            user_input = user_input.replace("--verbose", "").replace("-v", "").strip()

        if user_input:
            investigate(user_input, model_name, verbose=verbose)


if __name__ == "__main__":
    main()