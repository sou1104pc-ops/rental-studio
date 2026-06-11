# 株式会社ESM 売上管理・日報 Discordシステム

Discordと連携して、**売上管理**と**日報**を扱う業務ボットです。

- 💬 **自然言語で指示**できる（「今日の売上は？」「先月の入金まとめて」「日報書いて」など）— Claude が解釈して処理
- 🧾 **AI日報の自動生成**（その日の売上＋スタッフのメモを Claude が整形）
- 📊 **売上サマリーの自動通知**（毎日 設定時刻にチャンネルへ投稿）
- 📝 **日報の投稿・記録**（指定チャンネルへの投稿を自動でメモ化）
- 💳 **決済会社（UnivaPay）と銀行明細CSV**を取り込んで集計

データは SQLite に保存（サーバ不要・無料）。

---

## セットアップ

### 1. 依存パッケージ

```bash
cd esm
python -m pip install -r requirements.txt
```

### 2. Discordボットを作成

1. https://discord.com/developers/applications で New Application
2. **Bot** タブでボットを作成し、**TOKEN** をコピー
3. **Privileged Gateway Intents** の **MESSAGE CONTENT INTENT** を **ON**（自然言語処理と日報の自動記録に必要）
4. **OAuth2 → URL Generator** で `bot` と `applications.commands` を選び、
   権限 `Send Messages` / `Read Message History` を付けて生成したURLからサーバーに招待

### 3. 環境変数

`.env.example` をコピーして `.env` を作成し、各値を設定します。

```bash
cp .env.example .env
```

| 変数 | 説明 |
|------|------|
| `DISCORD_TOKEN` | ボットのトークン（必須） |
| `DISCORD_GUILD_ID` | テスト用サーバーID（設定するとコマンドが即反映） |
| `REPORT_CHANNEL_ID` | 日報チャンネルID（投稿を自動でメモ記録） |
| `SUMMARY_CHANNEL_ID` | 自動サマリー投稿先のチャンネルID |
| `SUMMARY_TIME` | 自動サマリーの時刻 `HH:MM`（JST） |
| `ANTHROPIC_API_KEY` | Claude APIキー（AI機能に必要） |
| `CLAUDE_MODEL` | 使用モデル（既定 `claude-opus-4-8`） |

> チャンネルIDは Discord の「開発者モード」を ON にして、チャンネル右クリック →「IDをコピー」で取得できます。

### 4. 起動

```bash
python -m esm.bot
```

---

## 使い方

### スラッシュコマンド

| コマンド | 内容 |
|----------|------|
| `/売上 期間:本日` | 期間（本日/昨日/今週/今月/先月）の売上サマリーを表示 |
| `/サマリー 期間:今月` | サマリーをチャンネルに投稿（共有向け） |
| `/日報 [日付]` | その日の売上とメモから **AI日報** を生成 |
| `/メモ 内容:...` | 日報メモを記録 |

### 自然言語

ボットを **@メンション** するか **DM** で話しかけると、Claude が意図を解釈して処理します。

- 「今日の売上教えて」→ 当日サマリー
- 「先月の入金まとめて」→ 先月サマリー
- 「明日は棚卸し、と日報に入れておいて」→ メモ記録
- 「今日の日報作って」→ AI日報生成

### 日報の自動記録

`REPORT_CHANNEL_ID` のチャンネルに投稿された内容は、自動で日報メモとして保存されます（📝 がつきます）。`/日報` 実行時にそれらのメモと売上をまとめてAIが日報化します。

---

## 売上データの取込

### UnivaPay（決済会社）

管理画面からエクスポートした取引明細CSVを取り込みます。

```bash
python -m esm.scripts.import_csv univapay 取引明細.csv
```

### 銀行明細

各銀行の入出金明細CSVを取り込みます（既定は入金のみ）。

```bash
python -m esm.scripts.import_csv bank 入出金明細.csv
# 出金も負の金額で取り込む場合
python -m esm.scripts.import_csv bank 明細.csv --with-withdrawals
```

列名は銀行・決済会社ごとに異なりますが、候補語であいまい一致させるため多くの形式に対応します（`日付/取引日`、`金額`、`手数料`、`入金/お預入金額` など）。同じ明細を重複して取り込んでもスキップされます。

> CSVの列名が特殊で取り込めない場合は、`esm/ingest/univapay.py` / `bank_csv.py` の候補語リストに列名を追加してください。

---

## 無料での運用について

- **保存**: SQLite なので追加のDBサーバは不要・無料です。
- **AI**: Claude API は従量課金（無料ではありません）ですが、日報生成や売上照会は1回あたり数円程度です。コストを抑えたい場合は `.env` の `CLAUDE_MODEL=claude-haiku-4-5` に変更してください。`ANTHROPIC_API_KEY` 未設定でも、AIなしの簡易日報・スラッシュコマンドは動作します。
- **常時起動のホスティング**: 自然言語処理のためボットは常時起動が必要です。手元のPC、社内サーバ、無料枠のある小型VM等で `python -m esm.bot` を動かしてください。

---

## ファイル構成

```
esm/
├── bot.py             Discordボット本体（コマンド・メンション・自動投稿）
├── ai.py              Claude API（自然言語の tool use / AI日報生成）
├── sales.py           売上集計と整形
├── reports.py         日報の記録・生成
├── db.py              SQLite データ層
├── util.py            日付・金額ヘルパー
├── config.py          環境設定
├── ingest/
│   ├── univapay.py    UnivaPay 取引CSVの取込
│   ├── bank_csv.py    銀行明細CSVの取込
│   └── _common.py     CSV読込・列名あいまい一致
└── scripts/
    └── import_csv.py  CSV取込コマンド
```
