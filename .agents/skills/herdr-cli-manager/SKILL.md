---
name: herdr-cli-manager
description: VS Code など Herdr ペイン外のターミナルから Herdr CLI でワークスペース・ペイン・Codex エージェントを管理し、作業を分担させるときに使う。
---

# Herdr CLI から作業を分担する

外部ターミナルから同じ PC の Herdr サーバーへ CLI で接続する。最初に `herdr status server` と `herdr pane list` で接続先と既存ペインを確認する。`herdr` 単体は TUI を起動・接続するコマンドで、これらの CLI 操作に TUI 表示は不要。操作対象はその都度、応答または一覧で得た ID を使う。次の例は対象リポジトリのルートで実行する。

```powershell
herdr status server
herdr pane list
$cwdPath = (Get-Location).Path
$created = herdr workspace create --cwd $cwdPath --no-focus | ConvertFrom-Json
$paneId = $created.result.root_pane.pane_id
herdr agent start reviewer --kind codex --pane $paneId
```

Linux の Bash では同じ応答から Python 標準ライブラリでペイン ID を取得する。

```bash
herdr status server
herdr pane list
created=$(herdr workspace create --cwd "$PWD" --no-focus)
pane_id=$(printf '%s' "$created" | python3 -c 'import json, sys; print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
herdr agent start reviewer --kind codex --pane "$pane_id"
```

Windows の VS Code ホストに固有の問題として `host Job Object prevents daemon detachment; ... --no-daemon` と表示されて起動に失敗した場合は、同じ空きペインを指定して次のコマンドで再試行する。通常起動が成功した場合、この再試行は不要。

```powershell
herdr agent start reviewer --kind codex --pane $paneId -- --no-daemon
```

起動できたら依頼と状態確認を続ける。次のコマンドは PowerShell と Bash で共通。

```powershell
herdr agent prompt reviewer "この変更をレビューして" --wait
herdr agent get reviewer
herdr agent read reviewer --source recent-unwrapped --lines 120
```

既存ペインを分割するときは、`herdr pane list` で確認した分割元の ID を指定し、応答の `.result.pane.pane_id` を次の `agent start --pane` に渡す。Bash では次のように取得する。

```bash
source_pane_id="w1:p1"  # herdr pane list で確認した実際の ID に置き換える
split=$(herdr pane split "$source_pane_id" --direction right --no-focus)
pane_id=$(printf '%s' "$split" | python3 -c 'import json, sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])')
```

`agent start` の前に対象ペインを作り、そのペインの対話シェルが入力待ちであることを確かめる。エージェント名は生存中のエージェント間で一意にする。

この例の `reviewer` とペイン ID は実行時の値に置き換える。過去の `w6:p1` は実例であり固定 ID ではない。

`HERDR_ENV=1` は Herdr 管理ペイン内で設定される印であり、外部 CLI がサーバーへ接続するための条件ではない。`--current` は呼び出し元ペインの `HERDR_PANE_ID` が必要なので、外部ターミナルからは明示 ID を使う。ただし、適用中のエージェント向け Skill がペイン外での操作を制限する場合は、その指示とユーザーの明示的な指示に従う。

進行状況は `herdr agent get <name>` で状態を確認し、必要に応じて `herdr agent read <name>` で画面出力を読む。状態と出力だけで判断できないときに `herdr agent prompt <name> <質問>` でエージェントへ質問する。人が保存ログまで確認する手順は [references/agent-logs.md](references/agent-logs.md) を参照する。

Herdr のペインを閉じた後も委任先の Codex セッションを探せるよう、親セッション ID と委任先のエージェント名・ワークスペース ID・ペイン ID・Codex ネイティブセッション ID を `.agents/skills/herdr-cli-manager/session-state/sessions.md` に対応付けて記録する。スキル直下の `.gitignore` が `session-state/` を除外するため、スキルだけを別のリポジトリへ配置しても台帳は Git 管理外になる。`agent start` 直後にネイティブ ID が未取得なら `pending` と記し、`herdr agent get <name>` の `agent_session.value` で確認できたら更新する。ペインを閉じる前にも ID とログファイルの所在を再確認して更新する。ID が返らない場合は推測しない。具体的な確認方法と記録例は [references/agent-logs.md](references/agent-logs.md) を参照する。

別ターミナルの接続形態、名前付き session、SSH、保存済み machine、失敗時の確認方法は [references/connections.md](references/connections.md) を読む。詳細なコマンド仕様は [リポジトリ内の CLI リファレンス](../../../.repository-docs/examples/herdr-cli-reference.md) を参照し、バージョン差があるときはインストール済み `herdr --help` と各サブコマンドの `--help` を優先する。
