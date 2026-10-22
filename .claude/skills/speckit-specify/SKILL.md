---
name: "speckit-specify"
description: "Create or update the feature specification from a natural language feature description."
argument-hint: 任意の入力
disable-model-invocation: true
---

手順の正本は [.agents/skills/speckit-specify/SKILL.md](../../../.agents/skills/speckit-specify/SKILL.md) です。最初にそれを Read し、その内容に従ってください。このファイルに手順は書きません。

ユーザー入力: $ARGUMENTS

これを正本の `$ARGUMENTS` として扱い、正本中の `$speckit-xxx` と `/skill:speckit-xxx` は `/speckit-xxx` と読み替えます（未導入の拡張コマンド `$speckit-github-*` は除く）。
