# Claude Code の .env 読み取り拒否はエラー文がディレクトリ単位の表現になる

- 適用条件: `.claude/settings.json` の `permissions.deny` に `Read(**/.env)`、`Read(**/.env.*)` を置き、Claude Code のサブエージェントから `.env` を Read する場合。
- 観測結果（成功・失敗を区別）: 2026-10-18 の手動確認で、`investigate` と `review` の Read が `.env` に対して拒否された（成功）。エラー文は "File is in a directory that is denied by your permission settings." で、ファイルではなくディレクトリが拒否されたかのような表現だった。
- 教訓と次の行動: 拒否が効いていればこの文面は不具合ではない。文面だけを理由に `permissions.deny` の書式を再調査しない。拒否されず読めた場合に限り、書式とパスの解決を見直す。
- 根拠（確認できるパス・コマンド・資料）: [settings.json](../../../.claude/settings.json)。手動確認の記録はハーネス開発元の計画書 `add-claude-harness-plan/tasks.md` のフェーズ 5（配布物には含まれない）。
- 限界・未確認: Read ツールのみ確認した。`Bash` の `cat .env` などの経路は未確認（[読み取り専用役割の書込み経路](claude-read-only-roles.md)と同様、`Bash` は deny の対象外になりうる）。文面は CLI のバージョンで変わりうる。
- 確認日: 2026-10-18
