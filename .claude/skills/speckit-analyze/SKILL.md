---
name: "speckit-analyze"
description: "Perform a non-destructive cross-artifact consistency and quality analysis across spec.md, plan.md, and tasks.md after task generation."
argument-hint: 任意の入力
---

手順の正本は [.agents/skills/speckit-analyze/SKILL.md](../../../.agents/skills/speckit-analyze/SKILL.md) です。最初にそれを Read し、その内容に従ってください。このファイルに手順は書きません。

ユーザー入力: $ARGUMENTS

これを正本の `$ARGUMENTS` として扱い、正本中の `$speckit-xxx` と `/skill:speckit-xxx` は `/speckit-xxx` と読み替えます（未導入の拡張コマンド `$speckit-github-*` は除く）。
