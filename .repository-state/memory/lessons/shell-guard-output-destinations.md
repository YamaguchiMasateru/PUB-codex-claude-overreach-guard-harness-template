# 読取り系コマンドも出力先の文法に沿って書込みを判定する

- 適用条件: Claude・CodexのPreToolUse guardで `external/repos` 等の保護パスへのshell書込みを判定する場合。Gitの明示出力、Git `-C`、Windowsのxcopy・robocopyを含む。
- 観測結果（失敗）: レビューで `git diff --output="external/repos/vendor/out.patch"`、`git -C external/repos/vendor diff --output=out.patch` 等の書込みが通ることを検出した。引用符付きオプション値やコマンド固有の操作cwdを取りこぼし、copy系の末尾引数だけを宛先とするとflags・wildcardsも宛先と誤認した。
- 観測結果（成功）: 両guardで引用符付き `--output` 値、Git `-C` 起点の相対出力、xcopy・robocopyの宛先を文法に沿って抽出する修正とRed→Green回帰テストを追加した。対象テスト成功後、親の全体checkも181 tests成功、POSIX専用1件skipだった。
- 教訓と次の行動: 読取りサブコマンドの名前だけで許可せず、出力オプションとコマンド固有の宛先位置を調べる。保護内を宛先にした拒否例と、保護内を読取り元にして保護外へ出す許可例を揃える。
- 根拠: `.claude/hooks/pretool_guard.py`、`.codex/hooks/pretool_guard.py`、`.harness/tests/test_claude_pretool_guard.py` と `.harness/tests/test_codex_pretool_guard.py` の `test_quoted_git_output`、`test_output_and_windows_copy_destinations`。Red→Greenの生出力は実装担当のtool出力のみ。親の全体checkログは `.harness/.harness-results/20261022T063653Z-380800/unit-tests.stderr.log`（Git管理外）。全体checkは120秒でtimeout後、上限300秒で成功した。設計と限界は [architecture.md](../../../.repository-docs/architecture.md)。
- 限界・未確認: 任意のshell間接実行・全コマンド文法を解析するものではなく、誤操作防止でありsecurity boundaryではない。Codexの実機Hook拒否は別途未確認であり、単体テスト成功から推定しない。読み取り専用役割全体の経路は [既存lesson](claude-read-only-roles.md) を参照する。
- 確認日: 2026-10-22
