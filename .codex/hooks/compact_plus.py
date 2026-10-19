"""Codex compact-plus hooks. Derived from compact-plus (MIT, Yuichi Uemura)."""

# MIT License
#
# Copyright (c) 2026 Yuichi Uemura
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# https://github.com/u-ichi/compact-plus/tree/main
#

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = ROOT / ".repository-state" / "compact-plus"
SECTIONS = ("active_plan", "current_phase", "tasklist_summary", "session_decisions",
            "constraints_and_blockers", "worker_topology", "skills_invoked",
            "editing_files", "failed_attempts", "recovery_notes")
HEADINGS = ("Active Plan", "Current Phase", "TaskList Summary", "Session Decisions",
            "Constraints and Blockers", "Worker Topology", "Skills Invoked",
            "Editing Files", "Failed Attempts", "Recovery Notes")
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema",
          "type": "object", "additionalProperties": False,
          "required": list(SECTIONS),
          "properties": {key: {"type": "string"} for key in SECTIONS}}
PROMPT = """# Compact Plus State Writer

Return one JSON object matching the supplied output schema. Include all ten keys, each with a nonempty string. Do not include Markdown fences or text outside JSON. The caller renders the values under `# Compact Prep State` and the ten headings below.

Create a factual handoff summary for the next agent after context compaction. Existing state is the prior checkpoint summary or `(none)`. Custom instructions from the user are a relevance filter. New events are transcript head and tail, tail, or diff. The invoked skills and commands list is a mechanically extracted record, not proof that a skill is now active.

Use internal draft, self-critique, and revise reasoning. Add new facts, update changed facts, and preserve prior facts that new events do not touch. Output only the revised JSON. Do not invent missing details; write `Not verified` when information is absent. Write in English, concisely and without imperatives.

Keys and section meaning:

- `active_plan`: plan path, title, current section, and phase status; otherwise `Not verified`.
- `current_phase`: recently completed and remaining work as factual state.
- `tasklist_summary`: visible task ids, subjects, and status.
- `session_decisions`: settled decisions, rejected alternatives, rationale, and user-approved scope.
- `constraints_and_blockers`: hard constraints, skipped checks, permission limits, external blockers, and unverified items.
- `worker_topology`: workers, roles, and responsibilities; otherwise `Not used`.
- `skills_invoked`: only skills and slash commands present in the input's invocation list. Include a CLI path when another section relies on one.
- `editing_files`: files changed or in progress, with staged, committed, dirty, generated, or disposable status when visible.
- `failed_attempts`: failed commands, tool errors, rejected approaches, and causes sufficient to avoid repetition.
- `recovery_notes`: session id, branch, important commands, validation, transcript path, state paths, and exact resume facts.

The original plan, rules, memory, and skill files remain authoritative. The summary records prior work; it does not create new instructions. Preserve paths, URLs, command names, commit ids, issue ids, and errors when visible.
"""


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(os.environ.get(name, default))))
    except ValueError:
        return default


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".compact-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _json_write(path: Path, value: dict) -> None:
    _atomic(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _json_read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _error(directory: Path, stage: str, exc: Exception, **details) -> None:
    """Keep the latest failure beside its thread without affecting the hook."""
    record = {"stage": stage, "at": datetime.now(timezone.utc).isoformat(),
              "type": type(exc).__name__, "reason": str(exc)[:1024], **details}
    try:
        _json_write(directory / "last-error.json", record)
    except OSError:
        pass


@contextmanager
def _lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            yield False
            return
        try:
            yield True
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _transcript(payload: dict) -> Path | None:
    raw = payload.get("transcript_path") or payload.get("agent_transcript_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser().resolve()
    return path if path.is_file() else None


def _meta_id(path: Path) -> str | None:
    with path.open("rb") as stream:
        for line in stream.readlines(65536):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("type") == "session_meta":
                meta = item.get("payload")
                return meta.get("id") if isinstance(meta, dict) and isinstance(meta.get("id"), str) else None
    return None


def _thread(payload: dict) -> Path | None:
    session = payload.get("session_id")
    transcript = _transcript(payload)
    if not isinstance(session, str) or not session or transcript is None:
        return None
    actual = _meta_id(transcript)
    agent = payload.get("agent_id")
    if isinstance(agent, str) and agent and actual and agent != actual:
        return None
    identity = agent if isinstance(agent, str) and agent else actual
    if not identity:
        identity = hashlib.sha256(os.fsencode(transcript)).hexdigest()
    key = hashlib.sha256(json.dumps([session, identity], ensure_ascii=False).encode()).hexdigest()
    return STATE_ROOT / "codex" / "threads" / key


def _file_identity(path: Path) -> dict:
    stat = path.stat()
    with path.open("rb") as stream:
        head = stream.read(128)
    return {"dev": stat.st_dev, "ino": stat.st_ino,
            "head_sha256": hashlib.sha256(head).hexdigest(),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _same_transcript(old: dict, now: dict) -> bool:
    return (old.get("dev") == now["dev"] and old.get("ino") == now["ino"]
            and old.get("head_sha256") == now["head_sha256"]
            and (now["size"] > old.get("size", -1) or
                 (now["size"] == old.get("size") and now["mtime_ns"] == old.get("mtime_ns"))))


def _complete(path: Path, offset: int) -> tuple[bytes, int]:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        if offset > size:
            raise ValueError("transcript shrank")
        stream.seek(offset)
        raw = stream.read()
    end = raw.rfind(b"\n") + 1
    return raw[:end], offset + end


def _valid_rows(rows: list[bytes]) -> None:
    for row in rows:
        value = json.loads(row.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("transcript row must be an object")


def _semantic_tail(path: Path, turns: int, byte_limit: int) -> list[bytes]:
    # Scan backwards in bounded chunks; keep complete lines and semantic turns.
    with path.open("rb") as stream:
        stream.seek(0, 2)
        pos = stream.tell()
        chunks = deque()
        total = 0
        while pos and total < max(byte_limit * 20, 2 * 1024 * 1024):
            size = min(pos, 65536)
            pos -= size
            stream.seek(pos)
            chunk = stream.read(size)
            chunks.appendleft(chunk)
            total += size
        data = b"".join(chunks)
    if pos:
        data = data[data.find(b"\n") + 1:]
    data = data[:data.rfind(b"\n") + 1]
    rows = data.splitlines()
    _valid_rows(rows)
    selected = []
    seen = 0
    for row in reversed(rows):
        selected.append(row)
        item = json.loads(row)
        payload = item.get("payload", {})
        if isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
            seen += 1
        if seen >= turns:
            break
    return list(reversed(selected))


def _squash(row: bytes) -> str:
    item = json.loads(row.decode("utf-8-sig"))
    payload = item.get("payload", {}) if isinstance(item, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    if os.environ.get("COMPACT_PLUS_SQUASH_ENABLED", "1") == "0":
        return row.decode("utf-8")
    text = payload.get("output") or payload.get("content") or payload.get("text")
    if payload.get("type") == "function_call_output" and len(str(text)) > _int_env("COMPACT_PLUS_SQUASH_BASH_CHARS", 500, 50, 100000):
        return f"[ToolResult: {len(str(text))} chars output]"
    return row.decode("utf-8")


def _cap(value: str, limit: int, tail: bool = False) -> str:
    raw = value.encode("utf-8")
    raw = raw[-limit:] if tail else raw[:limit]
    return raw.decode("utf-8", errors="ignore")


def _events(path: Path, checkpoint: dict) -> tuple[str, int, str]:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        end = 0
        position = size
        while position:
            start = max(0, position - 65536)
            stream.seek(start)
            chunk = stream.read(position - start)
            index = chunk.rfind(b"\n")
            if index >= 0:
                end = start + index + 1
                break
            position = start
    mode = os.environ.get("COMPACT_PLUS_TRANSCRIPT_MODE", "incremental")
    if mode not in ("incremental", "head-tail", "tail"):
        mode = "incremental"
    count = int(checkpoint.get("updates", 0)) if isinstance(checkpoint.get("updates"), int) else 0
    refresh = _int_env("COMPACT_PLUS_INCREMENTAL_REFRESH", 10, 1, 1000)
    offset = checkpoint.get("offset")
    identity = checkpoint.get("transcript_identity")
    same = isinstance(identity, dict) and _same_transcript(identity, _file_identity(path))
    if mode == "incremental" and (not isinstance(offset, int) or offset > end or
                                   not same or count % refresh == 0):
        mode = "head-tail"
    head_n = _int_env("COMPACT_PLUS_TRANSCRIPT_HEAD_TURNS", 5, 0, 100)
    tail_n = _int_env("COMPACT_PLUS_TRANSCRIPT_TAIL_TURNS", 25, 1, 500)
    head_limit = _int_env("COMPACT_PLUS_TRANSCRIPT_HEAD_KB", 10, 1, 512) * 1024
    tail_limit = _int_env("COMPACT_PLUS_TRANSCRIPT_TAIL_KB", 40, 1, 1024) * 1024
    raw_factor = _int_env("COMPACT_PLUS_RAW_DELTA_FACTOR", 20, 1, 100)
    if mode == "incremental" and size - offset > tail_limit * raw_factor:
        mode = "head-tail"
    if mode == "incremental":
        data, _ = _complete(path, offset)
        selected = data.splitlines()
        _valid_rows(selected)
        text = "\n".join(_squash(row) for row in selected if row)
        return _cap(text or "(no new transcript events)", tail_limit, True), end, mode
    tail_rows = _semantic_tail(path, tail_n, tail_limit)
    tail = _cap("\n".join(map(_squash, tail_rows)), tail_limit, True)
    if mode == "tail":
        return tail, end, mode
    head_rows = []
    seen = 0
    with path.open("rb") as stream:
        while seen < head_n and len(head_rows) < 1000:
            row = stream.readline()
            if not row or not row.endswith(b"\n"):
                break
            row = row.rstrip(b"\r\n")
            _valid_rows([row])
            head_rows.append(row)
            item = json.loads(row)
            payload = item.get("payload", {})
            if isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
                seen += 1
    head = _cap("\n".join(map(_squash, head_rows)), head_limit)
    return f"Transcript head:\n{head}\n\nTranscript tail:\n{tail}", end, mode


def _skills(path: Path) -> str:
    found = set()
    with path.open("rb") as stream:
        for row in stream:
            try:
                item = json.loads(row)
                payload = item.get("payload", {})
                if item.get("type") != "response_item" or payload.get("role") != "user":
                    continue
                for part in payload.get("content", []):
                    if isinstance(part, dict):
                        found.update(re.findall(r"(?<!\w)[$/][A-Za-z0-9_-]+", str(part.get("text", ""))))
            except (ValueError, TypeError, AttributeError):
                continue
    return ", ".join(sorted(found)) or "Not verified"


def _ancestor_codex_pid(processes: dict, pid: int) -> int | None:
    seen = set()
    while pid in processes and pid not in seen:
        seen.add(pid)
        pid = processes[pid][0]
        if pid in processes and processes[pid][1].lower() == "codex.exe":
            return pid
    return None


def _parent_codex() -> str:
    """Find the Codex executable in this hook's process ancestry."""
    if os.name == "nt":
        w = ctypes.wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                        ("th32ProcessID", w.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                        ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG),
                        ("dwFlags", w.DWORD), ("szExeFile", w.WCHAR * 260)]

        kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.Process32FirstW.restype = kernel.Process32NextW.restype = w.BOOL
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            processes = {}
            if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            while True:
                processes[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
                if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel.CloseHandle(snapshot)
        pid = _ancestor_codex_pid(processes, os.getpid())
        if pid is not None:
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                path = ctypes.create_unicode_buffer(32768)
                size = w.DWORD(len(path))
                if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                    raise ctypes.WinError(ctypes.get_last_error())
                return path.value
            finally:
                kernel.CloseHandle(handle)
    else:
        pid = os.getpid()
        seen = set()
        if sys.platform == "darwin":
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            libproc.proc_pidpath.restype = ctypes.c_int
        while pid not in seen and pid > 1:
            seen.add(pid)
            if sys.platform == "darwin":
                parent = subprocess.run(["ps", "-p", str(pid), "-o", "ppid="],
                                        capture_output=True, text=True, check=True, timeout=5)
                pid = int(parent.stdout.strip())
                path = ctypes.create_string_buffer(4096)
                if libproc.proc_pidpath(pid, path, len(path)) <= 0:
                    raise OSError(f"Cannot inspect parent process {pid}")
                executable = os.fsdecode(path.value)
            else:
                status = Path(f"/proc/{pid}/status").read_text()
                pid = int(re.search(r"^PPid:\s*(\d+)", status, re.MULTILINE).group(1))
                executable = os.readlink(f"/proc/{pid}/exe")
            if Path(executable).name.lower() in ("codex", "codex.exe"):
                return executable
    raise ValueError("Codex executable not found in hook process ancestry")


def run_backend(prompt: str, model: str | None, temporary_dir: Path,
                diagnostic=None) -> dict | None:
    """Run the user's Codex provider in a bounded, isolated summarization process."""
    output = temporary_dir / "summary.json"
    schema_path = temporary_dir / "schema.json"
    args = ["codex", "exec", "--sandbox", "read-only", "--ephemeral",
            "--skip-git-repo-check", "--output-schema", str(schema_path),
            "--output-last-message", str(output),
            "-c", "project_doc_max_bytes=0", "-c", "web_search=disabled",
            "-c", "features.multi_agent=false", "-c", "features.apps=false",
            "-c", "features.plugins=false", "-c", "features.shell_tool=false",
            "-c", "features.hooks=false"]
    if model:
        args.extend(["--model", model])
    args.append("-")
    env = os.environ.copy()
    env["COMPACT_PLUS_CHILD"] = "1"
    timeout = _int_env("COMPACT_PLUS_BACKEND_TIMEOUT", 80, 1, 150)
    try:
        args[0] = _parent_codex()
        version_result = subprocess.run([args[0], "--version"], capture_output=True,
                                        text=True, encoding="utf-8", cwd=temporary_dir,
                                        env=env, timeout=5, shell=False)
        if version_result.returncode != 0:
            raise ValueError(f"Codex CLI version check failed: executable={args[0]}, exit_code={version_result.returncode}")
        schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")
        result = subprocess.run(args, input=prompt, text=True, encoding="utf-8",
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                cwd=temporary_dir, env=env, timeout=timeout, shell=False)
        if result.returncode != 0:
            if diagnostic:
                diagnostic("backend", RuntimeError("Codex CLI exited unsuccessfully"),
                           exit_code=result.returncode, stderr=_cap(result.stderr, 8192, tail=True))
            return None
        try:
            value = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            if diagnostic:
                diagnostic("backend-output", exc)
            return None
        if not isinstance(value, dict):
            if diagnostic:
                diagnostic("backend-output", ValueError("summary JSON is not an object"))
            return None
        return value
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if diagnostic:
            diagnostic("backend", exc)
        return None


def _valid(value: dict | None) -> bool:
    return isinstance(value, dict) and set(value) == set(SECTIONS) and all(isinstance(value[key], str) and value[key].strip() for key in SECTIONS)


def _markdown(value: dict) -> str:
    return "# Compact Prep State\n" + "".join(f"\n## {heading}\n{value[key].strip()}\n" for key, heading in zip(SECTIONS, HEADINGS))


def _state(directory: Path, checkpoint: dict) -> str:
    summary = checkpoint.get("summary")
    if not _valid(summary):
        return ""
    rendered = _markdown(summary)
    target = directory / "state.md"
    try:
        if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            _atomic(target, rendered.encode("utf-8"))
    except (OSError, UnicodeError):
        pass
    return rendered


def _context(directory: Path, recovery: dict) -> str:
    state = directory / "state.md"
    checkpoint = _json_read(directory / "checkpoint.json")
    content = _state(directory, checkpoint)
    fresh = checkpoint.get("generation") == recovery.get("generation") and bool(content)
    intro = "[COMPACTION RECOVERY] Saved working state follows."
    if not fresh:
        intro += " Summary is stale or unavailable; consult the transcript backup."
    refs = (f"\nFull state: {state}\nCheckpoint: {directory / 'checkpoint.json'}\n"
            f"Transcript backup: {recovery.get('backup') or 'Not available'}\n")
    ending = "Original plan, memory, rule, and skill files remain authoritative.\n"
    budget = 8192 - len((intro + "\n" + refs + ending).encode("utf-8"))
    if budget < 0:
        return _cap(intro + refs + ending, 8192)
    if not content:
        return intro + refs + ending
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    priority = ("Active Plan", "Current Phase", "Session Decisions", "Constraints and Blockers", "Recovery Notes",
                "TaskList Summary", "Worker Topology", "Skills Invoked", "Editing Files", "Failed Attempts")
    chosen = ["# Compact Prep State\n"]
    remaining = max(0, budget - len(chosen[0].encode()))
    for heading in priority:
        section = next((part for part in sections if part.startswith(f"## {heading}\n")), "")
        if section and remaining > 0:
            piece = _cap(section, remaining)
            chosen.append(piece)
            remaining -= len(piece.encode("utf-8"))
    return intro + "\n" + "".join(chosen) + refs + ending


def _output(event: str, context: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def _deliver(event: str, directory: Path, recovery: dict, emit) -> dict:
    result = _output(event, _context(directory, recovery))
    if emit is not None:
        emit(result)
        recovery["delivered"] = True
        _json_write(directory / "recovery.json", recovery)
    return result


def _pre(payload: dict, directory: Path) -> dict:
    transcript = _transcript(payload)
    assert transcript is not None
    checkpoint_path = directory / "checkpoint.json"
    recovery_path = directory / "recovery.json"
    generation = str(uuid.uuid4())
    with _lock(directory) as locked:
        if not locked:
            return {}
        checkpoint = _json_read(checkpoint_path)
        recovery = _json_read(recovery_path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = directory / "backups" / f"{stamp}-{generation}.jsonl"
        backup_ok = False
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
            with transcript.open("rb") as source:
                _atomic(backup, source.read())
            backup_ok = True
        except (OSError, ValueError, UnicodeError) as exc:
            _error(directory, "backup", exc)
            backup = Path(recovery["backup"]) if recovery.get("backup") else None
        if backup_ok:
            try:
                prior = sorted(backup.parent.glob("*.jsonl"), key=lambda p: p.stat().st_mtime_ns)
                for old in prior[:-20]:
                    old.unlink(missing_ok=True)
            except OSError:
                pass
        recovery = {"generation": generation, "post_seen": False, "delivered": False,
                    "backup": str(backup) if backup else None}
        _json_write(recovery_path, recovery)
        try:
            events, offset, mode = _events(transcript, checkpoint) if backup_ok else ("", 0, "unavailable")
        except (OSError, ValueError, UnicodeError) as exc:
            _error(directory, "transcript", exc)
            events, offset, mode = "", 0, "unavailable"
        if not events:
            return {}
        previous = _state(directory, checkpoint) if isinstance(checkpoint.get("transcript_identity"), dict) and _same_transcript(checkpoint["transcript_identity"], _file_identity(transcript)) else ""
        previous = previous or "(none)"
        prompt = PROMPT + "\n\n" + json.dumps({
            "session_id": payload.get("session_id"), "transcript_path": str(transcript),
            "mode": mode, "existing_state": previous,
            "custom_instructions": payload.get("custom_instructions") or "(none)",
            "skills_and_commands": _skills(transcript), "new_events": events}, ensure_ascii=False)
        model = os.environ.get("COMPACT_PLUS_MODEL") or payload.get("model") or None
        tmp_dir = directory / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        temporary = tmp_dir / uuid.uuid4().hex
        temporary.mkdir()
        try:
            summary = run_backend(prompt, model, temporary,
                                  lambda stage, exc, **details: _error(directory, stage, exc, **details))
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        if not _valid(summary):
            if summary is not None:
                _error(directory, "summary-schema", ValueError("summary does not match required sections"))
            return {}
        rendered = _markdown(summary)
        _json_write(checkpoint_path, {"schema_version": 1, "summary": summary,
                                      "generation": generation, "saved_at": datetime.now(timezone.utc).isoformat(),
                                      "model": model, "identity": _meta_id(transcript), "offset": offset,
                                      "transcript_identity": _file_identity(transcript),
                                      "updates": checkpoint.get("updates", 0) + 1})
        _atomic(directory / "state.md", rendered.encode("utf-8"))
        try:
            (directory / "last-error.json").unlink(missing_ok=True)
        except OSError:
            pass
    return {}


def _reminder(directory: Path, payload: dict, emit) -> dict:
    transcript = _transcript(payload)
    if transcript is None or (directory / "warned").exists():
        return {}
    latest = None
    with transcript.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - 512 * 1024))
        data = stream.read()
        if size > len(data):
            data = data[data.find(b"\n") + 1:]
        for row in data.splitlines()[-500:]:
            try:
                item = json.loads(row)
                info = item.get("payload", {}).get("info", {})
                if item.get("type") == "event_msg" and item.get("payload", {}).get("type") == "token_count":
                    usage = info.get("last_token_usage", {})
                    total = usage.get("total_tokens")
                    window = info.get("model_context_window")
                    if isinstance(total, int) and isinstance(window, int) and window > 0:
                        latest = (total, window)
            except (ValueError, AttributeError):
                continue
    threshold = _int_env("COMPACT_PLUS_CODEX_WARN_THRESHOLD", 75, 1, 100)
    if latest is None or latest[0] * 100 < latest[1] * threshold:
        return {}
    state = (directory / "state.md").read_text(encoding="utf-8") if (directory / "state.md").is_file() else ""
    def line(heading):
        match = re.search(rf"^## {heading}\n\s*[-*]?\s*(.+)$", state, re.MULTILINE)
        return match.group(1) if match else "Not verified"
    context = (f"[COMPACT REMINDER] context usage reached {min(100, latest[0] * 100 // latest[1])}%. "
               "At a work boundary, tell the user they can run /compact.\n"
               f"Active Plan: {line('Active Plan')}\nCurrent Phase: {line('Current Phase')}\n"
               f"Recent Session Decision: {line('Session Decisions')}")
    result = _output("UserPromptSubmit", _cap(context, 8192))
    if emit is not None:
        emit(result)
        _atomic(directory / "warned", b"1")
    return result


def dispatch(event_name: str, payload: dict, emit=None) -> dict:
    """Return proposed output; emit callback is required to commit delivery state."""
    if os.environ.get("COMPACT_PLUS_CHILD") == "1" or not isinstance(payload, dict):
        return {}
    expected = {"pre-compact": "PreCompact", "post-compact": "PostCompact",
                "session-start": "SessionStart", "user-prompt-submit": "UserPromptSubmit"}
    if event_name not in expected or payload.get("hook_event_name", expected[event_name]) != expected[event_name]:
        return {}
    directory = None
    try:
        directory = _thread(payload)
        if directory is None:
            return {}
        if event_name == "pre-compact":
            return _pre(payload, directory)
        with _lock(directory) as locked:
            if not locked:
                return {}
            recovery_path = directory / "recovery.json"
            recovery = _json_read(recovery_path)
            if event_name == "post-compact":
                if recovery.get("generation"):
                    recovery["post_seen"] = True
                    _json_write(recovery_path, recovery)
                (directory / "warned").unlink(missing_ok=True)
                return {}
            if event_name == "session-start":
                if payload.get("source") != "compact":
                    return {}
                return _deliver("SessionStart", directory, recovery, emit) if recovery.get("generation") and not recovery.get("delivered") else {}
            if recovery.get("generation") and recovery.get("post_seen") and not recovery.get("delivered"):
                return _deliver("UserPromptSubmit", directory, recovery, emit)
            return _reminder(directory, payload, emit)
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, IndexError,
            subprocess.SubprocessError) as exc:
        if directory is not None:
            _error(directory, event_name, exc)
        return {"systemMessage": f"compact-plus skipped: {type(exc).__name__}"}


def main() -> int:
    if len(sys.argv) != 2:
        return 0
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        payload = {}
    emitted = False
    def emit(value: dict) -> None:
        nonlocal emitted
        sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        emitted = True
    result = dispatch(sys.argv[1], payload, emit)
    if not emitted:
        emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
