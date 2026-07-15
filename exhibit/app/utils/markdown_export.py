# -*- coding: utf-8 -*-
"""Markdown出力ユーティリティ"""

from datetime import datetime
from app.models.schemas import ExhibitionInfo


def generate_markdown(
    exhibition: ExhibitionInfo,
    purpose: str,
    themes: list[str],
    results: list[dict],
) -> str:
    """調査結果をMarkdown形式で出力"""
    now = datetime.now().strftime("%Y-%m-%d")
    themes_str = " / ".join(themes)

    md = f"""---
title: 展示会調査レポート
event: {exhibition.name}
date: {now}
---

# 展示会概要

| 項目 | 内容 |
|:-----|:-----|
| 展示会 | {exhibition.name} |
| 会場 | {exhibition.venue} |
| 会期 | {exhibition.dates} |
| 主催 | {exhibition.organizer} |
| URL | {exhibition.url} |
| 出展者一覧 | {exhibition.exhibitor_list_url} |

**目的**: {purpose}
**関心テーマ**: {themes_str}

---

# 企業調査

"""
    for i, r in enumerate(results, 1):
        company_name = r.get("company_name", "不明")
        basic = r.get("basic_info", {}) or {}
        business = r.get("business", {}) or {}
        tech = r.get("technology", {}) or {}
        exh = r.get("exhibition", {}) or {}
        score = r.get("relevance_score", 1)
        sources = r.get("sources", []) or []

        # 企業タブと同じ出展ステータス表記
        status_map = {
            "confirmed": "✅ 出展確認済",
            "estimated": "⚠️ 出展推定",
            "unknown": "❔ 出展未確認",
        }
        exh_status = status_map.get(exh.get("status", "unknown"), "❔ 出展未確認")
        stars = "★" * score + "☆" * (3 - score)

        md += f"""## {i}. {basic.get("official_name") or company_name}

`{exh_status}` `{stars}`

### 基本情報

| 項目 | 内容 |
|:-----|:-----|
| 本社 | {basic.get("headquarters") or "不明"} |
| 設立 | {basic.get("founded") or "不明"} |
| 従業員 | {basic.get("employees") or "不明"} |
| 売上 | {basic.get("revenue") or "不明"} |
| 業種 | {business.get("industry") or "不明"} |
| URL | {basic.get("url") or "不明"} |

"""
        # 主力製品（企業タブと同じテーブル）
        products = business.get("main_products", []) or []
        if products:
            md += "### 主力製品\n\n"
            md += "| 製品名 | 概要 | カテゴリ |\n|:-------|:-----|:--------|\n"
            for p in products:
                if isinstance(p, dict):
                    md += f"| {p.get('name', '')} | {p.get('description', '')} | {p.get('category', '')} |\n"
            md += "\n"

        # 技術情報（企業タブと同じく core_tech のみ）
        core_tech = tech.get("core_tech", []) or []
        if core_tech:
            md += "### 技術情報\n\n"
            md += ", ".join(f"`{t}`" for t in core_tech) + "\n\n"

        # 展示内容（企業タブと同じ confidence アイコン + content）
        contents = exh.get("contents", []) or []
        if contents:
            md += "### 展示内容\n\n"
            conf_icon = {"confirmed": "🟢", "official": "🔵", "estimated": "🟡"}
            for c in contents:
                if isinstance(c, dict):
                    icon = conf_icon.get(c.get("confidence", ""), "🟡")
                    md += f"- {icon} {c.get('content', '')}\n"
            md += "\n"

        # エビデンス（企業タブと同じく上位5件のリンク）
        if sources:
            md += "### エビデンス\n\n"
            for s in sources[:5]:
                if isinstance(s, dict):
                    title = s.get("title") or s.get("url", "リンク")
                    url = s.get("url", "")
                    md += f"- [{title}]({url})\n"
            md += "\n"

        md += "---\n\n"

    md += """> 生成: Vertex AI Gemini 2.5 Flash + Google検索グラウンディング
"""
    return md


def generate_visit_list_text(
    exhibition: ExhibitionInfo,
    companies: list[dict],
    purpose: str,
    themes: list[str],
) -> str:
    """訪問リストをテキスト形式で出力"""
    now = datetime.now().strftime("%Y-%m-%d")
    themes_str = " / ".join(themes)

    text = f"""=== 展示会 訪問リスト ===
作成日: {now}

■ 展示会情報
展示会名: {exhibition.name}
会場: {exhibition.venue}
会期: {exhibition.dates}
URL: {exhibition.url}

■ 目的
{purpose}

■ 関心テーマ
{themes_str}

■ 訪問予定企業
"""
    for i, c in enumerate(companies, 1):
        name = c.get("name", "")
        memo = c.get("memo", "")
        text += f"\n{i}. {name}"
        if memo:
            text += f"\n   メモ: {memo}"

    text += "\n\n=== END ===\n"
    return text
