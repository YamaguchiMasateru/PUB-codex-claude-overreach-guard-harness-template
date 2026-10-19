"""Claude Code PreToolUse guard: read-only roles (allow-list) and shared ask/deny rules.

Input: PreToolUse JSON on stdin. Output: exit 0 with a permissionDecision JSON, or nothing to allow.
This supplements the role definitions; it is not a security boundary (see
.repository-docs/examples/claude-settings.sample.md for the remaining paths).
"""

from __future__ import annotations

import json
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
