# compact-plus Hook の設計と運用

## 共通の概要

上流の [`compact-plus`](https://github.com/u-ichi/compact-plus) の考え方を、Codex と Claude Code のそれぞれで標準ライブラリだけの Python 実装へ移す。圧縮（`/compact` と自動圧縮）の前に transcript の原文をバックアップして状態を要約し、圧縮後に復旧情報を渡し、コンテキスト使用率が高いときに `/compact` を案内する。実装は環境ごとに独立しており（Codex は `.codex/hooks/compact_plus.py`、Claude Code は `.claude/hooks/compact_plus.py`）、コードもスレッド識別も実行時ステートも共有しない。次の点は両版で共通である。

- イベントは `PreCompact`、`PostCompact`、`SessionStart`（`source=compact`）、`UserPromptSubmit` の 4 つで、サブコマンド `pre-compact` / `post-compact` / `session-start` / `user-prompt-submit` が stdin の Hook JSON を読む。入口は `dispatch(event_name, payload, emit=None) -> dict`、要約実行の境界は `run_backend(prompt, model, temporary_dir) -> dict | None` とし、fake CLI でテストする。
- 要約は 10 項目（`active_plan` から `recovery_notes`）の JSON オブジェクトで、スクリプト内の `PROMPT` と JSON スキーマで指示し、Python 側でも文字列型と余分なキーの禁止を検証する。`checkpoint.json` が正本、`state.md` はその派生ビューである。
- 復旧コンテキストは重要項目を優先して UTF-8 最大 8192 bytes に収め、全文への参照とバックアップのパスを含める。配送は generation と `delivered` で重複を避け、`emit` の成功後にだけ状態を保存する。
- transcript は完全行だけを増分要約し、書きかけの末尾を含む原文を先にバックアップする（各スレッド 20 件、新しい保存の成功後だけ prune）。Hook はすべて fail open で、JSON 不正、識別子不一致、lock 取得不可、要約 CLI の失敗・timeout・スキーマ不正でも親を止めず、バックアップは保持する。`PreCompact` で圧縮を阻止することはない。
- 要約用の子 CLI は引数配列・`shell=False` で起動し、Hook・ツール・永続化を無効化し、再帰防止の環境変数を渡す。親 CLI の実行ファイルは Hook のプロセス祖先から特定し、その `--version` が成功したときだけ起動する。特定できなければ要約を省略して診断に残す。
- MIT License（Copyright 2026 Yuichi Uemura）の全文表示と要約指示・スキーマは、各スクリプトの冒頭コメントと本体に内包する。入れ子の `compact-plus` checkout は参照のみとし、編集・追加 Git 登録しない。
- 実 LLM の要約品質、実環境での配送、POSIX 上の動作は未確認である（確認は fake CLI と fixture が中心）。

## Codex 版

### 目的と境界

上流の [`compact-plus`](https://github.com/u-ichi/compact-plus) の圧縮前バックアップ、状態要約、圧縮後の復旧、使用率通知を、Codex 専用の Python 3.14 標準ライブラリ実装へ移す。実装は `.codex/hooks/compact_plus.py` のイベント別サブコマンドとし、[既存 Hook](../../.codex/hooks.json) の `SubagentStop` と `UserPromptSubmit` による [履歴案内](../operations/subagent-history.md) を維持する。`UserPromptSubmit` では独立したハンドラーを併用し、Codex が両方の出力を受け取る。既存 `subagent_history.py` を呼び直さない。起動は既存と同じ `uv run --project <root> --locked --no-sync --offline python -X utf8` を使い、POSIX と Windows の双方で Git root を解決する。

この節の Hook と実装は Codex 専用で、Claude Code 版は後述の「Claude 版」で別に実装する（コードは共有しない）。手動 `/compact-plus` スキル、旧データ移行も対象外。入れ子の `compact-plus` checkout は参照のみとし、編集・追加 Git 登録しない。compact-plus 由来の実装を利用し、MIT License（Copyright 2026 Yuichi Uemura）の全文表示は [`.codex/hooks/compact_plus.py`](../../.codex/hooks/compact_plus.py) の冒頭コメントに保持する。要約指示と JSON スキーマも同スクリプトに内包する。実 LLM 接続や実配送のサービス検証は今回行わず、ローカルの fake CLI で確認する。

### イベントと順序

| イベント | 入力と処理 | 出力・永続化 |
| --- | --- | --- |
| `PreCompact` | stdin の Hook JSON からセッション、実スレッド、transcript を特定。スレッド lock 下で transcript の原文全体を書きかけ末尾を含めて先にバックアップし、完全行だけを増分要約する。 | 180 秒以内にバックアップ確定、スキーマ検証、checkpoint の保存、復旧用 generation(UUID) 記録。LLM の上限は 80 秒。transcript 解析失敗時もバックアップを保持し、Hook 自体は fail open。 |
| `PostCompact` | 同一スレッドの復旧情報を lock 下で確認。 | `post_seen` を立て、通知の warned を解除する。`delivered` は戻さない。 |
| `SessionStart` (`source=compact`) | 対象 generation の checkpoint を lock 下で読む。`PostCompact` がまだ来ていなくても今回準備された世代を対象とする。 | UTF-8 最大 8192 bytes の追加コンテキストを stdout へ出力して確定し、その後 `delivered` を原子的に保存。 |
| `UserPromptSubmit` | `post_seen` かつ未配送なら同じ復旧処理を行う。続いて最新 token count による reminder を判定する。 | 復旧の補完と必要時の `/compact` 通知。既存履歴案内も保持する。 |

Hook の入力は信頼できる識別材料が揃う場合だけ利用する。JSON 不正、識別子不一致、transcript 不明、lock 取得不可では他スレッドの状態を混ぜず、注入を省略する。通常の重複配送は generation と `delivered` で避けるが、stdout への出力確定と配送状態の保存の間にプロセスが落ちた場合の厳密な exactly once は保証しない。ハンドラーの `additionalContextLimit` は 0 とし、独自の byte cap で巨大出力の一時ファイル化を避ける。Hook 並列実行と transcript 形式の不安定性を前提にする。

実装の入口は `dispatch(event_name: str, payload: dict, emit=None) -> dict`、要約実行の境界は `run_backend(prompt: str, model: str | None, temporary_dir: Path) -> dict | None` とする。CLI は stdin の JSON を読んでイベント別サブコマンドから `dispatch` へ渡す。`dispatch` は出力案だけを返し、CLI が渡す `emit` callback による stdout への出力確定の成功後にのみ `delivered` / `warned` を保存する。この境界を fake CLI によるテストで差し替え可能にする。

### スレッド識別と保存形式

Git 共有は `.repository-state/compact-plus/.gitignore` のみ。実行時データは `codex/threads/<thread-key>/` に置き、`.gitignore` と検索除外で共有しない。`thread-key` は `(session_id, 実 thread identity)` の安全な hash とする。実 identity は `agent_id`、transcript の `session_meta.id`、正規化した transcript 絶対パスの hash の順で採用する。入力と metadata が食い違う場合、またはどれも特定できない場合は省略する。親の `session_id` だけで子の状態を共有しない。

```text
.repository-state/compact-plus/
  .gitignore
  codex/threads/<thread-key>/
    .lock
    checkpoint.json
    state.md
    recovery.json
    last-error.json
    warned
    backups/<日時>-<ID>.jsonl
    tmp/<UUID>/schema.json
```

`checkpoint.json` が要約の唯一の正本であり、`schema_version`、10 項目の `summary`、`generation`、保存日時、使用 model、transcript 識別子（`transcript_identity`）、要約済み byte offset（`offset`）、更新回数を単一 JSON として原子的に保存する。`state.md` はそこから再描画する派生ビューで、描画失敗時も checkpoint を残し、次回再生成する。`recovery.json` は対象 generation、`post_seen`、`delivered`、最新バックアップのパスを持つ。各置換は置換先と同じディレクトリに一時ファイルを作り、write → flush → fsync → close → `os.replace` の順で行う。Windows は `msvcrt`、POSIX は `fcntl` によるスレッド単位の非ブロッキング OS lock を使い、バックアップから要約の保存まで保持する。復旧の読み取り・stdout 出力・配送状態更新も lock 下で行い、`.lock` ファイル自体は削除しない。

`last-error.json` は識別済みスレッドの直近の失敗診断で、段階・UTC 時刻・例外種・短い理由を記録する。CLI の非ゼロ終了時は終了コードと末尾最大 8192 bytes の stderr も保存する。transcript、prompt、summary の全文は複写しない。診断保存の失敗は Hook を止めず、要約成功時に直前の診断を削除する。通常の省略や lock 競合では作成しない。

バックアップは JSONL の原文 全体を binary で保存し、書きかけ末尾も保全する。要約は完全行だけを対象とし、`offset` は最後の対象行の改行終端 byte 位置だけを進める。末尾の不完全行は次回の要約へ保留する。短縮・置換を検出したら全体を読み直す。未知形式や解析失敗でも先にバックアップを確定し、checkpoint は更新しない。各スレッドで 20 件を保持し、新しいバックアップの保存成功後だけ古いものを prune する。元実装の incremental/head-tail/tail、先頭 5・末尾 25 turn、10 回ごとの全更新、長い tool output の squash を移す。定期的な head-tail 全更新でも同じ transcript の場合は前回 `summary` を要約入力へ渡し、中間の決定事項を引き継ぐ。

### 要約 CLI とコンテキスト

追加の `codex exec` は引数配列・`shell=False` で起動し、read-only/ephemeral とする。run 単位の設定で hooks、shell tool、multi agent、apps、plugins を無効化し、web search も無効化する。再帰 Hook 防止の環境変数を設定し、親プロセスの環境変数をコピーする。CLI のユーザー設定を無視する `--ignore-user-config` は使わない。`project_doc_max_bytes=0` で作業用 AGENTS 読込を止め、`--output-last-message` を使用する。危険な bypass flag は使わない。モデルは `COMPACT_PLUS_MODEL`、Hook の `model`、CLI 既定の順に決める。

要約 CLI の起動直前には毎回、Hook のプロセス祖先にある Codex の実行ファイルを特定する。Windows ではプロセス一覧から祖先をたどり、Linux では `/proc`、macOS では親 PID と `libproc` から実体パスを取得する。その同じ実行ファイルの `--version` が成功した場合だけ `exec` を起動する。親実行ファイルを特定できない場合や版確認が失敗した場合は要約を省略し、既存の backend 診断に理由を記録する。先に確定した transcript バックアップは保持し、Hook は継続する。PATH 上の別の CLI への切替は行わない。

`--output-schema` は CLI がファイルパスを要求するため、スクリプト内の JSON スキーマをスレッドの `tmp/<UUID>/schema.json` に実行時だけ書き出し、終了後に削除する。以下の 10 項目をすべて必須とし、Python 側で文字列型と余分なキーの禁止を検証する。受理後に `# Compact Prep State` と元の 10 見出しへ描画する。スキーマは出力形式を保証するが、記述の事実性は保証しない。復旧コンテキストは重要項目を優先して UTF-8 最大 8192 bytes に収め、全文への参照とバックアップのパスを必ず含める。古い状態しかない場合は古い情報と明記し、最新バックアップを示す。

#### 要約指示と出力項目

スクリプト内の `PROMPT` は圧縮後に作業を再開する担当者への事実の引き継ぎを指示する。前回の要約と新しい履歴を照合し、新しい事実を加え、変わった事実を更新する。新しい履歴に触れられていない前回の事実は保持する。ユーザーの追加指示は、残す情報を選ぶ際の関連性の判断に使う。スキルやコマンドの呼び出し一覧は機械的に抽出した記録であり、現在も有効な指示の証拠として扱わない。出力は次の 10 キーを持つ JSON オブジェクト一つとし、各値を空でない文字列にする。値は簡潔な英語で書き、命令文にしない。観測できない詳細を補わず、不明な項目は `Not verified` と記す。元の計画、規則、メモリー、スキルのファイルが正本であり、要約は過去の作業を記録するだけで新しい命令を作らない。

| JSON キー | 日本語の項目名 | 保持する内容 |
| --- | --- | --- |
| `active_plan` | 実行中の計画 | 計画ファイルのパス、題名、現在の節、段階の状態。不明なら `Not verified`。 |
| `current_phase` | 現在の段階 | 最近完了した作業と、残っている作業の事実。 |
| `tasklist_summary` | タスク一覧 | 確認できるタスクの ID、件名、状態。 |
| `session_decisions` | セッション中の決定 | 確定した判断、退けた案、その理由、ユーザーが許可した範囲。 |
| `constraints_and_blockers` | 制約と阻害要因 | 必須の制約、省略した検査、権限の限界、外部の障害、未確認事項。 |
| `worker_topology` | 担当者の構成 | 作業者、役割、担当範囲。利用していなければ `Not used`。 |
| `skills_invoked` | 使用されたスキル | 入力の呼び出し一覧に記録されたスキルとスラッシュコマンドのみ。他の項目が CLI のパスに依存する場合はそのパスも記す。 |
| `editing_files` | 編集中のファイル | 変更済みまたは作業中のファイル。確認できる場合はステージ済み、コミット済み、未コミットの変更、生成物、一時ファイルなどの状態。 |
| `failed_attempts` | 失敗した試行 | 失敗したコマンド、ツールエラー、退けた方法、同じ失敗を避けるために必要な原因。 |
| `recovery_notes` | 再開時の補足 | セッション ID、ブランチ、重要なコマンド、検証結果、履歴と状態のパス、再開に必要な正確な事実。 |

パス、URL、コマンド名、コミット ID、課題 ID、エラーが確認できる場合はその表記を保持する。要約の内容を現在の指示より優先しない。

reminder は同一 transcript の末尾最大 512 KiB・500 行だけから最新 `token_count` を探し、`last_token_usage.total_tokens / model_context_window` を参考使用率として計算する。閾値は `COMPACT_PLUS_CODEX_WARN_THRESHOLD` 環境変数、既定 75% で、以上なら `/compact` を通知する。累計 token 使用量や固定 12000 token の補正は使わない。欠損・不正・別スレッドの計数では通知しない。通知文は active plan、current phase、直近 decision 3 行を含み、作業範囲を縮める指示は出さない。`warned` により重複を抑え、`PostCompact` で解除する。

### 導入と日常運用

導入時は Python 3.14、`uv sync` 済みの環境、Codex CLI を用意し、プロジェクトを信頼したうえで新しいスレッドを開始する。Codex の `/hooks` で各コマンドを確認し、必要な trust 操作を行う。Hook 設定の変更は進行中のスレッドへ反映されない場合がある。状態を読む際は対象スレッドの識別子を確認する。Hook と要約 CLI が失敗しても通常の Codex 作業は止めない設計とする。

確認は fake CLI と fixture によるローカル試験が中心で、実 LLM の要約品質、実環境での配送、POSIX 上の動作は未確認である。

### 統合と確認

共有対象は要約指示とスキーマを内包したコード、ライセンス、文書、テストである。`.codex` の既定の除外設定には必要ファイルの例外を加え、実行時の状態は Git と検索の両方から除外する。[構造検査設定](../../.harness/config/harness.toml) の `required_files` に共有ファイルを加え、[README](../../README.md)、[文書索引](../index.md)、[構成](../architecture.md)、[規約](../conventions.md) の既存記述と統合する。

fake CLI と fixture によって全 Hook の正常系・旧 state・CLI 失敗と timeout・スキーマ不正・バックアップ 20 件・途中停止・原子的な保存・並列実行・lock 解放・イベント逆順・UTF-8/CRLF/不完全行・transcript 短縮・identity 不一致・Windows command・空白を含む path・subdir・Git ignore を検証する。担当実装者は失敗を検出する最小チェックを実行し、親は独立した verify に構造 `validate` / `check` と必要な追加確認を依頼する。成功済みの確認は重複実行しない。

Hook の並列動作、入力と出力の上限、transcript の不安定性は [Codex hooks](https://learn.chatgpt.com/docs/hooks)、CLI のスキーマと一時実行 は [developer commands](https://learn.chatgpt.com/docs/developer-commands) を根拠とする。atomic replace は [Python 3.14 `os.replace`](https://docs.python.org/3.14/library/os.html#os.replace)、byte offset を text stream の `tell` に依存させない判断は [Python 3.14 `TextIOBase.tell`](https://docs.python.org/3.14/library/io.html#io.TextIOBase.tell) を参照する。ネットワーク FS や電源断に対する完全な耐久性は対象外とする。

## Claude 版

実装は `.claude/hooks/compact_plus.py`、登録は [`.claude/settings.json`](../../.claude/settings.json) の `hooks` である。Codex 版の仕様（上節）を Claude Code の入出力と transcript 形式に合わせた別実装で、標準ライブラリのみを使い、MIT License 表示を冒頭コメントに保持する。既存の [履歴 Hook](subagent-history.md)（`SubagentStop` と `UserPromptSubmit`）と権限設定は保持する。`.codex/` は変更しない。

### 登録とイベント

各 command は `"shell": "bash"` を明示し、履歴 Hook と同形の `root="$(git rev-parse --show-toplevel)" && uv run --project "$root" --locked --no-sync --offline python -X utf8 "$root/.claude/hooks/compact_plus.py" <サブコマンド>` を使う。Windows では Git for Windows の bash を前提とし、ない環境は対象外とする。

| イベント | 登録 | 処理 |
| --- | --- | --- |
| `PreCompact` | timeout 180、statusMessage「圧縮前の履歴と状態を保存」 | Codex 版と同じ。入力の `trigger` と `custom_instructions` を要約入力に含める。exit 2 や `decision:block` は使わず、圧縮は常に続行する。 |
| `PostCompact` | timeout 5 | `post_seen` を立て `warned` を解除する。入力の `compact_summary` は使わず保存もしない（必須にしない）。 |
| `SessionStart` | matcher `compact`、timeout 5 | stdout の JSON `hookSpecificOutput`（`hookEventName: "SessionStart"`, `additionalContext`）で復旧コンテキストを注入する。Claude の注入上限は 10,000 文字で、超過分はファイル化されるため 8192 bytes の cap を守る。 |
| `UserPromptSubmit` | timeout 5。履歴 Hook の**前**に登録 | `post_seen` かつ未配送なら復旧を補完し、そうでなければ使用率通知を判定する。履歴案内は別 Hook が従来どおり出力する。 |

### スレッド識別と保存先

状態は `.repository-state/compact-plus/claude/threads/<thread-key>/` に置き、Codex の `codex/threads/` とは分ける（構成ファイルは Codex 版と同じ。ただし要約用の一時ディレクトリは OS の一時領域に作り、スレッド配下に `tmp/` は作らない）。`thread-key` は `(session_id, 実 identity)` の hash で、実 identity は `agent_id`（サブエージェントのとき）、なければ正規化した `transcript_path` の hash とする。Codex の `session_meta.id` は使わない。`agent_id` が `agent-<id>.jsonl` 形式の transcript 名と食い違う場合は省略する。共有しない設定は `.repository-state/compact-plus/.gitignore` と検索除外（[構造検査設定](../../.harness/config/harness.toml) の `exclude_paths`）で既存のまま有効で、`.gitignore` に `.claude/hooks/compact_plus.py` の例外を加えた。

### transcript の扱い

Claude の transcript（JSONL）は公式に行スキーマがない。実観察では `type` が user / assistant / attachment / system のほか内部用の多数の種別を持ち、`message` に `role` と `content`（文字列、または text / thinking / tool_use / tool_result の配列）がある。実装は未知の行種別と欠落を許容し、要約入力では内部用の行（`api-request*`、`file-history-*` など）を除外し、thinking を省き、500 文字を超える `tool_result` を文字数だけの表示へ短縮する。turn の数え方は `user` / `assistant` の行で、増分 offset・head-tail・全更新の更新方式は Codex 版と同じである。`skills_invoked` は、user 行の行頭スラッシュコマンドと `<command-name>`、assistant の `Skill` ツール呼び出し（`Skill:<名前>`）から機械抽出する。

### 要約 CLI

`claude -p` を引数配列・`shell=False` で起動し、プロンプトは stdin で渡す。実 CLI（2.1.302）で確認した構成は `--output-format json --json-schema <スキーマ> --no-session-persistence --tools "" --disable-slash-commands --setting-sources "" --settings '{"disableAllHooks":true}' --strict-mcp-config`（任意で `--model`）である。結果の JSON は `structured_output` にオブジェクトで入り、なければ `result` の JSON 文字列を解釈する。`--json-schema` は `$schema`（draft 2020-12）の参照を拒否するため、スキーマに含めない。`--bare` は Hook を読まない代わりに OAuth を使えず API キー前提になるため使わない。危険な権限 bypass フラグも使わない。子は作業ディレクトリ外の一時ディレクトリで実行し、環境変数 `COMPACT_PLUS_ACTIVE=1` を渡す。Hook はこの変数があれば何もせず終了する。LLM の上限は 80 秒（`COMPACT_PLUS_BACKEND_TIMEOUT`）。モデルは `COMPACT_PLUS_MODEL`、なければ CLI 既定とする（Hook の入力に model はない）。

親の `claude` 実行ファイルは Hook のプロセス祖先から特定する（Windows はプロセス一覧の `claude.exe`、Linux は `/proc`、macOS は親 PID と `libproc`）。その `--version` が成功したときだけ起動し、特定・版確認に失敗したら要約を省略して `last-error.json` に記録する。バックアップは保持し、PATH 上の別の `claude` へは切り替えない（VS Code 拡張同梱版と PATH 上の版が異なることがあるため）。

### 使用率通知

transcript 末尾最大 512 KiB・500 行から、最新の親スレッド（`isSidechain` でない）の assistant 行の `message.usage` を探し、`input_tokens + cache_creation_input_tokens + cache_read_input_tokens` を入力側の合計とする。欠損・不正な値は通知しない。圧縮の境界（`system` の `compact_boundary` や `isCompactSummary` の行）より前の使用量は破棄する。分母のコンテキストウィンドウは transcript やモデル名から決められないため、環境変数 `COMPACT_PLUS_CONTEXT_WINDOW`（既定 200000 トークン）で与える。**1M 文脈のモデルを使う場合は、この値を環境変数で 1000000 などへ上書きする**（既定のままだと早すぎる通知になる）。閾値は `COMPACT_PLUS_CLAUDE_WARN_THRESHOLD`（既定 75%）で、以上なら `/compact` を通知する。通知文、`warned` による重複抑止、`PostCompact` での解除は Codex 版と同じである。

### 未確認事項

- 手動 `/compact` を通した動作（`PreCompact` の要約から `SessionStart`(`compact`) の復旧注入の実配送まで）は、Windows の使い捨てプロジェクトで実 Claude Code（2.1.301、`claude -p`）に対して確認した（2026-10-18）。VS Code 拡張の実セッションでの手動 `/compact` でも、`PostCompact` の実配送（`post_seen` と `delivered` が true、`last-error.json` なし）と復旧注入の到達を確認した（2026-10-19）。使用率通知（80%）も実発火を確認した。未確認は、`UserPromptSubmit` 経由の復旧、自動圧縮、PATH 上の別バージョンの `claude`、Hook の実行順である。Git Bash から `claude -p "/compact"` を渡すときは、MSYS のパス変換で `/compact` が化けるため `MSYS_NO_PATHCONV=1` が要る。
- 実 LLM の要約品質は未評価である。
- `COMPACT_PLUS_CONTEXT_WINDOW` の既定 200000 は推定であり、実際のモデルの窓幅とは一致しない場合がある。
- 実 Claude Code が起動する bash 配下の Hook では、親 `claude.exe` の祖先探索が空白入りパスでも成功した（2026-10-18）。MSYS の bash から入れ子で `bash -c` を起動する手動テストでは祖先が途切れて特定に失敗することがあり、その場合は要約が省略される（バックアップは残る）。通しテストはネイティブな親（Python など）から Git Bash を直接起動して行う。
- macOS と Linux の祖先探索は fixture のみで確認している。
