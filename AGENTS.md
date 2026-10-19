# このリポジトリの案内図

このリポジトリはチームで共有する、Codex と Claude Code 共通のハーネスです。作業に関係する入口から辿ってください。

- 全体像と操作方法: [README.md](README.md)、[.repository-docs/index.md](.repository-docs/index.md)
- 調査: `delegate-investigate` Skill（[手順](.agents/skills/delegate-investigate/SKILL.md)）
- 実装: `delegate-implement` Skill（[手順](.agents/skills/delegate-implement/SKILL.md)）
- レビュー: `delegate-review` Skill（[手順](.agents/skills/delegate-review/SKILL.md)）
- 検証: `delegate-verify` Skill（[手順](.agents/skills/delegate-verify/SKILL.md)）
- 確認済みの経験知: [.repository-state/memory/index.md](.repository-state/memory/index.md)

調査・実装・レビュー・検証は該当 Skill の手順に従い、親が担当範囲を渡して結果を統合します。役割の起動と評価の詳細は各 Skill を正本とします。ユーザーが親の直接処理を明示した場合、または指定役割が使えない場合は親が処理し、後者は理由を報告します。

運用指示・規約または動作設定の変更後は、親が独立した `verify` サブエージェントを起動し、報告を確認します。

文書・コードを変更するときは直接関係する既存内容を確認し、重複・矛盾・古い参照を統合します。共有経験知は [repository-memory](.agents/skills/repository-memory/SKILL.md) に従い候補化し、親がタスク完了前に候補の採否と採用分の保存確認まで完了します。必須規約と確定設計は `.repository-docs/` に置きます。
