"""Independent Codex write guard. Mistake prevention, not a security boundary."""
from __future__ import annotations

import json
import posixpath
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = Path(__file__).resolve().with_name("guard_rules.json")
DEFAULT = ("external/repos",)
WRITE = set("touch mkdir rmdir rm unlink mv rename truncate chmod chown tee dd install del erase ren md rd move set-content add-content out-file new-item remove-item clear-content set-item remove-item rename-item move-item ni ri sc ac".split())
DEST = {"cp", "copy", "copy-item", "xcopy", "robocopy"}
READ_GIT = set("status diff log show rev-parse ls-files grep ls-tree cat-file blame rev-list describe shortlog merge-base name-rev diff-tree show-ref for-each-ref check-ignore".split())
OUTPUT = {"curl": {"-o", "--output", "--output-dir"}, "wget": {"-o", "-O", "-P", "--output-document"}, "tar": {"-C", "--directory"}, "unzip": {"-d"}, "invoke-webrequest": {"-outfile"}, "iwr": {"-outfile"}, "tee-object": {"-filepath"}, "export-csv": {"-path"}, "expand-archive": {"-destinationpath"}}


def normalize(value: str, cwd: str = "") -> str:
    """Normalize lexically; never follow junctions to their external targets."""
    value = value.replace("\\", "/")
    cwd = cwd.replace("\\", "/")
    if re.match(r"^/[A-Za-z]/", value):
        value = value[1] + ":" + value[2:]
    if not value.startswith("/") and not re.match(r"^[A-Za-z]:/", value):
        value = cwd.rstrip("/") + "/" + value
    return posixpath.normpath(value).rstrip("/").lower()


def load_protected_paths(path: Path = RULES_FILE) -> tuple[str, ...]:
    try:
        values = json.loads(path.read_text(encoding="utf-8-sig"))["protected_paths"]
        if not isinstance(values, list) or not values or any(
            not isinstance(v, str) or not v.strip() or v.startswith(("/", "\\"))
            or ":" in v or ".." in v.replace("\\", "/").split("/") for v in values
        ):
            raise ValueError("expected repository-relative protected_paths")
        return tuple(values)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"codex_pretool_guard: invalid settings; using external/repos: {exc}", file=sys.stderr)
        return DEFAULT


def statements(text: str) -> list[str]:
    out, buf, quote = [], [], ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in ";\n|&":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def tokens(text: str) -> list[str]:
    return [x[1:-1] if x[:1] in ("'", '"') and x[-1:] == x[:1] else x
            for x in re.findall(r'"[^\"]*"|\x27[^\x27]*\x27|[^\s]+', text)]


def shell_write(command: str, cwd: str, protected: tuple[str, ...], depth: int = 0) -> bool:
    if depth > 3:
        return False
    roots = [normalize(p, str(PROJECT_ROOT)) for p in protected]

    def hit(value: str) -> bool:
        p = normalize(value, cwd)
        return any(p == root or p.startswith(root + "/") for root in roots)

    # Heredoc bodies and comments are data. Preserve command lines containing redirects.
    lines, terminator = [], None
    for line in command.splitlines():
        if terminator:
            if line.strip() == terminator:
                terminator = None
            continue
        lines.append(line)
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            terminator = m[1]
    command = "\n".join(lines)
    for inner in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", command):
        if shell_write(inner[0] or inner[1], cwd, protected, depth + 1):
            return True
    for statement in statements(command.replace(">|", ">")):
        # Remove comments and mask quoted arrows for redirect detection.
        quote, masked = "", []
        for i, ch in enumerate(statement):
            if not quote and ch == "#" and (i == 0 or statement[i - 1].isspace()):
                break
            if quote:
                masked.append("\x01" if ch == ">" else ch)
                if ch == quote:
                    quote = ""
            else:
                if ch in "'\"":
                    quote = ch
                masked.append(ch)
        text = "".join(masked)
        for m in re.finditer(r'''(?<![\w<])(?:\d*>>?|&>>?)\s*(?!&)(?:"([^"]*)"|'([^']*)'|([^\s<>]+))''', text):
            target = next((x for x in m.groups() if x), "")
            if hit(target):
                return True
        words = tokens(text.replace("\x01", ">"))
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0].lower() in {"then", "do", "else", "if", "time", "exec", "command", "sudo", "env", "call", "xargs"}):
            words.pop(0)
        if not words:
            continue
        name = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
        args = words[1:]
        values = [a.split("=", 1)[1] if a.startswith("--") and "=" in a else a.split(":", 1)[1] if a.startswith("-") and ":" in a else a for a in args if not a.startswith("-") or "=" in a or ":" in a]
        if name in {"cd", "pushd", "set-location", "sl", "chdir"}:
            if values:
                cwd = normalize(values[0], cwd)
            continue
        if name in {"bash", "sh", "zsh", "powershell", "pwsh", "cmd"}:
            flag = next((i for i, a in enumerate(args) if re.match(r"^(?:-[a-z]*c|-command|/c|/k)$", a, re.I)), None)
            if flag is not None and shell_write(" ".join(args[flag + 1:]), cwd, protected, depth + 1):
                return True
        if name in WRITE and (any(hit(v) for v in values) or any(a.startswith("of=") and hit(a[3:]) for a in args)):
            return True
        if name in DEST:
            if name in {"xcopy", "robocopy"}:
                positional = [a for a in args if not a.startswith("-") and not re.match(r"^/[A-Za-z?]{1,8}(?:[:=].*)?$", a)]
                if len(positional) >= 2 and hit(positional[1]):
                    return True
                continue
            explicit = [args[i + 1] for i, a in enumerate(args[:-1]) if a in {"-t", "--target-directory"}]
            explicit += [a.split("=", 1)[1] for a in args if a.startswith("--target-directory=")]
            if any(hit(v) for v in explicit) or (not explicit and len(values) >= 2 and hit(values[-1])):
                return True
        if name in {"sed", "perl"} and any(a.startswith("-") and "i" in a for a in args) and any(hit(v) for v in values):
            return True
        if name == "find" and any(hit(v) for v in values) and any(a in {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls", "-exec", "-execdir"} for a in args):
            return True
        for i, a in enumerate(args):
            opts = OUTPUT.get(name, set())
            key = a if name in {"curl", "wget", "tar", "unzip"} else a.lower()
            if key in opts and i + 1 < len(args) and hit(args[i + 1]):
                return True
            if "=" in key and key.split("=", 1)[0] in opts and hit(a.split("=", 1)[1]):
                return True
            if len(a) > 2 and a[:2] in opts and hit(a[2:]):
                return True
        if name == "git":
            gitcwd, i = cwd, 0
            while i < len(args) and args[i].startswith("-"):
                if args[i] in {"-C", "--work-tree", "--git-dir", "-c"} and i + 1 < len(args):
                    if args[i] != "-c":
                        gitcwd = normalize(args[i + 1], gitcwd)
                    i += 2
                else:
                    i += 1
            # Output paths are relative to Git's effective cwd, even for read commands.
            for index, arg in enumerate(args[i + 1:], i + 1):
                target = args[index + 1] if arg == "--output" and index + 1 < len(args) else arg.split("=", 1)[1] if arg.startswith("--output=") else None
                if target is not None:
                    if target[:1] in ("'", '"') and target[-1:] == target[:1]:
                        target = target[1:-1]
                    candidate = normalize(target, gitcwd)
                    if any(candidate == root or candidate.startswith(root + "/") for root in roots):
                        return True
            sub = args[i] if i < len(args) else ""
            rest = args[i + 1:]
            # Only exact read forms: remote add/set-url and config assignments remain writes.
            safe_remote = sub == "remote" and (not rest or all(a in {"-v", "--verbose"} for a in rest))
            safe_config = sub == "config" and (
                rest in (["--list"], ["-l"])
                or (len(rest) == 2 and rest[0] in {"--get", "--get-all", "--get-regexp"}
                    and not rest[1].startswith("-"))
            )
            listing = sub in {"branch", "tag"} and (len(args) == i + 1 or "--list" in args or "-l" in args)
            if sub and sub not in READ_GIT and not listing and not safe_remote and not safe_config and (hit(gitcwd) or any(hit(v) for v in values)):
                return True
    return False


def decide(event: dict) -> dict | None:
    tool, data = event.get("tool_name"), event.get("tool_input")
    if not isinstance(data, dict) or not isinstance(data.get("command"), str):
        return None
    cwd = normalize(data.get("workdir") or data.get("cwd") or event.get("cwd") or str(PROJECT_ROOT), str(PROJECT_ROOT))
    protected, command = load_protected_paths(), data["command"]
    deny = tool == "Bash" and shell_write(command, cwd, protected)
    if tool == "apply_patch":
        for target in re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", command, re.M):
            candidate = normalize(target.strip(), cwd)
            deny |= any(candidate == normalize(p, str(PROJECT_ROOT)) or candidate.startswith(normalize(p, str(PROJECT_ROOT)) + "/") for p in protected)
    if deny:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Codex repository write guard: writes under protected paths are denied (" + ", ".join(protected) + ")"}}
    return None


def main() -> int:
    try:
        result = decide(json.loads(sys.stdin.buffer.read().decode("utf-8-sig")))
        if result:
            print(json.dumps(result))
    except Exception as exc:
        print(f"codex_pretool_guard: judgment failed, allowing: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
