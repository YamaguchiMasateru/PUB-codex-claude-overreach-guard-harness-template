"""Local behavior checks for the subagent history hook."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.codex/hooks/subagent_history.py'
HOOKS = ROOT / '.codex/hooks.json'


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.script = self.root / '.codex/hooks/subagent_history.py'
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.records = self.root / '.repository-state/subagent-history/codex/records'

    def invoke(self, *args, payload=None):
        return subprocess.run([sys.executable, str(self.script), *args], input=payload, capture_output=True)

    def test_records_listing_and_bounded_show(self):
        transcript = Path(self.temp.name) / 'history.jsonl'
        transcript.write_text('\ufeff' + 'x' * 30000 + '\n' + 'y' * 30000 + '\nsecond\n', encoding='utf-8')
        payload = json.dumps({'session_id': 's1', 'agent_id': 'a1', 'agent_type': 'review', 'agent_transcript_path': str(transcript), 'last_assistant_message': 'SECRET', 'prompt': 'SECRET'}).encode()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.invoke('subagent-stop', payload=payload), range(4)))
        self.assertTrue(all(json.loads(r.stdout) == {} for r in results))
        files = list(self.records.glob('*.json'))
        self.assertEqual(len(files), 4)
        self.assertFalse((self.root / '.repository-state/subagent-history/records').exists())
        self.assertFalse((self.root / '.repository-state/subagent-history/claude/records').exists())
        self.assertTrue(all('SECRET' not in f.read_text(encoding='utf-8') for f in files))
        listing = json.loads(self.invoke('list', '--session-id', 's1', '--json').stdout)['records']
        self.assertEqual(len(listing), 4)
        self.assertTrue(all(r['transcript_status'] == 'readable' for r in listing))
        self.assertEqual(json.loads(self.invoke('list', '--session-id', 's2', '--json').stdout)['records'], [])
        rid = listing[0]['record_id']
        shown = self.invoke('show', '--record-id', rid, '--lines', '1').stdout.decode()
        self.assertLess(len(shown), 21000)
        self.assertIn('上限', shown)
        self.assertIn('second', self.invoke('show', '--record-id', rid, '--tail', '1').stdout.decode())
        self.assertIn('上限', self.invoke('show', '--record-id', rid, '--start', '2', '--lines', '1').stdout.decode())
        self.assertEqual(self.invoke('show', '--record-id', '../bad').returncode, 2)
        self.assertEqual(self.invoke('show', '--record-id', str(uuid.uuid4())).returncode, 2)
        transcript.unlink()
        self.assertEqual(json.loads(self.invoke('list', '--session-id', 's1', '--json').stdout)['records'][0]['transcript_status'], 'missing')
        null_payload = json.dumps({'session_id': 's1', 'agent_id': 'a2', 'agent_transcript_path': None}).encode()
        self.assertEqual(self.invoke('subagent-stop', payload=null_payload).returncode, 0)
        self.assertIn('path-null', self.invoke('list', '--session-id', 's1').stdout.decode())
        self.assertEqual(len(json.loads(self.invoke('list', '--session-id', 's1', '--agent-id', 'a2', '--json').stdout)['records']), 1)

    def test_failure_and_prompt_quoting(self):
        self.records.parent.mkdir(parents=True)
        self.records.write_text('blocked', encoding='utf-8')
        result = self.invoke('subagent-stop', payload=b'{"session_id":"s"}')
        self.assertEqual(result.returncode, 0)
        self.assertIn('systemMessage', json.loads(result.stdout))
        payload = b'\xef\xbb\xbf' + json.dumps({'session_id': "x'; echo bad"}).encode()
        context = json.loads(self.invoke('user-prompt-submit', payload=payload).stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn("x''; echo bad", context)
        self.assertIn('uv run --project', context)
        self.assertIn('--locked --no-sync --offline python -X utf8', context)
        self.assertIn('systemMessage', json.loads(self.invoke('subagent-stop', payload=b'bad').stdout))

    def test_configured_posix_commands_from_subdir_and_spaced_root(self):
        if os.name != 'posix':
            self.skipTest('POSIX shell required')
        if not shutil.which('uv') or not shutil.which('git'):
            self.skipTest('uv and git required')
        space_root = Path(self.temp.name) / 'repo with space'
        shutil.copytree(self.root, space_root)
        shutil.copy2(ROOT / 'pyproject.toml', space_root / 'pyproject.toml')
        shutil.copy2(ROOT / 'uv.lock', space_root / 'uv.lock')
        subprocess.run(['git', 'init', '-q', str(space_root)], check=True)
        subdir = space_root / 'nested'
        subdir.mkdir()
        hooks = json.loads(HOOKS.read_text(encoding='utf-8'))['hooks']
        for event, payload in [('SubagentStop', b'{"session_id":"space","agent_id":"a"}'), ('UserPromptSubmit', b'{"session_id":"space"}')]:
            command = hooks[event][0]['hooks'][0]['command']
            result = subprocess.run(command, shell=True, cwd=subdir, input=payload, capture_output=True, env={**os.environ, 'UV_CACHE_DIR': str(Path(self.temp.name) / 'uv-cache')})
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn('hookSpecificOutput' if event == 'UserPromptSubmit' else '{}', result.stdout.decode())
        self.assertEqual(len(list((space_root / '.repository-state/subagent-history/codex/records').glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
