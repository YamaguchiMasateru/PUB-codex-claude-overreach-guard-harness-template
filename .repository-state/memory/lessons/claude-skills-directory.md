# Claude Code では .agents/skills を Skill として探索しない

- 適用条件: Codex 用の `.agents/skills/` を正本とし、Claude Code からも同じ Skill 本文を使うハーネス。
- 観測結果（成功・失敗を区別）: 公式ドキュメントの探索先は `.claude/skills/`、`~/.claude/skills/`、入れ子の `.claude/skills/`、`--add-dir` 先、plugin で、`.agents/skills/` は含まれない（探索先を追加する設定も見つからなかった）。経緯は次のとおり。(1) `.claude/skills/` の薄いラッパーを一度作ったが、description を正本と一致させる同期が必要で二重管理になるため削除した。(2) 削除後は `AGENTS.md` のリンクから直接 Read させたが、Skill として登録されないため `repository-memory` が自動で選ばれず、経験知を個人メモリへ誤保存する事象が起きた（失敗）。(3) `/delegate-*` の呼出しと、サブエージェント定義の `skills:` による事前読込（推測を含む）も使えなかった。(4) 薄いラッパーを `harness.py check` の一致検査つきで再導入した。
- 教訓と次の行動: `.claude/skills/<name>/SKILL.md` に薄いラッパーを置く。`name` と `description` は正本と完全一致、本文は正本への相対リンクと Read 指示だけにし、手順は書かない。ずれは `harness.py` の検査が検知するため、取り下げ理由だった同期の手間は検査で担保する。正本の description を変えるときはラッパーも同時に直す。symlink は Windows の Git が既定（`core.symlinks=false`）で実体化できないため採らない。Skill を直接 Read させるだけの運用では自動選択が効かず、手順の取りこぼしが起きうる。
- 根拠: [判断の経緯](../../../add-claude-harness-plan/codex-claude-mapping.md)（§3-1、D1）、[運用構成](../../../.repository-docs/architecture.md)、[運用規約](../../../.repository-docs/conventions.md)。公式: https://code.claude.com/docs/en/skills.md（Choose where skills load、Symlinked folders）、https://code.claude.com/docs/en/sub-agents.md（`skills` フィールド）。
- 限界・未確認: ドキュメントの引用は要約モデル経由で取得した。ラッパー導入後の Skill 一覧表示、自動選択、`/delegate-*` の呼出し、`skills:` による事前読込は実機で未確認（親が確認する）。Claude Code のバージョンで変わりうる。
- 確認日: 2026-10-18
