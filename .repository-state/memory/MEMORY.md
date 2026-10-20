# 共有経験知の要約

テンプレート初期状態で同梱する lessons はハーネス開発に基づく公開用サンプルであり、導入先で追加する検証記録とは区別します。

- このリポジトリはチーム共通の作業手順を管理するテンプレート。導入先固有の確定事項は導入時に追加する。
- ハーネス独自設定の正本は `.harness/config/harness.toml`。
- 検査の生出力は `.harness/.harness-results/` に保存し、Git では管理しない。

- 完了条件に関係しない障害への調査拡大を避ける。[詳細](lessons/incidental-failures.md)
- AGENTS.md は入口と親の責務、役割別の詳細は Skill に置く。[詳細](lessons/instruction-duplication.md)
- 変更結果の確認依頼では独立した verify を起動する。[詳細](lessons/verify-launch.md)
- Windows Hook の `commandWindows` はシェルの解釈層を確認し、設定値そのものを PowerShell で検証する。[詳細](lessons/windows-hook-shell.md)
- Hook の子 Codex CLI は親が使う実行ファイルを特定して起動する。[詳細](lessons/parent-codex-cli.md)
- 検討だけの依頼を実装許可へ読み替えない。[詳細](lessons/investigation-edit-scope.md)
- 経験知候補は親が採否を閉じ、採用分の実保存を確認する。[詳細](lessons/memory-candidate-closure.md)
- Claude Code は `.agents/skills/` を Skill として探索しない。直接 Read では自動選択されず誤保存した。symlink ではなく一致検査つきの薄いラッパーを `.claude/skills/` に置く。[詳細](lessons/claude-skills-directory.md)
- 取り下げた方針の古い参照は、パス全体に加えて名前の一部でも検索する。[詳細](lessons/stale-reference-search.md)
- Claude の読み取り専用役割は `disallowedTools` だけでは `Bash`・`Artifact`・MCP などの書込みを防げない。PreToolUse Hook の許可リストで補うが、長オプションの接頭辞・`uv run` の厳密照合・`.env` 等の抜け穴を別の検証者が実コマンドで探す。[詳細](lessons/claude-read-only-roles.md)
- Claude の `.env` 読み取り拒否は有効だが、エラー文はディレクトリ単位の表現になる。文面だけで書式を再調査しない。[詳細](lessons/claude-env-deny-message.md)
- `claude -p --json-schema` は `$schema` キーを拒否する。Codex 用スキーマを流用せず外す。[詳細](lessons/claude-p-json-schema.md)
- Git Bash から `claude -p "/compact"` を渡すときは `MSYS_NO_PATHCONV=1` が要る。祖先探索の通しテストは入れ子の MSYS シェルでなくネイティブな親から行う。[詳細](lessons/windows-git-bash-claude-testing.md)
- Hook のルートは `CLAUDE_PROJECT_DIR` で決める（`git rev-parse` だけだと、cd した別リポジトリを指して全 Hook が止まる）。別リポジトリは `cd` せず絶対パスか `git -C`。[詳細](lessons/hook-root-from-cwd.md)
- ツールを制限した要約子には親Hookで取得したGit情報を明示入力し、対象repoと取得不能時の扱いを指定する。mockの成功は実LLM品質を証明しない。[詳細](lessons/compact-summary-repository-facts.md)
