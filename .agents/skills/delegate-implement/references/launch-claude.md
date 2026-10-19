# Claude Code での起動手順

実行環境が Claude Code のときに、[SKILL.md](../SKILL.md) の「委譲元エージェントによる呼び出しと評価」で従う。

- Agent ツールで `subagent_type` に `implement` を指定して起動する。定義は [.claude/agents/implement.md](../../../../.claude/agents/implement.md)。
- 通常のサブエージェントは新しい文脈で始まり、親の会話履歴は見えない。委譲元エージェントが渡す指示文だけが入力になるため、[呼び出し指示テンプレート](agent-instructions.md) の5項目を単独で読める形で渡す。会話全体を引き継ぐ fork での起動は使わない。
- 親の permission mode が `bypassPermissions`、`acceptEdits`、`auto` のときは、役割側の `permissionMode` は無視される。権限の絞り込みは `permissionMode` ではなく `tools` と `disallowedTools` で行う。
- 追加の委譲は `disallowedTools`（`Agent`）で禁止している。それ以外のツールの制限は設けず、変更範囲は起動指示の「許可する作業」で限定する。
