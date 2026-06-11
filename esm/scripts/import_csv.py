"""CSV取込コマンド。

使い方:
    python -m esm.scripts.import_csv univapay 取引明細.csv
    python -m esm.scripts.import_csv bank 入出金明細.csv
    python -m esm.scripts.import_csv bank 明細.csv --with-withdrawals
"""
from __future__ import annotations

import argparse
import sys

from .. import db
from ..ingest import bank_csv, univapay


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ESM 売上CSV取込")
    p.add_argument("source", choices=["univapay", "bank"], help="取込元")
    p.add_argument("path", help="CSVファイルのパス")
    p.add_argument(
        "--with-withdrawals",
        action="store_true",
        help="(bankのみ) 出金行も負の金額で取り込む",
    )
    args = p.parse_args(argv)

    db.init_db()
    try:
        if args.source == "univapay":
            rows = univapay.parse_file(args.path)
        else:
            rows = bank_csv.parse_file(args.path, include_withdrawals=args.with_withdrawals)
    except (ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    inserted, skipped = db.bulk_insert_sales(rows)
    print(f"取込完了: {inserted}件 登録 / {skipped}件 スキップ（重複）/ 対象 {len(rows)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
