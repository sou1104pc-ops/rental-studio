"""Googleカレンダー（iCal形式）から予約時間を取り出して稼働率を計算するロジック。

Streamlit に依存しない純粋な関数だけを置き、app.py の「📆 稼働率」ページから使う。
"""
from bisect import bisect_left
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

LOCAL_TZ = ZoneInfo("Asia/Tokyo")

# 予定タイトルにこれらを含むものは「予約」ではなく「除外（清掃・ブロック等）」として扱う
DEFAULT_EXCLUDE_KEYWORDS = [
    "清掃", "掃除", "クリーニング", "片付け", "準備", "メンテ", "点検",
    "ブロック", "予約不可", "休業", "キャンセル",
]

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

Interval = Tuple[datetime, datetime]


# ─── 取得・パース ─────────────────────────────────────────────────────────────
def fetch_ics(url: str, timeout: int = 20) -> bytes:
    """iCal URL（webcal:// も可）から .ics を取得する。"""
    url = url.strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    req = Request(url, headers={"User-Agent": "rental-studio-occupancy/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _to_local_naive(v) -> Tuple[datetime, bool]:
    """icalendar の DTSTART/DTEND 値を JST の naive datetime に。終日なら (00:00, True)。"""
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(LOCAL_TZ).replace(tzinfo=None)
        return v, False
    return datetime.combine(v, time()), True


def parse_events(ics: bytes, start: date, end: date) -> List[dict]:
    """start〜end（end を含む）に掛かる予定を、繰り返し予定も展開して返す。"""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics)
    occ = recurring_ical_events.of(cal).between(start, end + timedelta(days=1))
    events = []
    for ev in occ:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        s, all_day = _to_local_naive(dtstart.dt)
        dtend = ev.get("DTEND")
        if dtend is not None:
            e, _ = _to_local_naive(dtend.dt)
        elif ev.get("DURATION") is not None:
            e = s + ev["DURATION"].dt
        else:
            e = s + (timedelta(days=1) if all_day else timedelta(0))
        if e <= s:
            continue
        events.append({
            "タイトル": str(ev.get("SUMMARY", "") or ""),
            "開始": s,
            "終了": e,
            "終日": all_day,
        })
    return events


# ─── 区間演算 ────────────────────────────────────────────────────────────────
def merge_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    """重なり・連続する区間を結合する（同じ予約が複数媒体から同期されても二重計上しない）。"""
    merged: List[Interval] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def subtract_intervals(base: List[Interval], minus: List[Interval]) -> List[Interval]:
    """結合済み区間 base から結合済み区間 minus を差し引く。"""
    out: List[Interval] = []
    for s, e in base:
        cur = s
        for ms, me in minus:
            if me <= cur or ms >= e:
                continue
            if ms > cur:
                out.append((cur, ms))
            cur = max(cur, me)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def overlap_minutes(merged: List[Interval], s: datetime, e: datetime) -> float:
    """結合済み区間と [s, e) の重なり（分）。"""
    if e <= s or not merged:
        return 0.0
    # s より前に終わる区間は飛ばす
    i = max(bisect_left(merged, (s, s)) - 1, 0)
    total = 0.0
    while i < len(merged) and merged[i][0] < e:
        ms, me = merged[i]
        lo, hi = max(ms, s), min(me, e)
        if hi > lo:
            total += (hi - lo).total_seconds() / 60
        i += 1
    return total


# ─── 営業時間 ────────────────────────────────────────────────────────────────
def parse_hhmm(v: str) -> int:
    """'09:00' → 540（分）。'24:00' も可。"""
    h, m = str(v).strip().split(":")
    return int(h) * 60 + int(m)


def business_window(day: date, open_min: int, close_min: int) -> Interval:
    """その日の営業時間帯。閉店が開店以前なら翌日にまたがる（例 10:00〜02:00、00:00〜00:00 は24時間）。"""
    base = datetime.combine(day, time())
    if close_min <= open_min:
        close_min += 24 * 60
    return base + timedelta(minutes=open_min), base + timedelta(minutes=close_min)


def is_excluded(title: str, keywords: Iterable[str]) -> bool:
    t = title.lower()
    return any(k and k.lower() in t for k in keywords)


# ─── 稼働率計算 ──────────────────────────────────────────────────────────────
def compute_occupancy(events: List[dict], start: date, end: date,
                      open_hhmm: str, close_hhmm: str,
                      exclude_keywords: Iterable[str],
                      closed_weekdays: Iterable[int] = (),
                      title_filter: str = "") -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """予定一覧から日別・時間帯別の稼働を集計する。

    戻り値:
      daily  … 日付ごとの 営業(分) / 予約(分) / 除外(分) / 予約件数
      hourly … 曜日×時間帯ごとの 営業(分) / 予約(分) / 除外(分)
      detail … 期間内の予定一覧（分類つき、確認用）

    ・終日予定は時間を持たないので集計対象外（一覧には「終日（対象外）」で表示）
    ・予約同士の重なりは結合して二重計上しない
    ・除外（清掃等）時間は、予約と重なる部分を差し引いた正味の時間
    """
    exclude_keywords = [k for k in exclude_keywords if k]
    closed = set(closed_weekdays)
    open_min, close_min = parse_hhmm(open_hhmm), parse_hhmm(close_hhmm)

    detail_rows, booked_raw, excluded_raw = [], [], []
    for ev in events:
        title = ev["タイトル"]
        if title_filter and title_filter.lower() not in title.lower():
            continue
        if ev["終日"]:
            kind = "終日（対象外）"
        elif is_excluded(title, exclude_keywords):
            kind = "除外"
            excluded_raw.append((ev["開始"], ev["終了"]))
        else:
            kind = "予約"
            booked_raw.append((ev["開始"], ev["終了"]))
        detail_rows.append({**ev, "分類": kind,
                            "時間(h)": round((ev["終了"] - ev["開始"]).total_seconds() / 3600, 2)})

    booked = merge_intervals(booked_raw)
    excluded = subtract_intervals(merge_intervals(excluded_raw), booked)

    daily_rows, hourly_rows = [], []
    day = start
    while day <= end:
        if day.weekday() not in closed:
            ws, we = business_window(day, open_min, close_min)
            n_book = sum(1 for s, e in booked_raw if s < we and e > ws)
            daily_rows.append({
                "日付": day,
                "営業(分)": (we - ws).total_seconds() / 60,
                "予約(分)": overlap_minutes(booked, ws, we),
                "除外(分)": overlap_minutes(excluded, ws, we),
                "予約件数": n_book,
            })
            slot = ws
            while slot < we:
                nxt = min(slot.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1), we)
                hourly_rows.append({
                    "曜日": WEEKDAYS_JA[day.weekday()],
                    "時": slot.hour,
                    "営業(分)": (nxt - slot).total_seconds() / 60,
                    "予約(分)": overlap_minutes(booked, slot, nxt),
                    "除外(分)": overlap_minutes(excluded, slot, nxt),
                })
                slot = nxt
        day += timedelta(days=1)

    daily = pd.DataFrame(daily_rows, columns=["日付", "営業(分)", "予約(分)", "除外(分)", "予約件数"])
    hourly = pd.DataFrame(hourly_rows, columns=["曜日", "時", "営業(分)", "予約(分)", "除外(分)"])
    if not hourly.empty:
        hourly = hourly.groupby(["曜日", "時"], as_index=False).sum()

    range_s = datetime.combine(start, time())
    range_e = datetime.combine(end + timedelta(days=1), time())
    detail = pd.DataFrame(detail_rows, columns=["開始", "終了", "タイトル", "分類", "時間(h)", "終日"])
    detail = detail[(detail["終了"] > range_s) & (detail["開始"] < range_e)].sort_values("開始")
    return daily, hourly, detail


def rates(booked_min: float, capacity_min: float, excluded_min: float) -> Tuple[Optional[float], Optional[float]]:
    """(営業時間ベースの稼働率, 清掃等を除いた実質稼働率) を % で返す。"""
    r1 = booked_min / capacity_min * 100 if capacity_min > 0 else None
    avail = capacity_min - excluded_min
    r2 = booked_min / avail * 100 if avail > 0 else None
    return r1, r2


def add_rate_cols(df: pd.DataFrame) -> pd.DataFrame:
    """集計済み DataFrame に 稼働率(%) / 実質稼働率(%) と時間(h)列を追加。"""
    df = df.copy()
    cap, book, exc = df["営業(分)"], df["予約(分)"], df["除外(分)"]
    df["稼働率(%)"] = (book / cap.where(cap > 0) * 100).round(1)
    avail = cap - exc
    df["実質稼働率(%)"] = (book / avail.where(avail > 0) * 100).round(1)
    df["営業(h)"] = (cap / 60).round(1)
    df["予約(h)"] = (book / 60).round(1)
    df["除外(h)"] = (exc / 60).round(1)
    return df
