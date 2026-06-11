"""日報の記録とAI生成。"""
from __future__ import annotations

from datetime import date

from . import ai, db, sales


def record_note(content: str, author: str | None = None, channel_id: str | None = None,
                report_date: str | None = None) -> int:
    """スタッフが書いた日報メモを記録。"""
    return db.insert_report(
        report_date=report_date or date.today().isoformat(),
        content=content,
        author=author,
        channel_id=channel_id,
        ai_generated=False,
    )


def generate_daily_report(report_date: str | None = None, save: bool = True) -> str:
    """その日の売上 + スタッフのメモから、AIで日報を生成する。

    Claude API が使えない場合は素材を結合した簡易日報を返す。
    """
    report_date = report_date or date.today().isoformat()
    summary = sales.summary_dict(report_date, report_date)
    notes = db.get_notes_for(report_date)

    text = ai.compose_daily_report(report_date, summary, notes)

    if save:
        db.insert_report(
            report_date=report_date,
            content=text,
            author="AI",
            ai_generated=True,
        )
    return text
