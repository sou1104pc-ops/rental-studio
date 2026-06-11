"""環境設定の読み込み。

すべての設定は環境変数（または .env ファイル）から読み込む。
.env.example をコピーして .env を作成し、各値を埋めること。
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv 未インストールでも環境変数だけで動くように
    pass

BASE_DIR = Path(__file__).resolve().parent

# ─── Discord ─────────────────────────────────────────────────────────────
DISCORD_TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
# スラッシュコマンドを即時反映させたいギルド（サーバー）ID。未指定だとグローバル反映（最大1時間）。
DISCORD_GUILD_ID: int | None = (
    int(os.environ["DISCORD_GUILD_ID"]) if os.environ.get("DISCORD_GUILD_ID") else None
)
# 日報を自動記録するチャンネルID（このチャンネルへの投稿はそのまま日報メモになる）
REPORT_CHANNEL_ID: int | None = (
    int(os.environ["REPORT_CHANNEL_ID"]) if os.environ.get("REPORT_CHANNEL_ID") else None
)
# 売上サマリーを自動投稿するチャンネルID
SUMMARY_CHANNEL_ID: int | None = (
    int(os.environ["SUMMARY_CHANNEL_ID"]) if os.environ.get("SUMMARY_CHANNEL_ID") else None
)
# 自動サマリーを投稿する時刻（JST, "HH:MM"）。空なら自動投稿しない。
SUMMARY_TIME: str = os.environ.get("SUMMARY_TIME", "09:00")

# ─── Claude API ──────────────────────────────────────────────────────────
# anthropic SDK は ANTHROPIC_API_KEY を自動で読む。明示参照用にも保持。
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
# 既定は最新の Claude Opus 4.8。コスト重視なら claude-haiku-4-5 などに変更可。
CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")

# ─── 保存先 ───────────────────────────────────────────────────────────────
DB_PATH: str = os.environ.get("ESM_DB_PATH", str(BASE_DIR / "esm.db"))

# ─── 会社情報 ─────────────────────────────────────────────────────────────
COMPANY_NAME: str = os.environ.get("COMPANY_NAME", "株式会社ESM")
TIMEZONE: str = os.environ.get("TIMEZONE", "Asia/Tokyo")


def require_discord() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN が未設定です。esm/.env.example を参考に .env を作成してください。"
        )


def has_claude() -> bool:
    return bool(ANTHROPIC_API_KEY)
