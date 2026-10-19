# 文書の入口

`.repository-docs/` はリポジトリ運用の文書・参考資料の置き場で、導入先の主コンテンツ用 `docs/` と区別します。

- [architecture.md](architecture.md): ハーネスの情報の流れと各ファイルの役割（Claude Code の権限制御 Hook の構成と限界を含む）
- [conventions.md](conventions.md): 設定・検索・検査・知識の運用規約
- `examples/` はユーザーが必要に応じて参考資料を保存する場所です。
- [examples/claude-settings.sample.md](examples/claude-settings.sample.md): Claude Code の権限設定の参考例です。初期有効の設定の正本は `../.claude/settings.json` です。
- [examples/codex-config.sample.toml](examples/codex-config.sample.toml): Codex の設定項目を調べるときの参考例です。このリポジトリの Codex 設定の正本は `../.codex/config.toml`、ハーネス設定の正本は `../.harness/config/harness.toml` です。

過去に確定した知見は [.repository-state/memory/index.md](../.repository-state/memory/index.md) から探します。
- [operations/repository-knowledge.md](operations/repository-knowledge.md): 経験知の保存方針
- [operations/subagent-history.md](operations/subagent-history.md): 履歴 Hook の参照方法（Codex と Claude Code）
- [operations/compact-plus.md](operations/compact-plus.md): compact-plus Hook の設計と運用（共通の概要、Codex 版、Claude 版）
- [operations/parallel-work.md](operations/parallel-work.md): 複数の親セッションが同時に作業するときの調整
