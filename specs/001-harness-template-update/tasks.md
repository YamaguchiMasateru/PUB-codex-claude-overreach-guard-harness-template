# 共通ハーネステンプレート更新のタスク

正本: [変更計画](plan.md)

状態: **実行中（一部完了。Codex Hook の実機確認は未達）**

チェック済み項目は担当結果を確認したうえで付ける。未チェックの項目は未完了であり、現行の必須運用指示は変更しない。Codex CLI の試行は Hook 到達前に read-only sandbox／policy で止まり、実機拒否を確認できなかったため T018・T027・T030 は未完了のままとする。

## 依存関係と分担

準備 → 外部管理 → Claude／Codex → 構造検査・文書 → 独立review・verify → 最終判定の順を基本とし、個別の依存IDを開始条件とする。T002はClaude確認とCodex安定root確認の成果・状態を分け、Codex部分の成立までT016に着手しない。Codex保留中も共通・ClaudeのT003〜T015と後続の該当部分を進められる。各タスク内に環境別の成果／保留を記録し、チェックは当該タスクの全条件成立時のみ付ける。部分着手・草案作成を全体完了としない。Claude／Codexは独立して進められるが、共有ファイルはT003で所有者を一人に割り当て直列編集する。既存テストを上書きせず、元テストは汎用化して差分統合する。最終362398d treeを正本とし、中間8件の影響を確認する。3コミットの逐次適用や8件の一括移植はしない。

## 準備

- [X] T001 参照元ROHTO_aiの場所を実行時指定し、反映先branchと計画記載の完全IDを確認する。

  最終362398d treeと8件の履歴について移植・一般化・新規修正・除外の分類対応表を作る。業務コード・業務データ（原資料・データ抽出物等の組織固有業務データ全般）、external/evidence/、組織registry値、既存specs履歴、未コミット変更、取下げworkspaceを除外し、計画列挙のmemory9ファイルを個別分類する。

- [X] T002 両runtimeの版、起動時/session cwd、実入力、tool.workdir、安定root情報と起動前失敗の通知可否を調査実証する（依存: T001）。

  成果はClaude確認部分とCodex安定root部分に分ける。公式URL https://learn.chatgpt.com/docs/hooks の取得日・対象runtime版・入力／起動記述の再確認を記録する。取得不可なら未確認とし代替公式根拠取得まで関連判断を保留する。ClaudeのCLAUDE_PROJECT_DIRを維持し、操作cwdと区別する。

  Codexはsession cwdとtool.workdirを混同せず、公式資料だけで成功としない。安定root情報がなければ導入先rootを起動時に固定して渡す手段を実証する。成立しなければT016を保留して未完了報告し、親が設計改訂する。初期有効・別repo cwd要件は弱めない。

- [X] T003 既存read-only役割・承認規則・履歴Hook・compact-plusの維持対象と共有ファイル所有者を定める（依存: T001）。

  親がimplement実機T015/T018と独立review・verifyの具体担当、環境別／全体validate・checkを割り当てる。CLI制限時の親の代替実行と成功済み検査の重複回避を分担表に記す。

- [X] T004 隔離一時ディレクトリ・Git repo・fixture・Git管理外ログ先を用意する（依存: T003）。

  合成fixtureは実repoを更新せず、実ツールも隔離先のみを対象とする。実サービス・既存外部repoへの書込みなしを確認する。


## 外部管理

- [X] T005 external/に空登録簿 `{"schema_version":1,"resources":[]}`、別sample、汎用導入手順を追加し、初期登録簿にはnoteを含めず元の組織固有noteを転載しない（依存: T004）。

  git-repo・splunk・server・local-dataを維持し、実パス・認証情報を含めず相対pathと環境変数名で指定できることを確認する。

- [X] T006 計画の入力基準に従い登録簿validationを実装し、受理／拒否fixtureで固定する（依存: T005）。

  schema_versionの整数1のみ受理とbool・文字列・欠落・未対応値の拒否（暗黙移行なし）、任意noteの文字列型、top/resources/要素の型、欠落、非空一意id、kind enum（git-repo・splunk・server・local-data）／access enum（read-only・read-write・manual）、path/refの型・backslash正規化・絶対／drive／..拒否、git path・script_ref・python_refの配下制限、env_vars配列と名前正規表現、link.kindを検査する。

  例外終了させず登録簿不正2とする。

- [X] T007 全種別の読取りCLIと `--json`・`--require-env` を実装する（依存: T006）。

  ローカル参照・env設定有無だけを確認しSplunk等へ実接続しない。計画のremote基準（credentialなしHTTPS、host/path必須、userinfo/query/fragment/非HTTPS拒否、SSH/scp対象外）をfixtureで検査する。エラーに元remote値・env値を出さず、正常0／未到達1／登録簿不正2を確認する。

- [X] T008 最初に非Git子dirが親HEADを拾う現実装で失敗する回帰テストを作り、その後、移植とは別の新規修正として登録先とshow-toplevelの実体一致判定を実装する（依存: T007）。

  非Gitdirは未到達、正常clone・worktree・junctionは一致成功とし、親HEAD誤取得を防ぐ。

- [X] T009 明示 `--record` の更新を実装する（依存: T008）。

  通常checkの不変性、指定noteを--recordでも保持すること、未到達時に親repo等の誤HEADを記録しないことをfixtureの前後比較で確認する。

- [X] T010 外部管理の統合ケースを確認する（依存: T006、T007、T008、T009）。

  空状態、schema_versionの整数1受理とbool・文字列・欠落・未対応値拒否、noteの型と保持、型不正・欠落・重複・不正path/ref・remote、env不足、到達不能、JSON、record更新と通常不変性を確認する。通常検査でrecordを呼ばないことを確認する。

- [X] T011 外部path定義に基づき `.gitignore` の `/external/repos/` とハーネス検索除外を追加する（依存: T003、T005）。

  外部実体・junctionがGit管理と検索対象から除外されることを確認する。workspaceは作成しない。


## Claude Code

- [X] T012 既存 `.claude/hooks/pretool_guard.py` へ保護を初期有効で差分統合する（依存: T002のClaude確認部分、T003、T004、T011）。

  `.claude/settings.json` の permissions.denyに `Edit(/external/repos/**)` を追加し、既存env denyを維持する。ファイル編集・shell書込み・redirect・コピー先・Git更新を対象とし既存機能を維持する。

  read-only判定（例外fail-closed）→全役割protected判定（例外stderr警告＋allow）→既存Bash rulesの順とし、先行denyを覆さない。

- [X] T013 既存CLAUDE_PROJECT_DIRによるroot決定を維持し、別の新規修正としてイベント実cwdを保護判定へ渡す（依存: T012）。

  cwd起点で相対操作pathを字句正規化し、元protected_write_reasonのcwd未使用による直接削除ALLOWを修正する。

- [X] T014 既存 `.harness/tests/test_claude_pretool_guard.py` へ元テストを汎用化して差分統合し、新規fixテストを追加する。

  `.claude/hooks/pretool_guard.py` のClaude合成試験で読取り・保護外書込みの許可と保護内書込みの拒否を確認する（依存: T013）。保護内 `rm victim.txt`、段階cd・保護外退出、引用符・コメント・heredoc・Windows path・Git出力先を含める。

  read-only先行deny／例外fail-closed、protected例外警告＋allow、先行deny非上書き、規則不正の既定path fallbackと判定例外の区別を元挙動と照合する。

- [X] T015 implement担当がClaude実ツールの拒否と起動を隔離先で確認する（依存: T014）。

  実入力による編集・shell拒否、サブdir・別repo cwdからの起動を確認する。版・OS・起動/session cwd・tool.workdir・入力・期待・実結果・秘密なしGit管理外ログを記録する。Windows実機とPOSIX形式／必要実行環境確認を区別し、未実行OSは成功扱いにしない。

  CLI制限時は親が代替実行し、権限・認証不足は未達として報告する。


## Codex

- [X] T016 T002のCodex安定root部分成立後、`.codex/hooks/pretool_guard.py` と初期有効保護を追加する（依存: T002のCodex安定root部分、T003、T004、T011）。

  `.codex/hooks/guard_rules.json` を作成し、初期値を `{"protected_paths":["external/repos"]}` とする。shell書込み・redirect・コピー先・Git更新・apply_patchを対象とし、実行／判定例外はstderr警告＋allow、既存機能は維持する。実装に合わせ `.gitignore` に `!/.codex/hooks/pretool_guard.py` と `!/.codex/hooks/guard_rules.json` を追加する。

- [X] T017 `.harness/tests/test_codex_pretool_guard.py` を追加し、元テストを汎用化して移植し新規fixテストを加える。

  `.codex/hooks/pretool_guard.py` のCodex合成試験で読取り・保護外書込みの許可と保護内書込みの拒否を確認する（依存: T016）。引用符・コメント・heredoc・cd・Windows path・Git出力先・patch追加／削除／移動を含める。

  `.codex/hooks/guard_rules.json` の既定値 `{"protected_paths":["external/repos"]}` と不正設定時のfallbackをテストする。実行／判定例外の警告＋allowと、規則不正の既定path fallbackを区別して元挙動に照合する。

- [ ] T018 implement担当がCodex実ツールの拒否と起動を隔離先で確認する（依存: T017）。

  実入力によるshell・apply_patch拒否、サブdir・別repo cwdからの起動を確認する。版・OS・起動/session cwd・tool.workdir・入力・期待・実結果・秘密なしGit管理外ログを記録する。Windows実機とPOSIX形式／必要実行環境確認を区別する。

  CLI制限時は親が代替実行し、権限・認証不足は未達として報告し、ユーザー手作業を暗黙前提にしない。


## 構造検査・文書

- [X] T019 `.harness/scripts/harness.py`・`.harness/config/harness.toml`・`.harness/tests/test_harness_environments.py` へ環境別のHook登録・必須file・保護path・設定妥当性検査を差分統合する（共通・Claude部分の依存: T012、Codex部分の依存: T016）。

  既存testを上書きせず追加テストを汎用化し、ClaudeのEdit(/external/repos/**)ルール存在を検査する。Codex保留中も共通・Claude部分を実装検証できる。不正設定はvalidateエラーとしfail-openを正常扱いしない。空登録簿・初期有効・通常record未使用を確認する。Codex部分では必須2file（`.codex/hooks/pretool_guard.py`・`.codex/hooks/guard_rules.json`）の存在とrulesの `protected_paths` の妥当性を検査し、`git check-ignore -v --no-index` 等で新規2fileが共有対象であることを確認する。

- [X] T020 READMEを概要・前提・導入手順・詳細への入口に整理し、詳細構成を `.repository-docs/harness-overview.md` へ移す（部分着手の依存: T011、T019の共通・Claude部分、Codex記述確定の依存: T019のCodex部分）。

  実装済部分の文書整備を先行し、Codex未実装部分は未実装と明記して待つ。最終treeを基準に重複sample・取下げworkspaceを再導入せず、旧説明・参照を統合する。

- [X] T021 実装結果に基づき配置規約・汎用導入手順・Hook限界を記す（共通・Claude部分の依存: T010、T012、T019の共通・Claude部分、T020の共通・Claude部分、Codex部分の依存: T016、T019のCodex部分、T020のCodex部分）。

  共通・Claudeの実装済部分を先行し、Codexは未実装と明記して待つ。ハーネス／導入先成果物／外部資源／計画／実行時データを区別し、workspace手順は含めない。判定順・fail-open／fail-closed・fallback・起動前失敗通知の制約、間接書込みを防ぐ境界ではないことと未対応条件を説明する。

- [X] T022 specs/README.mdに空状態表と更新手順を追加する（部分着手の依存: T021の共通・Claude部分、全完了の依存: T021全体）。

  実装済部分の状態表・更新手順を先行し、Codex保留は未実装と明記する。参照元案件名・実績行・完了件数を含めず、文書保存を実装完了として数えない。

- [X] T023 AGENTS・文書索引・共有対象一覧・検索／構造検査設定を同期する（部分着手の依存: T019〜T022の共通・Claude部分、Codex部分の完了依存: T019〜T022全体）。

  共通・Claudeの実装済部分を先行し、Codex未実装の索引・検査整備は未完了として待つ。重複・古い参照・壊れたリンク・組織固有情報・個人絶対pathを局所検索と参照検査で確認する。


## 独立review・verify

- [X] T024 独立reviewへ変更と分類対応表を渡す（共通・Claude部分の依存: T010、T014、T023の共通・Claude部分、Codex部分の依存: T017、T023全体）。

  共通・Claudeのみの部分reviewを先行できるが全体完了とはしない。最終state、cwd/root、Git実体一致、保護経路、例外方針、既存機能回帰の指摘を収集し、必須未達と対象外未確認を区別する。

- [X] T025 独立verifyが運用指示・設定変更を確認する（部分着手の依存: T003、T023の共通・Claude部分、全体検査の依存: T023全体）。

  共通・Claude部分のverifyを先行できるが全体完了とはしない。環境別・全体validateと標準checkを分担し、空登録簿成功・回帰なし・Codex2file共有対象を記録する。成功済み検査を重複実行しない。

- [X] T026 指摘を担当内で修正し、失敗と直接影響する検査だけを再実行する（共通・Claude部分の依存: T024/T025の共通・Claude部分、全完了の依存: T024/T025全体）。

  部分的な修正・再確認を先行できるが全体完了とはしない。追加差分に必要なレビューを更新し、必須未達を残して完了としない。

- [ ] T027 verifyがT015/T018の証拠を独立確認する（Claude部分の依存: T015、T026の共通・Claude部分、Codex部分の依存: T018、T026全体）。

  Claude証拠確認を先行できるが両環境確認まで全完了とはしない。両環境の実入力・拒否・別repo cwd起動と隔離先限定を確認する。未確認差分がある時のみ局所試験し、成功済み試験は繰り返さない。合成成功・公式資料・注記だけで代替せず、実機確認不能は未完了とする。


## 最終完了判定

- [X] T028 将来の実装検証後、保留中の元知見と新規実証知見を区別して評価する（草案着手の依存: T026/T027の共通・Claude部分、全完了の依存: T026/T027全体）。

  草案は先行できるが両環境の実証まで全完了とはしない。T001のmemory個別分類を踏まえjunction／shell guard一般化候補、read-only既存lesson統合候補を再評価し、他は実証なしなら除外する。親が採用・既存対応済み・不採用・保留を判断し、repository-memoryに従い採用分の所有者と本文・索引・必要要約の保存実在／差分を確認する。

  候補なしも明記する。今回の文書修正で保存しない。

- [X] T029 8件の分類対応表と指定3件の最終機能の対応を完成する（草案着手の依存: T026/T028の共通・Claude部分、全完了の依存: T026/T028全体）。

  分類草案は先行できるが両環境を待って確定する。移植・一般化・新規修正・除外、変更先・確認結果を報告し、中間US3業務移動や取下げworkspaceを混入させていないこと、memory9fileを個別分類したことを確認する。

- [ ] T030 必須完了条件を証拠と総合照合する（依存: T010、T025、T026、T027、T028、T029）。

  空登録簿検査成功、回帰なし、組織情報・壊れた参照なし、両環境の実機拒否と別repo cwd起動、知見採否・採用分保存を確認する。未達・未確認は未完了として残件を報告し、初期有効要件を弱めない。

## 移植結果の対応表

参照元の最終 `362398d` を基準に、間の履歴も次のように扱った。元repoの未コミット変更は読まず、組織固有の業務ファイル・データも転載していない。

| commit | 結果 |
| --- | --- |
| `b64b722` | 空登録簿、読取りCLI、外部管理の汎用手順、README分割を一般化。組織固有登録値・note・access情報は除外。 |
| `0e7aaab` | US3の業務記録・証跡移動は除外。配置規約に使える一般的なディレクトリ説明だけを最終treeから一般化。 |
| `5ce4fa8` | Claude CodeのPreToolUse保護を既存の読取り専用Hookへ統合し、root/event cwdの回帰も追加。 |
| `37fada4` | docs README内の内部path整理を、重複・古い参照を統合する方針へ一般化。 |
| `83d87de` | 重複sample削除を尊重し、重複例を再導入していない。 |
| `ce16979` | VS Code workspace提供は最終treeで取り下げ済みのため対象外。 |
| `6369345` | 前提・利用手順はテンプレート向けに一般化しREADMEへ統合。 |
| `362398d` | Codex PreToolUse Hook、rules、構造検査、テストを追加。Hook単体・構造検査は成功したが、実CLI runtimeでのHook拒否は未達。 |

経験知の参照元9ファイルも個別に分類した。

| source memory file | 結果 |
| --- | --- |
| `MEMORY.md`, `index.md` | 元repoのsummary/indexは一括転載せず、今回採用した対象repo側知見だけをtargetの既存index/summaryへ同期。 |
| `backup-untracked-docs-before-replace.md` | 保留。元 `docs/` の追跡状態に関する条件が本作業では再検証されていない。 |
| `claude-read-only-roles.md` | targetの同名lessonに本文相当の条件・教訓が既存。重複採用なし。 |
| `compare-complete-source-locator.md` | 対象とする業務XML・locatorがなく、対象外。 |
| `diff-against-authoritative-copy-before-moving.md` | 保留。対象repoの当該手順で原lessonのhash/改行判断を検証していない。 |
| `junction-external-repo-access.md` | 保留。外部Git root判定とは別のjunction走査・権限・撤去条件を本作業では実証していない。 |
| `shell-write-guard-verification.md` | 保留。今回保存した出力先文法のlessonとは条件が異なり、元lessonの全検証手順は再現していない。 |
| `uv-cache-dir-follows-cwd.md` | 保留。因果が元lessonでも未確認で、今回の対象環境では再検証していない。 |

対象repoで今回得た3つの採用知見は、既存 `hook-root-from-cwd.md` へのnested/short-path結果の追記、新規 `external-git-root.md`、新規 `shell-guard-output-destinations.md` に保存した。Codex Hook runtimeは到達前にsandbox/policyで拒否されたため、未達としてこの対応表とREADMEへ記録した。
