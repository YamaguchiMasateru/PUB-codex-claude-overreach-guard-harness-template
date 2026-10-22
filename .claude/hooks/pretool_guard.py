"""Claude Code PreToolUse guard: read-only roles (allow-list) and shared ask/deny rules.

Input: PreToolUse JSON on stdin. Output: exit 0 with a permissionDecision JSON, or nothing to allow.
This supplements the role definitions; it is not a security boundary (see
.repository-docs/examples/claude-settings.sample.md for the remaining paths).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from pathlib import Path

RULES_FILE = Path(__file__).resolve().with_name("guard_rules.json")

# Roles that must stay read-only. Must equal read_only_roles in .harness/config/harness.toml.
READ_ONLY_ROLES = ("investigate", "review")
# Tools a read-only role may never use (writes locally or externally, or runs unchecked commands).
READ_ONLY_DENIED_TOOLS = (
    "Artifact", "ArtifactComments", "NotebookEdit", "Write", "Edit", "MultiEdit", "PowerShell", "Monitor",
    "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "RemoteTrigger", "DesignSync",
)
# Tools whose calls are checked by action: only these actions are reads.
ARTIFACT_DATA_READ_ACTIONS = ("get", "list", "query")
# Every tool the settings matcher must route to this hook (literal so that harness.py can read it).
WATCHED_TOOLS = (
    "Bash", "ArtifactData", "Artifact", "ArtifactComments", "NotebookEdit", "Write", "Edit", "MultiEdit",
    "PowerShell", "Monitor", "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "RemoteTrigger", "DesignSync",
)

REASON_SUFFIX = "Not allowed for a read-only role. Ask the parent agent to do it."

SIMPLE_READERS = {
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "grep", "rg", "cut", "tr", "nl", "stat",
    "diff", "du", "which", "basename", "dirname", "realpath",
}
GIT_READ = {
    "status", "diff", "log", "show", "rev-parse", "ls-files", "grep", "ls-tree", "cat-file", "blame",
    "rev-list", "describe", "shortlog", "merge-base", "name-rev", "diff-tree", "show-ref", "for-each-ref",
    "check-ignore",
}
GIT_LISTERS = {"branch": {"--list", "-l", "-a", "-r", "-v", "-vv", "--show-current", "--all", "--remotes",
                          "--contains", "--merged", "--no-merged", "--sort", "--format"},
               "tag": {"--list", "-l", "-n", "--contains", "--merged", "--no-merged", "--sort", "--format"}}
FIND_DENIED = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
UV_FLAGS = {"--locked", "--no-sync", "--offline"}
SCRIPT_ARGS = {"inspect_repo.py": ("search", "show"), "harness.py": ("validate",)}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def split_command(command: str) -> tuple[list[list[str]], set[str]]:
    """Split a shell command into segments of tokens and report constructs that need care.

    Flags: sequence (; & && ||), newline, redirect (< >), substitution ($( ${ backtick),
    subshell ( ), pipe, unterminated. Pipes split segments.
    """
    segments: list[list[str]] = [[]]
    flags: set[str] = set()
    buf: list[str] = []
    has_buf = False

    def end_token() -> None:
        nonlocal buf, has_buf
        if has_buf:
            segments[-1].append("".join(buf))
        buf, has_buf = [], False

    def end_segment() -> None:
        end_token()
        if not segments[-1]:
            flags.add("empty-segment")
        segments.append([])

    i, n = 0, len(command)
    while i < n:
        c = command[i]
        nxt = command[i + 1] if i + 1 < n else ""
        if c in " \t\r":
            end_token()
        elif c == "\n":
            flags.add("newline")
            end_segment()
        elif c == "'":
            end = command.find("'", i + 1)
            if end < 0:
                flags.add("unterminated")
                buf.append(command[i + 1:])
                has_buf = True
                break
            buf.append(command[i + 1:end])
            has_buf = True
            i = end
        elif c == '"':
            has_buf = True
            i += 1
            while i < n and command[i] != '"':
                ch = command[i]
                if ch == "\\" and i + 1 < n and command[i + 1] in '"\\$`':
                    buf.append(command[i + 1])
                    i += 2
                    continue
                if ch == "`" or (ch == "$" and i + 1 < n and command[i + 1] in "({"):
                    flags.add("substitution")
                buf.append(ch)
                i += 1
            if i >= n:
                flags.add("unterminated")
        elif c == "\\":
            if nxt == "\n":
                i += 1
            elif nxt:
                buf.append(nxt)
                has_buf = True
                i += 1
        elif c == "`" or (c == "$" and nxt in ("(", "{")):
            flags.add("substitution")
            buf.append(c)
            has_buf = True
        elif c == ";":
            flags.add("sequence")
            end_segment()
        elif c == "&":
            flags.add("sequence")
            if nxt == "&":
                i += 1
            end_segment()
        elif c == "|":
            if nxt == "|":
                flags.add("sequence")
                i += 1
            else:
                flags.add("pipe")
            end_segment()
        elif c in "<>":
            flags.add("redirect")
            end_token()
        elif c in "()":
            flags.add("subshell")
            end_token()
        else:
            buf.append(c)
            has_buf = True
        i += 1
    end_token()
    if not segments[-1] and len(segments) > 1:
        flags.add("empty-segment")
    segments = [s for s in segments if s]
    return segments, flags


def _long_name(token: str) -> str | None:
    """Return the option name of a long option (without '--' and '=value'), or None."""
    if token.startswith("--") and len(token) > 2:
        return token[2:].split("=", 1)[0]
    return None


def _dangerous_long(token: str, names: tuple[str, ...]) -> bool:
    """True when a long option equals, abbreviates (2+ characters) or extends a dangerous option name.

    getopt_long and git parse-options accept unique prefixes such as --out for --output.
    """
    name = _long_name(token)
    if name is None:
        return False
    for danger in names:
        if name.startswith(danger) or (len(name) >= 2 and danger.startswith(name)):
            return True
    return False


def _check_allowed_options(tokens: list[str], short_flags: str, short_values: str, long_flags: set[str],
                           long_values: set[str], label: str) -> str | None:
    """Allow only the listed options (exact match); every other token starting with '-' is rejected.

    short_flags: single letters that take no value; short_values: letters whose value is attached or the next token.
    """
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if token == "--":
            return None
        if token.startswith("--"):
            name = _long_name(token)
            if name in long_flags:
                continue
            if name in long_values:
                if "=" not in token:
                    i += 1
                continue
            return f"{label} option is not allowed: {token}"
        if token.startswith("-") and len(token) > 1:
            body = token[1:]
            for index, letter in enumerate(body):
                if letter in short_values:
                    if index == len(body) - 1:
                        i += 1
                    break
                if letter not in short_flags:
                    return f"{label} option is not allowed: {token}"
    return None


SORT_OPTIONS = dict(short_flags="rnufbdhVszgM", short_values="kt",
                    long_flags={"reverse", "numeric-sort", "unique", "ignore-case", "ignore-leading-blanks", "dictionary-order",
                                "human-numeric-sort", "version-sort", "stable", "zero-terminated", "general-numeric-sort",
                                "month-sort"},
                    long_values={"key", "field-separator"}, label="sort")
GIT_GREP_OPTIONS = dict(short_flags="niwvlLcEFIhHoaqP", short_values="eABC",
                        long_flags={"count", "line-number", "ignore-case", "word-regexp", "files-with-matches", "files-without-match",
                                    "fixed-strings", "extended-regexp", "invert-match", "only-matching", "heading", "break",
                                    "no-color", "full-name", "untracked", "text", "null"},
                        long_values={"regexp", "after-context", "before-context", "context"}, label="git grep")
# Long options (and their abbreviations) that write files, run programs or block.
GIT_DANGEROUS_LONG = ("output", "ext-diff", "textconv", "open-files-in-pager", "no-index", "filters", "exec-path", "exec")
RG_DANGEROUS_LONG = ("pre", "hostname-bin", "search-zip")
TAIL_DANGEROUS_LONG = ("follow", "retry", "pid")
SENSITIVE_BASE = re.compile(r"\.env(\.[^/\\]*|\*)?")
SENSITIVE_PATH = re.compile(r"(^|[/\\:~])\.(ssh|aws|gnupg|kube|docker)([/\\]|$)|/etc/(shadow|sudoers)|(^|[/\\:])id_(rsa|dsa|ecdsa|ed25519)|\.(pem|key)$")


def _project_roots() -> set[str]:
    root = str(Path(__file__).resolve().parents[2]).replace("\\", "/").rstrip("/").lower()
    forms = {root}
    match = re.match(r"^([a-z]):(/.*)$", root)
    if match:
        forms.add(f"/{match.group(1)}{match.group(2)}")
    return forms


def _same_root(value: str) -> bool:
    return value == "." or value.replace("\\", "/").rstrip("/").lower() in _project_roots()


def _script_name(token: str) -> str | None:
    """Return inspect_repo.py / harness.py only for the repository's own relative or absolute script path."""
    path = token.replace("\\", "/")
    for name in SCRIPT_ARGS:
        relative = f".harness/scripts/{name}"
        if path == relative:
            return name
        if path.endswith("/" + relative) and path[: -len(relative) - 1].lower() in _project_roots():
            return name
    return None


def _check_uv(tokens: list[str]) -> str | None:
    if len(tokens) < 3 or tokens[1] != "run":
        return "uv may only run an allowed read-only script with uv run"
    i = 2
    while i < len(tokens) and tokens[i] != "python":
        if tokens[i] in UV_FLAGS:
            i += 1
        elif tokens[i] == "--project" and i + 1 < len(tokens) and _same_root(tokens[i + 1]):
            i += 2
        else:
            return f"uv run option is not allowed: {tokens[i]}"
    i += 1
    if i + 1 < len(tokens) and tokens[i] == "-X":
        if tokens[i + 1] != "utf8":
            return "python -X accepts only utf8"
        i += 2
    if i >= len(tokens):
        return "no script to run"
    name = _script_name(tokens[i])
    if name is None:
        return "only the repository's .harness/scripts/inspect_repo.py and harness.py can be run"
    rest = tokens[i + 1:]
    if name == "inspect_repo.py":
        if rest[:1] == ["search"] and len(rest) == 2 and not rest[1].startswith("-"):
            return None
        if rest[:1] == ["show"] and len(rest) == 3 and not rest[1].startswith("-") and re.fullmatch(r"[0-9]+", rest[2]):
            return None
        return "inspect_repo.py allows only: search <term> / show <path> <line>"
    if rest == ["validate"] or (len(rest) == 3 and rest[0] == "validate" and rest[1] == "--env" and rest[2] in ("codex", "claude")):
        return None
    return "harness.py allows only: validate [--env codex|claude]"


def _check_git(tokens: list[str]) -> str | None:
    args = tokens[1:]
    if args and args[0] == "--no-pager":
        args = args[1:]
    if not args:
        return "git subcommand is missing"
    sub, rest = args[0], args[1:]
    for token in rest:
        if _dangerous_long(token, GIT_DANGEROUS_LONG):
            return f"git file-output, no-index and external-run options are not allowed: {token}"
    if sub == "grep":
        return _check_allowed_options(rest, **GIT_GREP_OPTIONS)
    if sub in GIT_READ:
        return None
    if sub in GIT_LISTERS:
        allowed = GIT_LISTERS[sub]
        listing = any(t in ("--list", "-l") for t in rest) or not rest
        for token in rest:
            if token.startswith("-"):
                if token.split("=", 1)[0] not in allowed:
                    return f"git {sub} allows only listing options: {token}"
            elif not listing:
                return f"git {sub} without --list may create or delete"
        return None
    return f"git {sub} is not an allowed read-only subcommand"


def _check_secrets(tokens: list[str]) -> str | None:
    """Reject arguments that name .env files or obvious credential paths (not exhaustive)."""
    for token in tokens[1:]:
        base = re.split(r"[/\\:]", token)[-1]
        if (SENSITIVE_BASE.fullmatch(base) and base != ".env.example") or SENSITIVE_PATH.search(token):
            return f"argument looks like a secret file: {token}"
    return None


def check_segment(tokens: list[str]) -> str | None:
    """Return a reason when the command is not on the read-only allow-list."""
    name = tokens[0]
    if ASSIGNMENT.match(name):
        return "commands with environment assignments are not allowed"
    secret = _check_secrets(tokens)
    if secret:
        return secret
    if name == "git":
        return _check_git(tokens)
    if name == "uv":
        return _check_uv(tokens)
    if name == "find":
        bad = [t for t in tokens if t in FIND_DENIED]
        return f"find write/exec option is not allowed: {bad[0]}" if bad else None
    if name == "sort":
        return _check_allowed_options(tokens[1:], **SORT_OPTIONS)
    if name in SIMPLE_READERS:
        args = tokens[1:]
        if name == "rg" and any(_dangerous_long(t, RG_DANGEROUS_LONG) or (re.match(r"^-[A-Za-z]+$", t) and "z" in t) for t in args):
            return "rg external-command option is not allowed"
        if name == "tail" and any(_dangerous_long(t, TAIL_DANGEROUS_LONG) or (re.match(r"^-[A-Za-z0-9]+$", t) and re.search("[fF]", t)) for t in args):
            return "tail follow option is not allowed"
        return None
    return f"{name} is not an allowed read-only command"


def check_read_only_bash(command: str) -> str | None:
    segments, flags = split_command(command)
    blocking = flags & {"sequence", "newline", "redirect", "substitution", "subshell", "unterminated", "empty-segment"}
    if blocking:
        names = {"sequence": "command chaining", "newline": "multiple lines", "redirect": "redirection", "substitution": "command substitution",
                 "subshell": "subshell", "unterminated": "unterminated quote", "empty-segment": "empty command"}
        return ", ".join(names[f] for f in sorted(blocking)) + " is not allowed"
    if not segments:
        return "empty command"
    for tokens in segments:
        reason = check_segment(tokens)
        if reason:
            return reason
    return None


def read_only_decision(event: dict) -> str | None:
    """Return a deny reason for a read-only role, or None when the call is allowed."""
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool in READ_ONLY_DENIED_TOOLS:
        return f"{tool} can write or run commands"
    if tool == "ArtifactData":
        if tool_input.get("action") not in ARTIFACT_DATA_READ_ACTIONS:
            return "ArtifactData write actions are not allowed"
        return None
    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return "cannot judge the Bash command"
        return check_read_only_bash(command)
    return None


def load_rules(path: Path = RULES_FILE) -> list[dict]:
    """Load valid rules; broken files or entries are skipped (fail open) with one stderr line."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw = data["rules"]
        if not isinstance(raw, list):
            raise ValueError("rules must be a list")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"pretool_guard: cannot read the rules file, no rules applied: {exc}", file=sys.stderr)
        return []
    rules = []
    for index, rule in enumerate(raw):
        try:
            pattern = rule["pattern"]
            if (not isinstance(pattern, list) or not pattern
                    or any(not (isinstance(p, str) or (isinstance(p, list) and p and all(isinstance(x, str) for x in p))) for p in pattern)):
                raise ValueError("pattern")
            if rule["decision"] not in ("prompt", "forbidden"):
                raise ValueError("decision")
            rules.append(rule)
        except (KeyError, TypeError, ValueError) as exc:
            print(f"pretool_guard: rule {index} is invalid and ignored: {exc}", file=sys.stderr)
    return rules


def _prefix_matches(pattern: list, tokens: list[str]) -> bool:
    if len(tokens) < len(pattern):
        return False
    return all(token in part if isinstance(part, list) else token == part for part, token in zip(pattern, tokens))


def match_rules(rules: list[dict], command: str) -> dict | None:
    """Return the strictest matching rule (forbidden over prompt) for any segment of the command."""
    segments, _ = split_command(command)
    best = None
    for tokens in segments:
        while tokens and ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        for rule in rules:
            if _prefix_matches(rule["pattern"], tokens):
                if rule["decision"] == "forbidden":
                    return rule
                best = best or rule
    return best


# --- Protected paths: no writes to read-only links (external/repos holds junctions to other repositories) ---
# The Edit permission rule stops file-editing tools, but not shell redirects, rm, mv or git writes (observed 2026-10-21).
# This check is a guard against mistakes, not a security boundary: indirect writes (a script that writes by itself, xargs/find -exec,
# variables or computed paths, eval) are not detected.
PROTECTED_DEFAULT = ("external/repos",)
SHELL_TOOLS = ("Bash", "PowerShell")
PROTECTED_REASON = ("Writing under {path} is not allowed: it holds read-only links to external repositories. "
                    "If it is really needed, ask the user to perform the write in their own terminal.")
WRITE_ANY = {"rm", "mv", "rmdir", "mkdir", "touch", "ln", "chmod", "chown", "truncate", "dd", "tee", "patch", "unlink", "shred", "install",
             "del", "erase", "rd", "ri", "remove-item", "move-item", "mi", "set-content", "sc", "add-content", "ac", "out-file",
             "new-item", "ni", "clear-content", "clc", "rename-item", "rni", "set-item", "si", "remove-itemproperty",
             "mklink", "attrib", "icacls", "takeown", "set-itemproperty", "sp"}
WRITE_DEST = {"cp", "rsync", "copy-item", "copy", "cpi", "xcopy", "robocopy", "install", "compress-archive"}  # the last positional argument is the destination
WINDOWS_SWITCH = re.compile(r"^/[A-Za-z?]{1,8}(?:[:=].*)?$")  # xcopy/robocopy switches such as /E /MIR /XD:dir
GIT_WRITE = {"add", "commit", "checkout", "switch", "reset", "clean", "rm", "mv", "restore", "merge", "rebase", "push", "pull", "fetch",
             "apply", "am", "cherry-pick", "revert", "gc", "prune", "init", "clone", "update-index", "update-ref", "symbolic-ref",
             "filter-branch", "replace", "maintenance", "repack", "pack-refs", "write-tree", "commit-tree", "mktag"}
GIT_AMBIGUOUS_WRITE = {"remote": {"add", "remove", "rm", "rename", "set-url", "set-head", "set-branches", "prune", "update"},
                       "worktree": {"add", "remove", "move", "prune", "lock", "unlock", "repair"},
                       "submodule": {"add", "update", "init", "sync", "deinit", "foreach", "set-url", "set-branch", "absorbgitdirs"},
                       "notes": {"add", "append", "copy", "edit", "merge", "prune", "remove"},
                       "reflog": {"expire", "delete"}}
GIT_STASH_READ = {"list", "show"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
CD_COMMANDS = {"cd", "pushd", "set-location", "sl", "chdir"}
SHELL_WRAPPERS = {"bash", "sh", "zsh", "powershell", "pwsh"}
WRAPPER_FLAG = re.compile(r"^(?:-[A-Za-z]*c|-command)$", re.I)  # -c, -lc, -Command
# keywords and wrappers that precede the real command word
PREFIX_WORDS = {"do", "then", "else", "elif", "if", "while", "until", "time", "nohup", "nice", "ionice", "exec", "command", "sudo", "env",
                "call", "builtin", "stdbuf", "setsid", "timeout", "busybox", "xargs"}
PREFIX_VALUE_OPTIONS = {"sudo": {"-u", "-g", "-C"}, "nice": {"-n"}, "ionice": {"-c", "-n"}, "stdbuf": set(),
                        "xargs": {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"}}
# commands that write to the path given as the value of an output option
OUTPUT_OPTIONS = {"curl": {"-o", "--output", "--output-dir"}, "wget": {"-o", "-O", "-P", "--output-document", "--directory-prefix", "--output-file"},
                  "tar": {"-C", "--directory"}, "unzip": {"-d"}, "7z": {"-o"}, "invoke-webrequest": {"-outfile"}, "iwr": {"-outfile"},
                  "invoke-restmethod": {"-outfile"}, "irm": {"-outfile"}, "expand-archive": {"-destinationpath"},
                  "tee-object": {"-filepath"}, "export-csv": {"-path"}, "out-string": set()}
COMMENT_START = re.compile(r"(?<![^\s])#")
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
REDIRECT_TARGET = re.compile(r"(?<![\w<])(?:\d*>>?|&>>?)[ \t]*(?!&)(?:\"([^\"]*)\"|'([^']*)'|([^\s;&|<>]+))")
REDIRECT_IGNORED = {"/dev/null", "nul", "$null", "/dev/stderr", "/dev/stdout"}
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
GIT_BRANCH_LIST = {"--list", "-l", "-a", "-r", "-v", "-vv", "--show-current", "--all", "--remotes", "--contains", "--merged", "--no-merged"}
GIT_BRANCH_WRITE = {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "--force", "-f", "--set-upstream-to", "-u",
                    "--unset-upstream", "--edit-description"}
GIT_TAG_LIST = {"-l", "--list", "--contains", "--points-at", "-n", "--merged", "--no-merged"}
GIT_TAG_WRITE = {"-d", "--delete", "-f", "--force", "-a", "-s", "-m"}
GIT_CONFIG_READ = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--get-urlmatch"}
GIT_CONFIG_WRITE = {"--unset", "--unset-all", "--add", "--replace-all", "--edit", "-e", "--rename-section", "--remove-section"}


def load_protected_paths(path: Path = RULES_FILE) -> tuple[str, ...]:
    """Protected path prefixes from the rules file ("protected_paths"); the default when absent or broken."""
    try:
        values = json.loads(path.read_text(encoding="utf-8-sig")).get("protected_paths")
    except (OSError, ValueError, AttributeError):
        return PROTECTED_DEFAULT
    if isinstance(values, list) and values and all(
            isinstance(v, str) and v.strip().strip("/\\") and v.strip() not in (".", "..")
            for v in values):
        return tuple(v.strip().replace("\\", "/").rstrip("/") for v in values)
    return PROTECTED_DEFAULT


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies (they are data, not commands); the line that starts the heredoc is kept."""
    lines, out, terminator = command.split("\n"), [], None
    for line in lines:
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        out.append(line)
        match = HEREDOC.search(line)
        if match and "<<<" not in line:
            terminator = match.group(2)
    return "\n".join(out)


def _mask_quoted_arrows(command: str) -> str:
    """Hide > inside quotes (messages such as "a -> b") so they are not read as redirects; quotes and everything else stay."""
    out, quote = [], ""
    for ch in command:
        if quote:
            out.append("\x01" if ch == ">" else ch)
            if ch == quote:
                quote = ""
        else:
            if ch in "'\"":
                quote = ch
            out.append(ch)
    return "".join(out)


def _strip_comments(command: str) -> str:
    """Drop unquoted # comments (a # at the start of a word, up to the end of the line)."""
    out, quote, skipping, prev = [], "", False, "\n"
    for ch in command:
        if skipping:
            if ch == "\n":
                skipping = False
                out.append(ch)
        else:
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "'\"":
                quote = ch
            elif ch == "#" and prev in " \t\n":
                skipping = True
                prev = ch
                continue
            out.append(ch)
        prev = ch
    return "".join(out)


def _normalize_redirects(command: str) -> str:
    """>| and >&file are redirects to a file: rewrite them to > so the statement splitter does not cut them at | or &."""
    command = command.replace(">|", ">")
    return re.sub(r"(\d*)>&(?![\d-])", r"\1>", command)


def _statements(command: str) -> list[str]:
    """Split on unquoted ; | & and newlines (quote-aware; backslashes are kept because PowerShell paths use them)."""
    out, buf, quote, escaped = [], [], "", False
    for ch in command:
        if escaped:
            buf.append(ch)
            escaped = False
        elif quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
        elif ch == "\\":
            buf.append(ch)
            escaped = True  # an escaped quote or separator outside quotes does not open a quote or end a statement
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in ";\n|&":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def _tokens(statement: str) -> list[str]:
    return [tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"" else tok
            for tok in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", statement)]


def _command_word(tokens: list[str]) -> tuple[str, list[str]]:
    """Return the lower-cased command name and its arguments, skipping VAR=value, wrappers (sudo, time, ...) and keywords (do, then, ...)."""
    i = 0
    while i < len(tokens):
        word = re.sub(r"^(?:\$\(|[({!`])+", "", tokens[i])
        lower = word.lower()
        if not word:
            i += 1
        elif ASSIGNMENT.match(word) or lower in PREFIX_WORDS:
            i += 1
            values = PREFIX_VALUE_OPTIONS.get(lower, set())
            while lower != "env" and i < len(tokens) and tokens[i].startswith("-") or (lower == "env" and i < len(tokens) and tokens[i].startswith("-")):
                i += 2 if tokens[i] in values else 1
            if lower == "timeout" and i < len(tokens) and re.match(r"^\d", tokens[i]):
                i += 1
        else:
            break
    if i >= len(tokens):
        return "", []
    name = re.sub(r"^(?:\$\(|[({!`])+", "", tokens[i]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name, tokens[i + 1:]


def _is_absolute(path: str) -> bool:
    return path.startswith(("/", "~", "$")) or bool(re.match(r"^[A-Za-z]:[/\\]", path))


def _git_write(args: list[str]) -> bool:
    """True when the git invocation (arguments after "git") is a write subcommand."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_VALUE_OPTIONS else 1  # the --git-dir=<path> form is a single token
    if i >= len(args):
        return False
    sub, rest = args[i], args[i + 1:]
    flags = set(rest)
    positional = [a for a in rest if not a.startswith("-")]
    if sub in GIT_WRITE:
        return True
    if sub in GIT_AMBIGUOUS_WRITE:
        return any(a in GIT_AMBIGUOUS_WRITE[sub] for a in rest)
    if sub == "stash":
        return not positional or positional[0] not in GIT_STASH_READ
    if sub == "branch":
        return bool(flags & GIT_BRANCH_WRITE) or (bool(positional) and not flags & GIT_BRANCH_LIST)
    if sub == "tag":
        return bool(flags & GIT_TAG_WRITE) or (bool(positional) and not flags & GIT_TAG_LIST)
    if sub == "config":
        return bool(flags & GIT_CONFIG_WRITE) or (len(positional) >= 2 and not flags & GIT_CONFIG_READ)
    return False


def _values(args: list[str]) -> list[str]:
    """Non-option arguments plus the values of option=value, -Option:value and -t <dir> forms (candidate paths)."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-t", "--target-directory") and i + 1 < len(args):
            out.append(args[i + 1])
            i += 2
            continue
        if a.startswith("--") and "=" in a:
            out.append(a.split("=", 1)[1])
        elif a.startswith("-") and ":" in a[1:]:
            out.append(a.split(":", 1)[1])
        elif not a.startswith("-"):
            out.append(a)
        i += 1
    return out


def _lexical_path(value: str, cwd: str = "") -> str:
    """Normalize without resolving junctions or accessing another repository."""
    value = value.replace(chr(92), "/")
    cwd = cwd.replace(chr(92), "/")
    value = re.sub(r"^/([A-Za-z])(?=/)", r"\1:", value)
    if not (value.startswith("/") or re.match(r"^[A-Za-z]:/", value)):
        value = cwd.rstrip("/") + "/" + value
    return posixpath.normpath(value).rstrip("/").lower()


def _project_spelling(project: str, cwd: str) -> str:
    """Match only project-root identity, preserving the operation cwd's lexical spelling.

    Windows may supply an 8.3 cwd while git reports a long project path. Do not
    resolve write targets or descendants through external repository junctions.
    """
    if os.name != "nt":
        return project
    operation = Path(cwd)
    project_depth = len(Path(project).parts)
    for ancestor in (operation, *operation.parents):
        if len(ancestor.parts) > project_depth:
            continue
        try:
            if os.path.samefile(ancestor, project):
                return str(ancestor)
        except (OSError, ValueError):
            continue
    return project


def protected_write_reason(tool: str, command: str, protected: tuple[str, ...] | None = None, _depth: int = 0, cwd: str | None = None) -> str | None:
    """Return a deny reason when a Bash/PowerShell command writes under a protected path, else None."""
    if tool not in SHELL_TOOLS or not isinstance(command, str) or _depth > 3:
        return None
    paths = PROTECTED_DEFAULT if protected is None else protected
    current = _lexical_path(cwd or str(Path.cwd()))
    project = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path(__file__).absolute().parents[2])
    project = _project_spelling(project, current)
    roots = [_lexical_path(p, project) for p in paths]

    def mentions(value: str) -> bool:
        candidate = _lexical_path(value, current)
        return any(candidate == root or candidate.startswith(root + "/") for root in roots)

    def hit(value: str) -> bool:
        return bool(value) and not value.startswith("-") and mentions(value)

    text = _normalize_redirects(_mask_quoted_arrows(_strip_comments(_strip_heredocs(command))))
    for sub_match in SUBSTITUTION.finditer(text):  # $(...) and `...` run commands too
        inner = sub_match.group(1) or sub_match.group(2) or ""
        found = protected_write_reason(tool, inner, paths, _depth + 1, cwd=current) if inner.strip() else None
        if found:
            return found
    for statement in _statements(text):  # in order: a cd changes where relative paths point for the statements after it
        tokens = _tokens(statement)
        name, args = _command_word(tokens)
        for match in REDIRECT_TARGET.finditer(statement):
            target = match.group(1) or match.group(2) or match.group(3) or ""
            if target.lower() not in REDIRECT_IGNORED and hit(target):
                return PROTECTED_REASON.format(path=paths[0])
        if name in CD_COMMANDS:
            targets = [a for a in args if not a.startswith("-")]
            if targets:
                current = _lexical_path(targets[0], current)
            continue
        if name in SHELL_WRAPPERS or name == "cmd":
            inner = ""
            if name == "cmd" and len(args) >= 2 and args[0].lower() in ("/c", "/k"):
                inner = " ".join(args[1:])
            else:
                flag = next((k for k, a in enumerate(args) if WRAPPER_FLAG.match(a)), None)
                if flag is not None:
                    inner = " ".join(args[flag + 1:])
                else:
                    inner = " ".join(a for a in args if re.search(r"[\s;&|]", a))
            inner = inner.replace("", ">")  # the quoted text is the real command: restore the > hidden by _mask_quoted_arrows
            found = protected_write_reason(tool, inner, paths, _depth + 1, cwd=current) if inner else None
            if found:
                return found
            continue
        values = _values(args)
        if name in ("xcopy", "robocopy"):
            values = [v for v in values if not WINDOWS_SWITCH.match(v)]
        bad = False
        if name in WRITE_ANY:
            bad = any(hit(v) for v in values) or any(a.startswith("of=") and hit(a[3:]) for a in args)
        elif name == "sed" and any(a == "--in-place" or (a.startswith("-") and not a.startswith("--") and "i" in a[1:]) for a in args):
            bad = any(hit(v) for v in values)
        elif name in ("xcopy", "robocopy"):
            # Source and destination precede optional file filters and switches.
            bad = len(values) >= 2 and hit(values[1])
        elif name in WRITE_DEST:
            explicit = [args[k + 1] for k, a in enumerate(args) if a in ("-t", "--target-directory") and k + 1 < len(args)]
            explicit += [a.split("=", 1)[1] for a in args if a.startswith("--target-directory=")]
            if explicit:
                bad = any(hit(d) for d in explicit)
            elif len(values) >= 2:
                bad = hit(values[-1])
        elif name in OUTPUT_OPTIONS:
            options = OUTPUT_OPTIONS[name]
            insensitive = name not in ("curl", "wget", "tar", "unzip", "7z")  # PowerShell parameters ignore case
            for k, a in enumerate(args):
                key = a.lower() if insensitive else a
                if key in options and k + 1 < len(args) and hit(args[k + 1]):
                    bad = True
                elif "=" in key and key.split("=", 1)[0] in options and hit(a.split("=", 1)[1]):
                    bad = True
                elif ":" in key and key.split(":", 1)[0] in options and hit(a.split(":", 1)[1]):
                    bad = True
                elif not insensitive and len(a) > 2 and not a.startswith("--") and a[:2] in options and hit(a[2:]):
                    bad = True  # attached short option such as -ofile or -Cdir
        elif name == "find" and any(mentions(v) for v in values):
            bad = any(a in ("-delete", "-fprint", "-fprint0", "-fprintf", "-fls") for a in args) or any(
                a in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(args) and args[k + 1].replace("\\", "/").rsplit("/", 1)[-1].lower() in WRITE_ANY
                for k, a in enumerate(args))
        elif name == "perl" and any(a.startswith("-") and not a.startswith("--") and "i" in a[1:] for a in args):
            bad = any(hit(v) for v in values)
        elif name in ("awk", "gawk") and "inplace" in args:
            bad = any(hit(v) for v in values)
        elif name == "git":
            gitcwd, k = current, 0
            while k < len(args) and args[k].startswith("-"):
                if args[k] == "-C" and k + 1 < len(args):
                    gitcwd = _lexical_path(args[k + 1], gitcwd)
                k += 2 if args[k] in GIT_VALUE_OPTIONS else 1
            # Read subcommands can write an explicit output file as well.
            for index, arg in enumerate(args[k + 1:], k + 1):
                target = args[index + 1] if arg == "--output" and index + 1 < len(args) else arg.split("=", 1)[1] if arg.startswith("--output=") else None
                if target is not None:
                    if target[:1] in ("'", '"') and target[-1:] == target[:1]:
                        target = target[1:-1]
                    candidate = _lexical_path(target, gitcwd)
                    bad |= any(candidate == root or candidate.startswith(root + "/") for root in roots)
            if _git_write(args):
                bad |= mentions(gitcwd) or any(mentions(a) for a in args)
        if bad:
            return PROTECTED_REASON.format(path=paths[0])
    return None


def output(decision: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def decide(event: dict, rules: list[dict] | None = None) -> dict | None:
    """Return the hook output for an event, or None to allow."""
    if event.get("agent_type") in READ_ONLY_ROLES:
        try:
            reason = read_only_decision(event)
        except Exception as exc:  # fail closed for read-only roles
            reason = f"error while judging, denied ({type(exc).__name__})"
        if reason:
            return output("deny", f"{reason}. {REASON_SUFFIX}")
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if event.get("tool_name") in SHELL_TOOLS and isinstance(command, str):
        try:
            cwd = event.get("cwd")
            reason = protected_write_reason(event["tool_name"], command, load_protected_paths(),
                                            cwd=cwd if isinstance(cwd, str) and cwd else None)
        except Exception as exc:
            print(f"pretool_guard: protected-path check failed, not applied: {type(exc).__name__}", file=sys.stderr)
            reason = None
        if reason:
            return output("deny", reason)
    if event.get("tool_name") == "Bash" and isinstance(command, str):
        rule = match_rules(load_rules() if rules is None else rules, command)
        if rule:
            decision = "deny" if rule["decision"] == "forbidden" else "ask"
            justification = rule.get("justification") if isinstance(rule.get("justification"), str) else ""
            prefix = " ".join(p if isinstance(p, str) else "|".join(p) for p in rule["pattern"])
            return output(decision, f"{justification} (rule: {prefix})".strip())
    return None


def check_rules() -> int:
    """Self-check match / not_match examples of every rule (stand-in for an execpolicy check)."""
    rules = load_rules()
    failed = 0
    for rule in rules:
        for example in rule.get("match", []):
            if match_rules([rule], example) is None:
                print(f"match example does not match: {example}", file=sys.stderr)
                failed += 1
        for example in rule.get("not_match", []):
            if match_rules([rule], example) is not None:
                print(f"not_match example matches: {example}", file=sys.stderr)
                failed += 1
    print(f"rules: {len(rules)}, mismatches: {failed}")
    return 1 if failed else 0


def main() -> int:
    if sys.argv[1:] == ["check-rules"]:
        return check_rules()
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        if not isinstance(event, dict):
            raise ValueError("hook input must be an object")
    except (ValueError, UnicodeError) as exc:
        print(f"pretool_guard: cannot read the input, no judgment: {exc}", file=sys.stderr)
        return 0
    try:
        result = decide(event)
    except Exception as exc:  # fail open outside the read-only check
        print(f"pretool_guard: judgment failed, allowing: {exc}", file=sys.stderr)
        return 0
    if result:
        # ASCII escapes keep the Japanese reason intact whatever code page the host decodes stdout with.
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
