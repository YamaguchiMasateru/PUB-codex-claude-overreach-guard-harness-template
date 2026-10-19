# Herdr への接続形態と外部操作

出典: [Herdr CLI リファレンス](../../../../.repository-docs/examples/herdr-cli-reference.md)。コマンド仕様は使用中の Herdr の `--help` で確認する。以下の ID、machine 名、session 名は例示である。

## 同じ PC の別ターミナル

`herdr` は既定 session の TUI を起動または既存 session に接続する。CLI は稼働中サーバーのローカル socket API を使うため、TUI を開かずに `herdr status server`、`herdr pane list`、`herdr agent list` を実行できる。外部の VS Code ターミナルにも `herdr` CLI と接続先 session へのアクセスが必要。

名前付き session の TUI は `herdr --session <name>`。CLI は `HERDR_SESSION` で session を選択できる。現在の session は `herdr session list --json` で確認する。異なる session の ID を混ぜない。環境変数 `HERDR_SOCKET_PATH` は低レベルの socket 指定であり、通常は session 選択を使う。

ローカル操作では `herdr workspace create --cwd <path> --no-focus` の応答から `.result.root_pane.pane_id`、`herdr pane split <source-pane-id> --direction right --no-focus` の応答から `.result.pane.pane_id` を読む。`herdr pane list` でも ID を確認できる。`--no-focus` は画面のフォーカスを奪わない指定。`agent start` は既存の空いたシェルペインを使い、ペインや workspace を自動では作らない。

`herdr agent prompt <name-or-pane-id> <text> --wait` は観測された作業状態から待機状態への遷移を待つ。待機対象は個別のターンには紐付かない。timeout や `agent_prompt_stalled` の後は再送前に `herdr agent get` / `herdr agent read` で状態と出力を確認する。`agent read --source recent-unwrapped` は折り返しを除いた最近の出力、`--source visible` は現在の表示画面を読む。

## Herdr ペイン内の環境変数

`HERDR_ENV=1` は Herdr 管理ペイン内のプロセスに設定される。外部 CLI の認証条件や必須接続設定ではない。`--current` は呼び出し元の `HERDR_PANE_ID` を要求し、外部ターミナルではエラーになる。ペイン操作は明示 ID を指定する。`pane split` で対象を省略すると、呼び出し元ペインの ID があればそれを、なければフォーカス中のペインを使うため、外部自動化では省略しない。以前の「`HERDR_ENV` がないので接続できない」という説明は、エージェント向けガイドの停止条件を CLI の接続条件と取り違えたもの。

## SSH 先の TUI と遠隔 CLI

`herdr --remote <ssh-target>` は SSH 先の Herdr TUI に接続し、既定でローカルのキーバインドを使う。遠隔のキーバインドを使うなら `--remote-keybindings server`。名前付き遠隔 session は `--session <name>` を加える。

継続利用する SSH 接続は `herdr machine add <ssh-target> --label "Build machine"` で保存し、`herdr machine list --json` で確認する。遠隔の名前付き session を使う場合は `machine add` に `--remote-session <name>` を指定する。追加時にインストールや再起動の承認が必要なら対話ターミナルで操作する。保存済み profile はローカルクライアントから自動接続されるが、UI で machine を選んでも CLI の送信先は変わらない。

遠隔 API 操作には `herdr --machine "Build machine" pane list`、`herdr --machine "Build machine" agent prompt <remote-agent> "レビューして" --wait` のようにグローバル `--machine` を付ける。指定値は有効な保存済み profile の ID または一意で大文字小文字が一致する label で、任意の SSH ホスト名は使えない。`--machine` は `--session` / `--remote` と併用できない。遠隔ペイン ID は遠隔サーバーで取得する。ローカルの ID や `--current` は遠隔先を指さない。転送対応は API 系コマンドに限られ、対話的な terminal attach や session 管理には適用されない。遠隔 CLI のブリッジはサーバーのインストール、起動、再起動をしない。

## 接続や起動に失敗したとき

- `herdr status server` が失敗する場合、まず対象 session とサーバー状態、CLI バージョン、socket へのアクセスを確認する。VS Code の制限付き実行環境で socket のアクセスが拒否された実例では、許可された sandbox 権限昇格後に同じ CLI が動いた。権限昇格を一般的な接続要件とは扱わない。
- `--current` のエラーは `pane list` から ID を取得して明示する。
- `agent start` が失敗したら、指定ペインが存在し対話シェルの入力待ちか、同名エージェントが稼働中でないかを確認する。Windows ホストの Job Object が daemon 切り離しを拒否した実例では、Codex に `--no-daemon` を渡す `herdr agent start <name> --kind codex --pane <id> -- --no-daemon` が有効だった。
- 保存済み machine の自動接続が Attention の場合、表示された `herdr --remote <ssh-target>` を対話ターミナルで実行し、SSH 認証や必要な更新承認を終えてからクライアントを再起動する。遠隔 CLI 接続失敗はローカルへ自動フォールバックしない。
