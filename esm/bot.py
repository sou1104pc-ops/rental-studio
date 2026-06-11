"""株式会社ESM Discordボット。

機能:
- /売上     : 期間を選んで売上サマリーを表示
- /日報     : その日の売上とメモからAI日報を生成
- /サマリー : 売上サマリーをチャンネルに投稿
- /メモ     : 日報メモを記録
- 日報チャンネルへの投稿を自動でメモ記録
- @メンション / DM の自然文を Claude が解釈して処理
- 毎日 設定時刻に売上サマリーを自動投稿

起動: python -m esm.bot
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from . import ai, config, db, reports, sales
from .util import resolve_period

JST = ZoneInfo(config.TIMEZONE)

_PERIOD_CHOICES = [
    app_commands.Choice(name="本日", value="today"),
    app_commands.Choice(name="昨日", value="yesterday"),
    app_commands.Choice(name="今週", value="this_week"),
    app_commands.Choice(name="今月", value="this_month"),
    app_commands.Choice(name="先月", value="last_month"),
]


def _summary_time() -> dt.time:
    try:
        h, m = config.SUMMARY_TIME.split(":")
        return dt.time(hour=int(h), minute=int(m), tzinfo=JST)
    except Exception:
        return dt.time(hour=9, minute=0, tzinfo=JST)


class ESMBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # メッセージ本文の読み取り（要 開発者ポータルで有効化）
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        db.init_db()
        if config.DISCORD_GUILD_ID:
            guild = discord.Object(id=config.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        if config.SUMMARY_CHANNEL_ID:
            self.daily_summary.start()

    async def on_ready(self) -> None:
        print(f"ログイン: {self.user} / {config.COMPANY_NAME} 売上管理ボット 起動")

    # ─── 自動サマリー ────────────────────────────────────────────────────
    @tasks.loop(time=_summary_time())
    async def daily_summary(self) -> None:
        channel = self.get_channel(config.SUMMARY_CHANNEL_ID)
        if channel is None:
            return
        start, end, label = resolve_period("yesterday")
        await channel.send(sales.summary_text(start, end, f"{label}の実績"))

    @daily_summary.before_loop
    async def _before_summary(self) -> None:
        await self.wait_until_ready()

    # ─── メッセージ（自動記録 / 自然言語）──────────────────────────────────
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user or message.author.bot:
            return

        # 日報チャンネルへの投稿はメモとして自動記録
        if config.REPORT_CHANNEL_ID and message.channel.id == config.REPORT_CHANNEL_ID:
            reports.record_note(
                content=message.content,
                author=str(message.author),
                channel_id=str(message.channel.id),
            )
            await message.add_reaction("📝")
            return

        # メンション or DM → 自然言語として処理
        is_dm = isinstance(message.channel, discord.DMChannel)
        if self.user in message.mentions or is_dm:
            text = message.content.replace(f"<@{self.user.id}>", "").strip()
            if not text:
                return
            async with message.channel.typing():
                reply = await self.loop.run_in_executor(
                    None, ai.handle_natural_language, text
                )
            await _send_long(message.channel, reply)


client = ESMBot()


# ─── スラッシュコマンド ──────────────────────────────────────────────────
@client.tree.command(name="売上", description="期間を選んで売上サマリーを表示します")
@app_commands.describe(期間="集計する期間")
@app_commands.choices(期間=_PERIOD_CHOICES)
async def cmd_sales(interaction: discord.Interaction, 期間: app_commands.Choice[str]) -> None:
    start, end, label = resolve_period(期間.value)
    await interaction.response.send_message(sales.summary_text(start, end, label))


@client.tree.command(name="サマリー", description="売上サマリーをこのチャンネルに投稿します")
@app_commands.describe(期間="集計する期間")
@app_commands.choices(期間=_PERIOD_CHOICES)
async def cmd_summary(interaction: discord.Interaction, 期間: app_commands.Choice[str]) -> None:
    start, end, label = resolve_period(期間.value)
    await interaction.response.send_message(sales.summary_text(start, end, label))


@client.tree.command(name="日報", description="その日の売上とメモからAI日報を生成します")
@app_commands.describe(日付="対象日 YYYY-MM-DD（省略時は本日）")
async def cmd_report(interaction: discord.Interaction, 日付: str | None = None) -> None:
    await interaction.response.defer(thinking=True)
    from .util import parse_date

    d = parse_date(日付) if 日付 else None
    text = await client.loop.run_in_executor(
        None, reports.generate_daily_report, d.isoformat() if d else None
    )
    await _followup_long(interaction, text)


@client.tree.command(name="メモ", description="日報メモを記録します")
@app_commands.describe(内容="記録する内容")
async def cmd_note(interaction: discord.Interaction, 内容: str) -> None:
    reports.record_note(content=内容, author=str(interaction.user))
    await interaction.response.send_message("📝 メモを記録しました。", ephemeral=True)


# ─── 長文をDiscordの2000字制限に合わせて分割送信 ──────────────────────────
async def _send_long(channel, text: str) -> None:
    for chunk in _chunks(text):
        await channel.send(chunk)


async def _followup_long(interaction: discord.Interaction, text: str) -> None:
    parts = _chunks(text)
    if parts:
        await interaction.followup.send(parts[0])
        for chunk in parts[1:]:
            await interaction.followup.send(chunk)


def _chunks(text: str, size: int = 1900) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def main() -> None:
    config.require_discord()
    client.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
