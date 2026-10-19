# Claude Code での起動手順

実行環境が Claude Code のときに、[SKILL.md](../SKILL.md) の「委譲元エージェントによる呼び出しと評価」で従う。

- Agent ツールで `subagent_type` に `verify` を指定して起動する。定義は [.claude/agents/verify.md](../../../../.claude/agents/verify.md)。
- 通常のサブエージェントは新しい文脈で始まり、親の会話履歴は見えない。委譲元エージェントが渡す指示文だけが入力になるため、[呼び出し指示テンプレート](agent-instructions.md) の5項目を単独で読める形で渡す。会話全体を引き継ぐ fork での起動は使わない。
- 親の permission mode が `bypassPermissions`、`acceptEdits`、`auto` のときは、役割側の `permissionMode` は無視される。権限の絞り込みは `permissionMode` ではなく `tools` と `disallowedTools` で行う。
- 書込みを Git 管理外の検査ログに限る制限は、ツールの設定では保証できない（`disallowedTools` は `Agent` のみ）。起動指示の「実行してはいけない作業」に明記し、保証できない旨を報告に含める。厳密にしたい環境では、`tools` の許可リストや Hook による補完を検討する。
