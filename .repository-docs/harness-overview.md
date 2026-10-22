# ハーネスの詳細案内

導入手順は [README](../README.md)、保護機構の共通仕様と限界は[構成文書](architecture.md#書込み抑制の範囲と限界)を参照してください。

## 成果物・計画・外部参照の配置

| 配置 | 用途 |
| --- | --- |
| `.agents/`・`.codex/`・`.claude/`・`.harness/` | 共有手順、環境別設定、検査機構 |
| `.repository-docs/` | 現行の設計・運用規約。導入先の主コンテンツと分離 |
| `docs/` など導入先が定める場所 | 導入先の主成果物。既存構成を維持 |
| `specs/<計画名>/` | plan・tasks 等の計画。現行規約の正本ではない |
| `external/registry.json` | 外部リソースの参照メタデータ。初期値は空 |
| `external/repos/` | 外部 clone・junction。正本は外部にあり、Git 共有・検索から除外 |
| `.repository-state/memory/` | 条件・根拠付きの共有経験知 |
| `.repository-state/` の実行時領域、`.harness/.harness-results/` | 履歴・退避物・検査ログ。Git 管理外 |

外部の資料・抽出物は導入先で承認された保存先に置きます。[外部リソースの手順](../external/README.md)と[計画一覧の更新手順](../specs/README.md)を参照してください。

## フォルダとファイルの案内

主要な配置と用途は次のとおりです。設定や手順の詳細は下のリンクから確認できます。

```text
.
├── AGENTS.md               # 共通の作業手順の入口（Codex が読む。Claude も import する）
├── CLAUDE.md               # Claude Code の入口（AGENTS.md を import）
├── .agents/skills/         # 共通の作業手順（正本）、環境別の起動手順、Codex の役割設定
├── .claude/                # Claude Code の設定（役割定義、Skill ラッパー、履歴・権限制御 Hook）
│   ├── settings.json       # 権限設定（初期は .env 系の読み取り禁止と保護先の編集拒否）と履歴・compact-plus Hook の登録
│   ├── hooks/              # 履歴・compact-plus・権限制御 Hook の実装と ask / deny 規則
│   └── agents/             # 4 役割の定義
├── .codex/                 # Codex 本体の設定
│   ├── config.toml         # 役割登録と能力制御の設定例
│   ├── rules/              # コマンドの承認・禁止ルール例
│   ├── hooks.json          # 初期有効の履歴・compact-plus・書込み抑制 Hook
│   └── hooks/              # 各 Hook の実装と要約資材
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

- [`AGENTS.md`](../AGENTS.md): Codex が最初に読む案内図で、Claude Code も import します。作業に合う Skill と文書へ導き、役割の起動と親による結果統合を指示します。
- [`.agents/skills/`](../.agents/skills/): `delegate-investigate`（調査）、`delegate-implement`（実装）、`delegate-review`（レビュー）、`delegate-verify`（検証）の手順です。各 `SKILL.md` が環境共通の進め方を定め、`references/launch-codex.md` と `references/launch-claude.md` が環境別の起動手順を定めます。Codex では同じ場所の `agent.toml` がモデル、推論強度、権限、担当者向け指示を定めます。対応する役割名は `delegate-` を除いた名前です。 [herdr-cli-manager](../.agents/skills/herdr-cli-manager/SKILL.md) は Herdr 利用時の操作用 Skill です。
- [`.codex/config.toml`](../.codex/config.toml): 上記 4 役割を Codex に登録するプロジェクト設定です。承認・サンドボックス・能力制御の設定例もコメントで示します。各役割の詳細は対応する `agent.toml` を参照します。
- [`.codex/hooks.json`](../.codex/hooks.json): 初期有効の履歴・compact-plus・書込み抑制 Hook 設定。実装は [履歴 Hook](../.codex/hooks/subagent_history.py)、[compact-plus Hook](../.codex/hooks/compact_plus.py)、[書込み抑制 Hook](../.codex/hooks/pretool_guard.py)（[規則](../.codex/hooks/guard_rules.json)）です。compact-plus の運用は [専用手順](../.repository-docs/operations/compact-plus.md) を参照してください。
- [`.codex/rules/default.rules`](../.codex/rules/default.rules): サンドボックス外のコマンドに適用する `prompt` と `forbidden` のコメント例です。必要なルールだけ有効にします。
- [Codex 設定サンプル](../.repository-docs/examples/codex-config.sample.toml): 設定項目を調べるときの参考例です。このリポジトリの Codex 設定の正本は `.codex/config.toml`、ハーネス設定の正本は `.harness/config/harness.toml` です。

### Claude Code の手順と役割

- [`CLAUDE.md`](../CLAUDE.md): Claude Code の入口。`AGENTS.md` を import し、Claude 固有の補足だけを置きます。
- [`.claude/agents/`](../.claude/agents/): `investigate`、`implement`、`review`、`verify` の役割定義です。モデル、推論強度（`effort`）、ツール制限を定め、本文は共通の `SKILL.md` を読む指示だけにしています。
- [`.claude/skills/`](../.claude/skills/): `delegate-investigate`、`delegate-implement`、`delegate-review`、`delegate-verify`、`repository-memory` の薄いラッパーです。Claude Code は `.agents/skills/` を Skill として探索しないため、同名の Skill として登録して description による自動選択と `/delegate-*` の呼出しを可能にします。本文は `.agents/skills/<名前>/SKILL.md` への相対リンクと Read 指示だけで、手順は書きません。Windows の Git は symlink を実体化できない場合があるため symlink は使いません。frontmatter の `name` と `description` は正本と完全一致させ、`harness.py` の検査がずれを検出します。正本の `description` を変更するときは、同時に `.claude/skills/<名前>/SKILL.md` の `description` も同じ文面に直します。
- [`.claude/settings.json`](../.claude/settings.json): 権限設定と Hook の登録です。権限で初期有効なのは `.env` 系の読み取り禁止と `external/repos` の編集拒否で、他の例は [Claude 設定サンプル](../.repository-docs/examples/claude-settings.sample.md) にあります。`SubagentStop` と `UserPromptSubmit` に履歴 Hook、`PreCompact`・`PostCompact`・`SessionStart`（matcher `compact`）・`UserPromptSubmit` に compact-plus を登録し、`Bash`・`Artifact` 系などの matcher で `PreToolUse` に権限制御 Hook（[pretool_guard.py](../.claude/hooks/pretool_guard.py)、規則は [guard_rules.json](../.claude/hooks/guard_rules.json)）を登録し、各 command に `"shell": "bash"` を明示します（Windows では Git Bash が必要）。実装は [履歴 Hook](../.claude/hooks/subagent_history.py) と [compact-plus Hook](../.claude/hooks/compact_plus.py)、運用は [履歴の手順](../.repository-docs/operations/subagent-history.md) と [compact-plus の手順](../.repository-docs/operations/compact-plus.md) を参照してください。compact-plus の要約には親と同じ `claude` を `claude -p` で起動します。1M 文脈のモデルでは、使用率の分母を環境変数 `COMPACT_PLUS_CONTEXT_WINDOW` で上書きします。
- 現在の役割定義は、4 役割とも仮設定で `sonnet`（Sonnet 5.5）/ `medium` です。`investigate` と `review` は `Write`・`Edit` などを、全役割が追加委譲（`Agent`）を禁止しています。モデルと推論強度は、導入先のアカウントと用途に合わせて変更してください。
- 読み取り専用の制限は、`disallowedTools` による `Write`・`Edit`・`NotebookEdit` の禁止と、PreToolUse Hook（[pretool_guard.py](../.claude/hooks/pretool_guard.py)）による補完です。読み取り専用の判定は `agent_type` が `investigate` または `review` の呼び出しに適用し、`Bash` を読み取り専用コマンドの許可リスト（`git status|diff|log|show`、`ls`、`cat`、`rg`、`inspect_repo.py` など）に限ります。リダイレクト、コマンドの連結・置換、`rm`・`git push`・`python -c`、テストの実行は拒否され、`Artifact` 系、`PowerShell`、`Monitor` なども拒否します。許可リスト方式ですがパターンによる判定でありセキュリティ境界ではなく、`sort` と `git grep` は許可したオプションの完全一致だけを通し、`git`・`rg`・`tail` の危険な長オプションは省略形（`--out` など）も拒否します。`uv run` は `inspect_repo.py`（`search <語>`、`show <パス> <行>`）と `harness.py validate [--env codex|claude]` の既知の形だけで、スクリプトはこのリポジトリの相対パスか絶対パスに限ります。`.env` 系（`.env.example` を除く）や `~/.ssh`・`~/.aws`・`/etc/shadow` などを名指しする引数、`tail -f` も拒否します（機密の判定は網羅ではありません）。`git log -p` や `git diff` は許可のままで、`diff.external`・textconv・gpg など設定依存の外部コマンドを呼びうるため、`--no-ext-diff --no-textconv` を付けない限り残る経路です。MCP の書込み系ツールなど Hook の対象外の経路は残ります。起動指示の「実行してはいけない作業」に明記し、制約を報告させます。厳密にしたい環境では、`tools` の許可リスト化や sandbox を併用してください。規則ファイル `guard_rules.json` の `rules` に `pattern`（コマンドの接頭辞）、`decision`（`prompt` は確認、`forbidden` は拒否）、`justification` を書くと全役割とメインセッションの `Bash` に適用されます。`python .claude/hooks/pretool_guard.py check-rules` で `match`・`not_match` の例を自己検査できます。Windows の Claude Code は Hook の拒否理由の日本語を文字化けさせて表示するため、理由は英数字で書いてください。親のモードが `acceptEdits` などのときは役割側の `permissionMode` が無視されるため、権限の絞り込みは `tools` と `disallowedTools` で行います。

### 設計、知識、引き継ぎ

- [`.repository-docs/index.md`](../.repository-docs/index.md): 文書の入口。`.repository-docs/architecture.md` に現在の構成、`.repository-docs/conventions.md` に運用規約を置きます。`.repository-docs/examples/` はユーザーが必要に応じて参考資料を保存する場所です。
- [`.repository-state/memory/index.md`](../.repository-state/memory/index.md): Git で共有する長期知識の索引。`.repository-state/memory/MEMORY.md` は短い確定事項、`lessons/` に再発防止の経験知をテーマ別に置きます。AGENTS.md と Skill の指示に従い、関連事項を読んだエージェントが確認できた内容を手動で更新します。自動更新される記憶や、Codex・Claude Code の個人用ローカルメモリとは別です。

### 検索、検査、開発環境

- [`.harness/config/harness.toml`](../.harness/config/harness.toml): このリポジトリ用 CLI が読む検索範囲、構造要件、検査コマンドの設定。Codex 本体の設定ではありません。
- [`.harness/scripts/inspect_repo.py`](../.harness/scripts/inspect_repo.py): 候補一覧から必要な行だけを読む検索 CLI。
- [`.harness/scripts/harness.py`](../.harness/scripts/harness.py): 設定と文書参照を検証し、設定済みコマンドを実行する CLI。
- [`.harness/tests/`](../.harness/tests/): ハーネス自身のテスト。`check` の初期設定から呼ばれます。
- [`pyproject.toml`](../pyproject.toml)、[`.python-version`](../.python-version)、[`uv.lock`](../uv.lock): Python の要件、`uv` の設定、依存関係の固定。
- [`.gitignore`](../.gitignore): ローカル生成物と秘密情報を Git 管理から外す設定。

## 運用中の見直しと更新先

想定外の動作やタスクの変化があれば、原因と必要な制御を確認し、次の場所へ反映します。既存の説明を統合・置換し、同じ指示を複数箇所へ重複させないようにします。

| 更新する内容 | 更新先 |
|---|---|
| 確認済みの問題と再発防止の知見 | [`.repository-state/memory/`](../.repository-state/memory/index.md) |
| 確定した設計・運用規約 | [`.repository-docs/`](../.repository-docs/index.md)。共通の入口や親の責務は [`AGENTS.md`](../AGENTS.md) |
| 役割ごとの作業手順・担当者向け指示 | [各 Skill](../.agents/skills/) の `SKILL.md`（共通）と `references/launch-<環境>.md`（環境別）、Codex の `agent.toml` |
| 実行権限・能力・コマンド・Hook の制御 | Codex は [`.codex/`](../.codex/config.toml)（役割別の権限は各 `agent.toml`）、Claude Code は [`.claude/`](../.claude/settings.json)（役割別の制限は `.claude/agents/`） |
| 検査コマンド・検索範囲・出力上限 | [`.harness/config/harness.toml`](../.harness/config/harness.toml) |

作業の委任と結果統合は [AGENTS.md](../AGENTS.md)、役割ごとの進め方は各 Skill に従います。Codex の現在の役割定義は `investigate` が `gpt-6-luna` / `xhigh` / `read-only`、`implement` が `gpt-6.1-sol` / `low` / `workspace-write`、`review` が `gpt-6.1-sol` / `high` / `read-only`、`verify` が `gpt-6-luna` / `xhigh` / `workspace-write` です。親セッションの実行時権限も適用され、役割だけでネットワーク接続が一律に有効になるわけではありません。

変更後は直接影響する範囲を確認します。検査が失敗したら完了条件に関係する原因を調べ、修正後は必要な確認だけを再実行します。`verify` が修正を要する失敗を見つけた場合は、親が要点を `implement` に渡します。共有知見には確認済みの事実を記録し、個人の好みや環境固有の情報は Codex や Claude Code のローカルメモリに置きます。複数の親セッションで同時に作業するときの調整は [並行作業の手順](../.repository-docs/operations/parallel-work.md) に従います。
