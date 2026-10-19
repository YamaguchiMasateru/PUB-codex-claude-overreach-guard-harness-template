# 運用規約

- 検索・検査の設定値は `.harness/config/harness.toml` に置く。役割の責務・範囲・報告は共通の Skill（`.agents/skills/delegate-<役割>/SKILL.md`）、起動手順は実行環境別の `references/launch-<環境>.md`、役割の登録と実行時設定は環境別の設定（Codex は `.codex/config.toml` と Skill の `agent.toml`、Claude Code は `.claude/agents/`）に置く。共通の文書・Skill 本文には、どちらか一方の環境にしか通じない記述を置かない。
- `.claude/skills/<名前>/SKILL.md` は `.agents/skills/<名前>/SKILL.md` の薄いラッパーである。正本の `name` または `description` を変更するときは、同じ変更でラッパーも同時に直す（ずれると `harness.py` の検査が失敗する）。ラッパーに手順は書かない。
- 実装・レビュー・検証の依頼では、規模にかかわらず対応する役割のサブエージェントを起動する。調査は `delegate-investigate` の基準に従い、複数ファイル・複数コマンドにまたがる調査と外部アクセスを伴う調査ではサブエージェントを起動し、軽微な調査は親が直接行ってよい。ユーザーが親の直接処理を明示した場合、または起動ツール・該当役割が使えない場合だけ親が処理し、後者は理由を報告する。親は委任範囲を明示して結果を統合し、同じファイルを複数の実装エージェントへ同時に割り当てない。
- 検索は候補の一覧から始め、必要なファイルの必要な行だけを表示する。出力上限に達したら語句を絞って再検索する。
- `validate` は構造と参照を、`check` は設定済みコマンドの結果まで確認する。失敗時は要約を見てから保存された生出力を開く。
- `[structure].markdown_dirs` は既存設定にも必ず追加し、配下の Markdown を再帰的にリンク検査するディレクトリを指定する。空配列なら追加走査しない。`required_files` の Markdown と `skills` が指定する Skill 文書は、この一覧とは別に検査する。導入先の主コンテンツ `docs/` は明示して加えた場合だけ再帰検査する。
- `.repository-docs/` は現時点で正しい構成と規約、`.repository-state/memory/` は確認済みで将来役立つ事実を扱う。推測、秘密、一時的な出力は記録しない。
- GitHub へ共有する `.repository-docs/`・`.repository-state/memory/`・設定には秘密、個人情報、生ログを含めない。共有対象の判断は [README.md](../README.md) に従う。

- 経験知は [運用手順](operations/repository-knowledge.md) に従い候補と根拠を評価して保存する。サブエージェント履歴の参照は [履歴手順](operations/subagent-history.md) に従う。
- 複数の親セッション（Codex と Claude Code など）が同時に作業するときは [並行作業の手順](operations/parallel-work.md) に従う。
- 圧縮前後の履歴保全と復旧は [compact-plus 運用手順](operations/compact-plus.md) に従う。保存される要約は履歴の補助資料であり、現在の plan・memory・rules・skills の指示を上書きしない。
