"""Per-environment structure checks: Claude definitions, launch procedures and shared content."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".harness" / "scripts"))
import harness  # noqa: E402


SKILL = "delegate-investigate"
SKILL_TEXT = (
    f"---\nname: {SKILL}\ndescription: 調べるときに使う。\n---\n\n"
    "起動手順は [codex](references/launch-codex.md)、[claude](references/launch-claude.md) を読む。\n"
)
AGENT_TEXT = (
    "---\nname: investigate\ndescription: 調査担当。\nmodel: sonnet\neffort: medium\n"
    "disallowedTools: Write, Edit, NotebookEdit, Agent\n---\n\n"
    f"[{SKILL}](../../.agents/skills/{SKILL}/SKILL.md) を読む。\n"
)
WRAPPER_TEXT = (
    f"---\nname: {SKILL}\ndescription: 調べるときに使う。\n---\n\n"
    f"手順の正本は [.agents/skills/{SKILL}/SKILL.md](../../../.agents/skills/{SKILL}/SKILL.md) です。"
    "最初にそれを Read し、その内容に従ってください。\n"
)
def _hook(event_command: str, shell: str | None = "bash") -> dict:
    item = {"type": "command", "command": event_command}
    if shell:
        item["shell"] = shell
    return {"hooks": [item]}


HOOK_COMMAND = 'root="$(git rev-parse --show-toplevel)" && uv run python "$root/.claude/hooks/subagent_history.py" {}'
COMPACT_COMMAND = HOOK_COMMAND.replace("subagent_history.py", "compact_plus.py")
GUARD_COMMAND = HOOK_COMMAND.replace("subagent_history.py", "pretool_guard.py").replace(" {}", "")
GUARD_SOURCE = 'READ_ONLY_ROLES = ("investigate",)\nWATCHED_TOOLS = ("Bash", "Write")\n'
SETTINGS = {
    "permissions": {"deny": ["Read(**/.env)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash|Write", **_hook(GUARD_COMMAND)}],
        "PreCompact": [_hook(COMPACT_COMMAND.format("pre-compact"))],
        "PostCompact": [_hook(COMPACT_COMMAND.format("post-compact"))],
        "SessionStart": [{"matcher": "compact", **_hook(COMPACT_COMMAND.format("session-start"))}],
        "SubagentStop": [{"matcher": "*", **_hook(HOOK_COMMAND.format("subagent-stop"))}],
        "UserPromptSubmit": [_hook(COMPACT_COMMAND.format("user-prompt-submit")),
                             _hook(HOOK_COMMAND.format("user-prompt-submit"))],
    },
}
CONFIG = {
    "structure": {
        "markdown_dirs": [],
        "required_files": [],
        "skills": [SKILL],
        "environments": ["codex", "claude"],
        "codex": {"required_files": [".codex/config.toml"]},
        "claude": {
            "required_files": ["CLAUDE.md", ".claude/settings.json"],
            "read_only_roles": ["investigate"],
            "wrapper_skills": [SKILL],
        },
        "shared_content": {
            "files": [".agents/skills/delegate-*/SKILL.md"],
            "forbidden": ["fork_turns"],
        },
    }
}


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_repository(root: Path) -> None:
    write(root, f".agents/skills/{SKILL}/SKILL.md", SKILL_TEXT)
    write(root, f".agents/skills/{SKILL}/references/launch-codex.md", "# codex\n")
    write(root, f".agents/skills/{SKILL}/references/launch-claude.md", "# claude\n")
    write(
        root,
        ".agents/skills/repository-memory/SKILL.md",
        "---\nname: repository-memory\ndescription: 経験知を扱う。\n---\n",
    )
    write(root, ".codex/config.toml", "")
    write(root, "CLAUDE.md", "@AGENTS.md\n")
    write(root, ".claude/agents/investigate.md", AGENT_TEXT)
    write(root, f".claude/skills/{SKILL}/SKILL.md", WRAPPER_TEXT)
    write(root, ".claude/settings.json", json.dumps(SETTINGS))
    write(root, ".claude/hooks/subagent_history.py", "")
    write(root, ".claude/hooks/compact_plus.py", "")
    write(root, ".claude/hooks/pretool_guard.py", GUARD_SOURCE)
    write(root, ".claude/hooks/guard_rules.json", '{"rules": []}')


class EnvironmentStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        build_repository(self.root)
        self.config = copy.deepcopy(CONFIG)
        patcher = mock.patch.object(harness, "validate_agents", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def problems(self, environments: list[str] | None = None) -> list[str]:
        return harness.validate_structure(self.root, self.config, environments)

    def assertProblem(self, text: str, environments: list[str] | None = None) -> None:
        problems = self.problems(environments)
        self.assertTrue(any(text in item for item in problems), problems)

    def test_complete_repository_passes_for_every_selection(self) -> None:
        for selection in (None, ["codex"], ["claude"]):
            with self.subTest(selection=selection):
                self.assertEqual([], self.problems(selection))

    def test_unknown_environment_is_a_configuration_error(self) -> None:
        with self.assertRaisesRegex(harness.HarnessError, "設定にない実行環境"):
            self.problems(["other"])

    def test_repository_configuration_lists_both_environments(self) -> None:
        config = harness.load_config(ROOT)
        self.assertEqual(["codex", "claude"], config["structure"]["environments"])
        for environment in ("codex", "claude"):
            self.assertEqual([], harness.validate_structure(ROOT, config, [environment]))

    def test_missing_environment_file_is_reported_only_for_that_environment(self) -> None:
        (self.root / "CLAUDE.md").unlink()
        self.assertProblem("CLAUDE.md", ["claude"])
        self.assertProblem("CLAUDE.md")
        self.assertEqual([], self.problems(["codex"]))

    def test_missing_launch_procedure_is_reported_for_the_selected_environment(self) -> None:
        (self.root / f".agents/skills/{SKILL}/references/launch-claude.md").unlink()
        self.assertProblem("起動手順がありません（claude）", ["claude"])
        self.assertFalse(any("起動手順がありません" in item for item in self.problems(["codex"])))

    def test_skill_must_point_to_every_configured_launch_procedure(self) -> None:
        write(self.root, f".agents/skills/{SKILL}/SKILL.md", SKILL_TEXT.replace("launch-claude.md", "other.md"))
        self.assertProblem("launch-claude.md を案内していません", ["codex"])

    def test_missing_claude_agent_is_reported(self) -> None:
        (self.root / ".claude/agents/investigate.md").unlink()
        self.assertProblem("役割定義がありません", ["claude"])

    def test_claude_agent_frontmatter_is_checked(self) -> None:
        write(self.root, ".claude/agents/investigate.md", AGENT_TEXT.replace("model: sonnet\n", ""))
        self.assertProblem("model がありません", ["claude"])
        write(self.root, ".claude/agents/investigate.md", AGENT_TEXT.replace("name: investigate", "name: other"))
        self.assertProblem("役割名がファイル名と一致しません", ["claude"])

    def test_read_only_role_must_deny_editing_tools(self) -> None:
        write(
            self.root,
            ".claude/agents/investigate.md",
            AGENT_TEXT.replace("disallowedTools: Write, Edit, NotebookEdit, Agent\n", "disallowedTools: Agent\n"),
        )
        self.assertProblem("Write と Edit が必要", ["claude"])

    def test_unknown_read_only_role_is_reported(self) -> None:
        self.config["structure"]["claude"]["read_only_roles"] = ["investgate"]
        self.assertProblem("未知の役割", ["claude"])

    def test_every_role_must_deny_further_delegation(self) -> None:
        write(
            self.root,
            ".claude/agents/investigate.md",
            AGENT_TEXT.replace("disallowedTools: Write, Edit, NotebookEdit, Agent\n", "disallowedTools: Write, Edit\n"),
        )
        self.assertProblem("disallowedTools に Agent が必要", ["claude"])

    def test_wrapper_description_mismatch_is_reported(self) -> None:
        write(self.root, f".claude/skills/{SKILL}/SKILL.md", WRAPPER_TEXT.replace("調べる", "探す"))
        self.assertProblem("description が正本と一致しません", ["claude"])
        self.assertEqual([], self.problems(["codex"]))

    def test_wrapper_name_mismatch_is_reported(self) -> None:
        write(self.root, f".claude/skills/{SKILL}/SKILL.md", WRAPPER_TEXT.replace(f"name: {SKILL}", "name: other"))
        self.assertProblem("name が正本と一致しません", ["claude"])

    def test_missing_wrapper_is_reported(self) -> None:
        (self.root / f".claude/skills/{SKILL}/SKILL.md").unlink()
        self.assertProblem("ラッパーがありません", ["claude"])

    def test_wrapper_without_source_is_reported(self) -> None:
        (self.root / f".agents/skills/{SKILL}/SKILL.md").unlink()
        self.assertProblem("ラッパーの正本がありません", ["claude"])

    def test_wrapper_without_link_is_reported(self) -> None:
        text = WRAPPER_TEXT.replace(f"../../../.agents/skills/{SKILL}/SKILL.md", "SKILL.md")
        write(self.root, f".claude/skills/{SKILL}/SKILL.md", text)
        self.assertProblem("正本へのリンク", ["claude"])

    def test_wrapper_copying_the_procedure_is_reported(self) -> None:
        write(self.root, f".claude/skills/{SKILL}/SKILL.md", WRAPPER_TEXT + "手順。" * 200)
        self.assertProblem("本文が長すぎます", ["claude"])

    def test_invalid_claude_settings_are_reported(self) -> None:
        write(self.root, ".claude/settings.json", "{broken")
        self.assertProblem("設定を読めません", ["claude"])
        write(self.root, ".claude/settings.json", '{"permissions": {"deny": "Read"}}')
        self.assertProblem("permissions.deny は文字列の配列", ["claude"])

    def write_settings(self, settings: dict) -> None:
        write(self.root, ".claude/settings.json", json.dumps(settings))

    def test_missing_hooks_are_reported(self) -> None:
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]
        self.write_settings(settings)
        self.assertProblem("hooks がありません", ["claude"])
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["UserPromptSubmit"]
        self.write_settings(settings)
        self.assertProblem("UserPromptSubmit の履歴 Hook がありません", ["claude"])
        self.assertProblem("UserPromptSubmit のcompact-plus Hook がありません", ["claude"])
        self.assertEqual([], self.problems(["codex"]))

    def test_hook_without_explicit_bash_shell_is_reported(self) -> None:
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["SubagentStop"][0]["hooks"][0]["shell"]
        self.write_settings(settings)
        self.assertProblem('SubagentStop Hook に "shell": "bash" が必要', ["claude"])
        settings["hooks"]["SubagentStop"][0]["hooks"][0]["shell"] = "powershell"
        self.write_settings(settings)
        self.assertProblem('"shell": "bash" が必要', ["claude"])

    def test_missing_compact_plus_hooks_are_reported(self) -> None:
        for event in ("PreCompact", "PostCompact", "SessionStart"):
            with self.subTest(event=event):
                settings = copy.deepcopy(SETTINGS)
                del settings["hooks"][event]
                self.write_settings(settings)
                self.assertProblem(f"{event} のcompact-plus Hook がありません", ["claude"])
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["UserPromptSubmit"][0]
        self.write_settings(settings)
        self.assertProblem("UserPromptSubmit のcompact-plus Hook がありません", ["claude"])

    def test_compact_plus_hook_without_bash_or_matcher_is_reported(self) -> None:
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["PreCompact"][0]["hooks"][0]["shell"]
        self.write_settings(settings)
        self.assertProblem('PreCompact Hook に "shell": "bash" が必要', ["claude"])
        settings = copy.deepcopy(SETTINGS)
        settings["hooks"]["SessionStart"][0]["matcher"] = "startup"
        self.write_settings(settings)
        self.assertProblem('matcher "compact" が必要', ["claude"])

    def test_compact_plus_script_missing_is_reported(self) -> None:
        (self.root / ".claude/hooks/compact_plus.py").unlink()
        self.assertProblem("参照する実行ファイルがありません: .claude/hooks/compact_plus.py", ["claude"])

    def test_hook_referencing_missing_script_is_reported(self) -> None:
        (self.root / ".claude/hooks/subagent_history.py").unlink()
        self.assertProblem("参照する実行ファイルがありません", ["claude"])

    def test_hook_command_without_root_script_is_reported(self) -> None:
        settings = copy.deepcopy(SETTINGS)
        settings["hooks"]["SubagentStop"][0]["hooks"][0]["command"] = "python subagent_history.py subagent-stop"
        self.write_settings(settings)
        self.assertProblem("を参照していません", ["claude"])

    def test_pretool_guard_registration_is_checked(self) -> None:
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["PreToolUse"]
        self.write_settings(settings)
        self.assertProblem("PreToolUse の権限制御 Hook がありません", ["claude"])
        settings = copy.deepcopy(SETTINGS)
        del settings["hooks"]["PreToolUse"][0]["hooks"][0]["shell"]
        self.write_settings(settings)
        self.assertProblem('PreToolUse Hook に "shell": "bash" が必要', ["claude"])
        settings = copy.deepcopy(SETTINGS)
        settings["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
        self.write_settings(settings)
        self.assertProblem("matcher に不足するツールがあります: Write", ["claude"])

    def test_pretool_guard_files_and_constants_are_checked(self) -> None:
        write(self.root, ".claude/hooks/pretool_guard.py", GUARD_SOURCE.replace('("investigate",)', '("investigate", "review")'))
        self.assertProblem("READ_ONLY_ROLES が harness.toml の read_only_roles と一致しません", ["claude"])
        write(self.root, ".claude/hooks/pretool_guard.py", "READ_ONLY_ROLES = ('investigate',)\n")
        self.assertProblem("WATCHED_TOOLS がありません", ["claude"])
        write(self.root, ".claude/hooks/pretool_guard.py", GUARD_SOURCE)
        write(self.root, ".claude/hooks/guard_rules.json", '{"rules": {}}')
        self.assertProblem("規則ファイルが不正です", ["claude"])
        (self.root / ".claude/hooks/guard_rules.json").unlink()
        self.assertProblem("規則ファイルがありません", ["claude"])
        (self.root / ".claude/hooks/pretool_guard.py").unlink()
        self.assertProblem("参照する実行ファイルがありません: .claude/hooks/pretool_guard.py", ["claude"])

    def test_environment_specific_terms_in_shared_files_are_reported(self) -> None:
        write(self.root, f".agents/skills/{SKILL}/SKILL.md", SKILL_TEXT + '`fork_turns="none"` を指定する。\n')
        self.assertProblem("SKILL.md:7: fork_turns")
        launch = self.root / f".agents/skills/{SKILL}/references/launch-codex.md"
        launch.write_text('`fork_turns="none"` を指定する。\n', encoding="utf-8")
        self.assertEqual(1, len(self.problems()))

    def test_shared_content_pattern_without_files_is_reported(self) -> None:
        self.config["structure"]["shared_content"]["files"] = ["missing/*.md"]
        self.assertProblem("検査対象がありません")

    def test_invalid_environment_configuration_is_rejected(self) -> None:
        for fragment in (
            'environments = ["Bad Name"]',
            'environments = ["claude"]\n[structure.claude]\nrequired_files = ["../outside"]',
            'environments = ["claude"]\n[structure.shared_content]\nfiles = ["../x.md"]\nforbidden = ["a"]',
            'environments = ["claude"]\n[structure.shared_content]\nfiles = ["x.md"]',
            'environments = ["claude"]\n[structure.claude]\nwrapper_skills = ["Bad Name"]',
        ):
            with self.subTest(fragment=fragment), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original = (ROOT / harness.CONFIG).read_text(encoding="utf-8")
                head = original.split("environments", 1)[0]
                tail = original.split("[checks]", 1)[1]
                config_path = root / harness.CONFIG
                config_path.parent.mkdir(parents=True)
                config_path.write_text(f"{head}{fragment}\n\n[checks]{tail}", encoding="utf-8")
                with self.assertRaises(harness.HarnessError):
                    harness.load_config(root)


if __name__ == "__main__":
    unittest.main()
