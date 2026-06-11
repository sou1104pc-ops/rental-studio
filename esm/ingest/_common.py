"""取込の共通ユーティリティ（CSV読込・列名のあいまい一致）。"""
from __future__ import annotations

import pandas as pd


def read_csv(path: str) -> pd.DataFrame:
    """日本語CSV（Shift_JIS / UTF-8 / BOM付き）を頑健に読む。"""
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except (UnicodeDecodeError, UnicodeError):
            continue
    # 最後の手段：エラー無視で読む
    return pd.read_csv(path, dtype=str, encoding="cp932", encoding_errors="ignore").fillna("")


def find_col(columns, candidates: list[str]) -> str | None:
    """候補語のいずれかを「含む」列名を探して返す（部分一致・大文字小文字無視）。"""
    norm = {c: str(c).strip().lower() for c in columns}
    for cand in candidates:
        cl = cand.lower()
        for original, low in norm.items():
            if cl in low:
                return original
    return None
