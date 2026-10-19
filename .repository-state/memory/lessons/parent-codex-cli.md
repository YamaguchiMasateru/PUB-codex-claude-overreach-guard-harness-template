# Hook では親 Codex と同じ実行ファイルを使う

公開用サンプル（ハーネス開発例）。

- 適用条件: Codex CLI と VS Code の Codex 拡張機能など、複数の Codex 実行ファイルが同居し、Hook の Python から `codex exec` を呼ぶ場合。
- 観測結果（成功・失敗を区別）: ハーネス開発では同じ入力・引数・モデル・接続先でも、PATH 上の旧 CLI はモデル非対応エラーとなり、拡張機能同梱の CLI は JSON を出力した。Python は直接 API へ接続せず、子の CLI を起動していた。個人設定ファイルへのパス固定は clone 先の解決にならず、親との版一致を条件に旧 CLI の実行を拒否するだけの修正も、親 CLI を使う要件を満たさなかった。
- 教訓と次の行動: 認証やモデル変更を決める前に、Hook→Python→子CLIの実行経路と実体パスを確認する。環境変数のコピーや版一致は親実体の引継ぎを保証しない。プロセス祖先から親が実際に使う Codex の絶対パスを取得し、その同じファイルで `--version` を確認して `exec` する。特定できなければ別の CLI を推測して使わず、既存診断とバックアップを保つ。Windows の祖先探索では Codex のPIDと、さらに上位の `Code.exe` のPIDを取り違えない。
- 根拠: [親 CLI 取得と起動](../../../.codex/hooks/compact_plus.py)、[同一実行ファイル・祖先 PID・POSIX fixture のテスト](../../../.harness/tests/test_compact_plus.py)、[正式な運用手順](../../../.repository-docs/operations/compact-plus.md)。実行結果の原文ログは同梱しない。
- 限界・未確認: ハーネス開発時の Windows に関する例。Linux・macOS の祖先取得は fixture のみ。実 Hook による要約・LLM 応答は本サンプルでは確認できず、版確認や fake CLI テストだけでサービス成功を保証しない。
- 確認日: 未設定（公開用サンプル。導入先で検証後に記入）
