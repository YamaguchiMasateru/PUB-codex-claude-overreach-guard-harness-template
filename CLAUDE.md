@AGENTS.md

# Claude Code 固有の補足

- このセッションは Claude Code です。役割の起動は、各 Skill の `references/launch-claude.md` に従います。Codex 用の `launch-codex.md` は読みません。
- 役割の定義は [.claude/agents/](.claude/agents/) にあります。Skill は [.claude/skills/](.claude/skills/) の薄いラッパーで登録されています。ラッパーには手順がなく、正本の `.agents/skills/<名前>/SKILL.md` を Read ツールで読んで従います。
- Claude の auto memory（`~/.claude/projects/` 配下）は個人用です。共有経験知は [.repository-state/memory/](.repository-state/memory/index.md) で、`repository-memory` Skill の手順で扱います。
