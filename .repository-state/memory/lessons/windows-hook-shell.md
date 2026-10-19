# Windows Hook の PowerShell 実行層

公開用サンプル（ハーネス開発例）。

- 適用条件: Windows Hook runner が PowerShell で評価する `commandWindows` に、さらに変数入りの `powershell -Command` を渡す場合。
- 観測結果（成功・失敗を区別）: ハーネス開発では PowerShell を二重起動し、`$root` や `$LASTEXITCODE` が外側で展開されてコマンドが壊れ、`uv` の起動失敗と `hook returned invalid user prompt submit JSON output` が発生した。修正後は6つの `commandWindows` が直接 `git` と `uv` を実行する形となり、POSIX の `command` は維持した。空白を含むリポジトリパスとサブディレクトリから設定値を実行する回帰テストが成功した。
- 教訓と次の行動: まず Hook runner がどのシェルで何回解釈するかを確認する。この runner の `commandWindows` は直接 PowerShell スクリプトとして書く。入れ子の起動が必要なら外側による先行展開を検討する。Python 単体の成功だけで Hook 起動成功とせず、設定値そのものを runner と同じ PowerShell 呼出しに渡し、終了コード・stdout のJSON・Git root・空白パスを確認する。
- 根拠: [Hook 設定](../../../.codex/hooks.json)、[Windows 起動回帰テスト](../../../.harness/tests/test_compact_plus.py)、[運用文書](../../../.repository-docs/operations/compact-plus.md)。失敗時の原文ログは同梱しない。
- 限界・未確認: ハーネス開発時の Windows runner に関する例。他製品・別シェルでも二重起動が必ず壊れるという一般則ではない。元の失敗コマンドの再実行は本サンプルでは確認できない。
- 確認日: 未設定（公開用サンプル。導入先で検証後に記入）
