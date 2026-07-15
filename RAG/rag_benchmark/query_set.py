"""テストクエリ 20 問 (具体 10 + 俯瞰 10)."""
from __future__ import annotations

from typing import TypedDict


class Query(TypedDict):
    id: str
    type: str  # "specific" or "global"
    query: str
    ground_truth_keywords: list[str]
    expected_answer_direction: str


QUERY_SET: list[Query] = [
    {"id": "Q01", "type": "specific",
     "query": "レーザー変位センサで自動車部品の高さを検査する場合、OKになる条件は何ですか？",
     "ground_truth_keywords": ["自動車", "高さ", "検査", "OK"],
     "expected_answer_direction": "OK条件の具体例"},
    {"id": "Q02", "type": "specific",
     "query": "透明体のワークを測定する場合、NGになりやすい理由を教えてください",
     "ground_truth_keywords": ["透明", "NG", "反射", "材質"],
     "expected_answer_direction": "NG理由"},
    {"id": "Q03", "type": "specific",
     "query": "ロボットハンドにセンサを取り付けて部品の有無を確認する事例はありますか？",
     "ground_truth_keywords": ["ロボット", "有無", "搬送", "ハンド"],
     "expected_answer_direction": "具体事例"},
    {"id": "Q04", "type": "specific",
     "query": "高温環境（200度以上）での測定はOK判定されますか？",
     "ground_truth_keywords": ["高温", "耐環境", "NG"],
     "expected_answer_direction": "NG傾向"},
    {"id": "Q05", "type": "specific",
     "query": "基板実装の工程でZP-Lを提案する場合の注意点は？",
     "ground_truth_keywords": ["基板", "はんだ", "実装"],
     "expected_answer_direction": "注意点・制約"},
    {"id": "Q06", "type": "specific",
     "query": "IL置換でOKになる典型的なケースは何ですか？",
     "ground_truth_keywords": ["IL", "置換", "OK"],
     "expected_answer_direction": "置換成功パターン"},
    {"id": "Q07", "type": "specific",
     "query": "ウェハの反り測定にZP-Lを使った事例の結果は？",
     "ground_truth_keywords": ["ウェハ", "反り", "半導体"],
     "expected_answer_direction": "事例の結果"},
    {"id": "Q08", "type": "specific",
     "query": "段差が0.1mm以下の微小測定はこのセンサで対応可能ですか？",
     "ground_truth_keywords": ["微小", "段差", "分解能"],
     "expected_answer_direction": "条件依存"},
    {"id": "Q09", "type": "specific",
     "query": "食品包装ラインでの変位センサ導入はOKですか？",
     "ground_truth_keywords": ["食品", "包装", "粉塵"],
     "expected_answer_direction": "条件付きOK/NG"},
    {"id": "Q10", "type": "specific",
     "query": "EtherNet/IP通信が必要な案件の成約傾向はどうですか？",
     "ground_truth_keywords": ["EtherNet/IP", "通信", "NG"],
     "expected_answer_direction": "NG傾向"},
    {"id": "Q11", "type": "global",
     "query": "OK案件に共通するパターンを教えてください",
     "ground_truth_keywords": ["近距離", "金属", "反射", "標準"],
     "expected_answer_direction": "OK共通パターン列挙"},
    {"id": "Q12", "type": "global",
     "query": "NG案件の主な失注理由のトップ3は何ですか？",
     "ground_truth_keywords": ["環境", "材質", "精度", "通信"],
     "expected_answer_direction": "NG理由ランキング"},
    {"id": "Q13", "type": "global",
     "query": "検査工程と搬送工程で、成約率に差はありますか？",
     "ground_truth_keywords": ["検査", "搬送", "比較", "OK率"],
     "expected_answer_direction": "工程別比較"},
    {"id": "Q14", "type": "global",
     "query": "OKとNGの境界条件を一覧で教えてください",
     "ground_truth_keywords": ["境界", "距離", "材質", "環境"],
     "expected_answer_direction": "境界条件リスト"},
    {"id": "Q15", "type": "global",
     "query": "このセンサが最も活躍しているアプリケーション分類は何ですか？",
     "ground_truth_keywords": ["部品の高さ測定", "有無判別"],
     "expected_answer_direction": "トップアプリ分類+根拠"},
    {"id": "Q16", "type": "global",
     "query": "ILからの置換でOKになるケースとNGになるケースの違いは何ですか？",
     "ground_truth_keywords": ["IL", "置換", "差異"],
     "expected_answer_direction": "OK/NG差異"},
    {"id": "Q17", "type": "global",
     "query": "営業が商談で最も訴求すべきポイントをまとめてください",
     "ground_truth_keywords": ["訴求", "安定", "精度"],
     "expected_answer_direction": "訴求ポイント一覧"},
    {"id": "Q18", "type": "global",
     "query": "業界別のOK/NG傾向に差はありますか？",
     "ground_truth_keywords": ["自動車", "半導体", "食品"],
     "expected_answer_direction": "業界別比較"},
    {"id": "Q19", "type": "global",
     "query": "今後重点的に攻めるべきアプリケーションを推奨してください",
     "ground_truth_keywords": ["推奨", "成約率", "ポテンシャル"],
     "expected_answer_direction": "推奨+根拠"},
    {"id": "Q20", "type": "global",
     "query": "このセンサの苦手な用途・環境を整理してください",
     "ground_truth_keywords": ["苦手", "NG", "高温", "透明"],
     "expected_answer_direction": "苦手領域整理"},
]


def get_queries_by_ids(ids: list[str] | None) -> list[Query]:
    """指定 ID のみフィルタ. None なら全件."""
    if not ids:
        return list(QUERY_SET)
    id_set = set(ids)
    return [q for q in QUERY_SET if q["id"] in id_set]
