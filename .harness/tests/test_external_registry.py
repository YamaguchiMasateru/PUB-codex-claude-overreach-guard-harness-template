"""Local registry validation and Git repository identity regressions."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import contextlib
import io
import os
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_external", ROOT / "external/check_external.py")
external = importlib.util.module_from_spec(spec)
spec.loader.exec_module(external)
sys.path.insert(0, str(ROOT / ".harness/scripts"))
import harness
import inspect_repo


class GitIdentityTests(unittest.TestCase):
    def test_parent_repository_is_not_registered_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
            nested = root / "external/repos/nested"
            nested.mkdir(parents=True)
            item = {"id": "nested", "kind": "git-repo", "path": "external/repos/nested", "access": "read-only"}
            with mock.patch.object(external, "ROOT", root):
                row = external.check_git_repo(item)
            self.assertFalse(row["reachable"])
            registry = {"schema_version": 1, "resources": [item]}
            with mock.patch.object(external, "REGISTRY", root / "registry.json"):
                external.record(registry, [row])
            self.assertNotIn("verified", item)

    def test_healthy_repository_and_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "external/repos/clone"
            repo.parent.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
            worktree = repo.parent / "worktree"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree)], check=True, capture_output=True)
            with mock.patch.object(external, "ROOT", root):
                for name in ("clone", "worktree"):
                    item = {"id": name, "kind": "git-repo", "path": f"external/repos/{name}", "access": "read-only"}
                    self.assertTrue(external.check_git_repo(item)["reachable"])
            if os.name == "nt":
                junction = repo.parent / "junction"
                command = "New-Item -ItemType Junction -Path '" + str(junction).replace("'", "''") + "' -Target '" + str(repo).replace("'", "''") + "' | Out-Null"
                result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True)
                if result.returncode == 0:
                    try:
                        with mock.patch.object(external, "ROOT", root):
                            item = {"id": "junction", "kind": "git-repo", "path": "external/repos/junction", "access": "read-only"}
                            self.assertTrue(external.check_git_repo(item)["reachable"])
                    finally:
                        os.rmdir(junction)
                else:
                    self.fail("Local junction fixture creation failed")


class RegistryTests(unittest.TestCase):
    def registry(self, **changes):
        item = {"id": "sample", "kind": "git-repo", "access": "read-only", "path": "external/repos/sample"}
        item.update(changes)
        return {"schema_version": 1, "resources": [item]}

    def test_empty_and_generic_resource_kinds(self):
        self.assertEqual([], external.validate({"schema_version": 1, "resources": []}))
        for kind in external.KINDS:
            self.assertEqual([], external.validate(self.registry(kind=kind)))

    def test_invalid_shapes_never_raise_or_echo_values(self):
        sentinel = "private-token-value"
        cases = [None, [], {}, {"schema_version": True, "resources": []}, {"schema_version": 2, "resources": []}, {"schema_version": 1, "resources": {}}, {"schema_version": 1, "resources": [None]}, self.registry(kind=[]), self.registry(access={}), self.registry(id=[]), self.registry(env_vars={}), self.registry(env_vars=[sentinel]), self.registry(link=[]), self.registry(link={"kind": "clone"}), self.registry(verified=[]), self.registry(note=1), self.registry(extra=sentinel)]
        for case in cases:
            with self.subTest(case=case):
                errors = external.validate(case)
                self.assertTrue(errors)
                self.assertNotIn(sentinel, str(errors))

    def test_remote_contract(self):
        self.assertEqual([], external.validate(self.registry(remote="https://example.invalid/team/project.git")))
        for remote in ("git@example.invalid:team/repo", "ssh://example.invalid/team/repo", "https://user:private-token-value@example.invalid/team/repo", "https://example.invalid", "https://example.invalid/a?token=secret", "https://example.invalid/a#secret", "https://example.invalid/a?", "https://example.invalid/a#", [], "https://example.invalid:bad/a"):
            self.assertTrue(external.validate(self.registry(remote=remote)))

    def test_paths_are_normalized_and_confined(self):
        registry = self.registry(path="external\\repos\\sample", script_ref="external\\repos\\sample\\run.py")
        self.assertEqual([], external.validate(registry))
        self.assertEqual("external/repos/sample", registry["resources"][0]["path"])
        for path in ("/absolute", "C:\\absolute", "C:relative", "\\\\host\\share", "external/repos/../sample", "external/repos/./../sample", "external/repos", "external/repos-other/sample", "", ".", " "):
            self.assertTrue(external.validate(self.registry(path=path)))
        self.assertTrue(external.validate(self.registry(script_ref="scripts/run.py")))

    def test_duplicate_missing_and_unknown_fields(self):
        registry = self.registry()
        registry["resources"].append(dict(registry["resources"][0]))
        self.assertTrue(external.validate(registry))
        for key in ("id", "kind", "access", "path"):
            registry = self.registry()
            registry["resources"][0].pop(key)
            self.assertTrue(external.validate(registry))
        registry = self.registry()
        registry["unknown"] = True
        self.assertTrue(external.validate(registry))

    def test_note_is_optional_and_record_preserves_it(self):
        for note in (None, "Local interpretation of this resource"):
            registry = self.registry()
            if note is not None:
                registry["resources"][0]["note"] = note
            self.assertEqual([], external.validate(registry))
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "registry.json"
                with mock.patch.object(external, "REGISTRY", target):
                    external.record(registry, [{"id": "sample", "reachable": True, "branch": "main", "commit": "a" * 40}])
                saved = json.loads(target.read_text(encoding="utf-8"))["resources"][0]
                self.assertEqual(note, saved.get("note"))
                self.assertEqual(note is not None, "note" in saved)

    def run_cli(self, contents, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.json"
            registry.write_text(contents, encoding="utf-8")
            with mock.patch.object(external, "REGISTRY", registry), mock.patch.object(sys, "argv", ["check_external", *arguments]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = external.main()
            self.assertEqual(contents, registry.read_text(encoding="utf-8"))
            return result

    def test_cli_exit_codes_and_read_only_default(self):
        self.assertEqual(0, self.run_cli('{"schema_version":1,"resources":[]}', "--json"))
        self.assertEqual(2, self.run_cli("broken private-token-value"))
        self.assertEqual(2, self.run_cli("{}"))
        registry = self.registry(path="external/repos/not-present")
        self.assertEqual(1, self.run_cli(json.dumps(registry)))
        registry = self.registry(kind="splunk", env_vars=["TEST_EXTERNAL_MISSING"])
        registry["resources"][0].pop("path")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(external.subprocess, "run", side_effect=AssertionError("Splunk must not connect")):
            self.assertEqual(0, self.run_cli(json.dumps(registry)))
            self.assertEqual(1, self.run_cli(json.dumps(registry), "--require-env"))


class HarnessIntegrationTests(unittest.TestCase):
    def test_schema_validation_does_not_probe_external_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "external/registry.json"
            registry.parent.mkdir()
            with mock.patch.object(external.subprocess, "run", side_effect=AssertionError("must be schema only")):
                registry.write_text('{"schema_version":1,"resources":[]}', encoding="utf-8")
                self.assertEqual([], harness.validate_external_registry(root))
                registry.write_text('{"schema_version":true,"resources":[]}', encoding="utf-8")
                self.assertTrue(harness.validate_external_registry(root))
                registry.write_text('private-invalid-json', encoding="utf-8")
                self.assertTrue(harness.validate_external_registry(root))

    def test_search_excludes_external_repositories_only(self):
        config = harness.load_config(ROOT)["search"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("external/repos/sample/README.md", "external/README.md"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("external-fixture-needle", encoding="utf-8")
            hits, limited = inspect_repo.search(root, config, "external-fixture-needle")
            self.assertFalse(limited)
            self.assertEqual(["external/README.md"], [hit.path for hit in hits])
            with self.assertRaises(harness.HarnessError):
                inspect_repo.show(root, config, "external/repos/sample/README.md", 1)

    def test_git_ignores_working_copies_but_tracks_registry(self):
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "--stdin", "-z"], input=b"external/repos/sample/file.py\0external/registry.json\0.codex/hooks/pretool_guard.py\0.codex/hooks/guard_rules.json\0", capture_output=True, check=False)
        self.assertEqual(0, result.returncode)
        self.assertEqual(b"external/repos/sample/file.py\0", result.stdout)


if __name__ == "__main__":
    unittest.main()
