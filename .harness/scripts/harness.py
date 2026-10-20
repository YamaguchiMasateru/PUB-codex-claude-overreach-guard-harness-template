"""Repository-local harness validation and check runner."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path, PurePath
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(".harness/config/harness.toml")
CODEX_CONFIG = Path(".codex/config.toml")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKILL_NAME = re.compile(r"[a-z][a-z0-9-]*\Z")


class HarnessError(Exception):
    """An actionable configuration or structure error."""


def repo_path(root: Path, relative: str) -> Path:
    """Resolve a configured path while keeping it inside the repository."""
    if not relative or Path(relative).is_absolute() or PurePath(relative).anchor:
        raise HarnessError(f"相対パスを指定してください: {relative!r}")
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise HarnessError(f"リポジトリ外のパスは使えません: {relative}")
    return path


def _table(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HarnessError(f"{label} は TOML テーブルにしてください")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HarnessError(f"{label} は正の整数にしてください")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise HarnessError(f"{label} は空でない文字列の配列にしてください")
    return value


def _optional_strings(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    return _strings(value, label)


def _load_environment_config(root: Path, structure: dict[str, Any]) -> None:
    """Validate the optional per-environment settings of [structure]."""
    environments = _optional_strings(structure.get("environments"), "structure.environments")
    for name in environments:
        if not SKILL_NAME.fullmatch(name):
            raise HarnessError(f"実行環境名は小文字・数字・ハイフンで指定してください: {name}")
    for name in environments:
        if name not in structure:
            continue
        table = _table(structure[name], f"[structure.{name}]")
        for relative in _optional_strings(table.get("required_files"), f"structure.{name}.required_files"):
            repo_path(root, relative)
        _optional_strings(table.get("read_only_roles"), f"structure.{name}.read_only_roles")
        for skill in _optional_strings(table.get("wrapper_skills"), f"structure.{name}.wrapper_skills"):
            if not SKILL_NAME.fullmatch(skill):
                raise HarnessError(f"Skill 名は小文字・数字・ハイフンで指定してください: {skill}")
    shared = structure.get("shared_content")
    if shared is not None:
        shared = _table(shared, "[structure.shared_content]")
        for pattern in _strings(shared.get("files"), "structure.shared_content.files"):
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise HarnessError(f"structure.shared_content.files にリポジトリ外のパスは指定できません: {pattern}")
        _strings(shared.get("forbidden"), "structure.shared_content.forbidden")


def load_config(root: Path = ROOT) -> dict[str, Any]:
    path = root / CONFIG
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise HarnessError(f"設定ファイルがありません: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise HarnessError(f"TOML の構文を修正してください: {exc}") from exc

    search = _table(config.get("search"), "[search]")
    _strings(search.get("include"), "search.include")
    _strings(search.get("exclude_dirs"), "search.exclude_dirs")
    exclude_paths = search.get("exclude_paths", [])
    if not isinstance(exclude_paths, list) or any(
        not isinstance(item, str) or not item.strip() for item in exclude_paths
    ):
        raise HarnessError("search.exclude_paths は相対パス文字列の配列にしてください")
    normalized_paths = [repo_path(root, relative).relative_to(root.resolve()).as_posix() for relative in exclude_paths]
    if "." in normalized_paths:
        raise HarnessError("search.exclude_paths にリポジトリのルートは指定できません")
    search["exclude_paths"] = normalized_paths
    for key in ("max_files", "max_file_bytes", "context_lines", "max_output_chars"):
        _positive_int(search.get(key), f"search.{key}")

    structure = _table(config.get("structure"), "[structure]")
    markdown_dirs = structure.get("markdown_dirs")
    if not isinstance(markdown_dirs, list) or any(
        not isinstance(item, str) or not item.strip() for item in markdown_dirs
    ):
        raise HarnessError("structure.markdown_dirs は空でない相対パス文字列の配列にしてください")
    structure["markdown_dirs"] = []
    for relative in markdown_dirs:
        path = repo_path(root, relative)
        if path == root.resolve():
            raise HarnessError(f"structure.markdown_dirs にリポジトリのルートは指定できません: {relative}")
        structure["markdown_dirs"].append(path.relative_to(root.resolve()).as_posix())
    for relative in _strings(structure.get("required_files"), "structure.required_files"):
        repo_path(root, relative)
    for name in _strings(structure.get("skills"), "structure.skills"):
        if not SKILL_NAME.fullmatch(name):
            raise HarnessError(f"Skill 名は小文字・数字・ハイフンで指定してください: {name}")
    _load_environment_config(root, structure)

    checks = _table(config.get("checks"), "[checks]")
    _positive_int(checks.get("timeout_seconds"), "checks.timeout_seconds")
    _positive_int(checks.get("max_output_chars"), "checks.max_output_chars")
    log_dir = checks.get("log_dir")
    if not isinstance(log_dir, str):
        raise HarnessError("checks.log_dir は相対パスにしてください")
    repo_path(root, log_dir)
    commands = checks.get("commands")
    if not isinstance(commands, list) or not commands:
        raise HarnessError("[[checks.commands]] を1つ以上設定してください")
    seen: set[str] = set()
    for index, item in enumerate(commands, 1):
        command = _table(item, f"checks.commands #{index}")
        name = command.get("name")
        if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
            raise HarnessError(f"checks.commands #{index} の name が不正です")
        if name in seen:
            raise HarnessError(f"検査名が重複しています: {name}")
        seen.add(name)
        _strings(command.get("argv"), f"checks.commands.{name}.argv")
    return config


def _markdown_files(root: Path, config: dict[str, Any]) -> list[Path]:
    files = [
        repo_path(root, relative)
        for relative in config["structure"]["required_files"]
        if Path(relative).suffix.lower() == ".md"
    ]
    for directory in config["structure"]["markdown_dirs"]:
        files.extend(repo_path(root, directory).rglob("*.md"))
    for name in config["structure"]["skills"]:
        files.append(root / ".agents/skills" / name / "SKILL.md")
        files.extend(sorted((root / ".agents/skills" / name / "references").glob("*.md")))
    for env in config["structure"].get("environments", []):
        table = config["structure"].get(env, {})
        files.extend(
            repo_path(root, relative)
            for relative in table.get("required_files", [])
            if Path(relative).suffix.lower() == ".md"
        )
    files.extend(sorted(root.glob(".claude/agents/*.md")))
    return list(dict.fromkeys(files))


def _frontmatter(path: Path) -> dict[str, str] | None:
    """Return the simple ``key: value`` frontmatter of a Markdown file, or None."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    return {key.strip(): value.strip() for key, _, value in (line.partition(":") for line in lines[1:end]) if _}


def _environments(structure: dict[str, Any], requested: list[str] | None) -> list[str]:
    configured = list(structure.get("environments", []))
    if requested is None:
        return configured
    unknown = [name for name in requested if name not in configured]
    if unknown:
        raise HarnessError(f"設定にない実行環境です: {', '.join(unknown)}（設定済み: {', '.join(configured) or 'なし'}）")
    return list(requested)


def validate_environment_files(root: Path, structure: dict[str, Any], selected: list[str]) -> list[str]:
    """Check per-environment required files and the launch procedure of each role Skill."""
    problems: list[str] = []
    configured = structure.get("environments", [])
    for env in selected:
        for relative in structure.get(env, {}).get("required_files", []):
            if not repo_path(root, relative).is_file():
                problems.append(f"必要なファイルがありません（{env}）: {relative}")
        for name in structure["skills"]:
            launch = root / ".agents/skills" / name / "references" / f"launch-{env}.md"
            if not launch.is_file():
                problems.append(f"起動手順がありません（{env}）: {launch.relative_to(root)}")
    for name in structure["skills"]:
        skill = root / ".agents/skills" / name / "SKILL.md"
        if not skill.is_file():
            continue
        text = skill.read_text(encoding="utf-8-sig")
        for env in configured:
            if f"launch-{env}.md" not in text:
                problems.append(f"Skill が起動手順 launch-{env}.md を案内していません: {skill.relative_to(root)}")
    return problems


WRAPPER_BODY_LIMIT = 400


def validate_claude_wrappers(root: Path, names: list[str]) -> list[str]:
    """Check that each .claude/skills wrapper mirrors its source Skill and holds no procedure."""
    problems: list[str] = []
    for name in names:
        wrapper = root / ".claude/skills" / name / "SKILL.md"
        source = root / ".agents/skills" / name / "SKILL.md"
        label = wrapper.relative_to(root).as_posix()
        source_label = source.relative_to(root).as_posix()
        if not wrapper.is_file():
            problems.append(f"Claude 用の Skill ラッパーがありません: {label}")
            continue
        if not source.is_file():
            problems.append(f"ラッパーの正本がありません: {source_label}（ラッパー: {label}）")
            continue
        meta = _frontmatter(wrapper)
        original = _frontmatter(source)
        if meta is None or original is None:
            problems.append(f"frontmatter がありません: {label if meta is None else source_label}")
            continue
        for field in ("name", "description"):
            if meta.get(field) != original.get(field):
                problems.append(
                    f"ラッパーの {field} が正本と一致しません。正本 {source_label} を基準に {label} を直してください"
                    f"（正本を変えた場合はラッパーも同時に直す）"
                )
        text = wrapper.read_text(encoding="utf-8-sig")
        body = text.split("\n---\n", 1)[1] if text.startswith("---\n") and "\n---\n" in text else ""
        if f"../../../{source_label}" not in body:
            problems.append(f"ラッパーに正本へのリンク（../../../{source_label}）がありません: {label}")
        if len(body.strip()) > WRAPPER_BODY_LIMIT:
            problems.append(f"ラッパーの本文が長すぎます。手順は正本に置き、リンクだけにしてください: {label}")
    return problems


def validate_claude(root: Path, structure: dict[str, Any]) -> list[str]:
    """Check Claude Code role definitions and project settings."""
    problems: list[str] = []
    read_only = structure.get("claude", {}).get("read_only_roles", [])
    roles = [name.removeprefix("delegate-") for name in structure["skills"]]
    for role in read_only:
        if role not in roles:
            problems.append(f"read_only_roles に未知の役割があります: {role}")
    for name in structure["skills"]:
        role = name.removeprefix("delegate-")
        path = root / ".claude/agents" / f"{role}.md"
        label = path.relative_to(root).as_posix()
        if not path.is_file():
            problems.append(f"Claude の役割定義がありません: {label}")
            continue
        meta = _frontmatter(path)
        if meta is None:
            problems.append(f"frontmatter がありません: {label}")
            continue
        if meta.get("name") != role:
            problems.append(f"Claude の役割名がファイル名と一致しません: {label}")
        for field in ("description", "model", "effort"):
            if not meta.get(field):
                problems.append(f"Claude の役割 {role} の {field} がありません: {label}")
        denied = {item.strip() for item in meta.get("disallowedTools", "").split(",")}
        if "Agent" not in denied:
            problems.append(f"Claude の役割 {role} は追加の委譲を防ぐため disallowedTools に Agent が必要です: {label}")
        if role in read_only:
            if not {"Write", "Edit"} <= denied:
                problems.append(f"読み取り専用の役割 {role} は disallowedTools に Write と Edit が必要です: {label}")
        text = path.read_text(encoding="utf-8-sig")
        if f".agents/skills/{name}/SKILL.md" not in text:
            problems.append(f"Claude の役割 {role} が共通 Skill を案内していません: {label}")

    problems.extend(validate_claude_wrappers(root, structure.get("claude", {}).get("wrapper_skills", [])))

    settings = root / ".claude/settings.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"Claude の設定を読めません: .claude/settings.json: {exc}")
        else:
            permissions = data.get("permissions", {}) if isinstance(data, dict) else None
            if not isinstance(permissions, dict):
                problems.append("Claude の設定の permissions はオブジェクトにしてください: .claude/settings.json")
            else:
                for key in ("allow", "ask", "deny"):
                    value = permissions.get(key, [])
                    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                        problems.append(f"Claude の設定の permissions.{key} は文字列の配列にしてください: .claude/settings.json")
            problems.extend(validate_claude_hooks(root, data, read_only))
    return problems


CLAUDE_HISTORY_HOOKS = ("SubagentStop", "UserPromptSubmit")
CLAUDE_COMPACT_HOOKS = ("PreCompact", "PostCompact", "SessionStart", "UserPromptSubmit")
CLAUDE_HOOK_FILE = re.compile(r'"\$root/(\.claude/hooks/[^"]+)"')


def _claude_hook_groups(hooks: dict[str, Any], event: str) -> list[dict[str, Any]]:
    groups = hooks.get(event)
    return [group for group in groups if isinstance(group, dict)] if isinstance(groups, list) else []


def _check_claude_hook_items(root: Path, event: str, items: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for item in items:
        if item.get("shell") != "bash":
            problems.append(f'Claude の {event} Hook に "shell": "bash" が必要です: .claude/settings.json')
        found = CLAUDE_HOOK_FILE.findall(item["command"])
        if not found:
            problems.append(f'Claude の {event} Hook の command が "$root/.claude/hooks/..." を参照していません: .claude/settings.json')
        for relative in found:
            if not (root / relative).is_file():
                problems.append(f"Claude の {event} Hook が参照する実行ファイルがありません: {relative}")
    return problems


def validate_claude_hooks(root: Path, data: Any, read_only_roles: list[str] | None = None) -> list[str]:
    """Check the history, compact-plus and PreToolUse guard hooks (explicit bash shell, existing scripts)."""
    problems: list[str] = []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return ["Claude の設定に hooks がありません: .claude/settings.json"]
    for script, label, events in (("subagent_history.py", "履歴", CLAUDE_HISTORY_HOOKS),
                                  ("compact_plus.py", "compact-plus", CLAUDE_COMPACT_HOOKS)):
        for event in events:
            groups = _claude_hook_groups(hooks, event)
            matching: list[dict[str, Any]] = []
            for group in groups:
                inner = group.get("hooks")
                if not isinstance(inner, list):
                    continue
                found = [item for item in inner if isinstance(item, dict) and item.get("type") == "command"
                         and isinstance(item.get("command"), str) and script in item["command"]]
                if event == "SessionStart" and script == "compact_plus.py":
                    if found and group.get("matcher") != "compact":
                        problems.append('Claude の SessionStart の compact-plus Hook は matcher "compact" が必要です: .claude/settings.json')
                matching.extend(found)
            if not matching:
                problems.append(f"Claude の設定に {event} の{label} Hook がありません: .claude/settings.json")
                continue
            problems.extend(_check_claude_hook_items(root, event, matching))
    problems.extend(_validate_claude_pretool_guard(root, hooks, read_only_roles))
    return problems


def _guard_constant(source: str, name: str) -> list[str] | None:
    """Read a top-level tuple/list of strings assigned in the guard script, without importing it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
                return list(value)
    return None


def _validate_claude_pretool_guard(root: Path, hooks: dict[str, Any], read_only_roles: list[str] | None) -> list[str]:
    """Check PreToolUse registration of pretool_guard.py and its consistency with the configuration."""
    problems: list[str] = []
    matching: list[dict[str, Any]] = []
    matchers: set[str] = set()
    for group in _claude_hook_groups(hooks, "PreToolUse"):
        inner = group.get("hooks")
        found = [item for item in inner if isinstance(item, dict) and item.get("type") == "command"
                 and isinstance(item.get("command"), str) and "pretool_guard.py" in item["command"]] if isinstance(inner, list) else []
        if found:
            matchers.update(str(group.get("matcher", "")).split("|"))
        matching.extend(found)
    if not matching:
        return ["Claude の設定に PreToolUse の権限制御 Hook がありません: .claude/settings.json"]
    problems.extend(_check_claude_hook_items(root, "PreToolUse", matching))
    script = root / ".claude/hooks/pretool_guard.py"
    if not script.is_file():
        return problems
    source = script.read_text(encoding="utf-8-sig")
    watched = _guard_constant(source, "WATCHED_TOOLS")
    if watched is None:
        problems.append("pretool_guard.py に WATCHED_TOOLS がありません: .claude/hooks/pretool_guard.py")
    else:
        missing = sorted(set(watched) - matchers)
        if missing:
            problems.append(f"Claude の PreToolUse の matcher に不足するツールがあります: {', '.join(missing)}")
    if read_only_roles is not None:
        roles = _guard_constant(source, "READ_ONLY_ROLES")
        if roles is None or sorted(roles) != sorted(read_only_roles):
            problems.append(f"pretool_guard.py の READ_ONLY_ROLES が harness.toml の read_only_roles と一致しません: {roles} / {read_only_roles}")
    rules = root / ".claude/hooks/guard_rules.json"
    if not rules.is_file():
        problems.append("Claude の PreToolUse Hook の規則ファイルがありません: .claude/hooks/guard_rules.json")
    else:
        try:
            data = json.loads(rules.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
                raise ValueError("rules は配列にしてください")
        except (OSError, ValueError) as exc:
            problems.append(f"Claude の PreToolUse Hook の規則ファイルが不正です: .claude/hooks/guard_rules.json: {exc}")
    return problems


def validate_shared_content(root: Path, structure: dict[str, Any]) -> list[str]:
    """Reject environment-specific terms in files that both environments read."""
    shared = structure.get("shared_content")
    if not shared:
        return []
    problems: list[str] = []
    for pattern in shared["files"]:
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if not matches:
            problems.append(f"共通ファイルの検査対象がありません: {pattern}")
        for path in matches:
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                for term in shared["forbidden"]:
                    if term in line:
                        problems.append(
                            f"共通ファイルに環境固有の記述があります: {path.relative_to(root).as_posix()}:{number}: {term}"
                        )
    return problems


def validate_agents(root: Path, skills: list[str], config_file: Path = CODEX_CONFIG) -> list[str]:
    """Check Codex role registration and each referenced Skill-local agent."""
    problems: list[str] = []
    config_path = repo_path(root, str(config_file))
    if not config_path.is_file():
        return [f"Codex 設定がありません: {config_file}"]
    try:
        with config_path.open("rb") as stream:
            codex_config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"Codex 設定を読めません: {config_file}: {exc}"]

    roles = codex_config.get("agents")
    if not isinstance(roles, dict):
        return [f"Codex 設定に [agents] がありません: {config_file}"]

    for name in skills:
        role_name = name.removeprefix("delegate-") if name.startswith("delegate-") else name
        role = roles.get(role_name)
        if not isinstance(role, dict):
            problems.append(f"Codex の役割がありません: {name}")
            continue
        if not isinstance(role.get("description"), str) or not role["description"].strip():
            problems.append(f"Codex の役割 description がありません: {name}")
        relative = role.get("config_file")
        if not isinstance(relative, str) or not relative.strip():
            problems.append(f"Codex の役割 config_file がありません: {name}")
            continue
        try:
            agent_path = repo_path(root, str(config_file.parent / relative))
        except HarnessError as exc:
            problems.append(f"Codex の役割 {name}: {exc}")
            continue
        expected = repo_path(root, f".agents/skills/{name}/agent.toml")
        if agent_path != expected:
            problems.append(f"Codex の役割 {name} は対応する Skill の agent.toml を参照してください")
            continue
        if not agent_path.is_file():
            problems.append(f"エージェント定義がありません: {agent_path.relative_to(root.resolve())}")
            continue
        try:
            with agent_path.open("rb") as stream:
                agent = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"エージェント定義を読めません: {agent_path.relative_to(root.resolve())}: {exc}")
            continue
        if agent.get("name") != role_name:
            problems.append(f"エージェント名が役割名と一致しません: {role_name}")
        for field in ("description", "developer_instructions", "model", "model_reasoning_effort"):
            if not isinstance(agent.get(field), str) or not agent[field].strip():
                problems.append(f"エージェント {name} の {field} がありません")
        if agent.get("sandbox_mode") not in ("read-only", "workspace-write"):
            problems.append(f"エージェント {name} の sandbox_mode が不正です")
    return problems


def validate_structure(root: Path, config: dict[str, Any], environments: list[str] | None = None) -> list[str]:
    """Validate shared structure plus the selected environments (all configured ones by default)."""
    root = root.resolve()  # TEMP の 8.3 短縮名など、解決済みの子パスと比べられるようにそろえる
    problems: list[str] = []
    structure = config["structure"]
    selected = _environments(structure, environments)
    for relative in config["structure"]["required_files"]:
        path = repo_path(root, relative)
        if not path.is_file():
            problems.append(f"必要なファイルがありません: {relative}")

    for relative in config["structure"]["markdown_dirs"]:
        if not repo_path(root, relative).is_dir():
            problems.append(f"Markdown 走査先ディレクトリがありません: {relative}")

    for name in config["structure"]["skills"]:
        path = root / ".agents/skills" / name / "SKILL.md"
        if not path.is_file():
            problems.append(f"Skill がありません: {path.relative_to(root)}")
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if not lines or lines[0] != "---":
            problems.append(f"frontmatter がありません: {path.relative_to(root)}")
            continue
        try:
            end = lines.index("---", 1)
        except ValueError:
            problems.append(f"frontmatter の終了行がありません: {path.relative_to(root)}")
            continue
        metadata = dict(
            line.split(":", 1) for line in lines[1:end] if ":" in line
        )
        if metadata.get("name", "").strip() != name:
            problems.append(f"Skill 名がディレクトリ名と一致しません: {path.relative_to(root)}")
        if not metadata.get("description", "").strip():
            problems.append(f"description がありません: {path.relative_to(root)}")

    if structure["skills"]:
        if "environments" not in structure or "codex" in selected:
            problems.extend(validate_agents(root, structure["skills"]))
        if "claude" in selected:
            problems.extend(validate_claude(root, structure))
        problems.extend(validate_environment_files(root, structure, selected))
    problems.extend(validate_shared_content(root, structure))

    for path in _markdown_files(root, config):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8-sig")
        for target in LINK.findall(content):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            try:
                resolved = repo_path(root, str(path.parent.relative_to(root) / target))
            except HarnessError:
                problems.append(f"参照先がリポジトリ外です: {path.relative_to(root).as_posix()} → {target}")
                continue
            if not resolved.exists():
                problems.append(f"参照先がありません: {path.relative_to(root).as_posix()} → {target}")
    return problems


def _tail(path: Path, max_chars: int) -> str:
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - max_chars * 4))
        preview = stream.read().decode("utf-8", errors="replace")[-max_chars:]
    return ("…先頭を省略…\n" if size > max_chars * 4 else "") + preview


def _print_safe(message: str, *, file: TextIO | None = None) -> None:
    stream = file if file is not None else sys.stdout
    encoding = stream.encoding or "utf-8"
    print(message.encode(encoding, errors="backslashreplace").decode(encoding), file=stream)


def run_command(root: Path, command: dict[str, Any], checks: dict[str, Any], run_dir: Path) -> bool:
    name = command["name"]
    argv = [sys.executable if part == "{python}" else part for part in command["argv"]]
    stdout_path = run_dir / f"{name}.stdout.log"
    stderr_path = run_dir / f"{name}.stderr.log"
    started = time.monotonic()
    status = "FAIL"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            result = subprocess.run(
                argv,
                cwd=root,
                stdout=stdout,
                stderr=stderr,
                timeout=checks["timeout_seconds"],
                check=False,
            )
            if result.returncode == 0:
                status = "PASS"
            else:
                stderr.write(f"終了コード: {result.returncode}\n".encode("utf-8"))
        except subprocess.TimeoutExpired:
            stderr.write(f"時間切れ: {checks['timeout_seconds']} 秒\n".encode("utf-8"))
        except OSError as exc:
            stderr.write(f"起動できません: {exc}\n".encode("utf-8"))

    elapsed = time.monotonic() - started
    _print_safe(f"{name}: {status} ({elapsed:.1f} 秒)")
    if status != "PASS":
        source = stderr_path if stderr_path.stat().st_size else stdout_path
        _print_safe(_tail(source, checks["max_output_chars"]).rstrip())
        _print_safe(f"詳細: {stdout_path.relative_to(root)}, {stderr_path.relative_to(root)}")
    return status == "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description="リポジトリ内ハーネスを検査します")
    parser.add_argument("action", choices=("validate", "check"))
    parser.add_argument(
        "--env",
        default="all",
        help="検査する実行環境。all は設定済みの全環境（CI 用）、環境名を指定すると共通部分とその環境だけを検査する（ローカル用）",
    )
    args = parser.parse_args()
    try:
        config = load_config(ROOT)
        problems = validate_structure(ROOT, config, None if args.env == "all" else [args.env])
    except HarnessError as exc:
        _print_safe(f"設定エラー: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            _print_safe(f"構造エラー: {problem}", file=sys.stderr)
        return 1
    _print_safe("構造検査: PASS")
    if args.action == "validate":
        return 0

    checks = config["checks"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{time.time_ns() % 1000000:06d}"
    run_dir = repo_path(ROOT, checks["log_dir"]) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    passed = [run_command(ROOT, command, checks, run_dir) for command in checks["commands"]]
    _print_safe(f"検査結果: {sum(passed)}/{len(passed)} PASS")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
