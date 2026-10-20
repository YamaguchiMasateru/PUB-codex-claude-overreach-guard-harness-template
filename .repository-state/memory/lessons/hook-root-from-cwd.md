# Hook のルートを作業ディレクトリから求めると、別リポジトリへ移った瞬間に全 Hook が止まる

- 適用条件: Claude Code で、追加の作業ディレクトリ（例: `<別リポジトリ>`）を持つセッション。Hook のコマンドが `git rev-parse --show-toplevel` でルートを決め、`$root/.claude/hooks/*.py` を実行する構成。
- 観測結果（失敗）: 親が Bash で `cd <別リポジトリ> && ...` を実行し、Bash の作業ディレクトリがそこに残った（追加の作業ディレクトリなので自動では戻らない）。以降、PreToolUse がルートを `<別リポジトリ>` と解釈して `pretool_guard.py` を開けず、親と調査担当 3 件の Bash・PowerShell が全滅した。UserPromptSubmit も `compact_plus.py` を開けず「ブロック」扱いになり、サブエージェントの完了報告とユーザーの質問が親に届かず、セッションが無応答になった（ログ上 5 回）。Read / Grep / Glob は影響を受けなかった。
- 観測結果（成功）: Hook の環境には `CLAUDE_PROJECT_DIR` が `C:/Users/.../<project>` 形式で渡される（2026-10-20、`claude -p`、Windows で実測。ハーネス開発元での観測）。全 Hook の `root` を `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}` に変え、別の git リポジトリを作業ディレクトリにした一時環境で、3 種の Hook が起動することをテストで確認した。変更前の形は同じ状況で失敗する。
- 教訓と次の行動: Hook のルートは作業ディレクトリでなく、起動したプロジェクトを指すもの（`CLAUDE_PROJECT_DIR`）で決める。別リポジトリを調べるときは `cd` せず、絶対パスか `git -C <パス>` を使う。Hook を変えたときは、設定の実 `command` を別の git リポジトリを作業ディレクトリにして実行する確認を入れる。
- 根拠（確認できるパス・コマンド・資料）: `.claude/settings.json`、`.harness/tests/test_claude_compact_plus.py` の `test_configured_commands_ignore_cwd_in_foreign_git_repository`、`test_claude_pretool_guard.py`、`test_claude_subagent_history.py`。運用文書は [compact-plus.md](../../../.repository-docs/operations/compact-plus.md)、[subagent-history.md](../../../.repository-docs/operations/subagent-history.md)。元セッションのログはハーネス開発元の個人環境にあり、配布物には含まれない。
- 限界・未確認: `.codex/hooks.json` は未対応（Codex は `CLAUDE_PROJECT_DIR` を持たない）。実機で `cd` 済みのセッションから入力が通ることは、新しいセッションでの確認が必要。`CLAUDE_PROJECT_DIR` の挙動は claude.exe のバージョンに依存しうる。
- 確認日: 2026-10-20
