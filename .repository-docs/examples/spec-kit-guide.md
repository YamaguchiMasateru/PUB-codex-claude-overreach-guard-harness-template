# Spec Kit をこのリポジトリで使う

ハーネスの範囲外にある任意ツール、Spec Kit を使う参考ガイドです。新しい必須ワークフローではありません。実行手順の正本は `.agents/skills/speckit-*/SKILL.md`、役割分担と規約は [AGENTS.md](../../AGENTS.md) と [運用規約](../conventions.md) です。

## 導入状態と変更の確認

CLI・エージェント・ヘルパーはリポジトリのルートで実行します。作業前後に次の PowerShell コマンドで状態を比べます。

```powershell
git status --short
git diff -- AGENTS.md .agents .claude .specify .codex .gitignore
git ls-files --others --exclude-standard
```

`git diff` は追跡済みの差分、`git ls-files` は未追跡ファイルの確認用です。開始前の変更を記録し、他の作業による差分を保持します。ignore 対象のローカル状態は別途確認してください。

この環境の `.specify/integration.json` は Spec Kit 1.2.0、Codex 連携、`script: py` を記録しています。正本は `.venv/Scripts/python.exe .specify/scripts/python/*.py` を呼びます。PowerShell はシェルとして使えますが、PowerShell ヘルパー版の手順へ置換しません。これは導入済み版のローカル情報であり、CLI の最新バージョンを示しません。

導入済み環境では再初期化せず、必要な Skill から進めます。新規導入や更新を別途行う場合は、利用する CLI の `specify --version`、`specify init --help`、`specify check` を確認し、対象と差分を確認してから実施します。既存の `.agents/skills/`、`.claude/skills/`、`.specify/` を上書きする可能性があります。

`.specify/` はテンプレート・ヘルパーなどの共有資材、`.agents/skills/speckit-*/` は実行手順の正本、`.claude/skills/speckit-*/` は Claude 用ラッパーです。生成物は既存の規約・設計・Skill と照合し、重複や矛盾を各正本で整理します。機能別の `specs/<計画名>/` は計画であり、現行規約の正本ではありません。[計画一覧の更新手順](../../specs/README.md)も参照してください。

## 仕様から実装へ進める

以下はエージェントのチャットに一件ずつ入力する形式です。シェルコマンドではありません。Codex は `$speckit-plan <入力>`、Claude Code は `/speckit-plan <入力>` のように呼びます。各段階で成果物と差分を確認してから次へ進みます。

| 段階 | Codex の Skill / 正本 | 用途 |
| --- | --- | --- |
| 原則 | [$speckit-constitution](../../.agents/skills/speckit-constitution/SKILL.md) | 既存規約を根拠に原則を整理する。既存の原則があれば確認・必要な更新から始める |
| 仕様 | [$speckit-specify](../../.agents/skills/speckit-specify/SKILL.md) | 機能の目的・範囲・受け入れ条件を記す |
| 計画 | [$speckit-plan](../../.agents/skills/speckit-plan/SKILL.md) | 既存構成に沿う設計と検証方法をまとめる |
| タスク | [$speckit-tasks](../../.agents/skills/speckit-tasks/SKILL.md) | 計画を実行可能な作業単位へ分ける |
| 実装 | [$speckit-implement](../../.agents/skills/speckit-implement/SKILL.md) | タスクに従って変更と検査を進める |
| 収束確認 | [$speckit-converge](../../.agents/skills/speckit-converge/SKILL.md) | 実装後に仕様・計画・タスクと照合し残作業を追加する。必要に応じ implement → converge を繰り返す |

仕様には「対象機能の利用者、困っていること、期待する振る舞い、変更範囲」などを入力します。constitution では既存の AGENTS.md・設計・規約・関連 Skill を読み、独自の新規規則を黙って追加しないよう依頼します。詳細な前提条件・出力は各 Skill を参照してください。

必要に応じて [$speckit-clarify](../../.agents/skills/speckit-clarify/SKILL.md) で計画前に曖昧さを解消します。[$speckit-analyze](../../.agents/skills/speckit-analyze/SKILL.md) は tasks 作成後・実装前の成果物間の一貫性分析、[$speckit-checklist](../../.agents/skills/speckit-checklist/SKILL.md) は要件の完全性・明確さなどを確認するチェックリスト作成に使います。

[$speckit-taskstoissues](../../.agents/skills/speckit-taskstoissues/SKILL.md) は導入済み正本で非推奨です。外部への issue 作成を通常の流れに含めず、実行時は正本とユーザーの許可範囲を確認します。

Claude 用の引数受渡し・手動呼出し指定・確認範囲は [ラッパー設計](claude-speckit-wrapper-design.md) を参照してください。Claude Code 実機での起動と引数転送は未確認です。
