# 外部リソース登録簿

外部リポジトリ、Splunk、サーバー、ローカル資料の参照を共有する入口です。初期状態の [registry.json](registry.json) は空で、接続先や組織固有の値を含みません。導入先で必要なリソースだけを登録します。

- [registry.json](registry.json): 登録簿の正本。
- [check_external.py](check_external.py): ローカルの存在・Git 状態・環境変数の設定有無を確認する CLI。
- [local-setup.md](local-setup.md): clone・junction の導入と撤去。
- `repos/`: 外部作業コピーの配置場所。Git 管理とハーネスの検索から除外します。

リポジトリルートで実行します。

```powershell
uv run --project . --locked --no-sync --offline python -X utf8 external/check_external.py
```

`--json` は結果を JSON にします。`--require-env` は環境変数の未設定も失敗とします。通常は読み取り専用で、`--record` を明示すると到達できた Git リポジトリの確認日・branch・commit だけを登録簿へ記録します。終了コードは `0` が成功（空の登録簿も成功）、`1` が未到達、`2` が登録簿の読込み・検証・記録エラーです。環境変数は設定有無だけを表示し、値と長さは表示しません。Splunk やサーバーへの通信は行いません。

登録簿の形式は `{ "schema_version": 1, "resources": [] }` です。未知のキー、必須キーの欠落、型違いを拒否します。`schema_version` は整数 `1` だけです。各要素の共通必須項目は次のとおりです。

| 項目 | 値 |
| --- | --- |
| `id` | 重複しない識別子。英数字で始め、英数字・`_`・`.`・`-` を使用 |
| `kind` | `git-repo`、`splunk`、`server`、`local-data` |
| `access` | `read-only`、`read-write`、`manual` |

任意項目は以下です。`access` は利用方針の記録であり、OS のアクセス権を変更しません。

| 項目 | 形式 |
| --- | --- |
| `path` | リポジトリ基準の相対パス。`git-repo` では必須で `external/repos/<名前>` 配下 |
| `remote` | 認証情報のない HTTPS URL。hostname と path を必須とし、userinfo・query・fragment・SSH・scp 形式を拒否 |
| `script_ref`、`python_ref` | `external/repos/` 配下の相対パス。Splunk では存在だけ確認 |
| `env_vars` | 環境変数名の配列。`[A-Z][A-Z0-9_]*` の形式で値を書かない |
| `link` | `{"kind":"junction", "source_env":"EXTERNAL_REPOS_ROOT"}`。kind は `junction` または `clone` |
| `verified` | `{"date":"YYYY-MM-DD", "branch":"main", "commit":"..."}`。`--record` が更新 |
| `note` | 任意の文字列。省略可能で、`--record` でも保持 |

パスの `\` は `/` に正規化します。絶対パス、drive 指定、`..` を拒否します。外部参照では junction の接続先を使えるため、登録簿にはローカルの絶対パスを書きません。秘密・個人情報を `note` や URL に書かないでください。

Git の確認は登録パス自体が Git ルートであることを確認します。通常 clone・worktree・junction を扱い、親リポジトリの下にあるだけの通常フォルダは未到達とします。branch、HEAD、未コミット変更件数、remote の一致、clone の push 無効化状態を表示します。remote 一致や push 無効化の表示は参考情報で、到達判定とは別です。`manual` のローカル資料は不在でも成功とします。サーバーは path がなければ確認不能として表示します。

外部リポジトリの正本は接続先にあります。外部配下へ書き込む操作は導入先の明示許可に従ってください。新しい検索・走査ツールにも `external/repos` の除外を設定します。CLI とハーネスの `validate` はアクセス権を強制する機構ではありません。
