# -*- coding: utf-8 -*-
"""おすすめ企業提案サービス"""

import asyncio
import logging
from urllib.parse import urlparse

from app.services.grounding import call_gemini_json
from app.models.schemas import ExhibitionInfo

logger = logging.getLogger("exhibit.recommend")
logger.setLevel(logging.INFO)


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc if url else ""
    except Exception:
        return ""


async def _recommend_for_theme(
    exhibition: ExhibitionInfo,
    theme: str,
    purpose: str,
) -> list[dict]:
    """1つのテーマに対して出展企業を検索する。

    展示会の出展者ページを Google 検索でたどり、テーマに関連する企業を最大8社抽出。
    各社に relevance_score (1-3) と reason を付ける。
    """
    exhibitor_url = exhibition.exhibitor_list_url or exhibition.url
    base_url = exhibition.url or exhibitor_url
    domain = _domain_of(base_url)

    prompt = f"""あなたは展示会の出展企業リサーチの専門家です。
1つのテーマに対して、展示会の出展企業から関連する企業を最大8社、Google検索で抽出してください。

【展示会情報】
展示会名: {exhibition.name}
公式トップ: {base_url}
出展者一覧URL（参考）: {exhibitor_url}
公式ドメイン: {domain}

【今回のテーマ】
{theme}

【検索手順】
必ず以下の順に検索を試し、出展者一覧ページや出展企業詳細ページの実データを参照すること。
公式トップだけを見るのは禁止。下層ページを必ずたどる。

  1. site:{domain} 出展者
  2. site:{domain} exhibitor
  3. site:{domain} "{theme}"
  4. "{exhibition.name}" 出展者一覧
  5. "{exhibition.name}" "{theme}" 出展
  6. "{exhibition.name}" "{theme}" exhibitor
  7. "{theme}" 出展企業 "{exhibition.name}"

【選定基準】
- 上記の検索結果から、テーマ「{theme}」に関連する **実在する出展企業** を最大8社選ぶ
- 関連度の判断: 製品/サービス/技術領域がテーマに合致するか
- relevance_score: 3=テーマがその企業の主力領域 / 2=テーマが主要事業の一つ / 1=テーマに部分的に関連
- 出展未確認の場合のみ、reason に「※推測（出展未確認）」と明記

【最終判断の参考（検索クエリには使わないこと）】
調査目的: {purpose}

【出力】
JSON のみ。前置きや説明は一切書かない。

```json
{{
  "companies": [
    {{
      "name": "企業の正式名称",
      "industry": "業種カテゴリ（例: AI/ML, クラウド, セキュリティ）",
      "reason": "テーマ「{theme}」との関連の根拠を1文で",
      "relevance_score": 3
    }}
  ]
}}
```
"""
    try:
        result, sources, queries = await call_gemini_json(prompt, max_output_tokens=3072)
        if not result or "companies" not in result:
            logger.warning(f"[Recommend/{theme}] no companies. Raw: {str(result)[:200]}")
            return []
        companies = result["companies"] or []
        # テーマ情報を付与
        for c in companies:
            if isinstance(c, dict):
                c["matching_themes"] = [theme]
                # AIが付けたかもしれないURLを破棄
                c.pop("evidence_url", None)
                c.pop("url", None)
        logger.info(f"[Recommend/{theme}] {len(companies)}社 (queries={len(queries)}, sources={len(sources)})")
        return [c for c in companies if isinstance(c, dict) and c.get("name")]
    except Exception as e:
        logger.exception(f"[Recommend/{theme}] 例外: {e}")
        return []


def _merge_and_rank(
    per_theme_results: list[tuple[str, list[dict]]],
    max_total: int = 20,
) -> list[dict]:
    """テーマごとの結果をマージし、優先順位でソートする。

    優先順位:
      1. 該当テーマ数が多い企業（複数テーマでヒットした企業）
      2. relevance_score の合計が高い順
      3. テーマ別の出現順（最初のテーマほど優先）
    """
    # company_name (lowered) -> 統合データ
    merged: dict[str, dict] = {}
    for theme_idx, (theme, companies) in enumerate(per_theme_results):
        for c in companies:
            name = c.get("name", "").strip()
            if not name:
                continue
            key = name.lower()
            if key in merged:
                # 既存企業: テーマを追加・スコアを集計
                existing = merged[key]
                if theme not in existing["matching_themes"]:
                    existing["matching_themes"].append(theme)
                existing["_score_sum"] += int(c.get("relevance_score") or 1)
                existing["_theme_count"] += 1
                # reason はテーマごとに改行で追記
                new_reason = c.get("reason", "")
                if new_reason and new_reason not in existing["reason"]:
                    existing["reason"] = existing["reason"] + " / " + new_reason
            else:
                merged[key] = {
                    "name": name,
                    "industry": c.get("industry", ""),
                    "reason": c.get("reason", ""),
                    "matching_themes": list(c.get("matching_themes", [theme])),
                    "relevance_score": int(c.get("relevance_score") or 1),
                    "_score_sum": int(c.get("relevance_score") or 1),
                    "_theme_count": 1,
                    "_first_theme_idx": theme_idx,
                }

    # ソート: テーマ数降順 → スコア合計降順 → 初出テーマ昇順
    sorted_companies = sorted(
        merged.values(),
        key=lambda x: (-x["_theme_count"], -x["_score_sum"], x["_first_theme_idx"]),
    )

    # 最終的な relevance_score を再計算（複数テーマヒットで底上げ）
    for c in sorted_companies:
        # テーマ複数該当なら max=3、単一テーマで強関連なら元のスコア、それ以外は1-3
        if c["_theme_count"] >= 2:
            c["relevance_score"] = 3
        else:
            c["relevance_score"] = max(1, min(3, c["_score_sum"]))
        # 内部キーを削除
        c.pop("_score_sum", None)
        c.pop("_theme_count", None)
        c.pop("_first_theme_idx", None)

    return sorted_companies[:max_total]


async def recommend_companies(
    exhibition: ExhibitionInfo,
    purpose: str,
    themes: list[str],
) -> list[dict]:
    """関心テーマごとに並列で出展企業を検索し、優先順位順に統合して返す。

    各テーマで最大8社、合計最大20社まで。
    """
    if not themes:
        return []

    # 各テーマを並列で検索（API並列上限は grounding 側のセマフォで制御）
    tasks = [_recommend_for_theme(exhibition, t, purpose) for t in themes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    per_theme_results: list[tuple[str, list[dict]]] = []
    for theme, res in zip(themes, results):
        if isinstance(res, Exception):
            logger.warning(f"[Recommend] theme '{theme}' failed: {res}")
            per_theme_results.append((theme, []))
        else:
            per_theme_results.append((theme, res))

    merged = _merge_and_rank(per_theme_results, max_total=20)
    logger.info(f"[Recommend] merged: {len(merged)}社（テーマ別: {[(t, len(r)) for t, r in per_theme_results]}）")
    return merged
