"""Claude API 連携。

役割は2つ:
1. compose_daily_report ... 売上とメモから日報を生成
2. handle_natural_language ... 自由文の指示を tool use で解釈して実行

ANTHROPIC_API_KEY が未設定でも import は通り、AI機能だけ無効化される。
"""
from __future__ import annotations

import json
from datetime import date

from . import config
from .util import fmt_yen, parse_date, resolve_period

# anthropic は遅延importにして、CSV取込など非AI用途でも動くようにする
try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

_client = None


def _get_client():
    global _client
    if anthropic is None:
        raise RuntimeError(
            "anthropic SDK が未インストールです。`pip install anthropic` を実行してください。"
        )
    if _client is None:
        _client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を自動で読む
    return _client


def available() -> bool:
    return anthropic is not None and config.has_claude()


# ─── 日報生成 ─────────────────────────────────────────────────────────────
_REPORT_SYSTEM = (
    "あなたは{company}の経理・運営アシスタントです。"
    "その日の売上データとスタッフのメモをもとに、簡潔で読みやすい日報を日本語で作成します。"
    "事実（数値）はデータに忠実に。メモが空でも売上から日報を組み立ててください。"
    "構成は『日付 / 売上サマリー / トピック・所感 / 明日への申し送り』。"
    "誇張せず、わかりやすく。"
)


def compose_daily_report(report_date: str, summary: dict, notes: list[str]) -> str:
    if not available():
        return _fallback_report(report_date, summary, notes)

    src_lines = [
        f"- {s['source']}: {s['cnt']}件 / 売上{fmt_yen(s['amount'])} / 入金{fmt_yen(s['net'])}"
        for s in summary.get("by_source", [])
    ]
    user = (
        f"対象日: {report_date}\n\n"
        f"【売上データ】\n"
        f"件数: {summary['count']}件\n"
        f"売上総額: {fmt_yen(summary['amount'])}\n"
        f"手数料: {fmt_yen(summary['fee'])}\n"
        f"純額(入金): {fmt_yen(summary['net'])}\n"
        + ("内訳:\n" + "\n".join(src_lines) + "\n" if src_lines else "")
        + "\n【スタッフのメモ】\n"
        + ("\n".join(f"- {n}" for n in notes) if notes else "(メモなし)")
        + "\n\n上記から日報を作成してください。"
    )
    try:
        resp = _get_client().messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            system=_REPORT_SYSTEM.format(company=config.COMPANY_NAME),
            messages=[{"role": "user", "content": user}],
        )
        return _text_of(resp) or _fallback_report(report_date, summary, notes)
    except Exception as e:  # API障害時もフォールバック
        return _fallback_report(report_date, summary, notes) + f"\n\n(AI生成に失敗: {e})"


def _fallback_report(report_date: str, summary: dict, notes: list[str]) -> str:
    lines = [
        f"📝 {report_date} 日報",
        "",
        "■ 売上サマリー",
        f"・件数 {summary['count']}件 / 売上 {fmt_yen(summary['amount'])} / 入金 {fmt_yen(summary['net'])}",
        "",
        "■ メモ",
    ]
    lines += [f"・{n}" for n in notes] if notes else ["・(なし)"]
    return "\n".join(lines)


# ─── 自然言語ハンドラ（tool use）────────────────────────────────────────────
_TOOLS = [
    {
        "name": "query_sales",
        "description": (
            "指定期間の売上を集計して返す。ユーザーが売上・入金・実績を尋ねたら使う。"
            "period か、start/end のどちらかを指定する。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "this_week", "this_month", "last_month"],
                    "description": "相対期間。具体的な日付が無いときに使う。",
                },
                "start": {"type": "string", "description": "開始日 YYYY-MM-DD"},
                "end": {"type": "string", "description": "終了日 YYYY-MM-DD"},
            },
        },
    },
    {
        "name": "record_note",
        "description": (
            "スタッフの日報メモ・申し送り・出来事を記録する。"
            "ユーザーが『〜を記録して』『日報に〜』『メモ:』などと伝えたら使う。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "記録する本文"},
                "date": {"type": "string", "description": "対象日 YYYY-MM-DD（省略時は本日）"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "generate_daily_report",
        "description": "その日の売上とメモからAI日報を生成して保存する。ユーザーが日報作成を求めたら使う。",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "対象日 YYYY-MM-DD（省略時は本日）"},
            },
        },
    },
]

_NL_SYSTEM = (
    "あなたは{company}のDiscord業務アシスタントです。"
    "売上管理と日報作成を担当します。ユーザーの日本語の指示を理解し、"
    "必要に応じてツールを呼び出して処理してください。"
    "売上・入金を聞かれたら query_sales、記録を頼まれたら record_note、"
    "日報作成を頼まれたら generate_daily_report を使います。"
    "金額は『¥1,234』形式、回答は簡潔な日本語で。"
)


def _execute_tool(name: str, args: dict) -> str:
    # 循環import回避のため関数内import
    from . import db, reports, sales

    if name == "query_sales":
        if args.get("period"):
            start, end, label = resolve_period(args["period"])
        else:
            sd = parse_date(args.get("start", "")) or date.today()
            ed = parse_date(args.get("end", "")) or sd
            start, end, label = sd.isoformat(), ed.isoformat(), None
        return json.dumps(
            {"label": label, **sales.summary_dict(start, end)}, ensure_ascii=False
        )

    if name == "record_note":
        rid = reports.record_note(
            content=args["content"],
            report_date=parse_date(args.get("date", "")).isoformat()
            if parse_date(args.get("date", ""))
            else None,
        )
        return json.dumps({"ok": True, "id": rid}, ensure_ascii=False)

    if name == "generate_daily_report":
        d = parse_date(args.get("date", ""))
        text = reports.generate_daily_report(d.isoformat() if d else None)
        return json.dumps({"report": text}, ensure_ascii=False)

    return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)


def handle_natural_language(user_message: str) -> str:
    """自由文の指示を処理して、Discordに返す文字列を返す。"""
    if not available():
        return (
            "AI機能が無効です（ANTHROPIC_API_KEY 未設定）。"
            "スラッシュコマンド `/売上` `/日報` `/サマリー` をご利用ください。"
        )

    client = _get_client()
    system = _NL_SYSTEM.format(company=config.COMPANY_NAME)
    messages = [{"role": "user", "content": user_message}]

    # 手動エージェントループ（最大5周）
    for _ in range(5):
        resp = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            system=system,
            tools=_TOOLS,
            messages=messages,
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = _execute_tool(block.name, block.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": out}
                    )
            messages.append({"role": "user", "content": results})
            continue
        return _text_of(resp) or "(応答を生成できませんでした)"

    return "処理がループ上限に達しました。指示を分けてお試しください。"


def _text_of(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
