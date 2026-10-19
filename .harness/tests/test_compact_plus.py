"""Offline behavior tests for the Codex compact-plus hook."""
import importlib.util
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.codex/hooks/compact_plus.py'
KEYS = ('active_plan', 'current_phase', 'tasklist_summary', 'session_decisions',
        'constraints_and_blockers', 'worker_topology', 'skills_invoked',
        'editing_files', 'failed_attempts', 'recovery_notes')


def summary(**changes):
    result = {key: 'Not verified' for key in KEYS}
    result.update(active_plan='Keep the test plan', current_phase='Testing',
                  session_decisions='Use the saved checkpoint')
    result.update(changes)
    return result


class CompactPlusTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.harness/.harness-results').mkdir(parents=True, exist_ok=True)
        self.temp_root = ROOT / '.harness/.harness-results' / ('compact-plus-' + uuid.uuid4().hex)
        self.temp_root.mkdir()
        self.addCleanup(shutil.rmtree, self.temp_root)
        self.root = self.temp_root / 'repo with space'
        self.script = self.root / '.codex/hooks/compact_plus.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        shutil.copyfile(ROOT / '.codex/hooks/subagent_history.py',
                        self.script.with_name('subagent_history.py'))
        spec = importlib.util.spec_from_file_location('compact_plus_test', self.script)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)
        self.transcript = self.temp_root / 'rollout.jsonl'
        self.write_lines(self.meta('thread-1'), self.message('first turn'))
        self.payload = {'session_id': 'thread-1', 'transcript_path': str(self.transcript)}
        self.threads = self.root / '.repository-state/compact-plus/codex/threads'

    @staticmethod
    def meta(identity):
        return {'type': 'session_meta', 'payload': {'id': identity}}

    @staticmethod
    def message(text):
        return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                'content': [{'type': 'input_text', 'text': text}]}}

    def write_lines(self, *lines, append=False, newline=b'\n'):
        data = b''.join(json.dumps(line, ensure_ascii=False).encode('utf-8') + newline for line in lines)
        with self.transcript.open('ab' if append else 'wb') as stream:
            stream.write(data)

    def event(self, name, payload=None, emit=None):
        return self.hook.dispatch(name, self.payload if payload is None else payload, emit=emit)

    def checkpoint(self):
        files = list(self.threads.glob('*/checkpoint.json'))
        self.assertEqual(len(files), 1, files)
        return json.loads(files[0].read_text(encoding='utf-8'))

    def state_dir(self):
        dirs = list(self.threads.iterdir())
        self.assertEqual(len(dirs), 1, dirs)
        return dirs[0]

    def precompact(self, response=None):
        with mock.patch.object(self.hook, 'run_backend', return_value=response or summary()) as backend:
            self.event('pre-compact')
        self.assertEqual(backend.call_count, 1)
        return backend.call_args

    def test_precompact_saves_recoverable_backup_and_schema_state(self):
        self.precompact(summary(recovery_notes='Recovered café'))
        state = self.state_dir()
        checkpoint = self.checkpoint()
        self.assertEqual(set(checkpoint['summary']), set(KEYS))
        self.assertIn('Recovered café', (state / 'state.md').read_text(encoding='utf-8'))
        backups = list((state / 'backups').glob('*.jsonl'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.transcript.read_bytes())
        self.assertEqual(checkpoint['offset'], len(self.transcript.read_bytes()))
        self.assertTrue(checkpoint['generation'])

    def test_backend_failure_or_invalid_schema_preserves_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        self.write_lines(self.message('second turn'), append=True)
        with mock.patch.object(self.hook, 'run_backend', return_value=None):
            self.event('pre-compact')
        self.assertEqual(self.checkpoint(), before)
        with mock.patch.object(self.hook, 'run_backend', return_value={'active_plan': 'only one field'}):
            self.event('pre-compact')
        self.assertEqual(self.checkpoint(), before)

    def test_malformed_complete_row_keeps_raw_backup_and_old_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        with self.transcript.open('ab') as stream:
            stream.write(b'{broken json}\n')
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact')
        backend.assert_not_called()
        self.assertEqual(self.checkpoint(), before)
        backups = list((self.state_dir() / 'backups').glob('*.jsonl'))
        self.assertTrue(any(path.read_bytes() == self.transcript.read_bytes() for path in backups))

    def test_new_backup_failure_keeps_prior_checkpoint_and_backup(self):
        self.precompact()
        before = self.checkpoint()
        prior_backup = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))['backup']
        self.write_lines(self.message('second turn'), append=True)
        atomic = self.hook._atomic
        def fail_backup(path, data):
            if path.parent.name == 'backups':
                raise OSError('backup write denied')
            return atomic(path, data)
        with mock.patch.object(self.hook, '_atomic', side_effect=fail_backup), \
             mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact')
        backend.assert_not_called()
        self.assertEqual(self.checkpoint(), before)
        recovery = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))
        self.assertEqual(recovery['backup'], prior_backup)
        self.assertFalse(recovery['delivered'])

    def test_main_emits_one_json_when_delivery_commit_fails(self):
        self.precompact()
        source = io.TextIOWrapper(io.BytesIO(json.dumps({**self.payload, 'source': 'compact'}).encode()), encoding='utf-8')
        target_bytes = io.BytesIO()
        target = io.TextIOWrapper(target_bytes, encoding='utf-8')
        atomic = self.hook._atomic
        def fail_recovery(path, data):
            if path.name == 'recovery.json':
                raise OSError('commit denied')
            return atomic(path, data)
        with mock.patch.object(self.hook.sys, 'stdin', source), \
             mock.patch.object(self.hook.sys, 'stdout', target), \
             mock.patch.object(self.hook.sys, 'argv', ['compact_plus.py', 'session-start']), \
             mock.patch.object(self.hook, '_atomic', side_effect=fail_recovery):
            self.assertEqual(self.hook.main(), 0)
        lines = target_bytes.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('hookSpecificOutput', json.loads(lines[0]))
        self.assertFalse(json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))['delivered'])

    def test_checkpoint_is_authoritative_when_state_view_is_tampered(self):
        self.precompact(summary(active_plan='Trusted checkpoint plan'))
        (self.state_dir() / 'state.md').write_text('Forged plan', encoding='utf-8')
        output = self.event('session-start', {**self.payload, 'source': 'compact'})
        context = output['hookSpecificOutput']['additionalContext']
        self.assertIn('Trusted checkpoint plan', context)
        self.assertNotIn('Forged plan', context)

    def test_state_view_write_failure_keeps_checkpoint_recoverable(self):
        original_atomic = self.hook._atomic
        def fail_state(path, data):
            if path.name == 'state.md':
                raise OSError('state view unavailable')
            return original_atomic(path, data)
        with mock.patch.object(self.hook, 'run_backend', return_value=summary(active_plan='Saved in checkpoint')):
            with mock.patch.object(self.hook, '_atomic', side_effect=fail_state):
                self.event('pre-compact')
        self.assertEqual(self.checkpoint()['summary']['active_plan'], 'Saved in checkpoint')
        output = self.event('session-start', {**self.payload, 'source': 'compact'})
        self.assertIn('Saved in checkpoint', output['hookSpecificOutput']['additionalContext'])

    def test_same_size_transcript_replacement_starts_full_refresh(self):
        self.precompact()
        original = self.checkpoint()
        raw = self.transcript.read_bytes()
        self.transcript.write_bytes(raw.replace(b'first turn', b'other turn'))
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact')
        self.assertEqual(backend.call_count, 1)
        self.assertNotEqual(self.checkpoint()['generation'], original['generation'])
        self.assertIn('other turn', backend.call_args.args[0])

    def test_latest_token_count_and_context_byte_cap(self):
        self.precompact(summary(active_plan='計画' * 4000))
        count = lambda last, cumulative: {'type': 'event_msg', 'payload': {
            'type': 'token_count', 'info': {'last_token_usage': {'total_tokens': last},
            'total_token_usage': {'total_tokens': cumulative}, 'model_context_window': 1000}}}
        self.write_lines(count(700, 9000), append=True)
        self.assertEqual(self.event('user-prompt-submit'), {})
        self.write_lines(count(750, 9001), append=True)
        output = self.event('user-prompt-submit')
        self.assertIn('/compact', output['hookSpecificOutput']['additionalContext'])
        self.assertLessEqual(len(output['hookSpecificOutput']['additionalContext'].encode('utf-8')), 8192)
        recovery = self.event('session-start', {**self.payload, 'source': 'compact'})
        self.assertLessEqual(len(recovery['hookSpecificOutput']['additionalContext'].encode('utf-8')), 8192)

    def test_binary_offset_waits_for_complete_crlf_line(self):
        self.write_lines(self.meta('thread-1'), self.message('日本語'), newline=b'\r\n')
        pending = json.dumps(self.message('unfinished')).encode('utf-8')
        with self.transcript.open('ab') as stream:
            stream.write(pending)
        complete_size = self.transcript.stat().st_size - len(pending)
        self.precompact()
        self.assertEqual(self.checkpoint()['offset'], complete_size)
        self.assertEqual(list((self.state_dir() / 'backups').glob('*.jsonl'))[0].stat().st_size,
                         self.transcript.stat().st_size)
        with self.transcript.open('ab') as stream:
            stream.write(b'\r\n')
        self.precompact()
        self.assertEqual(self.checkpoint()['offset'], self.transcript.stat().st_size)

    def test_backup_retention_keeps_latest_twenty(self):
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()):
            for number in range(22):
                self.write_lines(self.message(f'turn {number}'), append=True)
                self.event('pre-compact')
        self.assertEqual(len(list((self.state_dir() / 'backups').glob('*.jsonl'))), 20)
        self.assertEqual(self.checkpoint()['offset'], self.transcript.stat().st_size)

    def test_periodic_full_refresh_keeps_prior_summary_as_input(self):
        with mock.patch.object(self.hook, 'run_backend', return_value=summary(
                session_decisions='Decision from previous period')) as backend:
            for number in range(10):
                self.write_lines(self.message(f'turn {number}'), append=True)
                self.event('pre-compact')
        self.assertEqual(backend.call_count, 10)
        self.assertIn('Decision from previous period', backend.call_args.args[0])

    def test_concurrent_precompact_serializes_and_releases_lock(self):
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()):
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.event('pre-compact'), range(4)))
        self.assertTrue(all(isinstance(result, dict) for result in results))
        self.assertEqual(len(list(self.threads.glob('*/checkpoint.json'))), 1)
        self.write_lines(self.message('after contention'), append=True)
        self.precompact()
        self.assertEqual(self.checkpoint()['offset'], self.transcript.stat().st_size)

    def test_untrusted_identity_and_child_guard_do_not_touch_state(self):
        wrong = {**self.payload, 'agent_id': 'other-thread'}
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact', wrong)
        backend.assert_not_called()
        self.assertFalse(self.threads.exists())
        with mock.patch.dict('os.environ', {'COMPACT_PLUS_CHILD': '1'}):
            self.assertEqual(self.event('pre-compact'), {})
        self.assertFalse(self.threads.exists())

    def test_session_start_emit_failure_retries_and_then_delivers_once(self):
        self.precompact()
        payload = {**self.payload, 'source': 'compact'}
        proposed = self.event('session-start', payload)
        self.assertIn('additionalContext', proposed['hookSpecificOutput'])
        def fails(_):
            raise OSError('stdout closed')
        failure = self.event('session-start', payload, emit=fails)
        self.assertIn('systemMessage', failure)
        seen = []
        self.event('session-start', payload, emit=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.event('session-start', payload), {})
        recovery = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))
        self.assertTrue(recovery['delivered'])

    def test_reverse_hook_order_and_postcompact_does_not_rearm_delivery(self):
        self.precompact()
        payload = {**self.payload, 'source': 'compact'}
        seen = []
        self.event('session-start', payload, emit=seen.append)
        self.event('post-compact')
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.event('user-prompt-submit'), {})
        recovery = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))
        self.assertTrue(recovery['delivered'])

    def test_parent_and_child_do_not_share_state(self):
        child = self.temp_root / 'child.jsonl'
        child.write_bytes((json.dumps(self.meta('child-1')) + '\n').encode())
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()):
            self.event('pre-compact')
            self.event('pre-compact', {'session_id': 'thread-1', 'agent_id': 'child-1',
                                       'transcript_path': str(child)})
        self.assertEqual(len(list(self.threads.glob('*/checkpoint.json'))), 2)
        before = sorted(p.read_bytes() for p in self.threads.glob('*/checkpoint.json'))
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()):
            self.event('pre-compact', {'session_id': 'thread-1', 'agent_id': 'wrong-child',
                                       'transcript_path': str(child)})
        self.assertEqual(sorted(p.read_bytes() for p in self.threads.glob('*/checkpoint.json')), before)

    def test_backend_uses_safe_cli_and_schema_file(self):
        def fake_run(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, 'codex-cli 0.162.0-alpha.17.2', '')
            self.assertIsInstance(args, list)
            self.assertFalse(kwargs.get('shell', False))
            schema_path = Path(args[args.index('--output-schema') + 1])
            self.assertTrue(schema_path.is_file())
            self.assertEqual(json.loads(schema_path.read_text(encoding='utf-8')), self.hook.SCHEMA)
            self.assertEqual(schema_path.parent, self.root)
            self.assertFalse(self.script.with_name('compact_plus_schema.json').exists())
            self.assertFalse(self.script.with_name('compact_plus_prompt.md').exists())
            output = Path(args[args.index('--output-last-message') + 1])
            output.write_text(json.dumps(summary()), encoding='utf-8')
            return subprocess.CompletedProcess(args, 0, '', '')
        with mock.patch.object(self.hook, '_parent_codex', return_value=str(self.root / 'CLI with space/codex.exe')), \
             mock.patch.dict(os.environ, {'CODEX_VERSION': ''}), \
             mock.patch.object(self.hook.shutil, 'which', side_effect=AssertionError('PATH consulted')), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=fake_run) as run:
            result = self.hook.run_backend('history', None, self.root)
        self.assertEqual(result, summary())
        args = run.call_args.args[0]
        self.assertEqual(args[0], str((self.root / 'CLI with space/codex.exe').resolve()))
        self.assertEqual(run.call_args_list[0].args[0], [args[0], '--version'])
        self.assertIn('--output-schema', args)
        self.assertIn('--output-last-message', args)
        self.assertNotIn('--ignore-user-config', args)
        self.assertFalse(any('dangerously-bypass' in arg for arg in args))
        self.assertIn('project_doc_max_bytes=0', ' '.join(args))

    def test_ancestor_lookup_selects_codex_pid_not_its_parent(self):
        processes = {10: (20, 'python.exe'), 20: (30, 'powershell.exe'),
                     30: (40, 'codex.exe'), 40: (0, 'Code.exe')}
        self.assertEqual(self.hook._ancestor_codex_pid(processes, 10), 30)
        self.assertIsNone(self.hook._ancestor_codex_pid({10: (20, 'python.exe'),
                                                         20: (0, 'Code.exe')}, 10))

    def test_linux_parent_lookup_uses_proc_ancestry_and_exe(self):
        from pathlib import PurePosixPath
        from types import SimpleNamespace
        statuses = {'/proc/10/status': 'PPid:\t20\n', '/proc/20/status': 'PPid:\t30\n'}
        def fake_path(value):
            value = str(value)
            return SimpleNamespace(name=PurePosixPath(value).name,
                                   read_text=lambda: statuses[value])
        def fake_readlink(value):
            return {'/proc/20/exe': '/usr/bin/sh',
                    '/proc/30/exe': '/opt/codex/bin/codex'}[value]
        with mock.patch.object(self.hook.os, 'name', 'posix'), \
             mock.patch.object(self.hook.sys, 'platform', 'linux'), \
             mock.patch.object(self.hook.os, 'getpid', return_value=10), \
             mock.patch.object(self.hook, 'Path', side_effect=fake_path), \
             mock.patch.object(self.hook.os, 'readlink', side_effect=fake_readlink) as readlink:
            self.assertEqual(self.hook._parent_codex(), '/opt/codex/bin/codex')
        self.assertEqual(readlink.call_count, 2)

    def test_macos_parent_lookup_uses_libproc_path(self):
        from pathlib import PurePosixPath
        from types import SimpleNamespace
        paths = {20: b'/usr/bin/uv', 30: b'/Applications/Codex.app/Contents/MacOS/codex'}
        def proc_pidpath(pid, buffer, size):
            buffer.value = paths[pid]
            return len(paths[pid])
        libproc = SimpleNamespace(proc_pidpath=mock.Mock(side_effect=proc_pidpath))
        def fake_ps(args, **kwargs):
            self.assertEqual(args[:2], ['ps', '-p'])
            self.assertEqual(kwargs['timeout'], 5)
            return subprocess.CompletedProcess(args, 0, {10: '20\n', 20: '30\n'}[int(args[2])], '')
        with mock.patch.object(self.hook.os, 'name', 'posix'), \
             mock.patch.object(self.hook.sys, 'platform', 'darwin'), \
             mock.patch.object(self.hook.os, 'getpid', return_value=10), \
             mock.patch.object(self.hook, 'Path', side_effect=lambda value: SimpleNamespace(
                 name=PurePosixPath(value).name)), \
             mock.patch.object(self.hook.ctypes, 'CDLL', return_value=libproc), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=fake_ps) as run:
            self.assertEqual(self.hook._parent_codex(), paths[30].decode())
        self.assertEqual(run.call_count, 2)
        self.assertEqual(libproc.proc_pidpath.call_count, 2)
        self.assertEqual(libproc.proc_pidpath.argtypes,
                         [self.hook.ctypes.c_int, self.hook.ctypes.c_void_p,
                          self.hook.ctypes.c_uint32])

    def test_backend_parent_lookup_and_version_failure_preserves_backup_and_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        self.write_lines(self.message('second turn'), append=True)
        executable = str(self.root / 'CLI with space/codex.exe')
        with mock.patch.object(self.hook, '_parent_codex', side_effect=ValueError('parent missing')), \
             mock.patch.object(self.hook.subprocess, 'run') as run:
            self.assertEqual(self.event('pre-compact'), {})
        run.assert_not_called()
        with mock.patch.object(self.hook, '_parent_codex', return_value=executable), \
             mock.patch.object(self.hook.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [executable, '--version'], 1, '', '')) as run:
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [executable, '--version'])
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(json.loads((self.state_dir() / 'last-error.json').read_text(
            encoding='utf-8'))['stage'], 'backend')
        self.assertEqual(len(list((self.state_dir() / 'backups').glob('*.jsonl'))), 3)

    def test_backend_timeout_fails_open(self):
        executable = str(self.root / 'codex.exe')
        def timeout_exec(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, 'codex-cli 0.162.0-alpha.17.2', '')
            raise subprocess.TimeoutExpired(args, 80)
        with mock.patch.object(self.hook, '_parent_codex', return_value=executable), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=timeout_exec) as run:
            self.assertIsNone(self.hook.run_backend('history', None, self.root))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], [str(Path(executable).resolve()), '--version'])
        self.assertEqual(run.call_args_list[1].args[0][1], 'exec')

    def test_backend_failures_leave_bounded_diagnostic_and_hook_json(self):
        stderr = 'failure detail ' * 1000
        def failed_exec(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, 'codex-cli 0.162.0-alpha.17.2', '')
            return subprocess.CompletedProcess(args, 7, '', stderr)
        with mock.patch.object(self.hook, '_parent_codex', return_value=str(self.root / 'codex.exe')), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=failed_exec):
            self.assertEqual(self.event('pre-compact'), {})
        state = self.state_dir()
        record = json.loads((state / 'last-error.json').read_text(encoding='utf-8'))
        self.assertEqual((record['stage'], record['exit_code']), ('backend', 7))
        self.assertLessEqual(len(record['stderr']), 8192)
        self.assertNotIn('first turn', json.dumps(record))
        self.assertEqual(len(list((state / 'backups').glob('*.jsonl'))), 1)
        with mock.patch.object(self.hook, '_parent_codex', return_value=str(self.root / 'codex.exe')), \
             mock.patch.object(self.hook.subprocess, 'run',
                               side_effect=subprocess.TimeoutExpired(['codex', '--version'], 5)) as run:
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1], '--version')
        record = json.loads((state / 'last-error.json').read_text(encoding='utf-8'))
        self.assertEqual(record['type'], 'TimeoutExpired')
        self.assertIn('timed out', record['reason'])

    def test_bad_backend_output_and_schema_preserve_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        self.write_lines(self.message('second turn'), append=True)
        def invalid_output(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, 'codex-cli 0.162.0-alpha.17.2', '')
            Path(args[args.index('--output-last-message') + 1]).write_text('{bad', encoding='utf-8')
            return subprocess.CompletedProcess(args, 0, '', '')
        with mock.patch.object(self.hook, '_parent_codex', return_value=str(self.root / 'codex.exe')), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=invalid_output):
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(json.loads((self.state_dir() / 'last-error.json').read_text(
            encoding='utf-8'))['stage'], 'backend-output')
        with mock.patch.object(self.hook, 'run_backend', return_value={'active_plan': 'short'}):
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(json.loads((self.state_dir() / 'last-error.json').read_text(
            encoding='utf-8'))['stage'], 'summary-schema')
        self.precompact()
        self.assertFalse((self.state_dir() / 'last-error.json').exists())

    def test_error_write_failure_still_returns_hook_json(self):
        atomic = self.hook._atomic
        def fail_error(path, data):
            if path.name == 'last-error.json':
                raise OSError('diagnostic denied')
            return atomic(path, data)
        with mock.patch.object(self.hook, '_atomic', side_effect=fail_error), \
             mock.patch.object(self.hook, '_parent_codex', return_value=str(self.root / 'codex.exe')), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=OSError('codex missing')) as run:
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.state_dir() / 'last-error.json').exists())

    def test_configured_windows_commands_resolve_spaced_git_root(self):
        if os.name != 'nt':
            self.skipTest('Windows command shell required')
        for name in ('pyproject.toml', 'uv.lock'):
            shutil.copyfile(ROOT / name, self.root / name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        nested = self.root / 'nested'
        nested.mkdir()
        config = json.loads((ROOT / '.codex/hooks.json').read_text(encoding='utf-8'))['hooks']
        environment = {**os.environ, 'UV_PROJECT_ENVIRONMENT': str(ROOT / '.venv')}
        for event in ('PreCompact', 'PostCompact', 'SessionStart', 'SubagentStop',
                      'UserPromptSubmit'):
            for hook in config[event][0]['hooks']:
                command = hook['commandWindows']
                with self.subTest(event=event, command=command):
                    result = subprocess.run(
                        ['powershell', '-NoProfile', '-Command', command], cwd=nested,
                        input=b'{"session_id":"synthetic-windows-launch"}',
                        capture_output=True, env=environment, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                    self.assertEqual(result.stderr, b'')
                    output = json.loads(result.stdout)
                    if event == 'UserPromptSubmit' and 'subagent_history.py' in command:
                        self.assertEqual(output['hookSpecificOutput']['hookEventName'], event)
                        self.assertIn('synthetic-windows-launch',
                                      output['hookSpecificOutput']['additionalContext'])
                    else:
                        self.assertEqual(output, {})


if __name__ == '__main__':
    unittest.main()
