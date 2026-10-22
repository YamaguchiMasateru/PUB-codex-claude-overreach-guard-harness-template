"""Local behavior checks for the Claude Code PreToolUse guard hook."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / '.claude/hooks/pretool_guard.py'
RULES = ROOT / '.claude/hooks/guard_rules.json'
SETTINGS = ROOT / '.claude/settings.json'
HARNESS_TOML = ROOT / '.harness/config/harness.toml'

spec = importlib.util.spec_from_file_location('pretool_guard', SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


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


def bash_event(command, agent_type='investigate'):
    event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': command}}
    if agent_type:
        event['agent_type'] = agent_type
    return event


def decision(result):
    return None if result is None else result['hookSpecificOutput']['permissionDecision']


REPO = str(ROOT).replace(chr(92), '/')
ALLOWED = [
    'git status', 'git status --short', 'git diff', 'git diff --stat -- .codex', 'git diff HEAD~1 -- a.py',
    'git log --oneline -5', 'git show HEAD:README.md', 'git rev-parse --show-toplevel', 'git ls-files',
    'git grep -n "foo bar" -- "*.py"', 'git branch', 'git branch --list', 'git branch -a', 'git branch --list "feat/*"',
    'git --no-pager log -3', 'ls', 'ls -la .claude', 'cat README.md', 'head -n 20 README.md', 'tail -n 5 README.md',
    'wc -l README.md', 'rg -n "foo" .', 'rg -i foo', 'grep -rn foo .', 'find . -name "*.py"', 'find . -type f -maxdepth 2',
    'pwd', 'echo hello', 'echo "a > b; c && d"', "echo 'a | b $(x)'", 'git diff | head -n 5', 'cat a.md | grep x | wc -l',
    'git diff --stat | rg -c py', 'sort a.txt', 'diff a b',
    'uv run --project %s --locked --no-sync --offline python -X utf8 %s/.harness/scripts/inspect_repo.py search foo' % (REPO, REPO),
    'uv run --project "%s" --locked --no-sync --offline python -X utf8 "%s/.harness/scripts/inspect_repo.py" show README.md 3' % (REPO, REPO),
    'uv run python .harness/scripts/inspect_repo.py search x', 'uv run --project . python -X utf8 .harness/scripts/inspect_repo.py show a.md 1',
    'uv run --project %s --locked --no-sync --offline python -X utf8 %s/.harness/scripts/harness.py validate' % (REPO, REPO),
    'uv run python .harness/scripts/harness.py validate --env claude', 'uv run python .harness/scripts/harness.py validate --env codex',
    'sort -rn a', 'sort -t, -k2,2 a', 'sort --reverse --key=2 a', 'git grep -n -i -e "a b" -- src', 'git grep -c foo', 'git grep --count --line-number foo',
    'git log -p --no-ext-diff --no-textconv -3', 'git diff --stat --name-only', 'cat .env.example', 'tail -n 20 a.log', 'rg --pretty-not-used-name x' if False else 'rg --files',
]
DENIED = [
    'echo hi > x.txt', 'echo hi >> x.txt', 'cat a 2>&1', 'cat < a', 'tee x', 'cat a | tee x', 'sed -i s/a/b/ x', 'sed -n 1p x',
    'ls; rm -rf x', 'ls && rm x', 'ls || rm x', 'ls & rm x', 'ls\nrm x', 'echo $(rm x)', 'echo `rm x`', 'echo "$(rm x)"',
    'echo ${x}', '(ls)', 'ls | sh', 'ls | bash', 'cat list | xargs rm', 'ls |', '| ls', '', '   ', 'echo "unterminated',
    'git push', 'git push origin main', 'git commit -m x', 'git checkout main', 'git reset --hard', 'git add .', 'git stash',
    'git branch -D x', 'git branch newname', 'git branch -m a b', 'git tag v1', 'git -c core.pager=x log', 'git -C x status',
    'git diff --output=x.patch', 'git log --output x', 'git grep -O"sh" foo', 'git show --ext-diff HEAD', 'git config user.name x',
    'git', 'git clean -fd', 'git restore x', 'git merge x', 'git apply x.patch',
    'rm x', 'mv a b', 'cp a b', 'mkdir d', 'touch x', 'curl https://example.com', 'wget x', 'python -c "open(1)"', 'python x.py',
    'node -e 1', 'bash -c ls', 'sh -c ls', 'xargs ls', 'env ls', 'FOO=1 ls', 'GIT_EXTERNAL_DIFF=x git diff', '/bin/ls', './ls',
    'find . -delete', 'find . -exec rm {} +', 'find . -name x -fprint out', 'find . -execdir ls ;', 'sort -o out a', 'sort -ro out a',
    'rg --pre sh foo', 'rg -z foo', 'chmod +x a', 'dd if=a of=b', 'npm install', 'pip install x', 'cd ..', 'source x',
    'uv sync', 'uv run pytest', 'uv run python -c "1"', 'uv run python x.py', 'uv run --with x python .harness/scripts/inspect_repo.py search x',
    'uv run python .harness/scripts/inspect_repo.py', 'uv run python .harness/scripts/inspect_repo.py write x',
    'uv run python .harness/scripts/harness.py check', 'uv run python .harness/scripts/harness.py validate --out x',
    'uv run python other/inspect_repo.py search x', 'uv run python .harness/scripts/inspect_repo.pyc search x',
    "git grep '--open=touch PWNED2;:' hi", 'git grep --open-files-i=echo hi', 'git grep --open hi', 'git grep -e a --open-files-in-pager=sh',
    'sort --out f a', 'sort --outp=f a', 'sort --compress-program=sh a', 'sort --output=f a', 'sort -T /tmp a', 'sort --files0-from=x',
    'git diff --out=x', 'git log --outp x', 'git diff --ext a b', 'git diff --no-index a b', 'git grep --no-index foo', 'git grep -e x -f y',
    'git cat-file --filters HEAD:a', 'git cat-file --textconv HEAD:a', 'git grep -O sh foo',
    'uv run --project /evil --locked --no-sync --offline python -X utf8 /evil/.harness/scripts/inspect_repo.py search foo',
    'uv run python -X dev .harness/scripts/inspect_repo.py search foo', 'uv run python -X utf8 -c 1',
    '/tmp/evil/.harness/scripts/inspect_repo.py search foo', 'uv run python /tmp/evil/.harness/scripts/inspect_repo.py search foo',
    'uv run python ../evil/.harness/scripts/harness.py validate', 'uv run python ./.harness/scripts/harness.py validate',
    'uv run python .harness/scripts/harness.py validate --env ../../etc', 'uv run python .harness/scripts/harness.py validate --env',
    'uv run --frozen python .harness/scripts/inspect_repo.py search x', 'uv run --project .. python .harness/scripts/inspect_repo.py search x',
    'uv run python .harness/scripts/inspect_repo.py search --help', 'uv run python .harness/scripts/inspect_repo.py search a b',
    'uv run python .harness/scripts/inspect_repo.py show a.md x', 'uv run python .harness/scripts/inspect_repo.py show a.md 1 2',
    'cat .env', 'head .env', 'cat .env.local', 'cat sub/.env.production', 'cat "dir with space/.env"', 'git show HEAD:.env', 'git show HEAD:sub/.env.local',
    'cat .env*', 'cat ~/.ssh/id_rsa', 'cat ~/.aws/credentials', 'cat /etc/shadow', 'rg token ~/.ssh', 'cat server.pem',
    'tail -f x', 'tail -F x', 'tail -fn5 x', 'tail --follow x', 'tail --fo x', 'tail --retry x',
    'rg --pr sh x', 'rg --hostname-b x', 'rg --search x',
]


class ReadOnlyRoleTests(unittest.TestCase):
    def test_read_only_bash_allow_list(self):
        for role in guard.READ_ONLY_ROLES:
            for command in ALLOWED:
                with self.subTest(role=role, command=command):
                    self.assertIsNone(guard.decide(bash_event(command, role), []))
            for command in DENIED:
                with self.subTest(role=role, command=command):
                    result = guard.decide(bash_event(command, role), [])
                    self.assertEqual(decision(result), 'deny')
                    self.assertIn('Ask the parent', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_other_roles_and_main_session_are_not_affected(self):
        for agent_type in (None, 'implement', 'verify', 'general-purpose', '', 5):
            for command in ('rm x', 'echo hi > x.txt', 'git push', 'ls; rm x'):
                with self.subTest(agent_type=agent_type, command=command):
                    self.assertIsNone(guard.decide(bash_event(command, agent_type), []))
            event = {'tool_name': 'Write', 'tool_input': {'file_path': 'x'}, 'agent_type': agent_type}
            self.assertIsNone(guard.decide(event, []))
            self.assertIsNone(guard.decide({'tool_name': 'Artifact', 'tool_input': {}, 'agent_type': agent_type}, []))

    def test_write_capable_tools_are_denied_for_read_only_roles(self):
        for tool in guard.READ_ONLY_DENIED_TOOLS:
            with self.subTest(tool=tool):
                result = guard.decide({'tool_name': tool, 'tool_input': {'action': 'publish'}, 'agent_type': 'review'}, [])
                self.assertEqual(decision(result), 'deny')

    def test_artifact_data_allows_only_read_actions(self):
        for action in ('get', 'list', 'query'):
            event = {'tool_name': 'ArtifactData', 'tool_input': {'action': action}, 'agent_type': 'investigate'}
            self.assertIsNone(guard.decide(event, []), action)
        for tool_input in ({'action': 'set'}, {'action': 'update'}, {'action': 'delete'}, {'action': 'batch'}, {}, {'action': 5}, 'x', None):
            event = {'tool_name': 'ArtifactData', 'tool_input': tool_input, 'agent_type': 'investigate'}
            self.assertEqual(decision(guard.decide(event, [])), 'deny', tool_input)

    def test_read_only_check_fails_closed_on_error_and_odd_input(self):
        for tool_input in (None, 'ls', {}, {'command': None}, {'command': 5}, {'command': ['ls']}):
            event = {'tool_name': 'Bash', 'tool_input': tool_input, 'agent_type': 'investigate'}
            self.assertEqual(decision(guard.decide(event, [])), 'deny', tool_input)
        original = guard.read_only_decision
        guard.read_only_decision = lambda event: 1 / 0
        try:
            self.assertEqual(decision(guard.decide(bash_event('ls'), [])), 'deny')
            self.assertIsNone(guard.decide(bash_event('ls', 'implement'), []))
        finally:
            guard.read_only_decision = original

    def test_constants_match_configuration_and_settings(self):
        import tomllib
        config = tomllib.loads(HARNESS_TOML.read_text(encoding='utf-8'))
        self.assertEqual(sorted(guard.READ_ONLY_ROLES), sorted(config['structure']['claude']['read_only_roles']))
        self.assertEqual(set(guard.WATCHED_TOOLS), {'Bash', 'ArtifactData', *guard.READ_ONLY_DENIED_TOOLS})
        settings = json.loads(SETTINGS.read_text(encoding='utf-8'))
        group = settings['hooks']['PreToolUse'][0]
        self.assertEqual(set(group['matcher'].split('|')), set(guard.WATCHED_TOOLS))


class RuleTests(unittest.TestCase):
    def rule(self, **kwargs):
        return {'pattern': ['git', 'push'], 'decision': 'prompt', 'justification': 'check', **kwargs}

    def test_prompt_and_forbidden_rules_apply_to_every_role(self):
        rules = [self.rule(), self.rule(pattern=['git', 'push', 'origin', 'release'], decision='forbidden', justification='no release')]
        for agent_type in (None, 'implement', 'verify'):
            self.assertEqual(decision(guard.decide(bash_event('git push origin main', agent_type), rules)), 'ask')
            result = guard.decide(bash_event('git push origin release', agent_type), rules)
            self.assertEqual(decision(result), 'deny')
            self.assertIn('no release', result['hookSpecificOutput']['permissionDecisionReason'])
            self.assertIsNone(guard.decide(bash_event('git status', agent_type), rules))
        self.assertEqual(decision(guard.decide(bash_event('cd x && git push', None), rules)), 'ask')
        self.assertEqual(decision(guard.decide(bash_event('FOO=1 git push', None), rules)), 'ask')
        self.assertEqual(decision(guard.decide(bash_event('git push origin release; ls', None), rules)), 'deny')

    def test_alternatives_and_non_bash_tools(self):
        rules = [self.rule(pattern=['git', ['push', 'pull']])]
        self.assertEqual(decision(guard.decide(bash_event('git pull', None), rules)), 'ask')
        self.assertIsNone(guard.decide(bash_event('git fetch', None), rules))
        self.assertIsNone(guard.decide({'tool_name': 'Write', 'tool_input': {'command': 'git push'}}, rules))

    def test_shipped_rules_pass_their_own_examples(self):
        data = json.loads(RULES.read_text(encoding='utf-8'))
        self.assertEqual(data['rules'], [])
        examples = data['_examples']
        for rule in examples:
            for example in rule['match']:
                self.assertIsNotNone(guard.match_rules([rule], example), example)
            for example in rule['not_match']:
                self.assertIsNone(guard.match_rules([rule], example), example)
        result = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT), 'check-rules'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_check_rules_reports_mismatch_and_broken_file(self):
        with tempfile.TemporaryDirectory() as temp:
            hooks = Path(temp) / 'hooks'
            hooks.mkdir()
            script = hooks / 'pretool_guard.py'
            shutil.copyfile(SCRIPT, script)
            rules = hooks / 'guard_rules.json'
            rules.write_text(json.dumps({'rules': [self.rule(match=['git status'], not_match=['git push x'])]}), encoding='utf-8')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(script), 'check-rules'], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('git status', result.stderr.decode(errors='replace'))
            self.assertIn('git push x', result.stderr.decode())
            ask = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git push'}}).encode()
            self.assertEqual(decision(json.loads(subprocess.run([sys.executable, '-X', 'utf8', str(script)], input=ask, capture_output=True).stdout)), 'ask')
            for broken in ('{broken', '[]', '{"rules": 5}', '{"rules": [{"pattern": [], "decision": "prompt"}, {"pattern": ["git"], "decision": "allow"}, 5]}'):
                rules.write_text(broken, encoding='utf-8')
                result = subprocess.run([sys.executable, '-X', 'utf8', str(script)], input=ask, capture_output=True)
                self.assertEqual((result.returncode, result.stdout), (0, b''), broken)
                self.assertTrue(result.stderr.decode().startswith('pretool_guard:'), broken)
            rules.unlink()
            result = subprocess.run([sys.executable, '-X', 'utf8', str(script)], input=ask, capture_output=True)
            self.assertEqual((result.returncode, result.stdout), (0, b''))

    def test_broken_rule_does_not_disable_valid_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rules.json'
            path.write_text(json.dumps({'rules': [5, self.rule()]}), encoding='utf-8')
            self.assertEqual(len(guard.load_rules(path)), 1)


class ProtectedPathTests(unittest.TestCase):
    def test_quoted_git_output(self):
        for role in (None, 'implement'):
            for command in ('git diff --output="external/repos/vendor/out.patch"',
                            "git diff --output='external/repos/vendor/out.patch'",
                            'git -C external/repos/vendor diff --output="out.patch"'):
                with self.subTest(role=role, command=command):
                    event = bash_event(command, role)
                    event['cwd'] = str(ROOT)
                    self.assertEqual(decision(guard.decide(event, [])), 'deny')

    def test_output_and_windows_copy_destinations(self):
        for role in (None, 'implement'):
            for command in ('git diff --output=external/repos/vendor/out.patch',
                            'git diff --output external/repos/vendor/out.patch',
                            'git -C external/repos/vendor diff --output=out.patch',
                            'git -C external/repos/vendor diff --output out.patch',
                            'git -C external -C repos/vendor diff --output=out.patch',
                            'robocopy safe external/repos/vendor /MIR',
                            'xcopy safe external/repos/vendor /E /Y',
                            'robocopy safe external/repos/vendor *.txt'):
                with self.subTest(role=role, command=command):
                    event = bash_event(command, role)
                    event['cwd'] = str(ROOT)
                    self.assertEqual(decision(guard.decide(event, [])), 'deny')
            for command in ('git -C external/repos/vendor status',
                            'robocopy safe output *.txt /MIR', 'xcopy safe output /E /Y',
                            'robocopy external/repos/vendor output *.txt'):
                with self.subTest(role=role, command=command):
                    event = bash_event(command, role)
                    event['cwd'] = str(ROOT)
                    self.assertIsNone(guard.decide(event, []))

    def test_operation_cwd_and_sequential_cd(self):
        protected = ROOT / 'external/repos/vendor'
        cases = [
            ('rm victim', protected, 'deny'),
            ('cd external; cd repos; cd vendor; rm victim', ROOT, 'deny'),
            ('cd external/repos/vendor; cd ../../..; rm victim', ROOT, None),
            ('cd ..; rm victim', protected, 'deny'),
            ('echo hi > victim', protected, 'deny'),
            ('git status', protected, None),
            ('git add victim', protected, 'deny'),
            ('rm external/repos/../safe', ROOT, None),
            ('echo "rm external/repos/vendor/victim"', ROOT, None),
            ('echo ok # rm external/repos/vendor/victim', ROOT, None),
            ("cat <<'EOF'\nrm external/repos/vendor/victim\nEOF", ROOT, None),
            ('bash -c "rm victim"', protected, 'deny'),
        ]
        for command, cwd, expected in cases:
            with self.subTest(command=command, cwd=cwd):
                event = bash_event(command, None)
                event['cwd'] = str(cwd)
                self.assertEqual(decision(guard.decide(event, [])), expected)
        self.assertIsNotNone(guard.protected_write_reason(
            'PowerShell', r'Remove-Item C:\fixture\external\repos\vendor\victim',
            ('C:/fixture/external/repos',), cwd='C:/elsewhere'))
        for command in ('git -C C:/fixture/external/repos/vendor diff --output out.patch',
                        'robocopy safe C:/fixture/external/repos/vendor *.txt /MIR',
                        'xcopy safe C:/fixture/external/repos/vendor /E /Y'):
            with self.subTest(command=command):
                self.assertIsNotNone(guard.protected_write_reason(
                    'PowerShell', command, ('C:/fixture/external/repos',), cwd='C:/elsewhere'))

    def test_protected_failure_keeps_read_only_deny_and_rules(self):
        from unittest.mock import patch
        import contextlib
        import io
        rule = {'pattern': ['git', 'push'], 'decision': 'forbidden'}
        with patch.object(guard, 'protected_write_reason', side_effect=RuntimeError('fixture')):
            with contextlib.redirect_stderr(io.StringIO()) as warnings:
                self.assertEqual(decision(guard.decide(bash_event('rm victim'), [])), 'deny')
                self.assertIsNone(guard.decide(bash_event('rm victim', None), []))
                self.assertEqual(decision(guard.decide(bash_event('git push', None), [rule])), 'deny')
            self.assertIn('protected-path check failed', warnings.getvalue())

    def test_project_root_preserves_runtime_short_path_spelling(self):
        from unittest.mock import patch
        project = 'C:/Users/M_YAMA~1/Temp/fixture'
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': project}):
            self.assertIsNotNone(guard.protected_write_reason(
                'Bash', 'touch external/repos/probe', cwd=project))
            self.assertIsNotNone(guard.protected_write_reason(
                'Bash', 'rm victim', cwd=project + '/external/repos/vendor'))
            self.assertIsNone(guard.protected_write_reason(
                'Bash', 'cd ../../..; touch probe', cwd=project + '/external/repos/vendor'))

    def test_invalid_protected_config_uses_default(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'rules.json'
            for payload in ('broken', '[]', '{}', '{"protected_paths":[]}', '{"protected_paths":[5]}'):
                path.write_text(payload, encoding='utf-8')
                self.assertEqual(guard.load_protected_paths(path), ('external/repos',))


class ProcessTests(unittest.TestCase):
    def run_hook(self, payload):
        return subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPT)], input=payload, capture_output=True)

    def test_protected_cwd_through_stdin(self):
        for role in (None, 'implement', 'verify', 'investigate', 'review'):
            event = bash_event('rm victim', role)
            event['cwd'] = str(ROOT / 'external/repos/fixture')
            result = self.run_hook(json.dumps(event).encode('utf-8'))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(decision(json.loads(result.stdout)), 'deny')

    def test_output_contract(self):
        result = self.run_hook(json.dumps(bash_event('echo hi > x.txt')).encode('utf-8'))
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(set(output), {'hookSpecificOutput'})
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'PreToolUse')
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        allowed = self.run_hook(b'\xef\xbb\xbf' + json.dumps(bash_event('git status')).encode('utf-8'))
        self.assertEqual((allowed.returncode, allowed.stdout), (0, b''))

    def test_known_bypass_inputs_are_denied_through_stdin(self):
        bypasses = ["git grep '--open=touch PWNED2;:' hi", 'git grep --open-files-i=echo hi', 'sort --out f a', 'sort --outp=f a',
                    'sort --compress-program=sh a', 'uv run --project /evil python .harness/scripts/inspect_repo.py search x',
                    'uv run python -X dev .harness/scripts/inspect_repo.py search x', '/tmp/evil/.harness/scripts/inspect_repo.py search foo',
                    '../evil/.harness/scripts/harness.py validate', 'uv run python .harness/scripts/harness.py validate --env ../../etc',
                    'cat .env', 'head .env', 'git show HEAD:.env', 'tail -f x', 'git diff --no-index a b']
        for command in bypasses:
            for role in guard.READ_ONLY_ROLES:
                result = self.run_hook(json.dumps(bash_event(command, role)).encode('utf-8'))
                self.assertEqual(result.returncode, 0, command)
                output = json.loads(result.stdout.decode('utf-8'))
                self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny', command)
                self.assertEqual(decision(guard.decide(bash_event(command, role), [])), 'deny', command)

    def test_broken_input_fails_open(self):
        for payload in (b'', b'bad', b'[]', b'null', b'\xff\xfe'):
            result = self.run_hook(payload)
            self.assertEqual((result.returncode, result.stdout), (0, b''), payload)
            self.assertTrue(result.stderr.decode().startswith('pretool_guard:'), payload)

    def test_configured_command_falls_back_when_project_dir_has_no_hook(self):
        bash = find_bash()
        if not bash or not shutil.which('uv') or not shutil.which('git'):
            self.skipTest('bash, uv and git required')
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'repo with space'
            hooks = project / '.claude/hooks'
            hooks.mkdir(parents=True)
            for name in ('pretool_guard.py', 'guard_rules.json'):
                shutil.copy2(ROOT / '.claude/hooks' / name, hooks / name)
            for name in ('pyproject.toml', 'uv.lock'):
                shutil.copy2(ROOT / name, project / name)
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            nested = project / 'nested'
            nested.mkdir()
            hook = json.loads(SETTINGS.read_text(encoding='utf-8'))['hooks']['PreToolUse'][0]['hooks'][0]
            event = bash_event('touch ../external/repos/fixture/probe.txt', 'implement')
            event['cwd'] = str(nested)
            for project_dir in (None, nested, project / 'missing'):
                with self.subTest(project_dir=project_dir):
                    env = {**os.environ, 'UV_CACHE_DIR': str(Path(temp) / 'uv-cache'), 'PYTHONUTF8': '1'}
                    env.pop('CLAUDE_PROJECT_DIR', None)
                    if project_dir is not None:
                        env['CLAUDE_PROJECT_DIR'] = str(project_dir)
                    result = subprocess.run([bash, '-c', hook['command']], cwd=nested,
                                            input=json.dumps(event).encode(), capture_output=True, env=env)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                    self.assertTrue(result.stdout, result.stderr.decode(errors='replace'))
                    self.assertEqual(decision(json.loads(result.stdout)), 'deny')
                    self.assertFalse((project / 'external/repos/fixture/probe.txt').exists())

    def test_configured_command_from_subdir_and_spaced_root(self):
        bash = find_bash()
        if not bash or not shutil.which('uv') or not shutil.which('git'):
            self.skipTest('bash, uv and git required')
        with tempfile.TemporaryDirectory() as temp:
            space_root = Path(temp) / 'repo with space'
            hooks = space_root / '.claude/hooks'
            hooks.mkdir(parents=True)
            for name in ('pretool_guard.py', 'guard_rules.json'):
                shutil.copy2(ROOT / '.claude/hooks' / name, hooks / name)
            shutil.copy2(ROOT / 'pyproject.toml', space_root / 'pyproject.toml')
            shutil.copy2(ROOT / 'uv.lock', space_root / 'uv.lock')
            subprocess.run(['git', 'init', '-q', str(space_root)], check=True)
            subdir = space_root / 'nested'
            subdir.mkdir()
            settings = json.loads(SETTINGS.read_text(encoding='utf-8'))
            group = settings['hooks']['PreToolUse'][0]
            hook = group['hooks'][0]
            self.assertEqual(hook['shell'], 'bash')
            env = {**os.environ, 'UV_CACHE_DIR': str(Path(temp) / 'uv-cache'), 'PYTHONUTF8': '1'}
            for command, agent_type, expected in [('echo hi > x.txt', 'investigate', 'deny'), ('git status', 'review', None),
                                                  ('echo hi > x.txt', 'implement', None)]:
                payload = json.dumps(bash_event(command, agent_type)).encode()
                result = subprocess.run([bash, '-c', hook['command']], cwd=subdir, input=payload, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                stdout = result.stdout.decode('utf-8').strip()
                self.assertEqual(decision(json.loads(stdout)) if stdout else None, expected, command)
            # cwd が別の git リポジトリへ移っても、CLAUDE_PROJECT_DIR のプロジェクトのフックが動く。
            foreign = Path(temp) / 'foreign repo'
            foreign.mkdir()
            subprocess.run(['git', 'init', '-q', str(foreign)], check=True)
            moved = {**env, 'CLAUDE_PROJECT_DIR': space_root.as_posix()}
            payload = json.dumps(bash_event('echo hi > x.txt', 'investigate')).encode()
            result = subprocess.run([bash, '-c', hook['command']], cwd=foreign, input=payload, capture_output=True, env=moved)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual(decision(json.loads(result.stdout.decode('utf-8'))), 'deny')


if __name__ == '__main__':
    unittest.main()
