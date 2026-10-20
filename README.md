# Codex Overreach Guard ハーネステンプレート

このリポジトリは、Codex や Claude Code がユーザーの指示や想定を超えて作業範囲を広げたり、意図されていない操作を実行したりすることを抑えるためのハーネステンプレートです。作業手順による抑制と実行権限による制御を組み合わせ、依頼された範囲で作業を進め、その結果を確認できる構成を提供します。

初期状態で提供する手順と、導入先で選んで有効化する制御例があります。配置だけですべての逸脱を防ぐものではありません。タスクで必要な操作と許可しない操作に合わせて、制御を変更・追加してください。Codex は [AGENTS.md](AGENTS.md)、Claude Code は [CLAUDE.md](CLAUDE.md)（`AGENTS.md` を import）を入口に、依頼に応じた Skill、設計文書、確定済みの知識を参照します。手順の正本は両者で共有し、実行環境ごとの起動手順・設定・Hook は環境別に持ちます。

## 初期状態で抑制する範囲と、サンプルの範囲

| 区分 | 提供する内容と適用範囲 | 調整先 |
|---|---|---|
| 指示・共有知見で抑制している範囲 | 担当範囲を明示した役割への委任と親による結果統合。エラー対応時は、完了条件と関係しない調査へ広げません。検証は必要な範囲に絞り、実サービス接続の明示依頼を確認し、外部状態・本番への書き込みを検証依頼から推定しません。関連する既知の問題を参照し、調査拡大・指示の重複・検証役割の起動漏れなどの再発を避けます。エージェントが従う作業手順と、参照して活用する共有知見です。 | [AGENTS.md](AGENTS.md)、[各 Skill](.agents/skills/)、[運用規約](.repository-docs/conventions.md)、[共有知見](.repository-state/memory/index.md) |
| 設定・スクリプトで提供している範囲 | 役割登録と役割別設定、検索 CLI の検索・表示量の上限、構造・参照検査、設定済み検査コマンドの実行とログ保存。検索上限や検査は、このハーネスの CLI を使ったときに適用されます。 | [Codex 設定](.codex/config.toml)、各 Skill の `agent.toml`、[Claude の役割定義](.claude/agents/)、[Claude 設定](.claude/settings.json)、[ハーネス設定](.harness/config/harness.toml) |
| 任意で有効化する制御例 | 承認・サンドボックスの共通設定、Web・shell・ネットワーク・Apps・MCP の制御、Rules の `prompt`／`forbidden`。Codex ではコメントアウトした例であり、このテンプレートでは有効化していません。Claude Code では `.env` 系の読み取り禁止だけを `.claude/settings.json` で有効にし、他は例として示します。 | [Codex 設定](.codex/config.toml)、[Rules](.codex/rules/default.rules)、[Claude 設定サンプル](.repository-docs/examples/claude-settings.sample.md) |
| 初期有効の Hook（Codex） | `hooks.json` はサブエージェント履歴の記録・案内に加え、`compact-plus` の圧縮前バックアップ、要約、圧縮後の復旧と使用率通知を有効化します。 | [Hook 設定](.codex/hooks.json)、[運用手順](.repository-docs/operations/compact-plus.md) |

Claude Code 用には、サブエージェント履歴の Hook（`.claude/hooks/subagent_history.py`。`.claude/settings.json` の `SubagentStop` と `UserPromptSubmit`）と、compact-plus の Claude 版（`.claude/hooks/compact_plus.py`。`PreCompact`、`PostCompact`、`SessionStart`、`UserPromptSubmit`）を提供します。権限制御には PreToolUse Hook（`.claude/hooks/pretool_guard.py` と規則ファイル `.claude/hooks/guard_rules.json`）を提供します。`investigate` と `review` の `Bash` を読み取り専用コマンドの許可リストに限り、`Artifact` 系などを拒否します。規則ファイルには `.codex/rules/default.rules` に当たる ask / deny の規則を置けます（既定は空）。補完であってセキュリティ境界ではなく、MCP の書込み系ツールなどは防げません（詳細は [Claude Code の手順と役割](#claude-code-の手順と役割)）。

指示による抑制は、OS やツールによる強制禁止とは異なります。また、このリポジトリの設定例が無効でも、ユーザー設定や親セッション、実行環境による権限・制限は別途適用され得ます。各制御の対象は設定内の説明を確認してください。

## 前提条件

- 実行環境: Codex CLI または Claude Code。導入する環境のぶんだけ用意すれば足ります。
- `uv`: 仮想環境の作成とコマンド実行に使います。
- Python 3.14 以上: `pyproject.toml` の `requires-python` が `>=3.14` です。未導入なら `uv python install 3.14` を実行してください。
- `git`: Claude Code の Hook は `CLAUDE_PROJECT_DIR` をルートとして使い、未設定のときだけ `git rev-parse --show-toplevel` で求めます。
- Git for Windows（Git Bash）: Windows で Claude Code を使う場合に必要です。Claude の Hook 設定は `"shell": "bash"` を明示しており、Git Bash がない環境では Hook が失敗します。
- Codex CLI または `claude`: compact-plus が要約のために起動します。Codex 版は追加の `codex exec` を使うため Codex CLI が必要で、Claude Code 版は親と同じ `claude` を使います。
- ネットワーク: 初回の `uv sync` だけ通信が必要です。以降のコマンド例は `--offline` で動きます。
- OS: Windows（PowerShell）と Linux（Bash）のどちらでも、次の例のコマンドを実行できます。macOS は未検証です。

## このテンプレートを試す

[前提条件](#前提条件)を満たしたうえで、このリポジトリのルートで次のコマンドを実行します。

```text
uv sync
uv run python --version
uv run --project . --locked --no-sync --offline python -X utf8 .harness/scripts/inspect_repo.py search harness
uv run --project . --locked --no-sync --offline python -X utf8 .harness/scripts/inspect_repo.py show AGENTS.md 1
uv run --project . --locked --no-sync --offline python -X utf8 .harness/scripts/harness.py validate
uv run --project . --locked --no-sync --offline python -X utf8 .harness/scripts/harness.py check
```

- `uv sync` は `.python-version` と `pyproject.toml`、`uv.lock` に従う仮想環境を用意します。既に同期済みなら `uv run` から実行できます。`uv` のキャッシュ先は `pyproject.toml` の `uv.chash/` です。
- `search` は一致したファイルと最初の行番号を一覧にし、`show` は指定行の周辺だけを表示します。結果が上限に達したら検索語や対象を絞ります。
- `validate` は設定、必須ファイル、役割定義、文書の参照先、共通ファイルへの環境固有の記述の混入などを検査します。`--env codex` や `--env claude` を付けると、共通部分とその環境だけを検査します（省略時は設定済みの全環境）。`check` は構造検査に加え、設定済みのコマンドを実行します。
- `check` の生出力は `.harness/.harness-results/` の実行別ディレクトリに残ります。失敗時は要約から該当ログを確認します。検査コマンド、検索範囲、表示上限、ログ先の正本は `.harness/config/harness.toml` です。

## 既存リポジトリへ導入する

1. タスクで必要な読み取り・編集・検査・外部接続と、許可しない操作を整理します。
2. 下の構成図を参考に、`AGENTS.md`、`.agents/skills/`、利用する実行環境の共有対象ファイル（Codex は `.codex/`、Claude Code は `CLAUDE.md` と `.claude/`）、`.harness/` の設定・スクリプト・テスト、`.repository-docs/`、`.repository-state/memory/` を導入先へ配置します。既存の `AGENTS.md`、`.codex/`、`.claude/`、文書があれば内容を統合し、上書きしません。片方の環境だけを導入する場合でも、README や運用文書には他方の環境の設定へのリンクが残るため、`validate` のリンク検査が失敗します。不要な環境のリンクと `harness.toml` の `environments` から該当環境を取り除いてください。この README は導入先の案内へ必要な説明を取り込みます。共有するファイルと除外する生成物は末尾の「Git で共有する範囲」を参照してください。
3. ハーネス用の Python 3.14 以上の実行環境を用意します。既存の `pyproject.toml`、`.python-version`、`uv.lock`、`.gitignore` は導入先の依存関係・実行環境に合わせて統合します。ロックファイルは導入先の定義から更新し、製品の Python 要件を一律に変更しません。製品とハーネスで要件が異なる場合は実行環境を分け、以下の検査をハーネス用の Python で実行してください。
4. 上の表を使って既存の指示と有効設定で足りるか確認し、必要な設定例だけを調整・有効化します。Apps と MCP は実際の ID とツール名へ置き換えます。不足する制御は Rules や Hook、導入先の運用規約へ追加します。初期有効の Hook は `/hooks` で内容を確認して信頼し、新しいスレッドで動作を確認します。compact-plus に必要な CLI は[前提条件](#前提条件)を参照してください。別の制御を導入する場合は、導入先の要件に応じた判定処理を追加します。例のコマンドは `uv sync` 済みの環境で同期・通信せずに動くため、実行環境を分けた場合はコマンドも合わせます。
5. Codex でそのプロジェクトを信頼済みにし、各 `agent.toml` のモデルがメンバーのアカウントで使えるか確認します。信頼されていないプロジェクトでは `.codex/config.toml` の役割登録が読み込まれません。Claude Code では、`.claude/agents/` の各役割のモデルと推論強度（`model`、`effort`）が使えるか確認します。モデルが使えない場合は利用可能なものへ変更します。
6. [ハーネス設定](.harness/config/harness.toml) の必須 `structure.markdown_dirs` に再帰リンク検査する文書ディレクトリを指定します。導入先の主コンテンツ `docs/` も検査する場合は明示して加えます。検索範囲・その他の構造要件・`[[checks.commands]]` を導入先に合わせます。初期の `unit-tests` は [ハーネス自身のテスト](.harness/tests/) です。導入先の機能や追加した制御の検査は別途設定します。[設計文書](.repository-docs/architecture.md) と [運用規約](.repository-docs/conventions.md) も実際の構成に合わせて更新します。

### 導入完了の確認

- 導入先のルートで `validate` と `check` を実行し、構造・参照と設定した検査が成功することを確認します。
- 調査・実装・レビュー・検証の役割が実際に利用できることを確認します。`validate` はモデルの利用可否やサブエージェントの起動までは確認しません。
- 実際に使う実行環境で、4 役割をそれぞれ起動し、各 Skill の起動手順（`references/launch-<環境>.md`）のとおりに動くことを確認します。Claude Code では、読み取り専用の役割が編集できないこと、`.env` が読めないことも確認します。
- 有効化した制御ごとに、許可したい操作と抑制したい操作の両方で期待した結果を確認します。Rules は、例えば `codex execpolicy check --rules .codex/rules/default.rules -- git push origin main` で判定を確認できます。

`check` の成功だけでは、追加したすべての制御が検証できたことにはなりません。通常はモックや fixture、ローカルの最小限の検査を使い、実サービスへの接続や外部書き込みは依頼で認められた範囲に従います。

## フォルダとファイルの案内

主要な配置と用途は次のとおりです。設定や手順の詳細は下のリンクから確認できます。

```text
.
├── AGENTS.md               # 共通の作業手順の入口（Codex が読む。Claude も import する）
├── CLAUDE.md               # Claude Code の入口（AGENTS.md を import）
├── .agents/skills/         # 共通の作業手順（正本）、環境別の起動手順、Codex の役割設定
├── .claude/                # Claude Code の設定（役割定義、Skill ラッパー、履歴・権限制御 Hook）
│   ├── settings.json       # 権限設定（初期は .env 系の読み取り禁止のみ）と履歴・compact-plus Hook の登録
│   ├── hooks/              # 履歴・compact-plus・権限制御 Hook の実装と ask / deny 規則
│   └── agents/             # 4 役割の定義
├── .codex/                 # Codex 本体の設定
│   ├── config.toml         # 役割登録と能力制御の設定例
│   ├── rules/              # コマンドの承認・禁止ルール例
│   ├── hooks.json          # 初期有効の履歴・compact-plus Hook
│   └── hooks/              # 両 Hook の実装と要約資材
├── .harness/               # このテンプレート独自の検査機構
│   ├── config/             # 検索範囲・検査コマンドなどの設定
│   ├── scripts/            # 検索・構造検査・コマンド実行
│   └── tests/              # ハーネス自身のテスト
├── .repository-state/     # 共有経験知と Git 管理外の実行時ステート
│   ├── memory/             # Git 共有の経験知・索引
│   ├── compact-plus/       # Git 管理外の圧縮前状態と退避物
│   ├── skills/             # スキルの Git 管理外実行時ステート
│   └── subagent-history/   # Git 管理外の履歴メタデータ
├── .repository-docs/      # 現在の構成・運用規約・参考資料
├── pyproject.toml          # Python 要件と開発環境の設定
├── .python-version         # 使用する Python バージョン
├── uv.lock                 # Python 依存関係のロックファイル
└── .gitignore              # ローカル生成物などの共有除外
```

### 共通の手順と Codex の役割

- [`AGENTS.md`](AGENTS.md): Codex が最初に読む案内図で、Claude Code も import します。作業に合う Skill と文書へ導き、役割の起動と親による結果統合を指示します。
- [`.agents/skills/`](.agents/skills/): `delegate-investigate`（調査）、`delegate-implement`（実装）、`delegate-review`（レビュー）、`delegate-verify`（検証）の手順です。各 `SKILL.md` が環境共通の進め方を定め、`references/launch-codex.md` と `references/launch-claude.md` が環境別の起動手順を定めます。Codex では同じ場所の `agent.toml` がモデル、推論強度、権限、担当者向け指示を定めます。対応する役割名は `delegate-` を除いた名前です。 [herdr-cli-manager](.agents/skills/herdr-cli-manager/SKILL.md) は Herdr 利用時の操作用 Skill です。
- [`.codex/config.toml`](.codex/config.toml): 上記 4 役割を Codex に登録するプロジェクト設定です。承認・サンドボックス・能力制御の設定例もコメントで示します。各役割の詳細は対応する `agent.toml` を参照します。
- [`.codex/hooks.json`](.codex/hooks.json): 初期有効の履歴・compact-plus Hook 設定。実装は [履歴 Hook](.codex/hooks/subagent_history.py) と [compact-plus Hook](.codex/hooks/compact_plus.py) です。後者の運用は [専用手順](.repository-docs/operations/compact-plus.md) を参照してください。
- [`.codex/rules/default.rules`](.codex/rules/default.rules): サンドボックス外のコマンドに適用する `prompt` と `forbidden` のコメント例です。必要なルールだけ有効にします。
- [Codex 設定サンプル](.repository-docs/examples/codex-config.sample.toml): 設定項目を調べるときの参考例です。このリポジトリの Codex 設定の正本は `.codex/config.toml`、ハーネス設定の正本は `.harness/config/harness.toml` です。

### Claude Code の手順と役割

- [`CLAUDE.md`](CLAUDE.md): Claude Code の入口。`AGENTS.md` を import し、Claude 固有の補足だけを置きます。
- [`.claude/agents/`](.claude/agents/): `investigate`、`implement`、`review`、`verify` の役割定義です。モデル、推論強度（`effort`）、ツール制限を定め、本文は共通の `SKILL.md` を読む指示だけにしています。
- [`.claude/skills/`](.claude/skills/): `delegate-investigate`、`delegate-implement`、`delegate-review`、`delegate-verify`、`repository-memory` の薄いラッパーです。Claude Code は `.agents/skills/` を Skill として探索しないため、同名の Skill として登録して description による自動選択と `/delegate-*` の呼出しを可能にします。本文は `.agents/skills/<名前>/SKILL.md` への相対リンクと Read 指示だけで、手順は書きません。Windows の Git は symlink を実体化できない場合があるため symlink は使いません。frontmatter の `name` と `description` は正本と完全一致させ、`harness.py` の検査がずれを検出します。正本の `description` を変更するときは、同時に `.claude/skills/<名前>/SKILL.md` の `description` も同じ文面に直します。
- [`.claude/settings.json`](.claude/settings.json): 権限設定と Hook の登録です。権限で初期有効なのは `.env` 系の読み取り禁止だけで、他の例は [Claude 設定サンプル](.repository-docs/examples/claude-settings.sample.md) にあります。`SubagentStop` と `UserPromptSubmit` に履歴 Hook、`PreCompact`・`PostCompact`・`SessionStart`（matcher `compact`）・`UserPromptSubmit` に compact-plus を登録し、`Bash`・`Artifact` 系などの matcher で `PreToolUse` に権限制御 Hook（[pretool_guard.py](.claude/hooks/pretool_guard.py)、規則は [guard_rules.json](.claude/hooks/guard_rules.json)）を登録し、各 command に `"shell": "bash"` を明示します（Windows では Git Bash が必要）。実装は [履歴 Hook](.claude/hooks/subagent_history.py) と [compact-plus Hook](.claude/hooks/compact_plus.py)、運用は [履歴の手順](.repository-docs/operations/subagent-history.md) と [compact-plus の手順](.repository-docs/operations/compact-plus.md) を参照してください。compact-plus の要約には親と同じ `claude` を `claude -p` で起動します。1M 文脈のモデルでは、使用率の分母を環境変数 `COMPACT_PLUS_CONTEXT_WINDOW` で上書きします。
- 現在の役割定義は、4 役割とも仮設定で `sonnet`（Sonnet 5.5）/ `medium` です。`investigate` と `review` は `Write`・`Edit` などを、全役割が追加委譲（`Agent`）を禁止しています。モデルと推論強度は、導入先のアカウントと用途に合わせて変更してください。
- 読み取り専用の制限は、`disallowedTools` による `Write`・`Edit`・`NotebookEdit` の禁止と、PreToolUse Hook（[pretool_guard.py](.claude/hooks/pretool_guard.py)）による補完です。Hook は `agent_type` が `investigate` または `review` の呼び出しだけに適用し、`Bash` を読み取り専用コマンドの許可リスト（`git status|diff|log|show`、`ls`、`cat`、`rg`、`inspect_repo.py` など）に限ります。リダイレクト、コマンドの連結・置換、`rm`・`git push`・`python -c`、テストの実行は拒否され、`Artifact` 系、`PowerShell`、`Monitor` なども拒否します。許可リスト方式ですがパターンによる判定でありセキュリティ境界ではなく、`sort` と `git grep` は許可したオプションの完全一致だけを通し、`git`・`rg`・`tail` の危険な長オプションは省略形（`--out` など）も拒否します。`uv run` は `inspect_repo.py`（`search <語>`、`show <パス> <行>`）と `harness.py validate [--env codex|claude]` の既知の形だけで、スクリプトはこのリポジトリの相対パスか絶対パスに限ります。`.env` 系（`.env.example` を除く）や `~/.ssh`・`~/.aws`・`/etc/shadow` などを名指しする引数、`tail -f` も拒否します（機密の判定は網羅ではありません）。`git log -p` や `git diff` は許可のままで、`diff.external`・textconv・gpg など設定依存の外部コマンドを呼びうるため、`--no-ext-diff --no-textconv` を付けない限り残る経路です。MCP の書込み系ツールなど Hook の対象外の経路は残ります。起動指示の「実行してはいけない作業」に明記し、制約を報告させます。厳密にしたい環境では、`tools` の許可リスト化や sandbox を併用してください。規則ファイル `guard_rules.json` の `rules` に `pattern`（コマンドの接頭辞）、`decision`（`prompt` は確認、`forbidden` は拒否）、`justification` を書くと全役割とメインセッションの `Bash` に適用されます。`python .claude/hooks/pretool_guard.py check-rules` で `match`・`not_match` の例を自己検査できます。Windows の Claude Code は Hook の拒否理由の日本語を文字化けさせて表示するため、理由は英数字で書いてください。親のモードが `acceptEdits` などのときは役割側の `permissionMode` が無視されるため、権限の絞り込みは `tools` と `disallowedTools` で行います。

### 設計、知識、引き継ぎ

- [`.repository-docs/index.md`](.repository-docs/index.md): 文書の入口。`.repository-docs/architecture.md` に現在の構成、`.repository-docs/conventions.md` に運用規約を置きます。`.repository-docs/examples/` はユーザーが必要に応じて参考資料を保存する場所です。
- [`.repository-state/memory/index.md`](.repository-state/memory/index.md): Git で共有する長期知識の索引。`.repository-state/memory/MEMORY.md` は短い確定事項、`lessons/` に再発防止の経験知をテーマ別に置きます。AGENTS.md と Skill の指示に従い、関連事項を読んだエージェントが確認できた内容を手動で更新します。自動更新される記憶や、Codex・Claude Code の個人用ローカルメモリとは別です。

### 検索、検査、開発環境

- [`.harness/config/harness.toml`](.harness/config/harness.toml): このリポジトリ用 CLI が読む検索範囲、構造要件、検査コマンドの設定。Codex 本体の設定ではありません。
- [`.harness/scripts/inspect_repo.py`](.harness/scripts/inspect_repo.py): 候補一覧から必要な行だけを読む検索 CLI。
- [`.harness/scripts/harness.py`](.harness/scripts/harness.py): 設定と文書参照を検証し、設定済みコマンドを実行する CLI。
- [`.harness/tests/`](.harness/tests/): ハーネス自身のテスト。`check` の初期設定から呼ばれます。
- [`pyproject.toml`](pyproject.toml)、[`.python-version`](.python-version)、[`uv.lock`](uv.lock): Python の要件、`uv` の設定、依存関係の固定。
- [`.gitignore`](.gitignore): ローカル生成物と秘密情報を Git 管理から外す設定。

## 運用中の見直しと更新先

想定外の動作やタスクの変化があれば、原因と必要な制御を確認し、次の場所へ反映します。既存の説明を統合・置換し、同じ指示を複数箇所へ重複させないようにします。

| 更新する内容 | 更新先 |
|---|---|
| 確認済みの問題と再発防止の知見 | [`.repository-state/memory/`](.repository-state/memory/index.md) |
| 確定した設計・運用規約 | [`.repository-docs/`](.repository-docs/index.md)。共通の入口や親の責務は [`AGENTS.md`](AGENTS.md) |
| 役割ごとの作業手順・担当者向け指示 | [各 Skill](.agents/skills/) の `SKILL.md`（共通）と `references/launch-<環境>.md`（環境別）、Codex の `agent.toml` |
| 実行権限・能力・コマンド・Hook の制御 | Codex は [`.codex/`](.codex/config.toml)（役割別の権限は各 `agent.toml`）、Claude Code は [`.claude/`](.claude/settings.json)（役割別の制限は `.claude/agents/`） |
| 検査コマンド・検索範囲・出力上限 | [`.harness/config/harness.toml`](.harness/config/harness.toml) |

作業の委任と結果統合は [AGENTS.md](AGENTS.md)、役割ごとの進め方は各 Skill に従います。Codex の現在の役割定義は `investigate` が `gpt-6-luna` / `xhigh` / `read-only`、`implement` が `gpt-6.1-sol` / `low` / `workspace-write`、`review` が `gpt-6.1-sol` / `high` / `read-only`、`verify` が `gpt-6-luna` / `xhigh` / `workspace-write` です。親セッションの実行時権限も適用され、役割だけでネットワーク接続が一律に有効になるわけではありません。

変更後は直接影響する範囲を確認します。検査が失敗したら完了条件に関係する原因を調べ、修正後は必要な確認だけを再実行します。`verify` が修正を要する失敗を見つけた場合は、親が要点を `implement` に渡します。共有知見には確認済みの事実を記録し、個人の好みや環境固有の情報は Codex や Claude Code のローカルメモリに置きます。複数の親セッションで同時に作業するときの調整は [並行作業の手順](.repository-docs/operations/parallel-work.md) に従います。

## Git で共有する範囲

- 共有するもの: `AGENTS.md`、この README、`.agents/skills/`、`CLAUDE.md`、`.claude/settings.json`、`.claude/agents/`、`.claude/skills/`、`.claude/hooks/subagent_history.py`、`.claude/hooks/compact_plus.py`、`.codex/config.toml`、`.codex/hooks.json`、`.codex/hooks/subagent_history.py`、`.codex/hooks/compact_plus.py`、`.codex/rules/default.rules`、`.harness/config/`、`.harness/scripts/`、`.harness/tests/`、`.repository-docs/`、`.repository-state/memory/`、`.repository-state/skills/.gitignore`、`.repository-state/subagent-history/.gitignore`、`.repository-state/compact-plus/.gitignore`、`pyproject.toml`、`.python-version`、`uv.lock`、`.gitignore`。compact-plus の要約指示、JSON schema、MIT ライセンス表示はスクリプトに内包します。手順、設定、コード、確定済みの文書をチームで再利用します。
- 共有しないもの: `.harness/.harness-results/`、`uv.chash/`、`.venv/`、`__pycache__/`、`.env` と `.env.*`、秘密鍵や証明書のファイル、`.repository-state/skills/`・`.repository-state/subagent-history/`（`codex/` と `claude/`）・`.repository-state/compact-plus/` の実行時ファイル、上記で列挙した共有対象以外の `.codex/` と `.claude/` 内ファイル（`.claude/settings.local.json` を含む）。認証情報、個人設定、生ログ、生成キャッシュはローカルに置きます。環境変数の雛形 `.env.example` は共有できます。
- 共有対象の文書や設定にも、秘密、個人情報、生ログを混ぜないでください。コミット前に変更内容を確認してください。

サブエージェント履歴の参照は [運用手順](.repository-docs/operations/subagent-history.md)、経験知の保存方針は [運用手順](.repository-docs/operations/repository-knowledge.md) を参照してください。
