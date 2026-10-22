# 貸しスペース 売上管理

レンタルスタジオ・貸し会議室などの売上（予約サイトのCSV・請求書払い）、入金確認、損益、稼働率（Googleカレンダー連携）を管理する Streamlit アプリです。

## 複数の会社で使う（ログイン機能）

Streamlit のシークレットに Google ログインの設定を入れると、ログインが必須になり、
**会社ごとにデータが完全に分かれた状態**で複数の会社が同じアプリを使えます。
設定を入れるまでは、従来どおりログインなしで動きます。

- 利用できるのは、管理者が「🛠 利用者管理」で登録したメールアドレスの人だけです（自分で新規登録はできません）。
- ログイン機能を入れる前からのデータは、最初の会社（管理者の会社）のデータとしてそのまま使われます。
- 1人が複数の会社に登録されている場合は、サイドバーで会社を切り替えられます。

### 設定手順（管理者が1回だけ）

#### 1. Google のログイン用設定を作る

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（既存のものでも可）
2. 「APIとサービス」→「OAuth 同意画面」
   - ユーザーの種類：**外部**
   - アプリ名・サポートメールを入力（スコープの追加は不要）
   - 最後に「**アプリを公開**」して本番環境にする（テスト中のままだと、テストユーザーに追加した人しかログインできません）
3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」
   - アプリケーションの種類：**ウェブアプリケーション**
   - 承認済みのリダイレクト URI：`https://<アプリのURL>/oauth2callback`
     （例：`https://rental-studio-xxxx.streamlit.app/oauth2callback`）
4. 表示された **クライアント ID** と **クライアント シークレット** を控える

#### 2. Streamlit のシークレットに追加する

Streamlit Community Cloud のアプリ管理画面 →「Settings」→「Secrets」に、既存の `[supabase]` に加えて次を追記します。

```toml
[auth]
redirect_uri = "https://<アプリのURL>/oauth2callback"
cookie_secret = "<ランダムな長い英数字（40文字以上）>"
client_id = "<クライアント ID>"
client_secret = "<クライアント シークレット>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[app]
admins = ["<管理者のGmailアドレス>"]
```

保存するとアプリが再起動し、ログイン画面が出るようになります。
`admins` に書いたアドレスでログインすると、既存のデータと「🛠 利用者管理」が使えます。

#### 3. 会社と利用者を登録する

「🛠 利用者管理」→「会社を追加」で、会社名と使う人のメールアドレス（Googleアカウント）を登録します。
登録された人はアプリの URL を開いて Google でログインするだけで使えます。
新しい会社は店舗もデータも空の状態から始まります（「⚙️ 設定」→「店舗管理」で店舗を登録）。

### データの保存先

Supabase の `app_storage` テーブル（`key` / `value`）に保存します。

| キー | 内容 |
|---|---|
| `master_data` / `invoice_data` / `config` / `rev` | ログイン導入前からの会社のデータ |
| `t:<会社ID>:master_data` など | 追加した会社ごとのデータ |
| `tenants` | 会社と利用者の一覧 |

同じ会社の複数人が同時に使っても、他の人の変更を上書きしないよう、保存時に版番号（`rev`）を確認しています。

## ローカルで起動

```bash
pip install -r requirements.txt
streamlit run app.py
```
