"""外部リソース登録簿（external/registry.json）に対する到達性の確認。読み取り専用。

- Splunk には接続しない。外部リポジトリへは git の読み取り系コマンドだけを実行する。
- 環境変数は「設定済み／未設定」だけを表示する（値も値の長さも出さない）。
- 終了コード: 0 = 到達可、1 = 未到達あり、2 = 登録簿の検証エラー。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path(__file__).resolve().parent / "registry.json"
KINDS = {"git-repo", "splunk", "server", "local-data"}
ACCESS = {"read-only", "read-write", "manual"}
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
CREDENTIAL_URL = re.compile(r"//[^/@\s]+@")


def redact(url: str) -> str:
    return CREDENTIAL_URL.sub("//", url)


def validate(registry: object) -> list[str]:
    """Validate without echoing untrusted values (including possible secrets)."""
    errors: list[str] = []
    if not isinstance(registry, dict):
        return ["registry must be an object"]
    if set(registry) != {"schema_version", "resources"}:
        errors.append("registry fields must be schema_version and resources")
    if type(registry.get("schema_version")) is not int or registry["schema_version"] != 1:
        errors.append("schema_version must be integer 1")
    if not isinstance(registry.get("resources"), list):
        return errors + ["resources must be an array"]
    seen: set[str] = set()
    fields = {"id", "kind", "access", "path", "remote", "script_ref", "python_ref", "env_vars", "link", "verified", "note"}
    for index, item in enumerate(registry["resources"], 1):
        label = f"resource #{index}"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        if set(item) - fields or not {"id", "kind", "access"} <= set(item):
            errors.append(f"{label}: unknown or missing fields")
        rid = item.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", rid):
            errors.append(f"{label}: id must be a nonempty identifier")
            rid = None
        if rid in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(rid)
        if not isinstance(item.get("kind"), str) or item["kind"] not in KINDS:
            errors.append(f"{label}: invalid kind")
        if not isinstance(item.get("access"), str) or item["access"] not in ACCESS:
            errors.append(f"{label}: invalid access")
        if "note" in item and not isinstance(item["note"], str):
            errors.append(f"{label}: note must be a string")
        if "remote" in item:
            remote = item["remote"]
            try:
                url = urlsplit(remote) if isinstance(remote, str) else None
                valid = bool(url and url.scheme == "https" and url.hostname and url.path.strip("/") and not url.username and not url.password and "?" not in remote and "#" not in remote and "@" not in url.netloc and not re.search(r"[\s\\]", remote))
                if url:
                    url.port  # Reject malformed ports too.
            except ValueError:
                valid = False
            if not valid:
                errors.append(f"{label}: remote must be credential-free HTTPS with hostname/path")
        for key in ("path", "script_ref", "python_ref"):
            if key not in item:
                continue
            value = item[key]
            normalized = value.replace("\\", "/") if isinstance(value, str) else ""
            parts = normalized.split("/")
            safe = bool(normalized.strip() and any(part and part != "." for part in parts) and not normalized.startswith("/") and not re.match(r"^[A-Za-z]:", normalized) and ".." not in parts and ":" not in normalized and "\x00" not in normalized)
            if not safe:
                errors.append(f"{label}: {key} must be a safe relative path")
                continue
            normalized = "/".join(part for part in parts if part and part != ".")
            item[key] = normalized
            if (key != "path" or item.get("kind") == "git-repo") and not normalized.startswith("external/repos/"):
                errors.append(f"{label}: {key} must be beneath external/repos")
        if item.get("kind") == "git-repo" and "path" not in item:
            errors.append(f"{label}: git-repo requires path")
        names = item.get("env_vars", [])
        if not isinstance(names, list):
            errors.append(f"{label}: env_vars must be an array")
            names = []
        link = item.get("link")
        if "link" in item:
            if not isinstance(link, dict) or set(link) != {"kind", "source_env"}:
                errors.append(f"{label}: invalid link fields")
            else:
                if not isinstance(link["kind"], str) or link["kind"] not in {"junction", "clone"}:
                    errors.append(f"{label}: invalid link kind")
                names = names + [link["source_env"]]
        if any(not isinstance(name, str) or not ENV_NAME.fullmatch(name) for name in names):
            errors.append(f"{label}: environment entries must be variable names")
        if "verified" in item:
            verified = item["verified"]
            if not isinstance(verified, dict) or set(verified) != {"date", "branch", "commit"} or any(not isinstance(v, str) or not v for v in verified.values()):
                errors.append(f"{label}: invalid verified fields")
    return errors


def git(path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(path), *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def kind_of_dir(path: Path) -> str:
    if not os.path.lexists(path):
        return "なし"
    if path.is_junction():
        return "junction" if path.exists() else "壊れた junction"
    return "clone（通常ディレクトリ）" if path.is_dir() else "不明"


def check_git_repo(item: dict) -> dict:
    path = ROOT / item["path"]
    state = kind_of_dir(path)
    row = {"id": item["id"], "kind": item["kind"], "dir": state, "reachable": False}
    if state not in {"junction", "clone（通常ディレクトリ）"}:
        return row
    top = git(path, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != path.resolve():
        return row
    branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    commit = git(path, "rev-parse", "HEAD")
    remote = git(path, "config", "--get", "remote.origin.url")
    dirty = git(path, "status", "--porcelain")
    row.update(
        reachable=bool(branch and commit),
        branch=branch,
        commit=commit,
        dirty_files=len([line for line in (dirty or "").splitlines() if line]),
        remote_matches=(redact(remote) == item.get("remote")) if remote else None,
    )
    if state.startswith("clone"):
        row["push_disabled"] = git(path, "config", "--get", "remote.origin.pushurl") == "DISABLED"
    verified = item.get("verified") or {}
    if not verified.get("commit"):
        row["vs_registered"] = "未登録"
    else:
        same = verified.get("commit") == commit and verified.get("branch") == branch
        row["vs_registered"] = "一致" if same else "不一致"
    return row


def check_splunk(item: dict) -> dict:
    row = {"id": item["id"], "kind": item["kind"], "reachable": True}
    for key in ("script_ref", "python_ref"):
        if item.get(key):
            exists = (ROOT / item[key]).exists()
            row[key] = "あり" if exists else "なし"
            row["reachable"] = row["reachable"] and exists
    row["env"] = {name: ("設定済み" if os.environ.get(name) else "未設定") for name in item.get("env_vars", [])}
    return row


def check_other(item: dict) -> dict:
    row = {"id": item["id"], "kind": item["kind"], "reachable": True}
    if item.get("path"):
        row["exists"] = (ROOT / item["path"]).exists()
        # access が manual の資料（origin-docs など）は環境ごとに無いことがあるため、不在を未到達として数えない
        row["reachable"] = True if item.get("access") == "manual" else row["exists"]
    else:
        row["exists"] = "確認不能（manual）"
    return row


def record(registry: dict, rows: list[dict]) -> None:
    today = datetime.date.today().isoformat()
    by_id = {row["id"]: row for row in rows}
    for item in registry["resources"]:
        row = by_id.get(item["id"])
        if item["kind"] == "git-repo" and row and row.get("reachable"):
            item["verified"] = {"date": today, "branch": row["branch"], "commit": row["commit"]}
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    parser.add_argument("--record", action="store_true", help="git-repo の確認日・branch・commit を registry.json に書き戻す")
    parser.add_argument("--require-env", action="store_true", help="未設定の環境変数も未到達として扱う")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        print("登録簿エラー: registry could not be read as JSON", file=sys.stderr)
        return 2
    errors = validate(registry)
    if errors:
        for message in errors:
            print(f"登録簿エラー: {message}")
        return 2

    rows = []
    for item in registry["resources"]:
        if item["kind"] == "git-repo":
            rows.append(check_git_repo(item))
        elif item["kind"] == "splunk":
            rows.append(check_splunk(item))
        else:
            rows.append(check_other(item))
        names = item.get("env_vars", []) + ([item["link"]["source_env"]] if item.get("link") else [])
        if names:
            rows[-1]["env"] = {name: ("設定済み" if os.environ.get(name) else "未設定") for name in names}

    missing_env = any(v == "未設定" for row in rows for v in row.get("env", {}).values())
    ok = all(row["reachable"] for row in rows) and not (args.require_env and missing_env)
    if args.record:
        try:
            record(registry, rows)
        except OSError:
            print("登録簿エラー: record could not be written", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            details = " ".join(f"{k}={v}" for k, v in row.items() if k not in {"id", "kind", "reachable"})
            print(f"[{'OK' if row['reachable'] else 'NG'}] {row['id']} ({row['kind']}) {details}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
