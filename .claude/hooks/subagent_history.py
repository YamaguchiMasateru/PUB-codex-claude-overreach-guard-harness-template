"""Claude Code: store minimal subagent pointers and inspect their transcripts locally."""

from __future__ import annotations

import argparse
from collections import deque
import datetime as dt
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / ".repository-state" / "subagent-history" / "claude" / "records"
FIELDS = ("session_id", "agent_id", "agent_type", "agent_transcript_path")
MAX_LINES = 200
MAX_CHARS = 20000
JST = dt.timezone(dt.timedelta(hours=9))


def emit(value: dict) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False))


def event() -> dict:
    raw = sys.stdin.buffer.read().decode("utf-8-sig")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("hook input must be an object")
    return value


def store(value: dict) -> dict:
    record = {key: value.get(key) if isinstance(value.get(key), str) else None for key in FIELDS}
    record.update(schema_version=1, record_id=str(uuid.uuid4()), recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
    RECORDS.mkdir(parents=True, exist_ok=True)
    target = RECORDS / (record["record_id"] + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".record-", suffix=".tmp", dir=RECORDS)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return record


def load_records() -> list[dict]:
    result = []
    if not RECORDS.exists():
        return result
    for path in RECORDS.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if (isinstance(record, dict) and record.get("record_id") == path.stem
                    and isinstance(record.get("recorded_at"), str)):
                result.append(record)
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def transcript_status(record: dict) -> str:
    path = record.get("agent_transcript_path")
    if not isinstance(path, str) or not path:
        return "path-null"
    target = Path(path)
    if not target.is_file():
        return "missing"
    try:
        with target.open("r", encoding="utf-8-sig") as stream:
            stream.read(1)
    except (OSError, UnicodeError):
        return "unreadable"
    return "readable"


def bounded_lines(stream):
    """Yield numbered lines without retaining an entire large JSONL row."""
    number = 1
    parts = []
    length = 0
    clipped = False
    while chunk := stream.readline(4096):
        content = chunk.rstrip("\r\n") if chunk.endswith("\n") else chunk
        room = MAX_CHARS - length
        if room > 0:
            piece = content[:room]
            parts.append(piece)
            length += len(piece)
        if len(content) > room:
            clipped = True
        if chunk.endswith("\n"):
            yield number, "".join(parts), clipped
            number += 1
            parts = []
            length = 0
            clipped = False
    if parts or clipped:
        yield number, "".join(parts), clipped


def list_records(args: argparse.Namespace) -> int:
    records = [r for r in load_records() if r.get("session_id") == args.session_id and (not args.agent_id or r.get("agent_id") == args.agent_id)]
    records.sort(key=lambda r: r.get("recorded_at", ""))
    if args.json:
        emit({"records": [{**r, "transcript_status": transcript_status(r)} for r in records]})
    elif not records:
        print("記録なし（未実行/フック不発/保存失敗の可能性）")
    else:
        for r in records:
            try:
                when = dt.datetime.fromisoformat(r["recorded_at"]).astimezone(JST).strftime("%Y-%m-%d %H:%M JST")
            except ValueError:
                when = "日時未設定"
            shown_path = r.get("agent_transcript_path") or "未設定"
            shown_agent = r.get("agent_id") or "未設定"
            shown_type = r.get("agent_type") or "未設定"
            print(f'{when}  {r.get("record_id")}  agent={shown_agent}  type={shown_type}  transcript={transcript_status(r)}  path={shown_path}')
    return 0


def show(args: argparse.Namespace) -> int:
    try:
        identity = str(uuid.UUID(args.record_id))
    except ValueError:
        print("invalid record id", file=sys.stderr)
        return 2
    path = RECORDS / (identity + ".json")
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        print("record not found or invalid", file=sys.stderr)
        return 2
    if not isinstance(record, dict) or record.get("record_id") != identity:
        print("record id mismatch", file=sys.stderr)
        return 2
    if args.session_id and record.get("session_id") != args.session_id:
        print("record does not belong to session", file=sys.stderr)
        return 2
    status = transcript_status(record)
    if status != "readable":
        print(f"本文未取得: {status}")
        return 0
    try:
        with Path(record["agent_transcript_path"]).open(encoding="utf-8-sig") as stream:
            if args.tail is not None:
                selected = list(deque(bounded_lines(stream), maxlen=args.tail))
            else:
                selected = []
                for number, line, clipped in bounded_lines(stream):
                    if number >= (args.start or 1):
                        selected.append((number, line, clipped))
                        if len(selected) >= args.lines:
                            break
    except (OSError, UnicodeError):
        print("本文未取得: unreadable")
        return 0
    used = 0
    for number, line, clipped in selected:
        room = MAX_CHARS - used
        if room <= 0:
            print("[文字数上限に達しました]")
            break
        snippet = line[:room]
        print(f"{number}: {snippet}")
        used += len(snippet)
        if clipped or len(snippet) < len(line):
            print("[行を文字数上限で切り詰めました]")
            break
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("subagent-stop")
    commands.add_parser("user-prompt-submit")
    listing = commands.add_parser("list")
    listing.add_argument("--session-id", required=True)
    listing.add_argument("--agent-id")
    listing.add_argument("--json", action="store_true")
    showing = commands.add_parser("show")
    showing.add_argument("--record-id", required=True)
    showing.add_argument("--session-id")
    choice = showing.add_mutually_exclusive_group()
    choice.add_argument("--tail", type=int)
    choice.add_argument("--start", type=int)
    showing.add_argument("--lines", type=int, default=50)
    args = parser.parse_args()
    if args.command == "list":
        return list_records(args)
    if args.command == "show":
        if not 1 <= args.lines <= MAX_LINES or args.start is not None and args.start < 1 or args.tail is not None and not 1 <= args.tail <= MAX_LINES:
            parser.error("line count must be 1..200 and start must be positive")
        return show(args)
    try:
        value = event()
        if args.command == "subagent-stop":
            store(value)
            emit({})
        else:
            session = value.get("session_id")
            if not isinstance(session, str) or not session:
                raise ValueError("session_id is missing")
            root = str(ROOT.as_posix())
            script = Path(__file__).resolve().as_posix()
            cli = f"uv run --project {shlex.quote(root)} --locked --no-sync --offline python -X utf8 {shlex.quote(script)} list --session-id {shlex.quote(session)}"
            emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": f"現在のsession_idは {session}。サブエージェント完了報告を収集した後、履歴一覧を確認してください。bash: {cli}。必要な履歴は record_id を指定して show で開いてください。"}})
    except (OSError, ValueError, UnicodeError) as error:
        print(f"subagent history: {type(error).__name__}", file=sys.stderr)
        emit({"systemMessage": "サブエージェント履歴の記録または案内に失敗しました。記録なしの可能性があります。"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
