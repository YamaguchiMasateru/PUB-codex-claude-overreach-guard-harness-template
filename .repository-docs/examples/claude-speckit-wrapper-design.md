# Claude Code 用 Spec Kit ラッパーの設計

Spec Kit はハーネスとは別の任意ツールです。この文書は、Codex 連携で導入した Skill を Claude Code から参照する設計の記録です。ハーネスの対象は `.harness/config/harness.toml` が定めます。利用の流れは [Spec Kit ガイド](spec-kit-guide.md) を参照してください。

## 対象と構成

正本は `.agents/skills/speckit-*/SKILL.md`、ラッパーは `.claude/skills/speckit-*/SKILL.md` です。対象は `speckit-analyze`、`speckit-checklist`、`speckit-clarify`、`speckit-constitution`、`speckit-converge`、`speckit-implement`、`speckit-plan`、`speckit-specify`、`speckit-tasks`、`speckit-taskstoissues` の10本です。

Claude Code が共通正本を Skill として探索しないため、既存の delegate ラッパーと同じ配置を使います。背景は [既存の経験知](../../.repository-state/memory/lessons/claude-skills-directory.md) を参照してください。手順と Python ヘルパーは共通正本と `.specify/` に保ちます。

| 項目 | 設計 |
| --- | --- |
| `name`・`description` | 正本と引用符を含めて一致させる。正本更新時には同時に同期する |
| 本文 | 正本への相対リンクと Read 指示、入力の受渡し、呼出し形式の読み替えだけを置く |
| 入力 | `ユーザー入力: $ARGUMENTS` を置き、これを正本の `$ARGUMENTS` として扱うよう指示する |
| 呼出し形式 | `$speckit-xxx` と `/skill:speckit-xxx` を `/speckit-xxx` と読み替える。未導入拡張の `$speckit-github-*` は対象外 |
| `argument-hint` | 任意入力の案内を置く |
| `disable-model-invocation: true` | constitution・implement・specify・taskstoissues の4本だけに設定し、手動呼出し専用にする |

正本を Read するだけでは入力を正本に渡す意図が明確にならないため、本文で引数を明示します。これはエージェントへの指示による橋渡しです。実機で引数転送を検証済みとは扱いません。taskstoissues の非推奨 description も正本どおりに維持します。

## 更新時の注意と確認範囲

`.specify/integration.json` の導入済み連携は Codex、ヘルパーは Python 版です。公式の Claude 連携を後から導入するとラッパーが上書きされる可能性があります。導入・更新前後の差分を記録し、ラッパーを保全して正本との整合を取り直してください。正本は `.specify/integrations/codex.manifest.json` に記録されているため、更新時には生成元と変更内容も確認します。

`specify` は機能を作成し、`.specify/feature.json` の参照先も変更し得ます。動作確認目的で通常フローを無断実行しません。実機確認は対象機能と許可範囲を決め、analyze であっても正本の前提条件を確認します。

2026-10-22 時点で移植した10本のメタデータ・正本参照・本文長・手動指定は独立した静的検証で整合確認済みです。Claude Code 実機での `/speckit-*` 起動と `$ARGUMENTS` の転送は未確認です。他環境の検証結果を本環境の動作保証として扱いません。
