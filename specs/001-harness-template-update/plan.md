# 共通ハーネステンプレート更新計画

状態: **実行中（一部完了。Codex Hook の実機検証は未達）**

本書は実装の基準であり、現行の必須運用指示を変更しない。実行状況と未達条件は [tasks.md](tasks.md) に記録する。Codex Hook の実機検証は未達のため、全体完了とはしない。

## 方針と参照範囲

参照元は `ROHTO_ai`（場所は実行時指定）、反映先は本リポジトリの `feature/harness-external-resources`。確定選択は「汎用化できる変更を一式反映」「空の登録簿＋Hook有効」とする。

指定された非連続の3コミットは以下のとおり。

- `b64b722f2023490a9df343d0f4f788bb0170ea39`
- `5ce4fa82ba77d8c0b27953c8932cb48a838fd580`
- `362398d43c4c6e1ec8db774708a83eeaf5da2b8d`

最終 `362398d` のtreeを正本とし、次の範囲全体の中間変更の影響を確認して、指定3件の汎用機能の最終形だけを既存内容に統合する。コミット単位の逐次適用や8件の一括移植は行わず、中間のUS3業務移動まで対象を広げない。

| 履歴順 | 内容 | 扱い |
| --- | --- | --- |
| b64b722 | 外部管理・README | 汎用機能の最終形を統合 |
| 0e7aaab | US3作業記録・証跡・sampleをdocs外へ | 業務移動は除外、最終配置への影響を確認 |
| 5ce4fa8 | Claude guard | 既存Hookへ統合 |
| 37fada4 | docs READMEの内部path言及削除 | 文書の最終形を確認 |
| 83d87de | 重複sample削除 | 削除を尊重し重複を再導入しない |
| ce16979 | workspace取下げ | workspaceは提供対象外 |
| 6369345 | README前提・利用手順追加 | 汎用説明の最終形を確認 |
| 362398d | Codex guard | 最終treeを基準に統合 |

組織固有接続先・登録値、業務コード・業務データ（原資料・データ抽出物等の組織固有業務データ全般）、`external/evidence/`、参照元の既存specs履歴、未コミット変更は除外する。workspace作成と外部フォルダ追加手順は最終treeで取下げ済みのため含めない。汎用の外部管理導入手順は保持する。

元の経験知も一括転載対象外とし、対応表で以下をファイルごとに分類する。

- `.repository-state/memory/MEMORY.md`
- `.repository-state/memory/index.md`
- `.repository-state/memory/lessons/backup-untracked-docs-before-replace.md`
- `.repository-state/memory/lessons/claude-read-only-roles.md`
- `.repository-state/memory/lessons/compare-complete-source-locator.md`
- `.repository-state/memory/lessons/diff-against-authoritative-copy-before-moving.md`
- `.repository-state/memory/lessons/junction-external-repo-access.md`
- `.repository-state/memory/lessons/shell-write-guard-verification.md`
- `.repository-state/memory/lessons/uv-cache-dir-follows-cwd.md`

junction・shell guardは一般化候補、read-onlyは既存lessonへの統合候補として将来の検証後に再評価する。他は必要な実証がない限り除外する。現在は元知見の転載・保存を保留し、今回の文書修正ではメモリーを保存しない。将来テンプレートでの実装検証後にT028で元候補と新規実証知見を区別して評価し、新規知見の採否・採用分保存確認も既存repository-memory手順に従う。

## 外部リソース管理と入力基準

`external/` に登録簿、確認CLI、汎用導入手順を追加する。有効な初期値は `{"schema_version":1,"resources":[]}`、架空例は別sampleとする。種別 `git-repo`・`splunk`・`server`・`local-data` を維持し、実パス・認証情報は登録せずリポジトリ相対パスと環境変数名を使う。

受理・拒否fixtureで次の入力基準を固定する。schema_versionは整数1のみ対応し、bool・文字列・欠落・未対応値は登録簿不正2とする。暗黙移行はしない。noteは任意の文字列による一般説明とし、初期登録簿から省略して元の組織固有noteを転載しない。指定時は型検査し、通常checkで書き換えず、--recordでも保持する。

- topはobject、`resources` はlist、各要素はobject。`id` は非空文字列かつ一意、`kind` は既存4種（`git-repo`・`splunk`・`server`・`local-data`）、`access` は `read-only`・`read-write`・`manual` のenumとする。欠落キー・型不正を登録簿エラーとして扱い例外終了させない。
- path/refは文字列とし、backslashも正規化して絶対パス・ドライブ指定・`..` を拒否する。Gitのpathと `script_ref`・`python_ref` は `external/repos/` 配下に限定する。
- `env_vars` は配列で名前は `^[A-Z][A-Z0-9_]*$`、`link.kind` は `junction` または `clone` とする。
- remoteを記す場合はcredentialなしHTTPSのみとし、host/pathを必須とする。userinfo（user/password）、query、fragment、非HTTPSを拒否する。元実装が `@` を一律拒否するためSSH/scp形式（`git@host:path` 等）は今回対象外。認証はローカルcredential helper等に置く。
- エラーへ元remote値・環境変数値を出さない。未定義の無制限な秘密検出を保証しない。

通常CLIは読み取りのみ。`--json`・`--require-env`・明示更新の `--record` を維持し、終了コードは正常0、未到達1、登録簿不正2とする。Splunk等へ実接続せずローカル参照と環境変数の設定有無を確認する。通常検査から `--record` は呼ばない。

Git登録先と `git rev-parse --show-toplevel` の実体一致は移植とは別の新規不具合修正とする。最初に非Git子ディレクトリで親HEADを拾う現実装に失敗する回帰テストを作り、その後一致判定を実装する。親repo探索は未到達として誤ったHEADを `--record` で保存しない。正常clone・worktree・junctionの実体一致を許可する。

外部実体・junctionは `.gitignore` の `/external/repos/` とハーネス検索除外で対象外にする。Codex実装追加時は `!/.codex/hooks/pretool_guard.py`・`!/.codex/hooks/guard_rules.json` を明示し、新規2ファイルを共有対象にする。

## 両環境の保護と起動

Claudeは既存Hookへ統合、Codexは独立Hookを追加し、両環境で `external/repos` の保護を初期有効にする。Codexには `.codex/hooks/pretool_guard.py` と `.codex/hooks/guard_rules.json` の2ファイルを追加し、rulesの初期値を `{"protected_paths":["external/repos"]}` とする。シェル書込み、リダイレクト、コピー先、Git更新、Claudeファイル編集権限、Codex `apply_patch` を対象にする。読取り専用役割、承認規則、履歴Hook、compact-plusを置換せず維持する。`.claude/settings.json` の `permissions.deny` に `Edit(/external/repos/**)` を追加し、既存のenv denyは維持する。

Claudeのrootは既存の `CLAUDE_PROJECT_DIR` を維持する。これとは別の新規修正としてイベントの実cwdを保護判定へ渡し、相対操作パスをcwd起点で字句正規化する。cwd未使用の元 `protected_write_reason` が保護内からの直接削除をALLOWする欠陥を修正し、段階的cd・保護外への退出も検証する。

保護順序と失敗時の扱いは次のとおり。先行denyを後段fail-openで覆さない。

| 対象・順序 | 失敗時の仕様 |
| --- | --- |
| Claude 1: 既存read-only役割判定 | 例外はfail-closedを維持 |
| Claude 2: 全役割protected判定 | 判定例外はstderr警告＋allow |
| Claude 3: 既存Bash rules | 既存規則を維持 |
| Codex guardの実行・判定 | 例外はstderr警告＋allow |
| 規則ファイル不正 | 既定保護pathへfallback。判定例外とは区別し元挙動と整合するテストを置く |
| 構造validate | 不正設定をエラー検出。fail-openを設定正常とは扱わない |
| Hookプロセス起動前の失敗 | 判定器の警告と区別しruntime側の通知可否を確認 |

Codexの元起動は `git rev-parse` によるcwd依存。公式資料上のevent.cwdはsession cwdであり、ツール個別のworkdirとは区別する。別repoのtool.workdirだけで直ちに起動失敗とは断言しない。保証された `CODEX_PROJECT_DIR` 相当は今回未確認であり、不存在とも断定しない。実装前に版・起動時cwd・実入力・利用可能な安定root情報を実証する。安定rootがなければ導入先rootを起動時に固定して渡す手段を用意する。成立しなければCodex実装を保留し、未完了を報告して親が設計を改訂する。両Hook初期有効や別repo cwd要件を勝手に弱めない。T002のClaude確認とCodex安定root確認は成果・状態を分ける。Codex保留中も共通・Claudeの実装、文書、部分review・verifyは先行でき、環境ごとに成果と保留を記録する。Codex関連記述は未実装と明記して待つ。T028/T029の草案も作成できるが、環境横断タスクの全完了とT030の総合完了は両環境の成立を待ち、各チェックは当該タスク全条件成立時のみ付ける。

Hookは誤操作防止であり、間接書込みまで防ぐセキュリティ境界ではない。環境別構造検査に登録・必須ファイル・保護path・設定妥当性を追加する。

## 文書の統合

READMEは概要・前提・導入手順・詳細への入口に整理し、詳細構成を `.repository-docs/harness-overview.md` へ移す。ハーネス、導入先成果物、外部リソース、計画書、実行時データの汎用配置を説明する。`specs/README.md` は空の状態表と更新手順を用意し、参照元案件名・実績行・完了件数を含めない。AGENTS・文書索引・共有対象一覧・検索／構造検査設定を同期し、重複・旧説明・壊れた参照を統合する。

## 検証と完了条件

- 登録簿は空状態、schema_versionの整数1受理とbool・文字列・欠落・未対応値拒否、noteの型・保持、欠落・型不正、重複ID、不正path/ref、remote拒否条件、環境変数不足、到達不能、JSON、明示recordと通常実行の不変性、Git実体一致と誤HEAD記録防止を確認する。
- 合成Hook試験は読取り／保護外書込みの許可、保護内書込みの拒否に加え、引用符・コメント・heredoc・cd・Windowsパス・Git出力先・patch追加／削除／移動、Claudeの保護内cwdでの `rm victim.txt`・段階的cd・退出、判定順序・例外・fallbackを扱う。
- 合成fixtureは実repoへ書き込まず、実サービス・既存外部repoも更新しない。実ツール試験も隔離一時ディレクトリのみ。implement担当がT015/T018を実行し、runtime版、OS、起動/session cwd、tool.workdir、入力・期待・実結果・秘密を含まないGit管理外ログを記録する。具体担当は親がT003で割り当てる。
- CLIが役割で使えなければ親が代替実行してログ・制約を報告する。権限・認証不足は未達のままとし、ユーザー手作業を暗黙前提にしない。Windows実機確認とPOSIX起動形式／必要実行環境確認を区別し、未実行OSを成功扱いにしない。対応できない条件も明記する。
- 両環境の実ツールによる拒否、実際の入力形式、サブディレクトリ・別repo cwdでの正しい起動を必須とする。公式資料や合成成功だけで代替せず、実機確認不能なら未完了とする。
- 実装後に独立review・verifyを起動し、環境別・全体validateと標準checkを分担する。verifyはT027で証拠を独立確認し、未確認差分がある時のみ局所試験する。成功済み検査を重複実行しない。`git check-ignore -v --no-index` 等でCodex新規2ファイルが共有対象になることも確認する。
- 空登録簿で検査成功、既存機能の回帰なし、組織固有情報・壊れた参照なし、両環境の必須実機確認、知見採否と採用分保存確認を完了条件とする。8件の分類と指定3件の最終機能について、移植・一般化・新規修正・除外の対応表を報告する。

## 参考

[Codex Hooks公式資料](https://learn.chatgpt.com/docs/hooks)（親が2026-10-22に今回もopenして本文確認済み）はHook commandがsession cwdで動くこと、event.cwdがsession cwdであること、Bash／apply_patchの `tool_input.command` を記載する。この資料確認は現在の実機成功を証明しない。将来のT002で取得日・対象runtime版と該当する入力／起動記述を再照合する。取得不可なら未確認として、代替の公式根拠を取得するまで関連判断を保留する。
