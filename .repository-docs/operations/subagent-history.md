# サブエージェント履歴の参照

## 共通の概要

サブエージェントの終了時に Hook が、親セッション、エージェント ID、履歴ファイルのパスだけを Git 管理外の実行時ステートへ記録します。履歴本文、最終メッセージ、Hook 入力全体は複製しません。ここは新しいスキルではありません。新しいユーザーターンの開始時には、もう一方の Hook が現在の `session_id` と参照コマンドを追加コンテキストとして案内します。Codex と Claude Code は別の実装・別の記録先を持ち、`list` と `show` の引数体系は同じです。

親はサブエージェントの完了報告を集めた後、案内されたセッション ID で一覧を読み、必要な履歴を `record_id` で開きます。リポジトリのルートで、自分が動いている環境のコマンドを使います。

- 一覧の記録日時は JST、JSON 出力の `recorded_at` は UTC です。一覧には履歴パスも表示します。
- 一覧には `record_id`、`agent_id`、`agent_type` と履歴の状態を表示します。`path-null` はフック入力にパスがない状態、`missing` は後からファイルが消えた状態、`unreadable` は読めない状態、`readable` は参照可能な状態です。
- 記録がない場合は、未実行・フック不発・保存失敗の可能性を区別できません。現在のセッション ID が案内されていない場合、最新の別会話を推測せず、現在のフック入力を確認できる次のユーザーターンを待つか、把握済みのセッション ID を明示して実行します。
- `show` は `--tail N`（末尾 N 行）か `--start N --lines M`（N 行目から M 行）で開きます。1 回の表示は最大 200 行・20000 文字です。
- 記録や案内に失敗した Hook は、終了コード 0 のまま標準エラーに `subagent history: <例外名>` を出し、標準出力に `systemMessage` の JSON を返します。
- 並列起動を手動確認するときは、親が各完了報告を収集した後に `list` の件数と ID を照合し、`show` で必要な範囲を確認します。履歴ファイルが消失しても記録の状態表示で判別できます。

## Codex 用コマンド

`.codex/hooks.json` の `SubagentStop` が親セッション、ターン、エージェント ID と履歴ファイルのパスを `.repository-state/subagent-history/codex/records/` に記録します。実装は `.codex/hooks/subagent_history.py` です。`UserPromptSubmit` の案内には PowerShell 版と POSIX 版の参照コマンドが含まれます。

```text
uv run --project . --locked --no-sync --offline python -X utf8 .codex/hooks/subagent_history.py list --session-id '案内されたID'
uv run --project . --locked --no-sync --offline python -X utf8 .codex/hooks/subagent_history.py list --session-id '案内されたID' --agent-id '対象agent_id' --json
uv run --project . --locked --no-sync --offline python -X utf8 .codex/hooks/subagent_history.py show --record-id '一覧のrecord_id' --tail 50
uv run --project . --locked --no-sync --offline python -X utf8 .codex/hooks/subagent_history.py show --record-id '一覧のrecord_id' --start 1 --lines 50
```

初回と新しい会話では実行環境の hooks UI で `.codex/hooks.json` のコマンドを確認し、必要な trust 操作を行います。設定変更は実行中の会話に反映されない場合があるため、新しい会話とユーザーターンで確認します。

### Codex の実セッションでの確認（2026-10-15）

- 条件: Linux、Codex CLI 0.153.4、通常のユーザー設定と信頼済みプロジェクト、親は `workspace-write`。試験用の親モデルは `gpt-6-astra`。組み込み `default` 役の子を1件、`fork_turns=none`、読取りだけの指示、モデル指定なしで起動した。確認済みの Hook に限り、この試験では `--dangerously-bypass-hook-trust` を一時的に使用した。通常導入時の hooks UI での trust 操作や、その永続設定の検証とは区別する。
- 成功: `UserPromptSubmit` から参照 CLI と現在のセッション ID が追加コンテキストに渡された。子の終了時に `SubagentStop` の記録が1件でき、履歴状態は `readable` だった。`list --json` と `show --tail 2` は終了コード0で成功した。試験は読取り指示で行い、履歴本文やフック入力全体は記録先へ複製されていない。
- 未確認: 子の sandbox が `read-only` の場合の記録、同種・異種の並列起動時の記録と親の wait の順序、Windows 実機、指定4役割それぞれのモデルでの起動可否。モデルの利用可否は [README の導入手順](../../README.md) に従い導入先で確認する。

## Claude 用コマンド

`.claude/settings.json` の `SubagentStop`（matcher `*`）が、親セッション、エージェント ID、`agent_type`、履歴ファイルのパスを `.repository-state/subagent-history/claude/records/` に記録します。実装は `.claude/hooks/subagent_history.py` で、Codex 版とコードは共有しません。`UserPromptSubmit` は現在の `session_id` と POSIX 版の `list` コマンドを案内します。

- 各 Hook の `command` は `"shell": "bash"` を明示します。Windows では Git for Windows（Git Bash）が前提で、`commandWindows` に当たる分岐はありません。
- Claude の入力に `turn_id` がないため、記録しません。内部エージェントを含め `SubagentStop` が届いたものはすべて記録し、`agent_type` が無い・空・文字列でない場合は未設定として扱います。
- 履歴ファイル（`agent_transcript_path`）は JSONL です。Windows ではバックスラッシュ区切りで届きますが、受け取ったまま保存し、読み出し時にパスとして扱います。行のスキーマは公式に定められていないため、`show` は行の内容を解釈せず、未知の行や欠落があっても行単位で表示します。
- `SubagentHandback` の本文を残す Hook は追加しません。サブエージェントの最終報告は親が受け取る完了報告を正とし、履歴は補助の確認に使います。

```text
uv run --project . --locked --no-sync --offline python -X utf8 .claude/hooks/subagent_history.py list --session-id '案内されたID'
uv run --project . --locked --no-sync --offline python -X utf8 .claude/hooks/subagent_history.py list --session-id '案内されたID' --agent-id '対象agent_id' --json
uv run --project . --locked --no-sync --offline python -X utf8 .claude/hooks/subagent_history.py show --record-id '一覧のrecord_id' --tail 50
uv run --project . --locked --no-sync --offline python -X utf8 .claude/hooks/subagent_history.py show --record-id '一覧のrecord_id' --start 1 --lines 50
```

設定の変更は実行中のセッションに反映されない場合があるため、`/hooks` で登録を確認し、新しいセッションとユーザーターンで動作を確認します。

### Claude の確認状況

- 確認済み（2026-10-18、Windows、`claude -p`、claude.exe v2.1.301）: `"shell": "bash"` は Git Bash で起動する。`git rev-parse --show-toplevel` は `C:/...` 形式で、空白を含むパスも二重引用符で扱える。`uv` は PATH で解決でき、`uv run --project "$root" --locked --no-sync --offline python -X utf8 ...` が成功する。`hookSpecificOutput.additionalContext` はモデルに届き、`systemMessage` は通知として出る。
- 自動テスト: `.harness/tests/test_claude_subagent_history.py` が、設定の実 `command` を bash でサブディレクトリ・空白入りパスの一時リポジトリから実行し、記録、秘密情報の非保存、並列書込み、巨大行、BOM、不正入力、`list`/`show` を確認する。bash・uv・git がない環境ではこの 1 件だけ skip する。`harness.py` の `--env claude` 検査が、Hook の登録、`"shell": "bash"`、参照する実行ファイルの存在を確認する。
- 実機確認（2026-10-19）: 手動 `/compact` の直後に、`agent_type` が空で transcript が存在しない（`transcript_status=missing`）記録が 1 件残った。内部エージェントの `SubagentStop` は `agent_type` が空で届くため、未設定として扱う実装で記録できている。
- 未確認: 内部エージェントごとの `agent_type` の種類、`SubagentStop` の `systemMessage` の表示先、並列起動時の記録。
