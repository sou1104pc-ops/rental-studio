"""銀行の入出金明細CSVを取り込む。

各銀行でフォーマットが異なるため、列名を候補語であいまい一致させる。
既定では「入金（お預入）」の行を売上として登録する。
出金も保持したい場合は include_withdrawals=True を使う（出金は amount/net を負で記録）。
"""
from __future__ import annotations

from ..util import parse_amount, parse_date
from ._common import find_col, read_csv

_C_DATE = ["取引日", "お取引日", "日付", "年月日", "date"]
_C_IN = ["お預入金額", "預入", "入金", "入金金額", "deposit", "credit"]
_C_OUT = ["お引出金額", "引出", "出金", "出金金額", "withdraw", "debit"]
_C_DESC = ["摘要", "お取引内容", "内容", "備考", "description", "memo"]
_C_BAL = ["残高", "balance"]


def parse_file(path: str, include_withdrawals: bool = False) -> list[dict]:
    df = read_csv(path)
    cols = list(df.columns)

    c_date = find_col(cols, _C_DATE)
    c_in = find_col(cols, _C_IN)
    c_out = find_col(cols, _C_OUT)
    c_desc = find_col(cols, _C_DESC)

    if not c_date or (not c_in and not c_out):
        raise ValueError(
            f"銀行CSV の必須列が見つかりません（日付/入出金）。検出列: {cols}"
        )

    rows: list[dict] = []
    for i, r in df.iterrows():
        d = parse_date(str(r[c_date])[:10])
        if not d:
            continue
        deposit = parse_amount(r[c_in]) if c_in else 0
        withdraw = parse_amount(r[c_out]) if c_out else 0
        desc = str(r[c_desc]) if c_desc else ""

        if deposit > 0:
            amount = deposit
        elif include_withdrawals and withdraw > 0:
            amount = -withdraw
        else:
            continue  # 入金のみ対象（既定）

        rows.append(
            {
                "source": "bank",
                "txn_date": d.isoformat(),
                "amount": amount,
                "fee": 0,
                "net": amount,
                "customer": None,
                "description": f"銀行: {desc}".strip(),
                "external_id": f"{d.isoformat()}-{amount}-{desc}-{i}",
                "raw": {k: str(v) for k, v in r.to_dict().items()},
            }
        )
    return rows
