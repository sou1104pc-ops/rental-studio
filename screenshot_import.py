"""予約管理画面のスクリーンショットから予約一覧を読み取る（Claude API の画像読み取り）。

よやっぴんのようにCSV出力が無い媒体で、管理画面のスクショをそのまま売上にするために使う。
APIキーは Streamlit のシークレット [anthropic] api_key に入れる。
"""
import base64
import json
from datetime import date

import anthropic

MODEL = "claude-opus-5-5"

MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "webp": "image/webp", "gif": "image/gif"}

ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "利用日":     {"type": "string", "description": "YYYY-MM-DD"},
        "開始時刻":   {"type": "string", "description": "HH:MM。分からなければ空文字"},
        "スペース名": {"type": "string"},
        "顧客名":     {"type": "string"},
        "金額":       {"type": "integer", "description": "税込の利用料金（円）。数字のみ"},
        "ステータス": {"type": "string", "description": "確定・キャンセルなど画面の表記のまま。無ければ空文字"},
        "決済方法":   {"type": "string", "description": "画面の表記のまま。無ければ空文字"},
        "予約番号":   {"type": "string", "description": "画面に出ていれば。無ければ空文字"},
    },
    "required": ["利用日", "開始時刻", "スペース名", "顧客名", "金額", "ステータス", "決済方法", "予約番号"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"予約": {"type": "array", "items": ROW_SCHEMA}},
    "required": ["予約"],
    "additionalProperties": False,
}

PROMPT = """これはレンタルスペースの予約管理画面（{platform}）のスクリーンショットです。
画面に写っている予約を1件ずつ、すべて書き出してください。

- 写っていない予約や、途中で切れて読めない予約は書かないでください。推測で埋めないでください。
- 利用日に年が書かれていない場合は、今日（{today}）に近い年を使ってください。
- 金額は「¥」「円」「,」を除いた整数にしてください。金額が写っていない予約は 0 にしてください。
- 複数の画像は同じ一覧の続きのことがあります。同じ予約が2枚に写っていても1件だけ書いてください。"""


class ScreenshotReadError(Exception):
    pass


def read_bookings(api_key: str, images: list, platform: str) -> list:
    """images: [(ファイル名, bytes), ...] → 予約の dict のリスト"""
    content = []
    for name, data in images:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": MEDIA_TYPES.get(ext, "image/png"),
            "data": base64.standard_b64encode(data).decode("utf-8")}})
    content.append({"type": "text",
                    "text": PROMPT.format(platform=platform, today=date.today().isoformat())})

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        raise ScreenshotReadError("APIキーが正しくありません。シークレットの [anthropic] api_key を確認してください。")
    except anthropic.RateLimitError:
        raise ScreenshotReadError("混み合っています。少し待ってからもう一度お試しください。")
    except anthropic.APIStatusError as e:
        raise ScreenshotReadError(f"読み取りに失敗しました（{e.status_code}）: {e.message}")
    except anthropic.APIConnectionError:
        raise ScreenshotReadError("通信に失敗しました。もう一度お試しください。")

    if response.stop_reason == "refusal":
        raise ScreenshotReadError("この画像は読み取れませんでした。")
    if response.stop_reason == "max_tokens":
        raise ScreenshotReadError("予約が多すぎて読み切れませんでした。画像を分けてお試しください。")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text).get("予約", [])
    except json.JSONDecodeError:
        raise ScreenshotReadError("読み取り結果を解析できませんでした。もう一度お試しください。")
