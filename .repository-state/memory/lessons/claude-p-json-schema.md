# claude -p の --json-schema は $schema キーを受け付けない

- 適用条件: Hook や自動化から `claude -p --json-schema <JSON>` で構造化出力を得るとき。Codex の `--output-schema` 用スキーマを流用する場合に起きやすい。
- 観測結果（成功・失敗を区別）: 失敗: `"$schema": "https://json-schema.org/draft/2020-12/schema"` を含めると exit 1、stderr は `--json-schema is not a valid JSON Schema: no schema with key or ref ...`。成功: `$schema` を除いた `{"type":"object","additionalProperties":false,"required":[...],"properties":{...}}` は通り、結果 JSON の `structured_output` にオブジェクトが入る（`result` は JSON 文字列）。
- 教訓と次の行動: Claude 用スキーマには `$schema` を入れない。Codex 用と共有しない。実 CLI で一度確認する。
- 根拠（確認できるパス・コマンド・資料）: [compact_plus.py](../../../.claude/hooks/compact_plus.py) の SCHEMA 注記。実 CLI での失敗と成功の各 1 回の呼び出し。設計は [compact-plus.md](../../../.repository-docs/operations/compact-plus.md) の Claude 版。
- 限界・未確認: 他のメタスキーマ指定の可否、`$defs` など他キーワードの扱いは未確認。
- 確認日: 2026-10-18
