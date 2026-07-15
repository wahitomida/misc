"""pytest 共通設定。

``misc_26/Orchestra`` 直下で ``pytest`` を実行できるように、リポジトリ内パッケージ
(``core``, ``tests`` など) を ``sys.path`` に追加する。
"""

from __future__ import annotations

import sys
from pathlib import Path

ORCHESTRA_ROOT = Path(__file__).resolve().parent
if str(ORCHESTRA_ROOT) not in sys.path:
    sys.path.insert(0, str(ORCHESTRA_ROOT))
