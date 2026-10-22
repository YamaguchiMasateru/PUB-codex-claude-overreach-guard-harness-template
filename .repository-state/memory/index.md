# リポジトリ経験知の索引

テンプレート初期状態で同梱する以下の lessons は、ハーネス開発の知見を一般化した公開用サンプルです。導入先で追加する記録とは区別し、適用時に条件・根拠・確認日を見直してください。

- [MEMORY.md](MEMORY.md): 短い要約
- [付随的な障害](lessons/incidental-failures.md)
- [指示の重複](lessons/instruction-duplication.md)
- [verify 起動漏れ](lessons/verify-launch.md)
- [Windows Hook の PowerShell 実行層](lessons/windows-hook-shell.md)
- [Hook では親 Codex と同じ実行ファイルを使う](lessons/parent-codex-cli.md)
- [検討依頼を実装修正の許可へ読み替えない](lessons/investigation-edit-scope.md)
- [経験知候補の報告だけで保存完了としない](lessons/memory-candidate-closure.md)
- [Claude Code では .agents/skills を Skill として探索しない（薄いラッパーを一致検査つきで置く）](lessons/claude-skills-directory.md)
- [取り下げた方針の古い参照は、パスの一部の名前でも検索する](lessons/stale-reference-search.md)
- [Claude Code の読み取り専用役割に残る書込み経路](lessons/claude-read-only-roles.md)
- [Claude Code の .env 読み取り拒否はエラー文がディレクトリ単位の表現になる](lessons/claude-env-deny-message.md)
- [claude -p の --json-schema は $schema を拒否する](lessons/claude-p-json-schema.md)
- [Windows の Git Bash から Claude Code 配下の Hook を試すときの落とし穴](lessons/windows-git-bash-claude-testing.md)
- [Hook のrootと操作cwdを分ける（Windows短縮表記、Codexの起動rootと実機未確認を含む）](lessons/hook-root-from-cwd.md)
- [登録先のGit到達性は親リポジトリのHEADで判定しない](lessons/external-git-root.md)
- [読取り系コマンドも出力先の文法に沿って書込みを判定する](lessons/shell-guard-output-destinations.md)
- [要約子へ再開用リポジトリ情報を明示入力する](lessons/compact-summary-repository-facts.md)
