"""銀行提出用の売上・損益報告書（PDF）を作る。

数字は「📈 損益レポート」と同じ集計（事業全体の月別 total、店舗×月の monthly）を受け取って並べるだけ。
日本語は IPAゴシック（packages.txt の fonts-ipafont-gothic）を PDF に埋め込む。
埋め込まないと、日本語フォントの無い閲覧環境で文字が表示されないため。
"""
import io
import os
from datetime import date

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

FONT_FILES = ["/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
              "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]


def _register_font() -> str:
    for path in FONT_FILES:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont("IPAGothic", path))
            return "IPAGothic"
    # フォントが無い環境の予備（埋め込まれないので、閲覧環境によっては文字が出ない）
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    return "HeiseiKakuGo-W5"


FONT = _register_font()
FONT_EMBEDDED = FONT == "IPAGothic"

STYLE_TITLE = ParagraphStyle("title", fontName=FONT, fontSize=18, leading=24, spaceAfter=4 * mm)
STYLE_H     = ParagraphStyle("h", fontName=FONT, fontSize=12, leading=16, spaceBefore=5 * mm, spaceAfter=2 * mm)
STYLE_BODY  = ParagraphStyle("body", fontName=FONT, fontSize=9, leading=13)
STYLE_NOTE  = ParagraphStyle("note", fontName=FONT, fontSize=8, leading=11, textColor=colors.HexColor("#555555"))

# (列名, 表の見出し) ― 売上は返金・割引を差し引いた実売上
TOTAL_COLS = [("実売上", "売上"), ("手数料", "予約サイト手数料"), ("手取り", "手取り"),
              ("固定費", "店舗固定費"), ("事業経費", "事業全体経費"), ("カード経費", "カード経費"),
              ("営業利益", "営業利益"), ("件数", "件数")]
STORE_COLS = [("実売上", "売上"), ("手数料", "予約サイト手数料"), ("手取り", "手取り"),
              ("固定費", "店舗固定費"), ("カード経費", "カード経費"), ("営業利益", "営業利益"),
              ("件数", "件数")]


def _yen(v) -> str:
    v = 0 if pd.isna(v) else float(v)
    return f"-¥{-v:,.0f}" if v < 0 else f"¥{v:,.0f}"


def _month_label(m: str) -> str:
    y, mo = str(m).split("-")
    return f"{y}年{int(mo)}月"


def _table(header: list, rows: list, total_row: list = None) -> Table:
    data = [header] + rows + ([total_row] if total_row else [])
    t = Table(data, repeatRows=1, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if total_row:
        style += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F3F3F3"))]
    t.setStyle(TableStyle(style))
    return t


def _monthly_rows(df: pd.DataFrame, cols: list) -> tuple:
    rows = []
    for _, r in df.sort_values("月").iterrows():
        rows.append([_month_label(r["月"])] + [
            f"{int(r[c]):,}" if c == "件数" else _yen(r[c]) for c, _ in cols])
    total = ["合計"] + [f"{int(df[c].sum()):,}" if c == "件数" else _yen(df[c].sum()) for c, _ in cols]
    return rows, total


def build_pdf(total: pd.DataFrame, monthly: pd.DataFrame, stores: list,
              start: str, end: str, company: str = "", notes: list = None) -> bytes:
    """total: 事業全体の月別（列は TOTAL_COLS + 月）、monthly: 店舗×月（列は STORE_COLS + 月, 店舗）。
    start / end は "YYYY-MM"（両端を含む）。"""
    tot = total[(total["月"] >= start) & (total["月"] <= end)]
    mon = monthly[(monthly["月"] >= start) & (monthly["月"] <= end)]
    period = f"{_month_label(start)}〜{_month_label(end)}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"売上・損益報告書（{period}）", author=company or "")
    story = [Paragraph("売上・損益報告書", STYLE_TITLE)]
    meta = [f"対象期間：{period}", f"作成日：{date.today():%Y年%m月%d日}"]
    if company:
        meta.insert(0, f"事業者：{company}")
    story += [Paragraph("　／　".join(meta), STYLE_BODY), Spacer(1, 3 * mm)]

    # 1. 期間合計
    story.append(Paragraph("1. 期間合計（事業全体）", STYLE_H))
    summary = [[label, f"{int(tot[c].sum()):,} 件" if c == "件数" else _yen(tot[c].sum())]
               for c, label in TOTAL_COLS]
    story.append(_table(["項目", "金額"], summary))

    # 2. 店舗別の期間合計
    story.append(Paragraph("2. 店舗別 期間合計", STYLE_H))
    present = [s for s in stores if s in set(mon["店舗"])] + \
              [s for s in mon["店舗"].unique() if s not in stores]
    store_rows = []
    for s in present:
        sd = mon[mon["店舗"] == s]
        store_rows.append([s] + [f"{int(sd[c].sum()):,}" if c == "件数" else _yen(sd[c].sum())
                                 for c, _ in STORE_COLS])
    store_total = ["合計"] + [f"{int(mon[c].sum()):,}" if c == "件数" else _yen(mon[c].sum())
                              for c, _ in STORE_COLS]
    story.append(_table(["店舗"] + [l for _, l in STORE_COLS], store_rows, store_total))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("※ 店舗別の営業利益には事業全体経費（店舗に割り振っていない経費）を含みません。"
                           "事業全体の営業利益 ＝ 店舗別営業利益の合計 − 事業全体経費 − 店舗に割り振っていないカード経費。",
                           STYLE_NOTE))

    # 3. 事業全体の月別
    story.append(PageBreak())
    story.append(Paragraph("3. 月別推移（事業全体）", STYLE_H))
    rows, tr = _monthly_rows(tot, TOTAL_COLS)
    story.append(_table(["月"] + [l for _, l in TOTAL_COLS], rows, tr))

    # 4. 店舗ごとの月別
    for i, s in enumerate(present):
        sd = mon[mon["店舗"] == s]
        rows, tr = _monthly_rows(sd, STORE_COLS)
        # 見出しと表がページをまたいで離れないようにする
        story.append(KeepTogether([Paragraph(f"{4 + i}. 月別推移（{s}）", STYLE_H),
                                   _table(["月"] + [l for _, l in STORE_COLS], rows, tr)]))

    # 注記
    story.append(Paragraph("注記", STYLE_H))
    base_notes = [
        "売上は、予約サイト・請求書払いの利用料金から返金・割引を差し引いた金額です（利用日の月で計上）。",
        "手取り ＝ 売上 − 予約サイト手数料。営業利益 ＝ 手取り − 店舗固定費 − 事業全体経費 − カード経費。",
        "銀行振込で入金が確認できていない予約、および未入金確定（回収不能）の予約は含みません。",
    ]
    for n in base_notes + (notes or []):
        story.append(Paragraph(f"・{n}", STYLE_NOTE))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.drawRightString(doc_.pagesize[0] - 14 * mm, 8 * mm, f"{doc_.page} ページ")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
