# Windows の Git Bash から Claude Code 配下の Hook を試すときの落とし穴

- 適用条件: Windows で Git Bash から `claude -p` を起動して Hook を試す、または Hook の親プロセス探索を MSYS シェルの中でテストするとき。
- 観測結果（成功・失敗を区別）: 失敗1: Git Bash から `claude -p "/compact"` を渡すと MSYS のパス変換で `/compact` が `C:/Program Files/Git/compact` に化け、圧縮が発火しない。`MSYS_NO_PATHCONV=1` を付けると発火した。失敗2: MSYS の bash 内で `bash -c` を入れ子にしたりパイプ・サブシェルを使うと、Hook の祖先プロセス探索が `claude.exe` に届かない。成功: 実 Claude Code が起動した bash 配下の Hook では、空白入りパスでも祖先探索が成功した。ネイティブな親（Python の `subprocess` など）から Git Bash を直接起動する形でも連鎖は保たれた。
- 教訓と次の行動: スラッシュコマンドを Git Bash から渡すときは `MSYS_NO_PATHCONV=1` を付ける。祖先探索の通しテストは MSYS の入れ子シェルではなく、ネイティブな親から直接起動して行う。入れ子で失敗しても実 Claude 配下の不具合と判断しない。
- 根拠（確認できるパス・コマンド・資料）: [compact-plus.md](../../../.repository-docs/operations/compact-plus.md) の未確認事項。2026-10-18 の使い捨てプロジェクトでの実 `claude -p` 検証（verify サブエージェント）。関連: [Windows Hook のシェル](windows-hook-shell.md)。
- 限界・未確認: 検証は VS Code 拡張同梱の `claude.exe` 2.1.301、手動 `/compact` のみ。自動圧縮と PATH 上の別バージョンは未確認。
- 確認日: 2026-10-18
