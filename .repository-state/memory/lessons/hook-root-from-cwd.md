# Hook のルートを作業ディレクトリから求めると、別リポジトリへ移った瞬間に全 Hook が止まる

- 適用条件: Claude Code で、追加の作業ディレクトリ（例: `<別リポジトリ>`）を持つセッション。Hook のコマンドが `git rev-parse --show-toplevel` でルートを決め、`$root/.claude/hooks/*.py` を実行する構成。
- 観測結果（失敗）: 親が Bash で `cd <別リポジトリ> && ...` を実行し、Bash の作業ディレクトリがそこに残った（追加の作業ディレクトリなので自動では戻らない）。以降、PreToolUse がルートを `<別リポジトリ>` と解釈して `pretool_guard.py` を開けず、親と調査担当 3 件の Bash・PowerShell が全滅した。UserPromptSubmit も `compact_plus.py` を開けず「ブロック」扱いになり、サブエージェントの完了報告とユーザーの質問が親に届かず、セッションが無応答になった（ログ上 5 回）。Read / Grep / Glob は影響を受けなかった。
- 観測結果（成功）: Hook の環境には `CLAUDE_PROJECT_DIR` が `C:/Users/.../<project>` 形式で渡される（2026-10-20、`claude -p`、Windows で実測。ハーネス開発元での観測）。全 Hook の `root` を `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}` に変え、別の git リポジトリを作業ディレクトリにした一時環境で、3 種の Hook が起動することをテストで確認した。変更前の形は同じ状況で失敗する。
- 教訓と次の行動: Hook のルートは作業ディレクトリでなく、起動したプロジェクトを指すもの（`CLAUDE_PROJECT_DIR`）で決める。別リポジトリを調べるときは `cd` せず、絶対パスか `git -C <パス>` を使う。Hook を変えたときは、設定の実 `command` を別の git リポジトリを作業ディレクトリにして実行する確認を入れる。
- 根拠（確認できるパス・コマンド・資料）: `.claude/settings.json`、`.harness/tests/test_claude_compact_plus.py` の `test_configured_commands_ignore_cwd_in_foreign_git_repository`、`test_claude_pretool_guard.py`、`test_claude_subagent_history.py`。運用文書は [compact-plus.md](../../../.repository-docs/operations/compact-plus.md)、[subagent-history.md](../../../.repository-docs/operations/subagent-history.md)。元セッションのログはハーネス開発元の個人環境にあり、配布物には含まれない。
- 限界・未確認: 以下の2026-10-22追記により「Codex未対応」という当初の状態は更新された。実機で `cd` 済みのセッションから入力が通ることは、新しいセッションでの確認が必要。`CLAUDE_PROJECT_DIR` の挙動は claude.exe のバージョンに依存しうる。
- 確認日: 2026-10-20

## Windows の短いパス表記を維持する

- 適用条件: Windows の Claude Code 2.1.207 が、Hook起動パス・イベントcwd・`CLAUDE_PROJECT_DIR` に同じ8.3短縮表記を渡す隔離環境。保護対象パスはイベントcwdを起点に字句正規化して比較する。
- 観測結果（失敗）: guardのプロジェクトrootを `Path(__file__).resolve()` で求めると長い表記へ変わり、短縮表記のイベントcwdと一致しなかった。実ツールの `touch external/repos/fixture/probe.txt` が通り、一時環境にファイルが出現した。
- 観測結果（成功）: `.claude/hooks/pretool_guard.py` の保護判定で `CLAUDE_PROJECT_DIR` の文字列表記を維持し、fallbackも `resolve()` ではなく `absolute()` とした。最終runtime traceではdeny、stderr空、対象ファイルなし。短縮表記の回帰テストも追加した。
- 教訓と次の行動: Hookを探すrootと操作cwdを分け、比較に使うrootの表記をruntime入力と揃える。物理パスへの解決が常に安全な正規化になるとは限らない。
- 根拠: `.claude/hooks/pretool_guard.py` の `protected_write_reason`、`.harness/tests/test_claude_pretool_guard.py` の `test_project_root_preserves_runtime_short_path_spelling`。失敗traceは `.harness/.harness-results/claude-protected-runtime-touch.json`、成功traceは `.harness/.harness-results/claude-protected-runtime-final.json`（Git管理外）。設計は [architecture.md](../../../.repository-docs/architecture.md)。
- 限界・未確認: この段階では短い表記と長い表記の混在が未対応だった。以下のnested起動修正で、event cwdの祖先からrepo rootを同定できる場合は対応した。任意のaliasやネットワークパス全般での一致は保証しない。
- 確認日: 2026-10-22

## nested 起動ではHookの所在とrootの実体を確認する

- 適用条件: Windows の Claude Code 2.1.207 をGit初期化済みの隔離repoの `nested` ディレクトリから起動する場合。`CLAUDE_PROJECT_DIR` がrepo rootではなくnestedを指すことがある。
- 観測結果（失敗）: `${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}` では値が設定済みなのでfallbackせず、`nested/.claude/hooks/pretool_guard.py` を探してmissingとなった。traceなし、probeなしだったが、これはguardのdenyではなくHookスクリプト起動エラーだった。
- 観測結果（成功）: `.claude/settings.json` のPreToolUse commandで候補rootにHookファイルがあるか確認し、なければGit rootへfallback、選択したrootを子の `CLAUDE_PROJECT_DIR` に渡すようにした。Python側は `_project_spelling` でevent cwdの祖先とproject rootの `samefile` 同一性を調べ、操作cwdの字句的表記にrootを揃える。修正後の実機traceではevent cwd・Hook cwdが8.3短縮表記のnested、project dirが長い表記でもPreToolUse deny、stderr空、probeなしを確認した。
- 教訓と次の行動: 環境変数の存在だけでHookの所在を保証しない。rootでの起動に加え、Git repoのnestedから設定の実commandが起動し、保護判定へ到達することを確認する。probe不在だけで拒否成功とせず、スクリプト起動エラーと明示denyを区別する。
- 根拠: `.claude/settings.json` のPreToolUse command、`.claude/hooks/pretool_guard.py` の `_project_spelling` と `protected_write_reason`、`.harness/tests/test_claude_pretool_guard.py` の `test_configured_command_falls_back_when_project_dir_has_no_hook`。失敗ログは `.harness/.harness-results/claude-protected-runtime-git-nested.json`、成功ログは `.harness/.harness-results/claude-protected-runtime-fixed-nested.json`（Git管理外）。設計は [architecture.md](../../../.repository-docs/architecture.md)。
- 限界・未確認: 実体比較はevent cwdの祖先からrepo rootを同定するために限定する。操作cwdや書込み先を物理解決してjunctionの外部targetへ置き換えない。無関係なパス間で意図的に混在させた任意のaliasやjunction、全ネットワークパスへの対応は保証しない。このHook所在fallbackを他のClaude Hookにも適用済みとはしない。
- 確認日: 2026-10-22

## Codex の起動rootと実機確認の状態を分ける

- 適用条件: ローカル Codex CLI 0.157.0、`.codex/hooks.json` にPreToolUse guardがある構成。Codexには `CLAUDE_PROJECT_DIR` に相当する文書化済みの変数を今回確認できていない。
- 観測結果（文書・調査）: `codex exec --help` は `-C, --cd <DIR>` を作業rootとして説明する。[公式Hooks資料](https://learn.chatgpt.com/docs/hooks)（親が2026-10-22確認）はcommand Hookの実行場所とevent `cwd` をsession cwdとする。起動時に `-C <repo>` を指定することでrootの前提を固定できる。個別toolのworkdirは別で、調査した入力では `tool_input.command` に含まれない。
- 観測結果（実機未成立）: T018の隔離repoでの入れ子起動はHook捕捉前にread-only sandbox／policyで阻止された。親による同一条件のfixture再試行も同じ原因で阻止され、`hook-events.jsonl` はなくprobeも存在しなかった。これはHookのdeny成功の証拠ではない。
- 教訓と次の行動: 起動rootの文書上の成立と実Hookの入力・拒否の実証を別々に記録する。実機検証はHookへ到達できる環境で継続し、session cwdから任意のtool workdirの安全性を推定しない。
- 根拠: `.codex/hooks.json`、`.codex/hooks/pretool_guard.py`、[plan.md](../../../specs/001-harness-template-update/plan.md)、[tasks.md](../../../specs/001-harness-template-update/tasks.md) のT018。実機ログはrepo外の一時環境 `C:\Users\M_YAMA~1\AppData\Local\Temp\codex-guard-runtime-5octtgqk\verification-summary.json` と同ディレクトリの `cli-stderr.txt`（永続配布物ではない）。親の再試行fixture `blocked-by-hook.txt` も未作成。
- 限界・未確認: Codexのlive Hook event入力と実ツールdenyは未確認。`-C` の文書上の条件だけで実機検証済みとしない。相当する安定root変数の不存在も断定しない。
- 確認日: 2026-10-22
