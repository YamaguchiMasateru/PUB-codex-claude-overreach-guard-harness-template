"""Codex hook fixtures. Commands are inspected, never executed."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('codex_guard', ROOT / '.codex/hooks/pretool_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class CodexGuardTests(unittest.TestCase):
    def decision(self, command, tool='Bash', cwd=None):
        return guard.decide({'tool_name': tool, 'cwd': cwd or str(ROOT), 'tool_input': {'command': command}})

    def test_shell_writes(self):
        for command in ('rm external/repos/a', 'touch "external/repos/a b"',
                        'echo x > external/repos/out', 'echo x >> external/repos/out',
                        'cp safe external/repos/dest', 'cp -t external/repos safe',
                        'cd external; cd repos; rm victim.txt',
                        'git -C external/repos/x reset --hard',
                        'curl --output external/repos/a https://example.invalid',
                        'git diff --output=external/repos/a',
                        'cat <<EOF > external/repos/out\nhello\nEOF',
                        'Remove-Item external\\repos\\a', 'bash -c "rm external/repos/a"'):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decision(command))

    def test_reads_and_unrelated_writes(self):
        for command in ('cat external/repos/a', 'git -C external/repos/x status',
                        'git -C external/repos/x remote -v', 'cp external/repos/a safe',
                        'touch external/repos-other/a', 'echo "x > external/repos/a"',
                        'echo ok # rm external/repos/a', 'cat <<EOF\nrm external/repos/a\nEOF',
                        'cd external/repos; cd ../..; touch safe'):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command))

    def test_output_and_windows_copy_destinations(self):
        for command in ('git diff --output=external/repos/vendor/out.patch',
                        'git diff --output external/repos/vendor/out.patch',
                        'git -C external/repos/vendor diff --output=out.patch',
                        'git -C external/repos/vendor diff --output out.patch',
                        'git -C external -C repos/vendor diff --output=out.patch',
                        'robocopy safe external/repos/vendor /MIR',
                        'xcopy safe external/repos/vendor /E /Y',
                        'robocopy safe external/repos/vendor *.txt'):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decision(command))
        for command in ('git -C external/repos/vendor status',
                        'robocopy safe output *.txt /MIR', 'xcopy safe output /E /Y',
                        'robocopy external/repos/vendor output *.txt'):
            with self.subTest(command=command):
                self.assertIsNone(self.decision(command))

    def test_quoted_git_output(self):
        for command in ('git diff --output="external/repos/vendor/out.patch"',
                        "git diff --output='external/repos/vendor/out.patch'",
                        'git -C external/repos/vendor diff --output="out.patch"'):
            with self.subTest(command=command):
                self.assertIsNotNone(self.decision(command))

    def test_patch_paths(self):
        for operation in ('Add File', 'Update File', 'Delete File', 'Move to'):
            self.assertIsNotNone(self.decision('*** Begin Patch\n*** '+operation+': external/repos/a\n*** End Patch', 'apply_patch'))
        self.assertIsNone(self.decision('*** Add File: safe', 'apply_patch'))

    def test_cwd_and_windows_paths(self):
        self.assertIsNotNone(self.decision('rm victim.txt', cwd=str(ROOT / 'external/repos')))
        self.assertEqual(guard.normalize('/C/repo/external/../safe'), 'c:/repo/safe')
        with patch.object(guard, 'PROJECT_ROOT', Path('C:/repo')):
            self.assertTrue(guard.shell_write('rm C:\\repo\\external\\repos\\a', 'C:/repo', ('external/repos',)))
            for command in ('git -C C:/repo/external/repos/vendor diff --output out.patch',
                            'robocopy safe C:/repo/external/repos/vendor *.txt /MIR',
                            'xcopy safe C:/repo/external/repos/vendor /E /Y'):
                with self.subTest(command=command):
                    self.assertTrue(guard.shell_write(command, 'C:/repo', ('external/repos',)))

    def test_defaults_and_invalid_settings(self):
        self.assertEqual(guard.load_protected_paths(), ('external/repos',))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rules.json'
            for value in ({}, {'protected_paths': []}, {'protected_paths': ['../bad']}, {'protected_paths': [False]}, {'protected_paths': ['/abs']}):
                path.write_text(json.dumps(value), encoding='utf-8')
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(guard.load_protected_paths(path), ('external/repos',))
                self.assertIn('invalid settings', err.getvalue())

    def test_exception_warns_and_allows(self):
        with patch.object(guard.sys, 'stdin', type('Input', (), {'buffer': io.BytesIO(b'{}')})()), patch.object(guard, 'decide', side_effect=RuntimeError('fixture')), contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(guard.main(), 0)
        self.assertIn('judgment failed, allowing', err.getvalue())
        self.assertEqual(out.getvalue(), '')

    def test_unsupported_input_allows(self):
        for event in ({}, {'tool_name': 'Bash', 'tool_input': {}}, {'tool_name': 'Other', 'tool_input': {'command': 'rm external/repos/a'}}):
            self.assertIsNone(guard.decide(event))
