# -*- coding: utf-8 -*-
"""展示会情報取得サービス"""

from urllib.parse import urlparse
from app.services.grounding import call_gemini_json


def _top_url(url: str) -> str:
    """URLからトップページURLを生成する。

    例: https://www.example.com/exhibitor/list?id=1 -> https://www.example.com/
    """
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/"
    except Exception:
        pass
    return url


async def fetch_exhibition_info(url: str = "", name: str = "") -> dict:
    """展示会URLまたは名前からAI検索で情報を取得

    ユーザーが下層URL（出展者一覧など）を貼った場合でも、
    自動でトップページに遡って展示会の基本情報を取得する。
    """
    if url:
        top = _top_url(url)
        is_sub_page = top.rstrip("/") != url.rstrip("/")

        prompt = f"""あなたは展示会情報のリサーチ専門家です。
以下のURLについて、Google検索を必ず使って下記5項目をすべて取得してください。

入力URL: {url}
公式トップ（推定）: {top}
{'※ 入力URLは下層ページの可能性があります。トップ ' + top + ' も必ず確認してください。' if is_sub_page else ''}

【必須取得項目】
以下の5項目はすべて空にせず、Google検索で根拠を見つけて埋めること:
  1. 展示会の正式名称（"展示会名"）
  2. 会場（"会場"、施設名と住所）
  3. 会期（"会期"、開催期間。例: 2026年6月15日〜17日）
  4. 主催者（"主催者"、主催団体・企業名）
  5. 出展者一覧ページのURL（"出展者一覧"、Exhibitor List/出展企業 のページ）

【実行すべき検索クエリ（複数試すこと）】
  - "{name or '展示会名'}" 会場 会期 主催
  - site:{_top_url(url).replace("https://", "").replace("http://", "").rstrip("/")} 出展者
  - site:{_top_url(url).replace("https://", "").replace("http://", "").rstrip("/")} exhibitor
  - site:{_top_url(url).replace("https://", "").replace("http://", "").rstrip("/")} 開催概要
  - "展示会名" 出展者一覧
  - 公式トップ {top} のHTML内容

【出力】
JSON形式のみ。前置きや説明は一切書かない。各項目は必ず文字列で埋める（不明な場合のみ "不明" と書く）。

```json
{{
  "name": "展示会の正式名称（必須）",
  "url": "公式トップページのURL（{top}相当）",
  "exhibitor_list_url": "出展者一覧ページのURL（下層、必須）",
  "venue": "会場名と住所（必須）",
  "dates": "開催期間（必須）",
  "organizer": "主催者名（必須）"
}}
```
"""
    else:
        prompt = f"""あなたは展示会情報のリサーチ専門家です。
以下の展示会について、Google検索で下記5項目をすべて取得してください。

展示会名: {name}

【必須取得項目】
以下の5項目はすべて空にせず、Google検索で根拠を見つけて埋めること:
  1. 展示会の正式名称
  2. 会場（施設名と住所）
  3. 会期（開催期間）
  4. 主催者
  5. 出展者一覧ページのURL（Exhibitor List/出展企業 のページ）

【実行すべき検索クエリ（複数試すこと）】
  - "{name}" 会場 会期 主催
  - "{name}" 開催概要
  - "{name}" 公式サイト
  - "{name}" 出展者一覧
  - "{name}" exhibitor list
  - "{name}" カテゴリ別 出展

【出力】
JSON形式のみ。前置きや説明は一切書かない。各項目は必ず文字列で埋める（不明な場合のみ "不明" と書く）。

```json
{{
  "name": "{name}",
  "url": "公式サイトのトップページURL（必須）",
  "exhibitor_list_url": "出展者一覧ページのURL（下層、必須）",
  "venue": "会場名と住所（必須）",
  "dates": "開催期間（必須）",
  "organizer": "主催者名（必須）"
}}
```
"""
    result, sources, queries = await call_gemini_json(prompt, max_output_tokens=2048)
    if result and "raw_text" not in result:
        # "不明" や null を空文字に正規化
        for k in ("name", "url", "exhibitor_list_url", "venue", "dates", "organizer"):
            v = result.get(k)
            if v is None or (isinstance(v, str) and v.strip() in ("不明", "null", "None", "-", "—")):
                result[k] = ""
        # 入力URLが下層ページなら、urlフィールドが空のときに補完
        if url and not result.get("url"):
            result["url"] = _top_url(url)
        # exhibitor_list_url が空で、入力URLが下層ページなら入力URLを充てる
        if url and not result.get("exhibitor_list_url"):
            top = _top_url(url)
            if top.rstrip("/") != url.rstrip("/"):
                result["exhibitor_list_url"] = url
        return result
    return {
        "name": name or "",
        "url": _top_url(url) if url else "",
        "exhibitor_list_url": url if url else "",
        "venue": "",
        "dates": "",
        "organizer": "",
    }
