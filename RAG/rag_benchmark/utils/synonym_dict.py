"""キーワード同義語辞書と再現率計算ユーティリティ.

v1 の単純部分一致 (`kw in answer`) では、表記揺れや同義表現を取りこぼすため、
RAGAS の Context Recall に近い概念をルールベースで近似する目的で導入する.

判定順:
  1. キーワードそのものが回答に部分一致
  2. SYNONYMS 辞書に登録された別表現が回答に部分一致
  3. キーワードがコンテキスト側にしか存在しない場合は「Retrieval した
     にも関わらず Generation が拾えなかった」ことを示すフラグを返す
"""
from __future__ import annotations

from dataclasses import dataclass


# 評価対象 QUERY_SET の ground_truth_keywords をベースに整備した同義語辞書.
# 完全網羅は不可能なため、ベンチマーク上で高頻度に出現する語のみを対象とする.
SYNONYMS: dict[str, list[str]] = {
    # 通信/プロトコル
    "EtherNet/IP": ["EIP", "イーサネット", "Ethernet", "EtherNetIP"],
    "通信": ["プロトコル", "ネットワーク", "I/O", "IO接続"],
    # 環境
    "高温": ["200度", "200℃", "耐熱", "熱", "高熱", "200度以上"],
    "耐環境": ["環境条件", "耐環境性", "環境耐性", "耐久", "耐性"],
    "環境": ["環境条件", "周辺環境", "設置環境"],
    "粉塵": ["粉じん", "粉体", "ダスト", "汚れ"],
    # ワーク/材質
    "透明": ["透過", "クリア", "光透過", "透明体", "透明物質"],
    "反射": ["反射率", "正反射", "乱反射", "鏡面"],
    "金属": ["メタル", "鉄", "アルミ", "ステンレス"],
    "材質": ["素材", "ワーク材質", "対象物"],
    # 検出種別
    "有無判別": ["有無検出", "在荷", "ワーク有無", "在荷確認"],
    "有無": ["在荷", "有無検出", "有無判別"],
    "段差": ["凹み", "凸凹", "高低差"],
    "分解能": ["解像度", "精度", "μm"],
    "精度": ["分解能", "誤差", "リニアリティ"],
    "距離": ["検出距離", "測定距離", "範囲"],
    "近距離": ["短距離", "至近"],
    # 工程/アプリ
    "搬送": ["コンベア", "搬送ライン", "移送", "搬送工程"],
    "検査": ["検査工程", "判別", "良否判定"],
    "包装": ["パッケージ", "パッケージング", "梱包"],
    "ロボット": ["ロボットハンド", "アーム", "オンハンド"],
    "ハンド": ["ロボットハンド", "オンハンド"],
    "基板": ["基板実装", "PCB", "プリント基板"],
    "はんだ": ["半田", "ハンダ", "ソルダ"],
    "実装": ["基板実装", "搭載"],
    "ウェハ": ["ウエハ", "ウェーハ", "半導体ウェハ"],
    "半導体": ["シリコン", "ウェハ", "半導体製造"],
    "自動車": ["車載", "自動車部品", "車両"],
    "食品": ["食品ライン", "食品包装"],
    "反り": ["そり", "歪み", "湾曲"],
    # 商談用語
    "OK": ["成約", "採用", "合格", "○", "〇", "受注", "決定"],
    "NG": ["失注", "不採用", "不可", "×", "不採用"],
    "OK率": ["成約率", "勝率", "採用率"],
    "成約率": ["OK率", "勝率", "採用率"],
    "境界": ["境目", "閾値", "しきい値", "ボーダー"],
    "比較": ["比較分析", "対比"],
    "差異": ["違い", "差", "ギャップ"],
    "推奨": ["おすすめ", "提案", "リコメンド"],
    "訴求": ["アピール", "セールスポイント", "強み"],
    "安定": ["安定検出", "安定性", "再現性"],
    "標準": ["標準仕様", "デフォルト"],
    "IL": ["インダクティブ", "誘導形", "近接", "近接センサ"],
    "置換": ["リプレース", "置き換え", "切替"],
    # 質問軸
    "ポテンシャル": ["将来性", "見込み", "余地"],
    "苦手": ["不得意", "弱点", "向かない"],
    "部品の高さ測定": ["高さ計測", "高さ検出", "高さ判別"],
}


@dataclass
class CoverageDetail:
    """1 ジョブのキーワード被覆計算結果."""

    coverage: float            # 0.0 - 1.0
    matched: list[str]         # 答えに含まれていたキーワード (同義語含む)
    missed: list[str]          # 答えに含まれていなかったキーワード
    only_in_context: list[str] # 答えには無いがコンテキストには出ていたもの


def _normalize(s: str) -> str:
    return (s or "").lower()


def _expand(keyword: str) -> list[str]:
    """キーワード本体 + 同義語のリストを返す (重複排除済み, 空文字除外)."""
    alts = SYNONYMS.get(keyword, [])
    pool = [keyword, *alts]
    seen: set[str] = set()
    expanded: list[str] = []
    for w in pool:
        if not w:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        expanded.append(w)
    return expanded


def coverage_with_synonyms(
    keywords: list[str],
    answer: str,
    contexts: list[str] | None = None,
) -> CoverageDetail:
    """同義語辞書を考慮した keyword coverage を返す.

    Parameters
    ----------
    keywords : list[str]
        評価したいキーワード (query_set の ground_truth_keywords)
    answer : str
        評価対象の回答
    contexts : list[str] | None
        Retrieval が返したコンテキスト. 与えると `only_in_context` を埋める.
    """
    if not keywords:
        return CoverageDetail(coverage=0.0, matched=[], missed=[], only_in_context=[])

    ans_norm = _normalize(answer)
    ctx_norm = _normalize("\n".join(contexts or []))

    matched: list[str] = []
    missed: list[str] = []
    only_in_context: list[str] = []

    for kw in keywords:
        variants = _expand(kw)
        if any(v.lower() in ans_norm for v in variants):
            matched.append(kw)
            continue
        # answer には無い → context にあるかをチェック
        if contexts and any(v.lower() in ctx_norm for v in variants):
            only_in_context.append(kw)
        missed.append(kw)

    coverage = len(matched) / len(keywords)
    return CoverageDetail(
        coverage=round(coverage, 3),
        matched=matched,
        missed=missed,
        only_in_context=only_in_context,
    )
