"""Local behavior checks for the Claude Code subagent history hook."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.claude/hooks/subagent_history.py'
SETTINGS = ROOT / '.claude/settings.json'
RECORDS_PATH = '.repository-state/subagent-history/claude/records'


def find_bash():
    """Return a bash that behaves like the one Claude Code uses (Git Bash on Windows)."""
    if os.name != 'nt':
        return shutil.which('bash')
    git = shutil.which('git')
    candidates = []
    if git:
        base = Path(git).resolve().parent.parent
        candidates += [base / 'bin' / 'bash.exe', base.parent / 'bin' / 'bash.exe']
    candidates.append(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git' / 'bin' / 'bash.exe')
    return next((str(c) for c in candidates if c.is_file()), None)


class ClaudeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.script = self.root / '.claude/hooks/subagent_history.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.records = self.root / RECORDS_PATH

    def invoke(self, *args, payload=None):
        return subprocess.run([sys.executable, '-X', 'utf8', str(self.script), *args], input=payload, capture_output=True)

    def text(self, result):
        return result.stdout.decode('utf-8')

    def test_records_listing_and_bounded_show(self):
        transcript = Path(self.temp.name) / 'history.jsonl'
        transcript.write_text('\ufeff' + 'x' * 30000 + '\n' + 'y' * 30000 + '\nsecond\n', encoding='utf-8')
        payload = json.dumps({'session_id': 's1', 'agent_id': 'a1', 'agent_type': 'review', 'agent_transcript_path': str(transcript),
                              'last_assistant_message': 'SECRET', 'prompt': 'SECRET', 'turn_id': 't'}).encode()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.invoke('subagent-stop', payload=payload), range(4)))
        self.assertTrue(all(json.loads(r.stdout) == {} for r in results))
        files = list(self.records.glob('*.json'))
        self.assertEqual(len(files), 4)
        for f in files:
            body = f.read_text(encoding='utf-8')
            self.assertNotIn('SECRET', body)
            self.assertNotIn('turn_id', json.loads(body))
        self.assertFalse((self.root / '.repository-state/subagent-history/codex/records').exists())
        listing = json.loads(self.text(self.invoke('list', '--session-id', 's1', '--json')))['records']
        self.assertEqual(len(listing), 4)
        self.assertTrue(all(r['transcript_status'] == 'readable' for r in listing))
        self.assertEqual(json.loads(self.text(self.invoke('list', '--session-id', 's2', '--json')))['records'], [])
        rid = listing[0]['record_id']
        shown = self.text(self.invoke('show', '--record-id', rid, '--lines', '1'))
        self.assertLess(len(shown), 21000)
        self.assertIn('上限', shown)
        self.assertIn('second', self.text(self.invoke('show', '--record-id', rid, '--tail', '1')))
        self.assertIn('上限', self.text(self.invoke('show', '--record-id', rid, '--start', '2', '--lines', '1')))
        self.assertEqual(self.invoke('show', '--record-id', '../bad').returncode, 2)
        self.assertEqual(self.invoke('show', '--record-id', str(uuid.uuid4())).returncode, 2)
        transcript.unlink()
        self.assertEqual(json.loads(self.text(self.invoke('list', '--session-id', 's1', '--json')))['records'][0]['transcript_status'], 'missing')

    def test_missing_empty_or_non_string_fields_are_tolerated(self):
        for index, payload in enumerate([
            {'session_id': 's', 'agent_id': 'a'},
            {'session_id': 's', 'agent_id': 'b', 'agent_type': '', 'agent_transcript_path': None},
            {'session_id': 's', 'agent_id': 'c', 'agent_type': 5, 'agent_transcript_path': 7},
        ]):
            result = self.invoke('subagent-stop', payload=json.dumps(payload).encode())
            self.assertEqual((result.returncode, json.loads(result.stdout)), (0, {}), index)
        listing = json.loads(self.text(self.invoke('list', '--session-id', 's', '--json')))['records']
        self.assertEqual(len(listing), 3)
        self.assertTrue(all(r['agent_type'] in (None, '') for r in listing))
        self.assertIn('path-null', self.text(self.invoke('list', '--session-id', 's')))
        self.assertEqual(len(json.loads(self.text(self.invoke('list', '--session-id', 's', '--agent-id', 'b', '--json')))['records']), 1)
        rid = listing[0]['record_id']
        self.assertIn('本文未取得', self.text(self.invoke('show', '--record-id', rid)))

    def test_backslash_windows_transcript_path_is_stored_as_received(self):
        payload = json.dumps({'session_id': 's', 'agent_id': 'a', 'agent_transcript_path': 'C:\\Users\\x\\agent-a.jsonl'}).encode()
        self.invoke('subagent-stop', payload=payload)
        record = json.loads(next(self.records.glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(record['agent_transcript_path'], 'C:\\Users\\x\\agent-a.jsonl')

    def test_unknown_transcript_rows_are_shown_line_by_line(self):
        transcript = Path(self.temp.name) / 't.jsonl'
        transcript.write_text('{"type":"new-kind","x":1}\nnot json\n\n{}\n', encoding='utf-8')
        self.invoke('subagent-stop', payload=json.dumps({'session_id': 's', 'agent_id': 'a', 'agent_transcript_path': str(transcript)}).encode())
        rid = json.loads(self.text(self.invoke('list', '--session-id', 's', '--json')))['records'][0]['record_id']
        shown = self.text(self.invoke('show', '--record-id', rid, '--lines', '4'))
        self.assertIn('1: {"type":"new-kind","x":1}', shown)
        self.assertIn('2: not json', shown)

    def test_failure_and_prompt_quoting(self):
        self.records.parent.mkdir(parents=True)
        self.records.write_text('blocked', encoding='utf-8')
        result = self.invoke('subagent-stop', payload=b'{"session_id":"s"}')
        self.assertEqual(result.returncode, 0)
        self.assertIn('subagent history:', result.stderr.decode())
        self.assertIn('systemMessage', json.loads(result.stdout))
        session = "x'; echo bad"
        payload = b'\xef\xbb\xbf' + json.dumps({'session_id': session}).encode()
        context = json.loads(self.text(self.invoke('user-prompt-submit', payload=payload)))['hookSpecificOutput']['additionalContext']
        self.assertIn(shlex.quote(session), context)
        self.assertIn('uv run --project', context)
        self.assertIn('--locked --no-sync --offline python -X utf8', context)
        self.assertIn('.claude/hooks/subagent_history.py', context)
        self.assertNotIn('PowerShell', context)
        for bad in (b'bad', b'[]', b'{"session_id":""}', b'{}'):
            result = self.invoke('user-prompt-submit', payload=bad)
            self.assertEqual(result.returncode, 0)
            self.assertIn('systemMessage', json.loads(result.stdout))
        self.assertIn('systemMessage', json.loads(self.invoke('subagent-stop', payload=b'bad').stdout))
        self.assertIn('systemMessage', json.loads(self.invoke('subagent-stop', payload=b'null').stdout))

    def test_configured_commands_from_subdir_and_spaced_root(self):
        bash = find_bash()
        if not bash or not shutil.which('uv') or not shutil.which('git'):
            self.skipTest('bash, uv and git required')
        space_root = Path(self.temp.name) / 'repo with space'
        shutil.copytree(self.root, space_root)
        shutil.copy2(ROOT / 'pyproject.toml', space_root / 'pyproject.toml')
        shutil.copy2(ROOT / 'uv.lock', space_root / 'uv.lock')
        subprocess.run(['git', 'init', '-q', str(space_root)], check=True)
        subdir = space_root / 'nested'
        subdir.mkdir()
        hooks = json.loads(SETTINGS.read_text(encoding='utf-8'))['hooks']
        env = {**os.environ, 'UV_CACHE_DIR': str(Path(self.temp.name) / 'uv-cache'), 'PYTHONUTF8': '1'}
        session = 'space'
        for event, payload in [('SubagentStop', {'session_id': session, 'agent_id': 'a', 'agent_type': 'implement', 'last_assistant_message': 'SECRET'}),
                               ('UserPromptSubmit', {'session_id': session, 'prompt': 'SECRET'})]:
            hook = next(h for g in hooks[event] for h in g['hooks'] if 'subagent_history.py' in h['command'])
            self.assertEqual(hook['shell'], 'bash')
            result = subprocess.run([bash, '-c', hook['command']], cwd=subdir, input=json.dumps(payload).encode(), capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            out = json.loads(result.stdout.decode('utf-8'))
            if event == 'UserPromptSubmit':
                self.assertIn(session, out['hookSpecificOutput']['additionalContext'])
            else:
                self.assertEqual(out, {})
        # cwd が別の git リポジトリへ移っても、CLAUDE_PROJECT_DIR のプロジェクトのフックが動く。
        foreign = Path(self.temp.name) / 'foreign repo'
        foreign.mkdir()
        subprocess.run(['git', 'init', '-q', str(foreign)], check=True)
        moved = {**env, 'CLAUDE_PROJECT_DIR': space_root.as_posix()}
        hook = next(h for g in hooks['UserPromptSubmit'] for h in g['hooks'] if 'subagent_history.py' in h['command'])
        result = subprocess.run([bash, '-c', hook['command']], cwd=foreign, input=json.dumps({'session_id': session, 'prompt': 'SECRET'}).encode(), capture_output=True, env=moved)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(session, json.loads(result.stdout.decode('utf-8'))['hookSpecificOutput']['additionalContext'])
        files = list((space_root / RECORDS_PATH).glob('*.json'))
        self.assertEqual(len(files), 1)
        self.assertNotIn('SECRET', files[0].read_text(encoding='utf-8'))
        listed = subprocess.run([sys.executable, '-X', 'utf8', str(space_root / '.claude/hooks/subagent_history.py'), 'list', '--session-id', session, '--json'], capture_output=True)
        self.assertEqual(json.loads(listed.stdout.decode('utf-8'))['records'][0]['agent_type'], 'implement')


if __name__ == '__main__':
    unittest.main()
