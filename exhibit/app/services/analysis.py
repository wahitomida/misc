# -*- coding: utf-8 -*-
"""分析生成サービス（ローカル集計のみ、API呼び出しなし）"""

from __future__ import annotations
from collections import Counter
from typing import Any


def _get(d: Any, *keys, default=None):
    """ネストされた辞書から安全に値を取得"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _company_name(c: dict) -> str:
    return _get(c, "basic_info", "official_name") or c.get("company_name", "不明")


# === 各分析の実装 ===

def _analyze_relevance_bar(companies: list[dict]) -> dict:
    """1. 関連度比較（横棒グラフ）"""
    items = []
    for c in companies:
        name = _company_name(c)
        score = c.get("relevance_score") or 1
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 1
        items.append((name, score))
    items.sort(key=lambda x: x[1], reverse=True)
    color_map = {3: "#6366F1", 2: "#818CF8", 1: "#C7D2FE"}
    return {
        "labels": [n for n, _ in items],
        "scores": [s for _, s in items],
        "colors": [color_map.get(s, "#C7D2FE") for _, s in items],
    }


def _analyze_industry_doughnut(companies: list[dict]) -> dict:
    """2. 業種・カテゴリ分布（ドーナツ）"""
    counter = Counter()
    for c in companies:
        ind = _get(c, "business", "industry") or "不明"
        if not isinstance(ind, str):
            ind = "不明"
        counter[ind.strip() or "不明"] += 1
    items = counter.most_common()
    return {
        "labels": [k for k, _ in items],
        "values": [v for _, v in items],
        "total": sum(counter.values()),
    }


def _analyze_theme_matrix(companies: list[dict], all_themes: list[str]) -> dict:
    """3. テーマ×企業マトリクス"""
    themes = list(all_themes) if all_themes else []
    seen_themes = set(themes)
    for c in companies:
        for t in (c.get("relevance_themes") or []):
            if isinstance(t, str) and t.strip() and t not in seen_themes:
                themes.append(t)
                seen_themes.add(t)

    company_names = [_company_name(c) for c in companies]
    matrix = []
    for c in companies:
        matched = set(c.get("relevance_themes") or [])
        score = c.get("relevance_score") or 1
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 1
        row = []
        for t in themes:
            if t in matched:
                row.append("◎" if score >= 3 else "○" if score >= 2 else "△")
            else:
                row.append("")
        matrix.append(row)
    return {
        "themes": themes,
        "companies": company_names,
        "matrix": matrix,
    }


def _analyze_tech_wordcloud(companies: list[dict]) -> dict:
    """4. 技術トレンドワードクラウド"""
    counter = Counter()
    company_map: dict[str, list[str]] = {}
    for c in companies:
        name = _company_name(c)
        techs = _get(c, "technology", "core_tech") or []
        if not isinstance(techs, list):
            techs = [str(techs)]
        for t in techs:
            if isinstance(t, str) and t.strip():
                key = t.strip()
                counter[key] += 1
                company_map.setdefault(key, []).append(name)
    if not counter:
        return {"words": []}
    max_count = max(counter.values())
    words = []
    for word, cnt in counter.most_common(50):
        # サイズは 14〜48 にスケーリング
        size = 14 + int(34 * (cnt / max_count))
        words.append({
            "text": word,
            "size": size,
            "count": cnt,
            "companies": company_map.get(word, []),
        })
    return {"words": words}


def _estimate_size_score(emp_str: str) -> int:
    """従業員数文字列から企業規模スコア (0-100) を推定"""
    if not isinstance(emp_str, str):
        return 30
    import re
    digits = re.sub(r"[^\d]", "", emp_str.replace(",", "").replace("万", "0000"))
    if not digits:
        return 30
    try:
        n = int(digits[:7])
        if n >= 100000:
            return 95
        if n >= 10000:
            return 80
        if n >= 1000:
            return 60
        if n >= 100:
            return 40
        return 20
    except ValueError:
        return 30


def _estimate_tech_score(c: dict) -> int:
    """技術成熟度スコア (0-100) を推定"""
    score = 30
    techs = _get(c, "technology", "core_tech") or []
    if isinstance(techs, list):
        score += min(len(techs) * 5, 25)
    api = _get(c, "technology", "api_sdk") or ""
    if isinstance(api, str) and api.strip() and api.strip() != "不明":
        score += 15
    oss = _get(c, "technology", "open_source") or ""
    if isinstance(oss, str) and oss.strip() and oss.strip() != "不明":
        score += 15
    patents = _get(c, "technology", "patents") or ""
    if isinstance(patents, str) and patents.strip() and patents.strip() != "不明":
        score += 15
    return min(score, 100)


def _analyze_bubble(companies: list[dict]) -> dict:
    """5. 企業規模×技術成熟度バブルチャート"""
    bubbles = []
    for c in companies:
        name = _company_name(c)
        emp = _get(c, "basic_info", "employees") or ""
        size_x = _estimate_size_score(emp)
        tech_y = _estimate_tech_score(c)
        relevance = c.get("relevance_score") or 1
        try:
            relevance = int(relevance)
        except (TypeError, ValueError):
            relevance = 1
        bubbles.append({
            "name": name,
            "x": size_x,
            "y": tech_y,
            "size": 10 + relevance * 10,
            "relevance": relevance,
        })
    return {"bubbles": bubbles}


def _analyze_network(companies: list[dict]) -> dict:
    """6. 企業間競合・連携マップ"""
    names = set()
    nodes = []
    links = []
    for c in companies:
        n = _company_name(c)
        if n not in names:
            names.add(n)
            nodes.append({"id": n, "group": 1})

    for c in companies:
        src = _company_name(c)
        competitors = _get(c, "market", "competitors") or []
        if not isinstance(competitors, list):
            continue
        for comp in competitors:
            if not isinstance(comp, str) or not comp.strip():
                continue
            target = comp.strip()
            if target not in names:
                names.add(target)
                nodes.append({"id": target, "group": 2})
            links.append({"source": src, "target": target, "type": "competitor"})

    return {"nodes": nodes, "links": links}


def _mark_from_text(text: str, *keywords: str) -> str:
    """テキストにキーワードが含まれていれば ◎、空でなければ ○、空なら ×"""
    if not isinstance(text, str):
        return "×"
    t = text.strip()
    if not t or t in ("不明", "—", "-"):
        return "×"
    lower = t.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return "◎"
    return "○"


ANALYSIS_REGISTRY = {
    1: _analyze_relevance_bar,
    2: _analyze_industry_doughnut,
    4: _analyze_tech_wordcloud,
    5: _analyze_bubble,
    6: _analyze_network,
}


async def execute_analysis(report_data: dict, analysis_type: int) -> dict:
    """選択された分析を実行（API呼び出しなし、ローカル集計のみ）"""
    companies = report_data.get("results", [])
    if not companies:
        return {"type": analysis_type, "data": None, "error": "データがありません"}

    try:
        if analysis_type == 3:
            themes = report_data.get("themes", []) or []
            data = _analyze_theme_matrix(companies, themes)
        else:
            fn = ANALYSIS_REGISTRY.get(analysis_type)
            if not fn:
                return {"type": analysis_type, "data": None, "error": "不明な分析タイプ"}
            data = fn(companies)
        return {"type": analysis_type, "data": data}
    except Exception as e:
        return {"type": analysis_type, "data": None, "error": str(e)}
