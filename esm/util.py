"""日付・金額まわりの共通ヘルパー。"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta


def fmt_yen(v: int | float | None) -> str:
    if v is None:
        return "—"
    return f"¥{int(v):,}"


def parse_date(s: str) -> date | None:
    """'2026-06-11' / '2026/6/11' / '6/11' / '20260611' 等をゆるくパース。"""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # 月/日 のみ → 今年で補完
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", s)
    if m:
        today = date.today()
        return date(today.year, int(m.group(1)), int(m.group(2)))
    return None


def month_range(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last).isoformat()


def resolve_period(keyword: str) -> tuple[str, str, str]:
    """'today' / 'yesterday' / 'this_week' / 'this_month' / 'last_month' を
    (start_iso, end_iso, ラベル) に変換する。"""
    today = date.today()
    if keyword == "today":
        return today.isoformat(), today.isoformat(), "本日"
    if keyword == "yesterday":
        y = today - timedelta(days=1)
        return y.isoformat(), y.isoformat(), "昨日"
    if keyword == "this_week":
        start = today - timedelta(days=today.weekday())  # 月曜始まり
        return start.isoformat(), today.isoformat(), "今週"
    if keyword == "this_month":
        s, _ = month_range(today.year, today.month)
        return s, today.isoformat(), "今月"
    if keyword == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        s, e = month_range(last_prev.year, last_prev.month)
        return s, e, f"先月({last_prev.year}/{last_prev.month})"
    # 既定: 今日
    return today.isoformat(), today.isoformat(), "本日"


def parse_amount(text) -> int:
    """'1,200円' '¥1200' '1200' などを整数(円)に。失敗時は0。"""
    if text is None:
        return 0
    s = str(text)
    s = s.replace(",", "").replace("円", "").replace("¥", "").replace("\\", "").strip()
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else 0
