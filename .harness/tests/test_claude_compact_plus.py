"""Offline behavior tests for the Claude Code compact-plus hook."""
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
SCRIPT = ROOT / '.claude/hooks/compact_plus.py'
KEYS = ('active_plan', 'current_phase', 'tasklist_summary', 'session_decisions',
        'constraints_and_blockers', 'worker_topology', 'skills_invoked',
        'editing_files', 'failed_attempts', 'recovery_notes')


def summary(**changes):
    result = {key: 'Not verified' for key in KEYS}
    result.update(active_plan='Keep the test plan', current_phase='Testing',
                  session_decisions='Use the saved checkpoint')
    result.update(changes)
    return result


def git_bash():
    """Locate Git Bash; on Windows `bash` on PATH may be the WSL launcher."""
    if os.name != 'nt':
        return shutil.which('bash')
    git = shutil.which('git')
    candidates = []
    if git:
        candidates.append(Path(git).resolve().parents[1] / 'bin' / 'bash.exe')
    candidates.append(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe')
    return next((str(path) for path in candidates if path.is_file()), None)


def envelope(value, **extra):
    return json.dumps({'type': 'result', 'is_error': False, 'structured_output': value,
                       'result': json.dumps(value), **extra})


class ClaudeCompactPlusTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.harness/.harness-results').mkdir(parents=True, exist_ok=True)
        self.temp_root = ROOT / '.harness/.harness-results' / ('claude-compact-plus-' + uuid.uuid4().hex)
        self.temp_root.mkdir()
        self.addCleanup(shutil.rmtree, self.temp_root)
        self.root = self.temp_root / 'repo with space'
        self.script = self.root / '.claude/hooks/compact_plus.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        spec = importlib.util.spec_from_file_location('claude_compact_plus_test', self.script)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)
        self.transcript = self.temp_root / 'session.jsonl'
        self.write_lines(self.message('first turn'))
        self.payload = {'session_id': 'session-1', 'transcript_path': str(self.transcript),
                        'cwd': str(self.root), 'hook_event_name': 'PreCompact', 'trigger': 'manual'}
        self.threads = self.root / '.repository-state/compact-plus/claude/threads'
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('COMPACT_PLUS_ACTIVE', None)

    @staticmethod
    def message(text, role='user'):
        return {'type': role, 'timestamp': '2026-01-01T00:00:00Z',
                'message': {'role': role, 'content': [{'type': 'text', 'text': text}]}}

    @staticmethod
    def assistant(total_input, cache_creation=0, cache_read=0):
        return {'type': 'assistant', 'isSidechain': False, 'message': {
            'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}],
            'usage': {'input_tokens': total_input, 'cache_creation_input_tokens': cache_creation,
                      'cache_read_input_tokens': cache_read, 'output_tokens': 5}}}

    def write_lines(self, *lines, append=False, newline=b'\n'):
        data = b''.join(json.dumps(line, ensure_ascii=False).encode('utf-8') + newline for line in lines)
        with self.transcript.open('ab' if append else 'wb') as stream:
            stream.write(data)

    EVENTS = {'pre-compact': 'PreCompact', 'post-compact': 'PostCompact',
              'session-start': 'SessionStart', 'user-prompt-submit': 'UserPromptSubmit'}

    def event(self, name, payload=None, emit=None):
        payload = {**self.payload, 'hook_event_name': self.EVENTS[name]} if payload is None else payload
        return self.hook.dispatch(name, payload, emit=emit)

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

    def test_prompt_carries_trigger_instructions_and_mechanical_skills(self):
        self.write_lines(
            {'type': 'user', 'message': {'role': 'user', 'content': '/compact-plus now'}},
            {'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'text', 'text': '<command-name>/review</command-name> see /c/scripts/x'}]}},
            {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'tool_use', 'name': 'Skill', 'input': {'skill': 'delegate-verify'}}]}},
            append=True)
        args = self.precompact()
        prompt = args.args[0]
        self.assertIn('Skill:delegate-verify', prompt)
        self.assertIn('/compact-plus', prompt)
        self.assertIn('/review', prompt)
        self.assertNotIn('/c/scripts/x"', prompt.split('skills_and_commands')[1].split('new_events')[0])
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact', {**self.payload, 'custom_instructions': 'keep API notes'})
        self.assertIn('keep API notes', backend.call_args.args[0])
        self.assertIn('"trigger": "manual"', backend.call_args.args[0])

    def test_transcript_squash_drops_noise_thinking_and_long_tool_output(self):
        long_output = 'x' * 3000
        self.write_lines(
            {'type': 'api-request-blob', 'hash': 'h', 'message': 'NOISEBLOB'},
            {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
                {'type': 'thinking', 'thinking': 'SECRETTHOUGHT', 'signature': 's'},
                {'type': 'text', 'text': 'visible'}]}},
            {'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': 't', 'content': long_output}]}},
            {'type': 'future-row-kind', 'surprise': True},
            append=True)
        prompt = self.precompact().args[0]
        self.assertIn('visible', prompt)
        self.assertIn('[ToolResult: 3000 chars output]', prompt)
        self.assertNotIn('NOISEBLOB', prompt)
        self.assertNotIn('SECRETTHOUGHT', prompt)
        self.assertNotIn(long_output, prompt)

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
        with mock.patch.object(self.hook, 'run_backend', return_value=summary(extra_key='x')):
            self.event('pre-compact')
        self.assertEqual(self.checkpoint(), before)
        with mock.patch.object(self.hook, 'run_backend', return_value=summary(active_plan=5)):
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
        source = io.TextIOWrapper(io.BytesIO(json.dumps({
            **self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'}).encode()), encoding='utf-8')
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
        output = json.loads(lines[0])
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertFalse(json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))['delivered'])

    def test_checkpoint_is_authoritative_when_state_view_is_tampered(self):
        self.precompact(summary(active_plan='Trusted checkpoint plan'))
        (self.state_dir() / 'state.md').write_text('Forged plan', encoding='utf-8')
        output = self.event('session-start', {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'})
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
        output = self.event('session-start', {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'})
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

    def test_transcript_shrink_falls_back_to_full_read(self):
        self.write_lines(self.message('turn A'), self.message('turn B'), append=True)
        self.precompact()
        self.write_lines(self.message('only turn'))
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact')
        self.assertIn('only turn', backend.call_args.args[0])
        self.assertEqual(self.checkpoint()['offset'], self.transcript.stat().st_size)

    def test_usage_notification_uses_input_side_total_and_context_byte_cap(self):
        self.precompact(summary(active_plan='計画' * 4000))
        os.environ['COMPACT_PLUS_CONTEXT_WINDOW'] = '1000'
        ups = {**self.payload, 'hook_event_name': 'UserPromptSubmit'}
        self.write_lines(self.assistant(100, 100, 499), append=True)  # 699 of 1000
        self.assertEqual(self.event('user-prompt-submit', ups), {})
        self.write_lines(self.assistant(100, 100, 550), append=True)  # 750 of 1000
        seen = []
        output = self.event('user-prompt-submit', ups, emit=seen.append)
        context = output['hookSpecificOutput']['additionalContext']
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        self.assertIn('/compact', context)
        self.assertIn('75%', context)
        self.assertLessEqual(len(context.encode('utf-8')), 8192)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.event('user-prompt-submit', ups, emit=seen.append), {})  # warned once
        recovery = self.event('session-start', {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'})
        self.assertLessEqual(len(recovery['hookSpecificOutput']['additionalContext'].encode('utf-8')), 8192)

    def test_usage_notification_ignores_invalid_stale_and_sidechain_usage(self):
        os.environ['COMPACT_PLUS_CONTEXT_WINDOW'] = '1000'
        ups = {**self.payload, 'hook_event_name': 'UserPromptSubmit'}
        self.precompact()
        os.environ['COMPACT_PLUS_CONTEXT_WINDOW'] = '1000'
        bad = self.assistant(900)
        bad['message']['usage']['input_tokens'] = 'many'
        side = self.assistant(900)
        side['isSidechain'] = True
        self.write_lines(bad, side, {'type': 'assistant', 'message': {'role': 'assistant', 'content': []}},
                         append=True)
        self.assertEqual(self.event('user-prompt-submit', ups), {})
        self.write_lines(self.assistant(900), {'type': 'system', 'subtype': 'compact_boundary'}, append=True)
        self.assertEqual(self.event('user-prompt-submit', ups), {})
        os.environ['COMPACT_PLUS_CLAUDE_WARN_THRESHOLD'] = '10'
        self.write_lines(self.assistant(150), append=True)
        self.assertIn('/compact', self.event('user-prompt-submit', ups)['hookSpecificOutput']['additionalContext'])

    def test_default_context_window_is_two_hundred_thousand(self):
        os.environ.pop('COMPACT_PLUS_CONTEXT_WINDOW', None)
        self.precompact()
        self.write_lines(self.assistant(149999), append=True)
        ups = {**self.payload, 'hook_event_name': 'UserPromptSubmit'}
        self.assertEqual(self.event('user-prompt-submit', ups), {})
        self.write_lines(self.assistant(150000), append=True)
        self.assertIn('75%', self.event('user-prompt-submit', ups)['hookSpecificOutput']['additionalContext'])

    def test_binary_offset_waits_for_complete_crlf_line(self):
        self.write_lines(self.message('日本語'), newline=b'\r\n')
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
        args = self.precompact()
        self.assertEqual(self.checkpoint()['offset'], self.transcript.stat().st_size)
        self.assertIn('unfinished', args.args[0])

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

    def test_untrusted_identity_and_recursion_guard_do_not_touch_state(self):
        sub = self.temp_root / 'agent-real-id.jsonl'
        sub.write_bytes((json.dumps(self.message('sub')) + '\n').encode())
        wrong = {**self.payload, 'agent_id': 'other-id', 'transcript_path': str(sub)}
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()) as backend:
            self.event('pre-compact', wrong)
            self.event('pre-compact', {**self.payload, 'session_id': ''})
            self.event('pre-compact', {**self.payload, 'transcript_path': str(self.temp_root / 'missing.jsonl')})
            self.event('pre-compact', {**self.payload, 'hook_event_name': 'PostCompact'})
        backend.assert_not_called()
        self.assertFalse(self.threads.exists())
        with mock.patch.dict('os.environ', {'COMPACT_PLUS_ACTIVE': '1'}):
            self.assertEqual(self.event('pre-compact'), {})
        self.assertFalse(self.threads.exists())

    def test_parent_and_subagent_do_not_share_state(self):
        sub = self.temp_root / 'agent-sub-1.jsonl'
        sub.write_bytes((json.dumps(self.message('sub')) + '\n').encode())
        with mock.patch.object(self.hook, 'run_backend', return_value=summary()):
            self.event('pre-compact')
            self.event('pre-compact', {**self.payload, 'agent_id': 'sub-1', 'transcript_path': str(sub)})
        self.assertEqual(len(list(self.threads.glob('*/checkpoint.json'))), 2)

    def test_session_start_emit_failure_retries_and_then_delivers_once(self):
        self.precompact()
        payload = {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'}
        proposed = self.event('session-start', payload)
        self.assertEqual(proposed['hookSpecificOutput']['hookEventName'], 'SessionStart')
        def fails(_):
            raise OSError('stdout closed')
        failure = self.event('session-start', payload, emit=fails)
        self.assertIn('systemMessage', failure)
        seen = []
        self.event('session-start', payload, emit=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.event('session-start', payload), {})
        self.assertEqual(self.event('session-start', {**payload, 'source': 'startup'}), {})
        recovery = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))
        self.assertTrue(recovery['delivered'])

    def test_reverse_hook_order_and_postcompact_does_not_rearm_delivery(self):
        self.precompact()
        payload = {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'}
        seen = []
        self.event('session-start', payload, emit=seen.append)
        self.event('post-compact', {**self.payload, 'hook_event_name': 'PostCompact',
                                    'compact_summary': 'ignored by design'})
        self.assertEqual(len(seen), 1)
        ups = {**self.payload, 'hook_event_name': 'UserPromptSubmit'}
        self.assertEqual(self.event('user-prompt-submit', ups), {})
        recovery = json.loads((self.state_dir() / 'recovery.json').read_text(encoding='utf-8'))
        self.assertTrue(recovery['delivered'])

    def test_user_prompt_submit_completes_recovery_after_postcompact(self):
        self.precompact(summary(active_plan='Resume this plan'))
        self.event('post-compact', {**self.payload, 'hook_event_name': 'PostCompact'})
        seen = []
        ups = {**self.payload, 'hook_event_name': 'UserPromptSubmit'}
        output = self.event('user-prompt-submit', ups, emit=seen.append)
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        context = output['hookSpecificOutput']['additionalContext']
        self.assertIn('Resume this plan', context)
        self.assertIn('COMPACTION RECOVERY', context)
        self.assertLessEqual(len(context.encode('utf-8')), 8192)
        self.assertEqual(self.event('user-prompt-submit', ups, emit=seen.append), {})
        self.assertEqual(len(seen), 1)

    def test_recovery_without_fresh_summary_points_to_backup(self):
        with mock.patch.object(self.hook, 'run_backend', return_value=None):
            self.event('pre-compact')
        context = self.event('session-start', {**self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'})[
            'hookSpecificOutput']['additionalContext']
        self.assertIn('stale or unavailable', context)
        self.assertIn(str(self.state_dir() / 'backups'), context)

    def test_backend_uses_safe_claude_cli_flags_and_parses_structured_output(self):
        executable = str(self.root / 'CLI with space/claude.exe')
        def fake_run(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, '2.1.302 (Claude Code)', '')
            self.assertIsInstance(args, list)
            self.assertFalse(kwargs.get('shell', False))
            self.assertEqual(kwargs['env']['COMPACT_PLUS_ACTIVE'], '1')
            self.assertEqual(kwargs['input'], 'history')
            self.assertEqual(kwargs['cwd'], self.root)
            return subprocess.CompletedProcess(args, 0, envelope(summary()), '')
        with mock.patch.object(self.hook, '_parent_claude', return_value=executable), \
             mock.patch.object(self.hook.shutil, 'which', side_effect=AssertionError('PATH consulted')), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=fake_run) as run:
            result = self.hook.run_backend('history', 'haiku', self.root)
        self.assertEqual(result, summary())
        args = run.call_args.args[0]
        self.assertEqual(args[0], executable)
        self.assertEqual(run.call_args_list[0].args[0], [executable, '--version'])
        self.assertEqual(json.loads(args[args.index('--json-schema') + 1]), self.hook.SCHEMA)
        self.assertEqual(args[args.index('--tools') + 1], '')
        self.assertEqual(json.loads(args[args.index('--settings') + 1]), {'disableAllHooks': True})
        self.assertEqual(args[args.index('--model') + 1], 'haiku')
        for flag in ('-p', '--no-session-persistence', '--disable-slash-commands', '--strict-mcp-config'):
            self.assertIn(flag, args)
        self.assertFalse(any('dangerously' in arg or arg == '--bare' for arg in args))
        with mock.patch.object(self.hook, '_parent_claude', return_value=executable), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=fake_run) as run:
            self.hook.run_backend('history', None, self.root)
        self.assertNotIn('--model', run.call_args.args[0])

    def test_backend_accepts_json_text_result_without_structured_output(self):
        def fake_run(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, '2.1.302', '')
            return subprocess.CompletedProcess(args, 0, json.dumps(
                {'is_error': False, 'result': json.dumps(summary())}), '')
        with mock.patch.object(self.hook, '_parent_claude', return_value='claude.exe'), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=fake_run):
            self.assertEqual(self.hook.run_backend('history', None, self.root), summary())

    def test_ancestor_lookup_selects_claude_pid_not_its_parent(self):
        processes = {10: (20, 'python.exe'), 20: (30, 'bash.exe'),
                     30: (40, 'claude.exe'), 40: (0, 'Code.exe')}
        self.assertEqual(self.hook._ancestor_claude_pid(processes, 10), 30)
        self.assertIsNone(self.hook._ancestor_claude_pid({10: (20, 'python.exe'),
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
            return {'/proc/20/exe': '/usr/bin/bash',
                    '/proc/30/exe': '/opt/claude/bin/claude'}[value]
        with mock.patch.object(self.hook.os, 'name', 'posix'), \
             mock.patch.object(self.hook.sys, 'platform', 'linux'), \
             mock.patch.object(self.hook.os, 'getpid', return_value=10), \
             mock.patch.object(self.hook, 'Path', side_effect=fake_path), \
             mock.patch.object(self.hook.os, 'readlink', side_effect=fake_readlink) as readlink:
            self.assertEqual(self.hook._parent_claude(), '/opt/claude/bin/claude')
        self.assertEqual(readlink.call_count, 2)

    def test_macos_parent_lookup_uses_libproc_path(self):
        from pathlib import PurePosixPath
        from types import SimpleNamespace
        paths = {20: b'/usr/bin/uv', 30: b'/Users/me/.local/bin/claude'}
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
            self.assertEqual(self.hook._parent_claude(), paths[30].decode())
        self.assertEqual(run.call_count, 2)

    def test_backend_parent_lookup_and_version_failure_preserves_backup_and_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        self.write_lines(self.message('second turn'), append=True)
        executable = str(self.root / 'CLI with space/claude.exe')
        with mock.patch.object(self.hook, '_parent_claude', side_effect=ValueError('parent missing')), \
             mock.patch.object(self.hook.subprocess, 'run') as run:
            self.assertEqual(self.event('pre-compact'), {})
        run.assert_not_called()
        with mock.patch.object(self.hook, '_parent_claude', return_value=executable), \
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
        def timeout_exec(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, '2.1.302', '')
            raise subprocess.TimeoutExpired(args, 80)
        with mock.patch.object(self.hook, '_parent_claude', return_value='claude.exe'), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=timeout_exec) as run:
            self.assertIsNone(self.hook.run_backend('history', None, self.root))
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(run.call_args_list[1].kwargs['timeout'], 80)
        self.assertEqual((self.state_dir() / 'last-error.json').exists(), True)

    def test_backend_failures_leave_bounded_diagnostic_and_hook_json(self):
        stderr = 'failure detail ' * 1000
        def failed_exec(args, **kwargs):
            if args[1] == '--version':
                return subprocess.CompletedProcess(args, 0, '2.1.302', '')
            return subprocess.CompletedProcess(args, 7, '', stderr)
        with mock.patch.object(self.hook, '_parent_claude', return_value='claude.exe'), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=failed_exec):
            self.assertEqual(self.event('pre-compact'), {})
        state = self.state_dir()
        record = json.loads((state / 'last-error.json').read_text(encoding='utf-8'))
        self.assertEqual((record['stage'], record['exit_code']), ('backend', 7))
        self.assertLessEqual(len(record['stderr']), 8192)
        self.assertNotIn('first turn', json.dumps(record))
        self.assertEqual(len(list((state / 'backups').glob('*.jsonl'))), 1)

    def test_bad_backend_output_and_schema_preserve_checkpoint(self):
        self.precompact()
        before = self.checkpoint()
        self.write_lines(self.message('second turn'), append=True)
        for stdout in ('{bad', json.dumps({'is_error': True, 'result': 'x'}),
                       json.dumps({'is_error': False, 'result': 'not json'}),
                       json.dumps({'is_error': False, 'structured_output': [1]})):
            def invalid_output(args, **kwargs):
                if args[1] == '--version':
                    return subprocess.CompletedProcess(args, 0, '2.1.302', '')
                return subprocess.CompletedProcess(args, 0, stdout, '')
            with self.subTest(stdout=stdout), \
                 mock.patch.object(self.hook, '_parent_claude', return_value='claude.exe'), \
                 mock.patch.object(self.hook.subprocess, 'run', side_effect=invalid_output):
                self.assertEqual(self.event('pre-compact'), {})
            self.assertEqual(self.checkpoint(), before)
            self.assertEqual(json.loads((self.state_dir() / 'last-error.json').read_text(
                encoding='utf-8'))['stage'], 'backend-output')
        with mock.patch.object(self.hook, 'run_backend', return_value={'active_plan': 'short'}):
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(json.loads((self.state_dir() / 'last-error.json').read_text(
            encoding='utf-8'))['stage'], 'summary-schema')
        self.precompact()
        self.assertFalse((self.state_dir() / 'last-error.json').exists())

    def test_unexpected_exception_fails_open(self):
        with mock.patch.object(self.hook, '_pre', side_effect=RuntimeError('boom')):
            result = self.event('pre-compact')
        self.assertIn('RuntimeError', result['systemMessage'])
        self.assertEqual(self.hook.dispatch('pre-compact', 'not a dict'), {})
        self.assertEqual(self.hook.dispatch('unknown', self.payload), {})

    def test_error_write_failure_still_returns_hook_json(self):
        atomic = self.hook._atomic
        def fail_error(path, data):
            if path.name == 'last-error.json':
                raise OSError('diagnostic denied')
            return atomic(path, data)
        with mock.patch.object(self.hook, '_atomic', side_effect=fail_error), \
             mock.patch.object(self.hook, '_parent_claude', return_value='claude.exe'), \
             mock.patch.object(self.hook.subprocess, 'run', side_effect=OSError('claude missing')) as run:
            self.assertEqual(self.event('pre-compact'), {})
        self.assertEqual(run.call_count, 1)
        self.assertFalse((self.state_dir() / 'last-error.json').exists())

    def test_runtime_state_is_ignored_and_script_is_shared(self):
        state = subprocess.run(
            ['git', 'check-ignore', '-q', '.repository-state/compact-plus/claude/threads/x/checkpoint.json'],
            cwd=ROOT)
        self.assertEqual(state.returncode, 0)
        script = subprocess.run(['git', 'check-ignore', '-q', '.claude/hooks/compact_plus.py'], cwd=ROOT)
        self.assertEqual(script.returncode, 1)

    def test_configured_commands_run_in_git_bash_from_spaced_subdirectory(self):
        bash = git_bash()
        if bash is None or shutil.which('uv') is None:
            self.skipTest('Git Bash and uv required')
        for name in ('pyproject.toml', 'uv.lock'):
            shutil.copyfile(ROOT / name, self.root / name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        nested = self.root / 'nested dir'
        nested.mkdir()
        config = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))['hooks']
        environment = {**os.environ, 'UV_PROJECT_ENVIRONMENT': str(ROOT / '.venv')}
        environment.pop('COMPACT_PLUS_ACTIVE', None)
        expected = {'PreCompact': 180, 'PostCompact': 5, 'SessionStart': 5, 'UserPromptSubmit': 5}
        missing = self.temp_root / 'missing-transcript.jsonl'  # launch check only: no state, no backend
        for event, timeout in expected.items():
            hooks = [hook for group in config[event] for hook in group['hooks']
                     if 'compact_plus.py' in hook['command']]
            self.assertEqual(len(hooks), 1, event)
            hook = hooks[0]
            self.assertEqual((hook['shell'], hook['timeout']), ('bash', timeout))
            if event == 'UserPromptSubmit':
                self.assertIn('compact_plus.py', config[event][0]['hooks'][0]['command'])
            payload = {'session_id': 'bash-launch', 'hook_event_name': event, 'source': 'compact',
                       'transcript_path': str(missing)}
            with self.subTest(event=event):
                result = subprocess.run([bash, '-c', hook['command']], cwd=nested,
                                        input=json.dumps(payload).encode(), capture_output=True,
                                        env=environment, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.assertEqual(result.stderr, b'')
                self.assertEqual(json.loads(result.stdout), {})
        self.assertFalse((nested / '.repository-state').exists())

    def test_settings_register_compact_plus_before_history_hook(self):
        hooks = json.loads((ROOT / '.claude/settings.json').read_text(encoding='utf-8'))['hooks']
        commands = [hook['command'] for group in hooks['UserPromptSubmit'] for hook in group['hooks']]
        self.assertLess([i for i, c in enumerate(commands) if 'compact_plus.py' in c][0],
                        [i for i, c in enumerate(commands) if 'subagent_history.py' in c][0])
        self.assertEqual(hooks['SessionStart'][0]['matcher'], 'compact')
        self.assertIn('SubagentStop', hooks)
        self.assertEqual(hooks['PreCompact'][0]['hooks'][0]['statusMessage'], '圧縮前の履歴と状態を保存')

    def test_utf8_output_is_not_escaped(self):
        self.precompact(summary(active_plan='計画 café'))
        source = io.TextIOWrapper(io.BytesIO(json.dumps({
            **self.payload, 'hook_event_name': 'SessionStart', 'source': 'compact'}).encode()), encoding='utf-8')
        target_bytes = io.BytesIO()
        target = io.TextIOWrapper(target_bytes, encoding='utf-8')
        with mock.patch.object(self.hook.sys, 'stdin', source), \
             mock.patch.object(self.hook.sys, 'stdout', target), \
             mock.patch.object(self.hook.sys, 'argv', ['compact_plus.py', 'session-start']):
            self.hook.main()
        self.assertIn('計画 café'.encode('utf-8'), target_bytes.getvalue())


if __name__ == '__main__':
    unittest.main()
