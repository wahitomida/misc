# -*- coding: utf-8 -*-
"""企業調査サービス"""

from __future__ import annotations
import asyncio
import logging
from app.services.grounding import call_gemini_json
from app.models.schemas import CompanyResult, CompanyInput, ExhibitionInfo
from app.config import settings

logger = logging.getLogger("exhibit.company")
logger.setLevel(logging.INFO)


def _build_company_prompt(
    company: CompanyInput,
    exhibition: ExhibitionInfo,
    purpose: str,
    themes: list[str],
) -> str:
    """企業調査用プロンプトを構築（バックアップ版のシンプル&強力なパターンを踏襲）"""
    themes_str = "、".join(themes) if themes else ""
    company_memo = company.memo if company.memo else ""
    return f"""あなたの作業は2段階です。

【第1段階：調査】
以下の企業について、Google検索を使って徹底的に調査してください。
公式Webサイト、IR、製品ページ、ニュース、プレスリリース、業界メディア、Wikipedia等を幅広く参照すること。
記憶や推測ではなく、必ず検索で得た情報を使うこと。

調査対象企業: {company.name}

【第2段階：出力】
調査結果を、以下のJSONフォーマット「のみ」で出力してください。
それ以外の文章、補足、前置き、まとめは一切出力しないでください。

```json
{{
  "basic_info": {{
    "official_name": "正式社名（例: 株式会社○○）",
    "headquarters": "本社所在地（都道府県・市区町村）",
    "founded": "設立年（西暦）",
    "employees": "従業員数（出典年付き、例: 約12,000名（2024年）)",
    "revenue": "売上高（出典年付き、例: 1,234億円（2024年3月期）)",
    "url": "公式サイトURL"
  }},
  "business": {{
    "industry": "業種カテゴリ（例: ITソリューション）",
    "main_products": [
      {{"name": "製品/サービス名", "description": "概要1文", "category": "カテゴリ"}}
    ]
  }},
  "technology": {{
    "core_tech": ["コア技術1", "コア技術2", "コア技術3"],
    "tech_stack": "使用している主な技術・プラットフォーム",
    "api_sdk": "API/SDK提供の有無と詳細",
    "open_source": "OSS貢献・公開リポジトリ",
    "patents": "代表的な特許・特許出願数"
  }},
  "exhibition": {{
    "status": "confirmed",
    "evidence_url": "出展確認のエビデンスURL",
    "contents": [
      {{"content": "想定される展示内容/サービス紹介", "confidence": "official", "source": "情報源URL"}}
    ]
  }},
  "market": {{
    "competitors": ["競合1", "競合2", "競合3"],
    "market_share": "市場ポジション・シェア情報",
    "target": "ターゲット顧客・業界",
    "case_studies": "代表的な導入実績・顧客例"
  }},
  "collaboration": {{
    "api_level": "◎",
    "trial": "無料試用・トライアルの有無",
    "partner_program": "パートナー制度の詳細",
    "pricing": "価格帯・課金体系"
  }},
  "relevance_score": 3,
  "relevance_themes": ["マッチするテーマ"]
}}
```

【出力ルール】
- 出力はJSONブロック（```jsonで囲んだもの）のみ。それ以外の文章は書かない。
- 不明な項目は文字列 "不明" を入れる（null や 空文字ではなく）。
- 各情報は検索で確認できた事実のみ記載。推測は避ける。
- 配列項目（main_products, core_tech, competitors）は最低1件、見つかれば3件以上記載。
- relevance_score: 3=複数テーマ該当 or 強関連 / 2=1テーマに関連 / 1=やや関連
- exhibition.status: confirmed=出展者ページで確認済 / estimated=プレスリリース等で推定 / unknown=不明
- exhibition.contents.confidence: confirmed=現地確認 / official=公式情報 / estimated=推測

【参考情報】
- 展示会: {exhibition.name}
- 出展者一覧URL: {exhibition.exhibitor_list_url or exhibition.url}
- 関心テーマ（OR条件）: {themes_str}
- ユーザーメモ: {company_memo}
- 調査目的（参考）: {purpose}
"""


# AIが生成しがちな架空URL・サイトアドレスのパターン
FAKE_URL_PATTERNS = [
    "example.com", "example.jp", "example.org",
    "company.com", "hogehoge", "yourdomain",
    "placeholder", "sample-url", "xxx.com", "yyy.com",
    "your-domain", "domain.com",
]


def _is_likely_fake_url(url: str) -> bool:
    """AIが生成しそうな架空URLかをチェック"""
    if not url or not isinstance(url, str):
        return True
    lower = url.lower().strip()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return True
    for pat in FAKE_URL_PATTERNS:
        if pat in lower:
            return True
    return False


def _sanitize_urls_in_result(result: dict, sources: list[dict]) -> dict:
    """AIが生成した架空URLを grounding_chunks の実在URLで置換・除去"""
    if not isinstance(result, dict):
        return result
    valid_urls = [s.get("url") for s in sources if s.get("url")]
    primary_url = valid_urls[0] if valid_urls else ""

    # basic_info.url（公式サイト）が架空URLの場合は実在URLで置換
    bi = result.get("basic_info") or {}
    if isinstance(bi, dict):
        url = bi.get("url", "")
        if url and _is_likely_fake_url(url):
            bi["url"] = primary_url if primary_url else "不明"
        result["basic_info"] = bi

    # exhibition.evidence_url を grounding ソース先頭で付与
    exh = result.get("exhibition") or {}
    if isinstance(exh, dict):
        ev = exh.get("evidence_url", "")
        if not ev or _is_likely_fake_url(ev):
            exh["evidence_url"] = primary_url if primary_url else ""
        contents = exh.get("contents") or []
        for c in contents:
            if isinstance(c, dict):
                src = c.get("source", "")
                if src and _is_likely_fake_url(src):
                    c["source"] = primary_url if primary_url else ""
        exh["contents"] = contents
        result["exhibition"] = exh

    return result


async def investigate_company(
    company: CompanyInput,
    exhibition: ExhibitionInfo,
    purpose: str,
    themes: list[str],
) -> CompanyResult:
    """1社の調査を実行（タイムアウトなし、複数検索で詳細調査）"""
    prompt = _build_company_prompt(company, exhibition, purpose, themes)
    logger.info(f"[Company] 調査開始: {company.name}")
    try:
        result, sources, queries = await call_gemini_json(prompt, max_output_tokens=8192)
        logger.info(f"[Company] {company.name}: 完了 (検索クエリ:{len(queries)}, ソース:{len(sources)})")
        if result and "raw_text" not in result:
            # AIが生成した架空URLをgrounding実在URLで置換
            result = _sanitize_urls_in_result(result, sources)
            return CompanyResult(
                company_name=company.name,
                basic_info=result.get("basic_info", {}) or {},
                business=result.get("business", {}) or {},
                technology=result.get("technology", {}) or {},
                exhibition=result.get("exhibition", {}) or {},
                market=result.get("market", {}) or {},
                collaboration=result.get("collaboration", {}) or {},
                relevance_score=result.get("relevance_score", 1) or 1,
                relevance_themes=result.get("relevance_themes", []) or [],
                sources=sources,
                search_queries=queries,
                status="completed",
            )
        else:
            logger.warning(f"[Company] {company.name}: JSON解析失敗")
            return CompanyResult(
                company_name=company.name,
                sources=sources,
                search_queries=queries,
                status="completed",
                error="JSON解析に失敗しましたが、検索は完了しました",
            )
    except Exception as e:
        logger.exception(f"[Company] {company.name}: 例外 {e}")
        return CompanyResult(
            company_name=company.name,
            status="error",
            error=str(e),
        )
