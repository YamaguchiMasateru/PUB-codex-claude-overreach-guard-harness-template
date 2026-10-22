# 構成

`AGENTS.md` は短い案内図で、Codex が読み、Claude Code は `CLAUDE.md` から import します。タスクに合う Skill が具体的な手順を示し、`.repository-docs/` は現在の構成・規約、`.repository-state/memory/` は後から再利用する確定事項を扱います。

```text
依頼 → AGENTS.md（Claude Code は CLAUDE.md 経由） → 該当 Skill → 必要な .repository-docs / .repository-state/memory
                              ↓
              対応する役割のサブエージェントを起動
                              ↓
                     検索・変更・検査
                              ↓
                      親が結果を統合
```

## 共通の構成

Skill 名は `delegate-<役割>`、役割名は `investigate`、`implement`、`review`、`verify` です。役割の責務・範囲・報告・完了条件は共通の `.agents/skills/delegate-<役割>/SKILL.md` が定めます。役割の起動手順は実行環境ごとに `references/launch-codex.md` と `references/launch-claude.md` に分け、SKILL.md は現在の環境に対応する手順だけを読むよう案内します。環境固有の記述（起動方法、`agent.toml` など）は共通ファイルに置きません。`harness.py` が共通ファイルへの混入を検査します。

実装・レビュー・検証の依頼では規模にかかわらず、親が起動ツールで対応する役割を指定し、担当範囲を渡して完了を待ちます。調査の依頼は、複数ファイル・複数コマンドにまたがる場合と外部アクセスを伴う場合に同様に起動し、軽微な調査は親が直接行ってよいものとします。複数役割はそれぞれ起動し、親が結果を統合します。同じファイルの同時編集は割り当てません。ユーザーが親の直接処理を明示した場合、または起動ツール・該当役割が使えない場合だけ親が処理し、後者では理由を報告します。別名のエージェントを該当役割の起動成功として扱いません。Skill を読むだけでは起動せず、定義ファイルの読み込みを確認できない場合は断定しません。

## Codex 固有

`.codex/config.toml` は役割登録です。役割定義は対応する `.agents/skills/delegate-<役割>/agent.toml` に置きます。Codex は信頼済みプロジェクトの設定だけを読み込み、サブエージェントには親セッションの実行時権限も適用されます。起動は `codex -C <repo>` で導入先ルートを session cwd に固定します。

## Claude Code 固有

`CLAUDE.md` が `AGENTS.md` を import します。役割定義は `.claude/agents/<役割>.md`（モデル、`effort`、`disallowedTools`。現在のモデルと `effort` は仮設定）に置き、本文は共通 SKILL.md を読む指示だけです。Claude Code は `.agents/skills/` を Skill として探索しないため、`.claude/skills/<名前>/SKILL.md` に薄いラッパーを置きます（対象は 4 役割の Skill と `repository-memory`）。ラッパーは正本と完全一致する `name` と `description`、正本への相対リンク、Read 指示だけを持ち、手順は書きません。symlink は Windows の Git が実体化できない場合があるため使いません。`harness.py` が `name`・`description` の一致、正本の存在、リンク、本文の短さを検査します。`.claude/settings.json` は権限設定で、初期有効は `.env` 系の読み取り禁止と `external/repos` の編集拒否です。サブエージェントは親の会話履歴を引き継がず、渡した指示文だけが入力になります。親の permission mode が `bypassPermissions`、`acceptEdits`、`auto` のときは役割側の `permissionMode` は無視されます。

## 共通の設定と検査

`.harness/config/harness.toml` が検索と検査の設定の正本です。`.harness/scripts/inspect_repo.py` はファイル候補と指定範囲を別々に表示します。`.harness/scripts/harness.py` は設定と資料の構造を検査し、設定されたコマンドを実行して短い結果を返します。構造検査は共通部分と環境別の部分に分かれ、`--env` で対象の環境を選べます（省略時は全環境）。生出力は `.harness/.harness-results/` に保存し、Git には含めません。

`.repository-state/memory/` は採用した共有経験知を扱います。`.repository-state/subagent-history/codex/records/`（Codex）と `.repository-state/subagent-history/claude/records/`（Claude Code）は Git 管理外の履歴メタデータであり、各環境の履歴 Hook が記録します。

Codex では、`.codex/hooks.json` は書込み抑制 Hook に加え、[履歴 Hook](operations/subagent-history.md) と [compact-plus Hook](operations/compact-plus.md) を登録します。後者は `PreCompact` の transcript バックアップと要約、`PostCompact` の状態更新、`SessionStart` と `UserPromptSubmit` の復旧を担当します。要約の正本は `.repository-state/compact-plus/codex/threads/<thread-key>/checkpoint.json`、生の退避物は同じスレッドの `backups/` に置き、いずれも Git 管理外です。[設計書](operations/compact-plus.md) にスレッド識別と障害時の扱いを記します。

Claude Code では、`.claude/settings.json` の `hooks` が `SubagentStop`（matcher `*`）と `UserPromptSubmit` に [履歴 Hook](operations/subagent-history.md)（`.claude/hooks/subagent_history.py`）、`PreCompact`・`PostCompact`・`SessionStart`（matcher `compact`）・`UserPromptSubmit` に [compact-plus Hook](operations/compact-plus.md)（`.claude/hooks/compact_plus.py`）を登録します。compact-plus は履歴 Hook の前に実行され、要約の正本は `.repository-state/compact-plus/claude/threads/<thread-key>/checkpoint.json`、生の退避物は同じスレッドの `backups/` に置き、いずれも Git 管理外です。要約には親と同じ `claude` を `claude -p` で起動します。各 command は `"shell": "bash"` を明示し、Windows でも Git for Windows の bash で実行します。Codex の `commandWindows` に当たる分岐は持ちません。コードは Codex 版と共有せず、記録先は Codex と分けた `claude/records/` です。Claude の入力に `turn_id` がないため記録しません。さらに `PreToolUse`（matcher は `Bash`・`ArtifactData`・`Artifact`・`ArtifactComments`・`NotebookEdit`・`Write`・`Edit` など書込み・実行経路になりうるツール）に権限制御の Hook（`.claude/hooks/pretool_guard.py`）を登録します。入力の `agent_type` が `harness.toml` の `read_only_roles`（`investigate`、`review`）のときだけ、`Bash` を読み取り専用コマンドの許可リストに限り、`Artifact` 系などを拒否します（判定に失敗した場合も拒否）。`.claude/hooks/guard_rules.json` の規則（`.codex/rules/default.rules` の `prefix_rule` に当たる `prompt` と `forbidden`）は全役割に適用し、規則ファイルの不備は fail open です。補完であってセキュリティ境界ではなく、MCP の書込み系ツールなど Hook の対象外の経路や、`git diff` 系が設定依存で呼ぶ外部ドライバは残ります。長オプションの省略形や `.env` 系・`uv run` の形は厳密に判定します。

## 外部参照と文書の分離

共通の手順・規約は `.agents/skills/` と `.repository-docs/`、実行環境固有の役割登録・権限・Hook は `.codex/` と `.claude/` に分けます。導入先成果物、計画、経験知、実行時データの配置とファイル一覧は [詳細案内](harness-overview.md) にまとめます。

`external/registry.json` は外部参照のメタデータの正本です。確認 CLI はローカルの存在・Git 状態・環境変数の設定有無を読み、通常実行では登録簿を更新しません。明示した `--record` だけが確認日・branch・commit を更新します。外部サービスへの通信はしません。clone・junction は `external/repos/` に置き、Git 共有とハーネス検索から除外します。登録簿の access は方針の記録です。OS の権限を変更しません。

## 書込み抑制の範囲と限界

両環境の guard_rules.json は `protected_paths: ["external/repos"]` を初期値とします。Codex の `.codex/hooks.json` は `Bash|apply_patch` に `.codex/hooks/pretool_guard.py` を登録し、シェル書込み・リダイレクト・コピー先・Git 更新・patch の追加／削除／移動先を字句的に判定します。Claude は既存の PreToolUse Hook に全役割の保護先判定を追加し、permissions.deny の `Edit(/external/repos/**)` と併用します。Claude の相対パス判定にはイベントの cwd を使い、root は既存の `CLAUDE_PROJECT_DIR` を使います。

Claude の順序は既存の読み取り専用役割判定、全役割の保護先判定、既存 Bash rules です。読み取り専用役割の判定例外は従来どおり拒否します。保護先の判定例外だけは stderr に警告して許可します。Codex guard の実行・判定例外も警告して許可します。規則ファイル不正時の既定保護先への fallback と、判定例外は別の扱いです。構造 validate は不正設定をエラーとして検出し、fail open を設定正常とは扱いません。Hook プロセスの起動前に失敗した場合は、判定器自身の警告が出るとは限りません。

Hook は誤操作防止の補助です。MCP など対象外のツール、間接的な書込み、シェル解釈の全構文を網羅するセキュリティ境界ではありません。読み取り専用役割の許可リストも併用する制限であり、保護先判定が全役割を読み取り専用にするものではありません。

Codex の Hook command と event.cwd は session cwd を基準とします。Bash の呼出しごとの独立した workdir は現行の Hook イベントから確認できないため、その配下への相対書込みを session cwd 基準で誤判定する場合があります。`codex -C <repo>` での起動はこの不足を解消しません。導入先では OS・sandbox 等の制限も必要に応じて組み合わせます。

今回の Codex 実ツール試験は CLI のポリシー／sandbox が Hook イベント取得前に操作を停止し、実イベント取得、実際の拒否、サブディレクトリ・別リポジトリ cwd 条件の実証が未完了です。静的・合成試験の成功を実ツール試験の完了として扱いません。Claude Code と Codex の成果・未確認は環境ごとに区別します。

対象プロジェクトに導入する際は、この文書にシステム境界と主要コンポーネントを追記します。
