# 要約子へ再開用リポジトリ情報を明示入力する

- 適用条件: ツールを制限した要約子に、現在のGit情報を引き継ぐ場合。
- 観測結果: Codexのbranch入力がない状態では追加テストが失敗。親HookがROOTから取得して渡す変更後、取得・入力伝達・null時継続の6テストが成功した。
- 教訓と次の行動: 再開に必要な観測情報は親側で取得して明示入力し、対象repoと取得不能時の扱いを指定する。子の権限を緩めない。
- 根拠: [Hook](../../../.codex/hooks/compact_plus.py)・[テスト](../../../.harness/tests/test_compact_plus.py)の差分、変更前後のテスト実行ログ（Git管理外でハーネス開発元にあり、配布物には含まれない）。正式仕様は [compact-plus運用正本](../../../.repository-docs/operations/compact-plus.md) を参照。
- 限界・未確認: ROOTは編集中repoとは限らない。mockの成功は実LLMの出力品質を証明しない。
- 確認日: 2026-10-20
