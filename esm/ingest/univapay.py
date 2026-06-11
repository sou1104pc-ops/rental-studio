"""UnivaPay（決済会社）の取引CSVを取り込む。

UnivaPay の管理画面からエクスポートした取引明細CSVを想定。
列名はバージョンや出力設定で変わるため、候補語であいまい一致させる。
APIからの取得が必要になった場合は fetch_via_api() を実装する。
"""
from __future__ import annotations

from ..util import parse_amount, parse_date
from ._common import find_col, read_csv

# 列名の候補（部分一致）
_C_DATE = ["課金日時", "取引日時", "決済日", "取引日", "日付", "created", "charged", "date"]
_C_AMOUNT = ["金額", "請求金額", "課金金額", "amount", "charge"]
_C_FEE = ["手数料", "fee", "commission"]
_C_NET = ["入金額", "精算", "純額", "net", "settlement"]
_C_ID = ["取引id", "課金id", "id", "transaction", "charge id"]
_C_CUST = ["顧客", "氏名", "name", "customer", "メール", "email"]
_C_STATUS = ["ステータス", "状態", "status"]


def parse_file(path: str) -> list[dict]:
    """CSVを売上レコード（db.insert_sale 互換のdict）のリストに変換。"""
    df = read_csv(path)
    cols = list(df.columns)

    c_date = find_col(cols, _C_DATE)
    c_amount = find_col(cols, _C_AMOUNT)
    c_fee = find_col(cols, _C_FEE)
    c_net = find_col(cols, _C_NET)
    c_id = find_col(cols, _C_ID)
    c_cust = find_col(cols, _C_CUST)
    c_status = find_col(cols, _C_STATUS)

    if not c_date or not c_amount:
        raise ValueError(
            f"UnivaPay CSV の必須列が見つかりません（日付/金額）。検出列: {cols}"
        )

    rows: list[dict] = []
    for i, r in df.iterrows():
        # 失敗・返金などはスキップ（成功課金のみ集計）
        if c_status and r[c_status]:
            st = str(r[c_status]).lower()
            if any(x in st for x in ("fail", "error", "失敗", "エラー", "cancel", "キャンセル")):
                continue

        d = parse_date(str(r[c_date])[:10])
        if not d:
            continue
        amount = parse_amount(r[c_amount])
        fee = parse_amount(r[c_fee]) if c_fee else 0
        net = parse_amount(r[c_net]) if c_net else amount - fee

        rows.append(
            {
                "source": "univapay",
                "txn_date": d.isoformat(),
                "amount": amount,
                "fee": fee,
                "net": net,
                "customer": str(r[c_cust]) if c_cust else None,
                "description": "UnivaPay決済",
                "external_id": str(r[c_id]) if c_id else f"row{i}-{d.isoformat()}-{amount}",
                "raw": {k: str(v) for k, v in r.to_dict().items()},
            }
        )
    return rows


def fetch_via_api(*_args, **_kwargs) -> list[dict]:  # pragma: no cover
    """将来用：UnivaPay API から直接取得する場合の入口（未実装）。

    UnivaPay のアプリトークン/シークレットを使い、charges エンドポイントを
    呼び出して parse_file と同じ形式の dict リストを返す想定。
    """
    raise NotImplementedError(
        "UnivaPay API 連携は未実装です。現状はCSVエクスポートを parse_file で取り込んでください。"
    )
