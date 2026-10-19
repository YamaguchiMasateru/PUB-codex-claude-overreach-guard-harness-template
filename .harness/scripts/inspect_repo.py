"""Two-step, bounded text inspection for this repository."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import sys

from harness import HarnessError, ROOT, _print_safe, load_config, repo_path


@dataclass(frozen=True)
class SearchHit:
    path: str
    first_line: int
    count: int


def _eligible(name: str, config: dict) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in config["include"])


def _excluded(relative: Path, config: dict) -> bool:
    if any(part in config["exclude_dirs"] for part in relative.parts):
        return True
    candidate = relative.as_posix().strip("/")
    return any(
        candidate == excluded or candidate.startswith(excluded.rstrip("/") + "/")
        for excluded in config.get("exclude_paths", [])
    )


def search(root: Path, config: dict, term: str) -> tuple[list[SearchHit], bool]:
    if not term:
        raise HarnessError("検索語を指定してください")
    hits: list[SearchHit] = []
    limit = config["max_files"]
    base = root.resolve()
    for current, directories, files in os.walk(base, followlinks=False):
        relative_current = Path(current).relative_to(base)
        directories[:] = sorted(
            name for name in directories
            if not _excluded(relative_current / name, config)
        )
        for name in sorted(files):
            if not _eligible(name, config) or _excluded(relative_current / name, config):
                continue
            path = Path(current) / name
            if not path.resolve().is_relative_to(base) or path.stat().st_size > config["max_file_bytes"]:
                continue
            matches = [
                number
                for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1)
                if term.casefold() in line.casefold()
            ]
            if matches:
                if len(hits) == limit:
                    return hits, True
                hits.append(SearchHit(path.relative_to(base).as_posix(), matches[0], len(matches)))
    return hits, False


def show(root: Path, config: dict, relative: str, line: int) -> str:
    path = repo_path(root, relative)
    if not path.is_file() or not _eligible(path.name, config):
        raise HarnessError(f"対象のテキストファイルがありません: {relative}")
    if _excluded(path.relative_to(root.resolve()), config):
        raise HarnessError(f"除外されたディレクトリです: {relative}")
    if path.stat().st_size > config["max_file_bytes"]:
        raise HarnessError(f"ファイルが上限を超えています: {relative}")
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if line < 1 or line > len(lines):
        raise HarnessError(f"行番号は 1 から {len(lines)} の範囲にしてください")
    context = config["context_lines"]
    start = max(1, line - context)
    end = min(len(lines), line + context)
    body = "\n".join(f"{number:>5} | {lines[number - 1]}" for number in range(start, end + 1))
    return f"{path.relative_to(root.resolve()).as_posix()}:{start}-{end}\n{body}"


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "\n…表示上限に達しました。検索語または対象範囲を絞ってください。"
    if limit <= len(marker):
        return marker[:limit]
    return value[: limit - len(marker)] + marker


def main() -> int:
    parser = argparse.ArgumentParser(description="候補一覧から必要な行だけ読む検索 CLI")
    actions = parser.add_subparsers(dest="action", required=True)
    find = actions.add_parser("search", help="一致するファイル名と最初の行を表示")
    find.add_argument("term")
    excerpt = actions.add_parser("show", help="指定した行の周辺を表示")
    excerpt.add_argument("path")
    excerpt.add_argument("line", type=int)
    args = parser.parse_args()
    try:
        config = load_config(ROOT)["search"]
        if args.action == "search":
            hits, limited = search(ROOT, config, args.term)
            result = "\n".join(
                f"{hit.path}:{hit.first_line} ({hit.count} 件)" for hit in hits
            ) or "一致するファイルはありません"
            if limited:
                result += "\n候補数の上限に達しました。検索語を絞ってください。"
        else:
            result = show(ROOT, config, args.path, args.line)
        _print_safe(_bounded(result, config["max_output_chars"]))
    except (HarnessError, OSError) as exc:
        _print_safe(f"検索エラー: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
