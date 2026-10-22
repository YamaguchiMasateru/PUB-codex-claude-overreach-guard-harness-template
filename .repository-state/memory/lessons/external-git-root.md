# 登録先のGit到達性は親リポジトリのHEADで判定しない

- 適用条件: `external/check_external.py` によるローカル外部Git登録先の確認。登録先が親Gitリポジトリ配下の通常ディレクトリ、clone、worktree、Windows junctionである場合。
- 観測結果（失敗）: 非Gitの登録先ディレクトリでGitを実行すると親repoへ探索され、親のHEADが取得できた。到達可能と誤認する修正前実装に対し、ローカルfixtureの回帰テストが失敗した。
- 観測結果（成功）: `git rev-parse --show-toplevel` の結果と登録先をそれぞれ `Path.resolve()` し、実体一致を確認してからHEAD等を読むようにした。非Git子dirは未到達となり `--record` で誤ったverifiedを保存しない。正常repo・worktree・Windows junctionのfixtureは成功した。
- 教訓と次の行動: Gitコマンドの成功だけで登録先repoの存在を判断しない。登録先自身がGitのrootであることを確認し、親探索の誤検出と正当なリンク経由の到達を一組のfixtureで検証する。
- 根拠: `external/check_external.py` の `check_git_repo`、`.harness/tests/test_external_registry.py` の `GitIdentityTests.test_parent_repository_is_not_registered_repository` と `test_healthy_repository_and_worktree`。Red→Greenは実装担当の実行報告（永続生ログなし）。登録・確認手順は [external/README.md](../../../external/README.md)、設計入口は [harness-overview.md](../../../.repository-docs/harness-overview.md)。
- 限界・未確認: 成立範囲はローカルfixture。任意のalias、ネットワークパス、全ファイルシステムでの同一性は保証しない。Shell guardの字句的な保護パス比較へこの物理解決を無条件に流用しない。
- 確認日: 2026-10-22
