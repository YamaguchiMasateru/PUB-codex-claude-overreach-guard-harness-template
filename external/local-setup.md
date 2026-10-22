# 外部作業コピーの導入

[登録簿](registry.json) は空で始まります。利用するリソースの識別子・種別・利用方針を先に登録し、Git リポジトリの配置先を `external/repos/<名前>` にします。登録形式と確認結果は [README](README.md) を参照してください。以下の `<repo-root>`、`<resource-name>`、`<credential-free-https-url>` は導入先で置き換えます。

既存の作業コピーを参照する Windows 環境では、手元のターミナルで junction を作れます。接続元は環境変数などローカル設定で指定し、共有ファイルへ絶対パスや環境変数の値を記録しません。

```powershell
$repoRoot = '<repo-root>'
$resourceName = '<resource-name>'
$sourceRoot = $env:EXTERNAL_REPOS_ROOT
if (-not $sourceRoot) { throw 'EXTERNAL_REPOS_ROOT をローカルに設定してください' }
New-Item -ItemType Directory -Force "$repoRoot\external\repos" | Out-Null
New-Item -ItemType Junction -Path "$repoRoot\external\repos\$resourceName" -Target "$sourceRoot\$resourceName"
```

別の作業コピーが必要なら clone を使います。読み取り用途では push URL を無効にします。この設定はファイル書込みや他の push 経路を禁止するものではありません。

```powershell
git clone '<credential-free-https-url>' '<repo-root>\external\repos\<resource-name>'
git -C '<repo-root>\external\repos\<resource-name>' remote set-url --push origin DISABLED
```

導入後はリポジトリルートで確認します。確認 CLI は clone や junction の作成、外部ファイルの編集、ネットワーク通信を行いません。

```powershell
Get-Item '<repo-root>\external\repos\*' | Select-Object Name, LinkType, Target
uv run --project . --locked --no-sync --offline python -X utf8 external/check_external.py --require-env
```

環境変数は登録簿に名前だけを記録し、値は導入先の秘密管理方法で設定します。Splunk の `script_ref`・`python_ref` は存在だけを確認します。実際の認証や検索手順は導入先で定めてください。

junction を撤去するときは、まず `Get-Item` で対象が junction であり接続先が意図した作業コピーであることを確認します。手元の **PowerShell** から、正確な junction パスを指定して以下を実行します。`/s` と `Remove-Item -Recurse` は使いません。

```powershell
Get-Item '<repo-root>\external\repos\<resource-name>' | Select-Object FullName, LinkType, Target
cmd /c rmdir "<repo-root>\external\repos\<resource-name>"
```

これは junction のリンクだけを外す手順です。通常 clone の撤去は未保存の作業を確認したうえで、導入先の削除手順に従います。Hook が導入操作を拒否する環境では、自動エージェントから迂回せず利用者のターミナルで実施します。Hook の適用範囲と限界は導入先の設定・運用資料を確認してください。

`external/repos/` は `.gitignore` と `.harness/config/harness.toml` の `search.exclude_paths` で除外します。junction は通常の symlink と異なる場合があるため、リンク検出だけに頼らずパスで除外します。uv はリポジトリルートから実行します（キャッシュ設定が相対パスのため）。
