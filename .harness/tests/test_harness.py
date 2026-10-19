"""Observable behavior of the local harness commands."""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / ".harness"
sys.path.insert(0, str(HARNESS / "scripts"))
import harness  # noqa: E402
import inspect_repo  # noqa: E402


def replace_exclude_paths(text: str, value: str) -> str:
    result, count = re.subn(r"^exclude_paths = .*$", lambda _: f"exclude_paths = {value}", text, flags=re.MULTILINE)
    assert count == 1, "exclude_paths の行が 1 つではありません"
    return result


class ConfigAndStructureTests(unittest.TestCase):
    def test_repository_structure_and_links(self) -> None:
        config = harness.load_config(ROOT)
        self.assertEqual([], harness.validate_structure(ROOT, config))

    def test_invalid_toml_is_actionable(self) -> None:
        with mock.patch.object(harness, "CONFIG", Path(".harness/tests/fixtures/invalid.toml")):
            with self.assertRaisesRegex(harness.HarnessError, "TOML"):
                harness.load_config(ROOT)

    def test_missing_file_and_broken_link_are_reported(self) -> None:
        root = HARNESS / "tests/fixtures/broken_repo"
        config = {"structure": {"markdown_dirs": [], "required_files": ["AGENTS.md", "missing.md"], "skills": []}}
        problems = harness.validate_structure(root, config)
        self.assertTrue(any("必要なファイル" in problem for problem in problems))
        self.assertTrue(any("参照先" in problem for problem in problems))

    def test_extra_canonical_memory_notes_are_checked_for_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            memory = root / ".repository-state/memory/lessons"
            memory.mkdir(parents=True)
            (memory / "extra.md").write_text("[missing](missing.md)\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": [".repository-state/memory"], "required_files": ["AGENTS.md"], "skills": []}}
            problems = harness.validate_structure(root, config)
            self.assertTrue(any("extra.md" in item and "missing.md" in item for item in problems))

    def test_repository_docs_are_recursive_but_project_docs_are_outside_structure_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            repository_doc = root / ".repository-docs/operations/nested/procedure.md"
            repository_doc.parent.mkdir(parents=True)
            repository_doc.write_text("[missing](missing.md)\n", encoding="utf-8")
            project_doc = root / "docs/project.md"
            project_doc.parent.mkdir(parents=True)
            project_doc.write_text("[missing](missing.md)\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": [".repository-docs"], "required_files": ["AGENTS.md"], "skills": []}}
            problems = harness.validate_structure(root, config)
            self.assertTrue(any("procedure.md" in item and "missing.md" in item for item in problems))
            self.assertFalse(any("project.md" in item for item in problems))

    def test_markdown_dirs_config_requires_safe_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / harness.CONFIG
            config_path.parent.mkdir(parents=True)
            original = (ROOT / harness.CONFIG).read_text(encoding="utf-8")
            declaration = 'markdown_dirs = [".repository-docs", ".repository-state/memory"]'
            cases = (
                (original.replace(declaration + "\n", ""), "markdown_dirs"),
                (original.replace(declaration, 'markdown_dirs = "wrong"'), "markdown_dirs"),
                (original.replace(declaration, 'markdown_dirs = [1]'), "markdown_dirs"),
                (original.replace(declaration, 'markdown_dirs = ["ok", ""]'), "markdown_dirs"),
                (original.replace(declaration, 'markdown_dirs = ["   "]'), "markdown_dirs"),
                (original.replace(declaration, 'markdown_dirs = ["/absolute"]'), "相対パス"),
                (original.replace(declaration, 'markdown_dirs = ["../outside"]'), "リポジトリ外"),
                (original.replace(declaration, 'markdown_dirs = ["."]'), "ルート"),
                (original.replace(declaration, 'markdown_dirs = ["a/.."]'), "ルート"),
            )
            for content, message in cases:
                with self.subTest(message=message, content=content):
                    config_path.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(harness.HarnessError, message):
                        harness.load_config(root)
            config_path.write_text(original.replace(declaration, 'markdown_dirs = []'), encoding="utf-8")
            self.assertEqual([], harness.load_config(root)["structure"]["markdown_dirs"])

    def test_markdown_dirs_require_existing_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (root / "file.md").write_text("# File\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": ["missing", "file.md"], "required_files": ["AGENTS.md"], "skills": []}}
            problems = harness.validate_structure(root, config)
            self.assertEqual(2, sum("Markdown 走査先ディレクトリ" in item for item in problems))

    def test_markdown_dirs_scan_configured_depth_and_skip_unlisted_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            for relative in ("custom/deep/guide.md", "unlisted/guide.md"):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_text("[missing](missing.md)\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": ["custom"], "required_files": ["AGENTS.md"], "skills": []}}
            problems = harness.validate_structure(root, config)
            self.assertEqual(1, len(problems))
            self.assertIn("custom/deep/guide.md", problems[0])

    def test_empty_markdown_dirs_still_check_required_markdown_and_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = root / "AGENTS.md"
            required.write_text("[missing](missing.md)\n", encoding="utf-8")
            skill = root / ".agents/skills/example/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: example\ndescription: Example\n---\n[missing](missing.md)\n", encoding="utf-8")
            # Isolate link validation from agent registration in this synthetic repository.
            config = {"structure": {"markdown_dirs": [], "required_files": ["AGENTS.md"], "skills": ["example"]}}
            with mock.patch.object(harness, "validate_agents", return_value=[]):
                problems = harness.validate_structure(root, config)
            self.assertEqual(2, len(problems))
            self.assertTrue(any("AGENTS.md" in item for item in problems))
            self.assertTrue(any("SKILL.md" in item for item in problems))

    def test_overlapping_markdown_dirs_and_required_files_report_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "docs/nested/guide.md"
            document.parent.mkdir(parents=True)
            document.write_text("[missing](missing.md)\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": ["docs", "docs/nested", "docs"], "required_files": ["docs/nested/guide.md"], "skills": []}}
            problems = harness.validate_structure(root, config)
            self.assertEqual(1, len(problems))
            self.assertIn("guide.md", problems[0])

    def test_configured_directory_and_skill_overlap_reports_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / ".agents/skills/example/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: example\ndescription: Example\n---\n[missing](missing.md)\n", encoding="utf-8")
            config = {"structure": {"markdown_dirs": [".agents"], "required_files": [], "skills": ["example"]}}
            with mock.patch.object(harness, "validate_agents", return_value=[]):
                problems = harness.validate_structure(root, config)
            self.assertEqual(1, len(problems))
            self.assertIn("SKILL.md", problems[0])

    def test_exclude_paths_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / ".harness/config/harness.toml"
            config_path.parent.mkdir(parents=True)
            original = (ROOT / harness.CONFIG).read_text(encoding="utf-8")
            for value in ('["../outside"]', '["/absolute"]', '[""]', '"wrong"', '["."]', '["a/.."]'):
                with self.subTest(value=value):
                    config_path.write_text(replace_exclude_paths(original, value), encoding="utf-8")
                    with self.assertRaises(harness.HarnessError):
                        harness.load_config(root)

    def test_exclude_paths_are_normalized_for_search_and_show(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / harness.CONFIG
            config_path.parent.mkdir(parents=True)
            original = (ROOT / harness.CONFIG).read_text(encoding="utf-8")
            for value in ("./.repository-state/skills", "other/../.repository-state/skills"):
                with self.subTest(value=value):
                    config_path.write_text(replace_exclude_paths(original, f'["{value}"]'), encoding="utf-8")
                    search_config = harness.load_config(root)["search"]
                    self.assertEqual([".repository-state/skills"], search_config["exclude_paths"])
                    path = root / ".repository-state/skills/runtime.md"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("needle-template\n", encoding="utf-8")
                    self.assertEqual(([], False), inspect_repo.search(root, search_config, "needle-template"))
                    with self.assertRaisesRegex(harness.HarnessError, "除外"):
                        inspect_repo.show(root, search_config, ".repository-state/skills/runtime.md", 1)

    def test_codex_agent_registration_and_invalid_toml(self) -> None:
        root = HARNESS / "tests/fixtures/agents/valid"
        self.assertEqual([], harness.validate_agents(root, ["investigate"]))
        problems = harness.validate_agents(root, ["investigate"], Path(".codex/invalid.toml"))
        self.assertTrue(any("Codex 設定を読めません" in problem for problem in problems))

    def test_missing_or_invalid_agent_definition_is_reported(self) -> None:
        missing = harness.validate_agents(HARNESS / "tests/fixtures/agents/missing", ["investigate"])
        invalid = harness.validate_agents(HARNESS / "tests/fixtures/agents/invalid", ["investigate"])
        self.assertTrue(any("エージェント定義がありません" in problem for problem in missing))
        self.assertTrue(any("エージェント名" in problem for problem in invalid))
        self.assertTrue(any("developer_instructions" in problem for problem in invalid))


class CheckRunnerTests(unittest.TestCase):
    def test_success_failure_and_timeout_keep_raw_logs(self) -> None:
        checks = {"timeout_seconds": 1, "max_output_chars": 100}
        cases = [
            ("success", "print('done')", True),
            ("failure", "raise SystemExit(7)", False),
            ("timeout", "import time; time.sleep(2)", False),
        ]
        run_dir = HARNESS / ".harness-results"
        run_dir.mkdir(exist_ok=True)
        names = {case: f"{case}-{uuid4().hex}" for case, _, _ in cases}
        log_paths = [run_dir / f"{name}.{stream}.log" for name in names.values() for stream in ("stdout", "stderr")]
        try:
            for name, script, expected in cases:
                log_name = names[name]
                command = {"name": log_name, "argv": ["{python}", "-c", script]}
                with self.subTest(name=name), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(expected, harness.run_command(ROOT, command, checks, run_dir))
                self.assertTrue((run_dir / f"{log_name}.stdout.log").exists())
                self.assertTrue((run_dir / f"{log_name}.stderr.log").exists())
            self.assertIn("時間切れ", (run_dir / f"{names['timeout']}.stderr.log").read_text(encoding="utf-8"))
        finally:
            for path in log_paths:
                path.unlink(missing_ok=True)


class SearchTests(unittest.TestCase):
    CONFIG = {
        "include": ["*.md"],
        "exclude_dirs": [".git"],
        "max_files": 1,
        "max_file_bytes": 1000,
        "context_lines": 1,
        "max_output_chars": 100,
    }

    def test_search_is_bounded_and_show_is_local(self) -> None:
        root = HARNESS / "tests/fixtures/search"
        hits, limited = inspect_repo.search(root, self.CONFIG, "target")
        self.assertEqual([inspect_repo.SearchHit("a.md", 2, 1)], hits)
        self.assertTrue(limited)
        excerpt = inspect_repo.show(root, self.CONFIG, "a.md", 2)
        self.assertIn("1 | first", excerpt)
        self.assertIn("3 | third", excerpt)
        with self.assertRaises(harness.HarnessError):
            inspect_repo.show(root, self.CONFIG, "../outside.md", 1)

    def test_search_and_show_include_repository_and_project_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (".repository-docs/operations/guide.md", "docs/project.md"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("needle-document\n", encoding="utf-8")
            config = {**self.CONFIG, "max_files": 10}
            hits, limited = inspect_repo.search(root, config, "needle-document")
            self.assertFalse(limited)
            self.assertEqual({".repository-docs/operations/guide.md", "docs/project.md"}, {hit.path for hit in hits})
            for relative in (".repository-docs/operations/guide.md", "docs/project.md"):
                with self.subTest(relative=relative):
                    self.assertIn("needle-document", inspect_repo.show(root, config, relative, 1))

    def test_display_limit(self) -> None:
        output = inspect_repo._bounded("x" * 200, 80)
        self.assertLessEqual(len(output), 80)
        self.assertIn("表示上限", output)

    def test_search_and_show_exclude_runtime_but_include_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                ".repository-state/skills/runtime.md",
                ".repository-state/subagent-history/session.md",
                ".repository-state/memory/lessons/knowledge.md",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("needle-template\n", encoding="utf-8")
            config = {**self.CONFIG, "exclude_paths": [".repository-state/skills", ".repository-state/subagent-history"]}
            hits, limited = inspect_repo.search(root, config, "needle-template")
            self.assertFalse(limited)
            self.assertEqual([inspect_repo.SearchHit(".repository-state/memory/lessons/knowledge.md", 1, 1)], hits)
            for relative in (".repository-state/skills/runtime.md", ".repository-state/subagent-history/session.md"):
                with self.subTest(relative=relative), self.assertRaisesRegex(harness.HarnessError, "除外"):
                    inspect_repo.show(root, config, relative, 1)
            self.assertIn("needle-template", inspect_repo.show(root, config, ".repository-state/memory/lessons/knowledge.md", 1))


    def test_cli_output_uses_terminal_encoding_safely(self) -> None:
        config = {"search": self.CONFIG}
        cases = [
            ("ascii", "show", "日本語", 0, "\\u65e5\\u672c\\u8a9e"),
            ("utf-8", "show", "日本語", 0, "日本語"),
            ("ascii", "search", None, 2, "\\u691c\\u7d22\\u30a8\\u30e9\\u30fc"),
        ]
        for encoding, action, result, expected_code, expected_text in cases:
            with self.subTest(encoding=encoding, action=action):
                output = io.BytesIO()
                error = io.BytesIO()
                stdout = io.TextIOWrapper(output, encoding=encoding)
                stderr = io.TextIOWrapper(error, encoding=encoding)
                argv = ["inspect_repo.py", action, "sample"]
                if action == "show":
                    argv.append("1")
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(inspect_repo, "load_config", return_value=config),
                    mock.patch.object(inspect_repo, "show", return_value=result),
                    mock.patch.object(inspect_repo, "search", side_effect=harness.HarnessError("失敗")),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    self.assertEqual(expected_code, inspect_repo.main())
                stdout.flush()
                stderr.flush()
                displayed = (output if expected_code == 0 else error).getvalue().decode(encoding)
                self.assertIn(expected_text, displayed)


if __name__ == "__main__":
    unittest.main()
