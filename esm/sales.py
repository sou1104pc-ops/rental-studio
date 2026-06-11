"""売上の集計とDiscord向け整形。"""
from __future__ import annotations

from . import db
from .util import fmt_yen

_SOURCE_LABEL = {"univapay": "UnivaPay(決済)", "bank": "銀行入金", "manual": "手入力"}


def source_label(src: str) -> str:
    return _SOURCE_LABEL.get(src, src)


def summary_text(start: str, end: str, label: str | None = None) -> str:
    """期間の売上サマリーを人間向けテキストに整形。"""
    s = db.summarize_sales(start, end)
    header = label or (start if start == end else f"{start}〜{end}")
    if s["count"] == 0:
        return f"【{header}】の売上データはまだありません。"

    lines = [
        f"📊 **{header} の売上サマリー**",
        f"・件数: {s['count']}件",
        f"・売上総額: {fmt_yen(s['amount'])}",
        f"・手数料: {fmt_yen(s['fee'])}",
        f"・純額(入金): {fmt_yen(s['net'])}",
    ]
    if s["by_source"]:
        lines.append("")
        lines.append("内訳:")
        for r in s["by_source"]:
            lines.append(
                f"　- {source_label(r['source'])}: "
                f"{r['cnt']}件 / {fmt_yen(r['amount'])}（入金 {fmt_yen(r['net'])}）"
            )
    return "\n".join(lines)


def summary_dict(start: str, end: str) -> dict:
    """AI(tool use)向けの構造化サマリー。"""
    return db.summarize_sales(start, end)
