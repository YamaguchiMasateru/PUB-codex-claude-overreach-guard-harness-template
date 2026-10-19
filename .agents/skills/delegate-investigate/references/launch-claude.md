# Claude Code での起動手順

実行環境が Claude Code のときに、[SKILL.md](../SKILL.md) の「委譲元エージェントによる呼び出しと評価」で従う。

- Agent ツールで `subagent_type` に `investigate` を指定して起動する。定義は [.claude/agents/investigate.md](../../../../.claude/agents/investigate.md)。
- 通常のサブエージェントは新しい文脈で始まり、親の会話履歴は見えない。委譲元エージェントが渡す指示文だけが入力になるため、[呼び出し指示テンプレート](agent-instructions.md) の5項目を単独で読める形で渡す。会話全体を引き継ぐ fork での起動は使わない。
- 親の permission mode が `bypassPermissions`、`acceptEdits`、`auto` のときは、役割側の `permissionMode` は無視される。権限の絞り込みは `permissionMode` ではなく `tools` と `disallowedTools` で行う。
- この役割の編集禁止は frontmatter の `disallowedTools`（`Write`、`Edit`、`NotebookEdit`）で行い、追加の委譲は `Agent` の禁止で防ぐ。これは拒否リスト方式なので、それだけでは `Bash`、`Artifact`、MCP の書込み系ツールなどの書込み経路が残る。`.claude/hooks/pretool_guard.py`（PreToolUse Hook）が `agent_type` でこの役割を判定し、`Bash` を読み取り専用コマンドの許可リスト（`git status|diff|log|show`、`ls`、`cat`、`rg`、`inspect_repo.py` の `search`/`show` など）に限り、`Artifact` 系などを拒否する。リダイレクト、コマンドの連結・置換、`rm`、`git push`、`python -c`、テストの実行は拒否されるため、必要なら理由を添えて親に依頼する。MCP の書込み系ツールなど Hook の対象外の経路は残るので、起動指示の「実行してはいけない作業」に編集禁止を明記し、この制約を報告に含める。
