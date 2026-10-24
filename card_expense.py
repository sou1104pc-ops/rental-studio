"""クレジットカード明細CSVの読み取りと経費の仕分けロジック。

カード会社ごとにCSVの形（文字コード・先頭の案内行・列名）が違うため、
・文字コードを自動判別し
・「日付」「金額」らしい列名がある行を見出し行として探し（無ければ見出しなしとして扱う）
・日付／利用先／金額の列を推測する
までをここで行う。列の最終決定と保存は app.py の画面側で行う。
"""
import csv
import hashlib
import io
import re
import unicodedata
from typing import List, Optional, Tuple

import pandas as pd

EXPENSE_CATEGORIES = [
    "未分類", "消耗品費", "備品費", "水道光熱費", "通信費", "広告宣伝費", "支払手数料",
    "地代家賃", "修繕費", "旅費交通費", "会議費", "外注費", "雑費",
]
BUSINESS_WIDE = "事業全体"     # 店舗に紐づかない経費

DATE_WORDS   = ["利用日", "ご利用日", "日付", "年月日", "取引日", "利用年月日", "date"]
DESC_WORDS   = ["利用先", "ご利用先", "利用店", "店名", "内容", "摘要", "加盟店", "利用店名", "ご利用店名", "description", "merchant"]
AMOUNT_WORDS = ["利用金額", "ご利用金額", "金額", "支払金額", "お支払金額", "請求金額", "amount"]

EXPENSE_COLS = ["明細ID", "利用日", "月", "利用先", "金額", "カード", "科目", "店舗", "経費", "メモ"]


def _norm(s) -> str:
    return unicodedata.normalize("NFKC", str(s)).strip().lower()


def decode_csv(raw: bytes) -> str:
    """UTF-8（BOM付き含む）→ Shift_JIS(cp932) → UTF-16 の順に試して文字列にする。"""
    for enc in ("utf-8-sig", "cp932", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("cp932", errors="replace")


def read_rows(text: str) -> List[List[str]]:
    rows = list(csv.reader(io.StringIO(text)))
    return [r for r in rows if any(c.strip() for c in r)]


def find_header(rows: List[List[str]], scan: int = 20) -> Optional[int]:
    """日付らしい列名と金額らしい列名の両方を含む最初の行。無ければ None（見出しなし）。"""
    for i, r in enumerate(rows[:scan]):
        cells = [_norm(c) for c in r]
        has_date = any(any(w in c for w in DATE_WORDS) for c in cells)
        has_amt = any(any(w in c for w in AMOUNT_WORDS) for c in cells)
        if has_date and has_amt:
            return i
    return None


def to_frame(rows: List[List[str]], header_row: Optional[int]) -> pd.DataFrame:
    """見出し行より下を DataFrame に。見出しなしなら「列1, 列2, …」と名付ける。"""
    if header_row is None:
        body = rows
        width = max((len(r) for r in body), default=0)
        cols = [f"列{i + 1}" for i in range(width)]
    else:
        cols, body = rows[header_row], rows[header_row + 1:]
        width = max([len(cols)] + [len(r) for r in body])
        seen, fixed = {}, []
        for i in range(width):
            name = (cols[i].strip() if i < len(cols) else "") or f"列{i + 1}"
            seen[name] = seen.get(name, 0) + 1
            fixed.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
        cols = fixed
    body = [r + [""] * (width - len(r)) for r in body]
    return pd.DataFrame([r[:width] for r in body], columns=cols)


def parse_dates(series: pd.Series) -> pd.Series:
    """2026/10/01・2026-10-01・20261001・2026年10月1日・26/10/01 などを日付に。"""
    def one(v):
        s = unicodedata.normalize("NFKC", str(v)).strip()
        if not s:
            return pd.NaT
        s = re.sub(r"[年月]", "/", s).replace("日", "")
        s = re.sub(r"\s.*$", "", s)                       # 時刻などを落とす
        if re.fullmatch(r"\d{8}", s):
            return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
        m = re.fullmatch(r"(\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
        if m:                                            # 西暦下2桁
            s = f"20{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return pd.to_datetime(s.replace("-", "/").replace(".", "/"), format="%Y/%m/%d", errors="coerce")
    return series.apply(one)


def parse_amounts(series: pd.Series) -> pd.Series:
    """¥・カンマ・円・空白を除いて数値に。（1,000）や▲1,000 はマイナス扱い。"""
    def one(v):
        s = unicodedata.normalize("NFKC", str(v)).strip()
        neg = s.startswith(("▲", "△", "(", "-")) and len(s) > 1
        s = re.sub(r"[^\d.]", "", s)
        if not s or s == ".":
            return None
        try:
            n = float(s)
        except ValueError:
            return None
        return -n if neg else n
    return pd.to_numeric(series.apply(one), errors="coerce")


def guess_columns(df: pd.DataFrame) -> dict:
    """日付・利用先・金額の列を、列名 → 中身の順で推測する。"""
    cols = list(df.columns)

    def by_name(words):
        for w in words:
            for c in cols:
                if w in _norm(c):
                    return c
        return None

    sample = df.head(50)

    def hit_rate(c, parser):
        """空欄を除いた値のうち、読めた割合（名義行・合計行が混ざっていても判定できるように）"""
        vals = sample[c][sample[c].astype(str).str.strip() != ""]
        return parser(vals).notna().mean() if len(vals) else 0.0

    date_c = by_name(DATE_WORDS)
    if date_c is None:
        scores = {c: hit_rate(c, parse_dates) for c in cols}
        date_c = max(scores, key=scores.get) if scores and max(scores.values()) >= 0.5 else None
    amt_c = by_name(AMOUNT_WORDS)
    if amt_c is None:
        cand = [c for c in cols if c != date_c]
        scores = {c: hit_rate(c, parse_amounts) for c in cand}
        # 数値の列が複数あるときは右側（合計・支払額が多い）より左側の最初の列を優先
        amt_c = next((c for c in cand if scores.get(c, 0) >= 0.6), None)
    desc_c = by_name(DESC_WORDS)
    if desc_c is None:
        cand = [c for c in cols if c not in (date_c, amt_c)]
        lens = {c: sample[c].astype(str).str.len().mean() for c in cand}
        desc_c = max(lens, key=lens.get) if lens else None
    return {"date": date_c, "desc": desc_c, "amount": amt_c}


def signature(df: pd.DataFrame, header_row: Optional[int]) -> str:
    """同じカード会社のCSVかどうかを見分けるための目印（見出しの並び）。"""
    key = "|".join(map(str, df.columns)) if header_row is not None else f"noheader:{len(df.columns)}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def apply_rules(row: dict, rules: List[dict]) -> dict:
    """利用先に含まれるキーワードで、科目・店舗・経費にするかを決める（最初に当たったルール）。"""
    desc = _norm(row.get("利用先", ""))
    for r in rules:
        kw = _norm(r.get("キーワード", ""))
        if kw and kw in desc:
            out = dict(row)
            if r.get("処理") == "除外":
                out["経費"] = False
            else:
                out["経費"] = True
                if r.get("科目"):
                    out["科目"] = r["科目"]
                if r.get("店舗"):
                    out["店舗"] = r["店舗"]
            return out
    return row


def build_expenses(df: pd.DataFrame, mapping: dict, card: str, rules: List[dict]) -> Tuple[pd.DataFrame, int]:
    """CSV の DataFrame から経費明細を作る。日付か金額が読めない行（合計行など）は飛ばす。

    明細ID = カード・日付・利用先・金額 + 同じ組み合わせの何件目か。
    同じCSVや期間の重なったCSVを取り込み直しても、同じ明細は同じIDになる。
    """
    dates = parse_dates(df[mapping["date"]])
    amts = parse_amounts(df[mapping["amount"]])
    descs = df[mapping["desc"]].astype(str).str.strip() if mapping.get("desc") else pd.Series("", index=df.index)
    rows, seen, skipped = [], {}, 0
    for i in df.index:
        d, a = dates[i], amts[i]
        if pd.isna(d) or pd.isna(a) or a == 0:
            skipped += 1
            continue
        base = f"{card}|{d:%Y-%m-%d}|{descs[i]}|{a:.0f}"
        seen[base] = seen.get(base, 0) + 1
        row = {
            "明細ID": hashlib.md5(f"{base}|{seen[base]}".encode("utf-8")).hexdigest()[:16],
            "利用日": d, "月": f"{d:%Y-%m}", "利用先": descs[i], "金額": float(a),
            "カード": card, "科目": "未分類", "店舗": BUSINESS_WIDE, "経費": True, "メモ": "",
        }
        rows.append(apply_rules(row, rules))
    return pd.DataFrame(rows, columns=EXPENSE_COLS), skipped
