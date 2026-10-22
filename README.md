# Codex Overreach Guard ハーネステンプレート

このリポジトリは、Codex や Claude Code がユーザーの指示や想定を超えて作業範囲を広げたり、意図されていない操作を実行したりすることを抑えるためのハーネステンプレートです。作業手順による抑制と実行権限による制御を組み合わせ、依頼された範囲で作業を進め、その結果を確認できる構成を提供します。

初期状態で提供する手順と、導入先で選んで有効化する制御例があります。配置だけですべての逸脱を防ぐものではありません。タスクで必要な操作と許可しない操作に合わせて、制御を変更・追加してください。Codex は [AGENTS.md](AGENTS.md)、Claude Code は [CLAUDE.md](CLAUDE.md)（`AGENTS.md` を import）を入口に、依頼に応じた Skill、設計文書、確定済みの知識を参照します。手順の正本は両者で共有し、実行環境ごとの起動手順・設定・Hook は環境別に持ちます。

## 初期状態と制御の限界

共通 Skill が担当範囲・役割への委任・親による結果統合を定めます。検索・検査 CLI は表示量の上限、構造・参照の検査、設定済みコマンドの実行を提供します。これらは該当 CLI を使ったときに適用されます。

Codex と Claude Code は履歴・compact-plus に加え、`external/repos` への書込み抑制 Hook を初期有効にしています。Claude Code は `.env` 系の読み取り拒否、保護先の編集拒否、読み取り専用役割の制限も持ちます。Codex の承認・sandbox・Apps・MCP・Rules のコメント例は任意で有効化します。

Hook はパターンに基づく誤操作防止の補助であり、セキュリティ境界ではありません。間接書込みや対象外ツールは網羅しません。Codex の実ツール試験は CLI のポリシー／sandbox が Hook イベント取得前に操作を止めたため、拒否と cwd 条件の実証が未完了です。Bash の呼出しごとの `workdir` が Hook イベントから確認できず、独立した workdir 内の相対操作を保護できない場合もあります。[構成文書](.repository-docs/architecture.md#書込み抑制の範囲と限界)に詳細を記します。

Codex は導入先を信頼済みにし、導入先ルートを session cwd に固定して起動します。

```text
codex -C <repo>
```

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
2. [詳細構成](.repository-docs/harness-overview.md)を参考に、`AGENTS.md`、`.agents/skills/`、利用する実行環境の共有対象ファイル（Codex は `.codex/`、Claude Code は `CLAUDE.md` と `.claude/`）、`.harness/` の設定・スクリプト・テスト、`.repository-docs/`、`.repository-state/memory/` を導入先へ配置します。既存の `AGENTS.md`、`.codex/`、`.claude/`、文書があれば内容を統合し、上書きしません。片方の環境だけを導入する場合でも、README や運用文書には他方の環境の設定へのリンクが残るため、`validate` のリンク検査が失敗します。不要な環境のリンクと `harness.toml` の `environments` から該当環境を取り除いてください。この README は導入先の案内へ必要な説明を取り込みます。共有するファイルと除外する生成物は末尾の「Git で共有する範囲」を参照してください。
3. ハーネス用の Python 3.14 以上の実行環境を用意します。既存の `pyproject.toml`、`.python-version`、`uv.lock`、`.gitignore` は導入先の依存関係・実行環境に合わせて統合します。ロックファイルは導入先の定義から更新し、製品の Python 要件を一律に変更しません。製品とハーネスで要件が異なる場合は実行環境を分け、以下の検査をハーネス用の Python で実行してください。
4. 初期状態の説明を使って既存の指示と有効設定で足りるか確認し、必要な設定例だけを調整・有効化します。Apps と MCP は実際の ID とツール名へ置き換えます。不足する制御は Rules や Hook、導入先の運用規約へ追加します。初期有効の Hook は `/hooks` で内容を確認して信頼し、新しいスレッドで動作を確認します。compact-plus に必要な CLI は[前提条件](#前提条件)を参照してください。別の制御を導入する場合は、導入先の要件に応じた判定処理を追加します。例のコマンドは `uv sync` 済みの環境で同期・通信せずに動くため、実行環境を分けた場合はコマンドも合わせます。
5. Codex でそのプロジェクトを信頼済みにし、各 `agent.toml` のモデルがメンバーのアカウントで使えるか確認します。信頼されていないプロジェクトでは `.codex/config.toml` の役割登録が読み込まれません。Claude Code では、`.claude/agents/` の各役割のモデルと推論強度（`model`、`effort`）が使えるか確認します。モデルが使えない場合は利用可能なものへ変更します。
6. [ハーネス設定](.harness/config/harness.toml) の必須 `structure.markdown_dirs` に再帰リンク検査する文書ディレクトリを指定します。導入先の主コンテンツ `docs/` も検査する場合は明示して加えます。検索範囲・その他の構造要件・`[[checks.commands]]` を導入先に合わせます。初期の `unit-tests` は [ハーネス自身のテスト](.harness/tests/) です。導入先の機能や追加した制御の検査は別途設定します。[設計文書](.repository-docs/architecture.md) と [運用規約](.repository-docs/conventions.md) も実際の構成に合わせて更新します。

### 導入完了の確認

- 導入先のルートで `validate` と `check` を実行し、構造・参照と設定した検査が成功することを確認します。
- 調査・実装・レビュー・検証の役割が実際に利用できることを確認します。`validate` はモデルの利用可否やサブエージェントの起動までは確認しません。
- 実際に使う実行環境で、4 役割をそれぞれ起動し、各 Skill の起動手順（`references/launch-<環境>.md`）のとおりに動くことを確認します。Claude Code では、読み取り専用の役割が編集できないこと、`.env` が読めないことも確認します。
- 有効化した制御ごとに、許可したい操作と抑制したい操作の両方で期待した結果を確認します。Rules は、例えば `codex execpolicy check --rules .codex/rules/default.rules -- git push origin main` で判定を確認できます。

`check` の成功だけでは、追加したすべての制御が検証できたことにはなりません。通常はモックや fixture、ローカルの最小限の検査を使い、実サービスへの接続や外部書き込みは依頼で認められた範囲に従います。

## 文書と配置の入口

- [詳細構成・更新先](.repository-docs/harness-overview.md)、[文書索引](.repository-docs/index.md)、[構成](.repository-docs/architecture.md)、[運用規約](.repository-docs/conventions.md)
- [外部リソース](external/README.md)、[導入・撤去](external/local-setup.md)
- [計画の状態表](specs/README.md)、[共有経験知](.repository-state/memory/index.md)

## Git で共有する範囲

- 共有するもの: `.codex/hooks/pretool_guard.py`、`.codex/hooks/guard_rules.json`、`.claude/hooks/pretool_guard.py`、`.claude/hooks/guard_rules.json`、`external/registry.json`、`external/README.md`、`external/check_external.py`、`external/local-setup.md`、`specs/` の計画文書、 `AGENTS.md`、この README、`.agents/skills/`、`CLAUDE.md`、`.claude/settings.json`、`.claude/agents/`、`.claude/skills/`、`.claude/hooks/subagent_history.py`、`.claude/hooks/compact_plus.py`、`.codex/config.toml`、`.codex/hooks.json`、`.codex/hooks/subagent_history.py`、`.codex/hooks/compact_plus.py`、`.codex/rules/default.rules`、`.harness/config/`、`.harness/scripts/`、`.harness/tests/`、`.repository-docs/`、`.repository-state/memory/`、`.repository-state/skills/.gitignore`、`.repository-state/subagent-history/.gitignore`、`.repository-state/compact-plus/.gitignore`、`pyproject.toml`、`.python-version`、`uv.lock`、`.gitignore`。compact-plus の要約指示、JSON schema、MIT ライセンス表示はスクリプトに内包します。手順、設定、コード、確定済みの文書をチームで再利用します。
- 共有しないもの: `external/repos/` の clone・junction と外部の業務資料・抽出物、 `.harness/.harness-results/`、`uv.chash/`、`.venv/`、`__pycache__/`、`.env` と `.env.*`、秘密鍵や証明書のファイル、`.repository-state/skills/`・`.repository-state/subagent-history/`（`codex/` と `claude/`）・`.repository-state/compact-plus/` の実行時ファイル、上記で列挙した共有対象以外の `.codex/` と `.claude/` 内ファイル（`.claude/settings.local.json` を含む）。認証情報、個人設定、生ログ、生成キャッシュはローカルに置きます。環境変数の雛形 `.env.example` は共有できます。
- 共有対象の文書や設定にも、秘密、個人情報、生ログを混ぜないでください。コミット前に変更内容を確認してください。

サブエージェント履歴の参照は [運用手順](.repository-docs/operations/subagent-history.md)、経験知の保存方針は [運用手順](.repository-docs/operations/repository-knowledge.md) を参照してください。
