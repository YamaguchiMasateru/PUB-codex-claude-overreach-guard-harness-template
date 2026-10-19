# Herdr 上の Codex の状態とログを確認する

人が別ターミナルから確認するときは、対象のエージェント名を指定する。以下の `reviewer` は例なので、実際の名前に置き換える。

```powershell
herdr agent get reviewer
herdr agent read reviewer --source recent-unwrapped --lines 120
```

`agent get` は Herdr が検出した状態と、報告されていれば `agent_session` を返す。`agent read` はペインのターミナル出力を読む。`recent-unwrapped` は最近の出力を折り返しを除いて表示し、`visible` は現在の画面を表示する。表示された進捗メッセージ、ツール実行結果、回答を確認できるが、これは Codex 自身が保存するセッションログとは別の履歴である。状態や出力から判断できないことを本人に尋ねる場合は `herdr agent prompt reviewer "現在の状況を教えて" --wait` を使う。送信は作業中のエージェントへ入力する操作になる。

## Codex のセッションファイルを探す

Herdr がネイティブのセッション参照を受け取っている場合、`agent get` の応答に `agent_session.value` が入る。この ID とファイル名の ID を照合し、Codex の保存先（`CODEX_HOME/sessions`、未設定なら `~/.codex/sessions`）にある `rollout-*.jsonl` を探す。PowerShell では次のようにファイル名だけを列挙できる。

```powershell
$agent = herdr agent get reviewer | ConvertFrom-Json
$sessionId = $agent.result.agent.agent_session.value
if (-not $sessionId) { throw 'agent_session.value がありません' }
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
Get-ChildItem -LiteralPath (Join-Path $codexRoot 'sessions') -Recurse -File -Filter 'rollout-*.jsonl' |
    Where-Object { $_.Name -like "*${sessionId}*" } |
    Select-Object -ExpandProperty FullName
```

Bash では同じ ID とログのファイル名を次のように確認する。

```bash
session_id=$(herdr agent get reviewer | python3 -c 'import json, sys; value = json.load(sys.stdin)["result"]["agent"].get("agent_session"); session = value.get("value") if value else None; print(session or "", end="")')
if [ -z "$session_id" ]; then echo 'agent_session.value がありません' >&2; exit 1; fi
CODEX_LOG_SESSION_ID="$session_id" python3 - <<'PYCODE'
import os
from pathlib import Path

root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
for path in root.rglob("rollout-*.jsonl"):
    if os.environ["CODEX_LOG_SESSION_ID"] in path.name:
        print(path)
PYCODE
```

`agent_session` が返らない場合は、この方法では特定できない。ID が見つかってもファイル名の一致だけで判断せず、対象エージェントとセッションが同じか確認する。過去の `w6:p1` やそのセッション ID は一例であり、固定値として使わない。このコマンドはファイル本文を表示しない。本文を読む場合は、会話内容や実行結果などが含まれることを踏まえ、必要な範囲だけを確認する。

## ペインを閉じた後のために ID を残す

このリポジトリでは、個人の作業記録を Git 管理外の `.agents/skills/herdr-cli-manager/session-state/sessions.md` に保存する。親 Codex セッション ID とログパス、委任先の Herdr エージェント名・ワークスペース ID・ペイン ID・Codex ネイティブセッション ID とログパス、記録日と用途を一組として書く。会話本文は転記しない。

親 Codex セッション ID は PowerShell では `$env:CODEX_SESSION_ID`、Bash では `${CODEX_SESSION_ID:-}` で確認できる。値がない環境では親 ID を `pending` と記し、Codex のセッション表示や既知の `rollout-*.jsonl` のファイル名などから別途確認してから埋める。ログ本文を読む必要はない。

`agent start` 直後に `agent_session.value` がまだ返らなければ委任先 ID を `pending` として記録し、`herdr agent get <name>` で取得後に更新する。ペインを閉じる前に再度 `agent get` を確認し、上のファイル名検索でログパスの存在も確認して記録を更新する。ID が取得できない場合は空欄を推測で埋めず、その旨を記す。ID を保存しても、Codex 側の保持設定やファイルの削除によって、後日のログ閲覧を保証するものではない。

保存ログに `reasoning` レコードがあっても、`encrypted_content` は読める形の思考過程ではない。画面やログに表示された進捗説明と、モデルの非公開の reasoning 全文は異なる。JSONL のレコード構造や Herdr の応答構造はバージョンで変わり得るため、上のプロパティが見つからないときは実際の応答とインストール済み CLI の `--help` を確認する。
