# Claude Code 設定サンプル

`.claude/settings.json` に追加できる権限制御の例です。JSON にはコメントを書けないため、この文書に注記を置きます。初期状態で有効なのは、リポジトリの [.claude/settings.json](../../.claude/settings.json) にある `.env` 系の読み取り禁止と、読み取り専用役割を補完する PreToolUse Hook（後述）だけです。以下の例はすべて既定では無効で、必要な項目だけを選んで追加します。

書式は Claude Code の公式ドキュメント（settings、permissions）に従います。導入先の Claude Code のバージョンで項目名と動作を確認し、追加後は新しいセッションを開いて実際に拒否・確認されることを試してください。`deny` は `ask` と `allow` より優先されます。

## 初期有効の設定

```json
{
  "permissions": {
    "deny": ["Read(**/.env)", "Read(**/.env.*)"]
  }
}
```

- パスは gitignore 形式です。`.env.*` には `.env.example` も含まれるため、サンプルファイルも読めなくなります。読ませたい場合は、`deny` を `Read(**/.env)` と `Read(**/.env.local)` のように具体的な名前へ絞ります。
- `Read` の `deny` は、Read・Grep・Glob ツールと、Bash の `cat` など一部のファイル系コマンドに適用されます。ファイル名を指定しない `grep -r` や、Python などがプログラム内で開くファイルは防げません。確実に止める必要があるときは、公式ドキュメントのサンドボックス設定を併用します。

## 承認の既定動作

```json
{
  "permissions": {
    "defaultMode": "default"
  }
}
```

- `default` は読み取り以外で確認を求めます。`acceptEdits`、`plan` などの選択肢は公式ドキュメントの permission modes を確認してください。
- 親のモードが `bypassPermissions`、`acceptEdits`、`auto` のとき、サブエージェント定義の `permissionMode` は無視されます。役割ごとの権限の絞り込みは、サブエージェント定義の `tools` と `disallowedTools` で行います。

## Web・shell・MCP の制御

```json
{
  "permissions": {
    "deny": ["WebSearch", "WebFetch", "Bash(curl *)", "mcp__<server-id>__*"],
    "ask": ["Bash(git push *)"]
  }
}
```

- `WebSearch` と `WebFetch` を禁止すると、調査役割の外部調査もできなくなります。
- `Bash(...)` のパターンはセキュリティ境界ではありません。`/usr/bin/curl` や `sh -c` 経由の実行は防げません。強制が必要なときはサンドボックスか、PreToolUse Hook で補います。このリポジトリには、読み取り専用役割（`investigate`、`review`）の `Bash` を読み取りコマンドの許可リストに限り、`Artifact` 系などを拒否する Hook（`.claude/hooks/pretool_guard.py`）が初期有効で入っています。`agent_type` で役割を判定するため、メインセッションと `implement`・`verify` には影響しません。同じ Hook が規則ファイル `.claude/hooks/guard_rules.json` の `rules`（`.codex/rules/default.rules` の `prefix_rule` と同形の `pattern`、`decision` の `prompt`（確認）と `forbidden`（拒否）、`justification`、`match`、`not_match`）を全役割の `Bash` に適用するので、`permissions.ask` / `deny` の代わりにチームで共有する規則はここへ置けます（`python .claude/hooks/pretool_guard.py check-rules` で例を自己検査）。許可リスト方式でもパターンによる判定であり、`sort` と `git grep` は許可したオプションの完全一致だけを通し、`git`・`rg`・`tail` の危険な長オプションは省略形（`--out` など）も拒否します。`uv run` は `inspect_repo.py`（`search <語>`、`show <パス> <行>`）と `harness.py validate [--env codex|claude]` の既知の形だけで、スクリプトはこのリポジトリの相対パスか絶対パスに限ります。`.env` 系（`.env.example` を除く）や `~/.ssh`・`~/.aws`・`/etc/shadow` などを名指しする引数、`tail -f` も拒否します（機密の判定は網羅ではありません）。`git log -p` や `git diff` は許可のままで、`diff.external`・textconv・gpg など設定依存の外部コマンドを呼びうるため、`--no-ext-diff --no-textconv` を付けない限り残る経路です。インタプリタ経由の回避を完全には防げません。MCP の書込み系ツールや Hook の対象外のツール（`SendMessage`、`WebFetch` など）は防げないため、必要ならこの節の `deny` や `tools` の許可リストを併用します。Windows の Claude Code は Hook の拒否理由の日本語を文字化けさせて表示するため、理由は英数字で書いてください。
- MCP は `<server-id>` を実際のサーバー名に置き換えます。ツール単位で絞る書式は公式ドキュメントで確認してください。

## サブエージェントの起動制御

```json
{
  "permissions": {
    "deny": ["Agent(Explore)"]
  }
}
```

特定のサブエージェントの起動を禁止する例です。役割（`investigate`、`implement`、`review`、`verify`）は禁止しないでください。
