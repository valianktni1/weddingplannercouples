import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'prepare_v140_release.py'
spec = importlib.util.spec_from_file_location('prepare_release', SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = self.root / 'control-centre.env'
        self.env.write_text('PLANNER_CONTROL_CENTRE_KEY=test-only-secret\nMAIL_PASSWORD=test$only\n')
        service = dict(image='control-centre:old', build=dict(context='/saved/old-release', dockerfile='Dockerfile'),
                       env_file=[dict(path=str(self.env), required=True)],
                       environment=dict(APP_URL='https://planner.ivorydigital.uk', VALUE='literal$NOT_ENV'),
                       volumes=[dict(type='bind', source='/mnt/couples', target='/data')],
                       read_only=True, security_opt=['no-new-privileges:true'])
        self.config = dict(name='weddingplannercouples', services=dict(web=copy.deepcopy(service), worker=copy.deepcopy(service)))
        self.config['services']['web']['ports'] = [dict(target=8000, published='30063', protocol='tcp')]
        self.config['services']['worker']['command'] = ['python', '-m', 'app.worker']
        self.config['services']['worker']['depends_on'] = dict(web=dict(condition='service_healthy'))
        self.before = copy.deepcopy(self.config)
        self.rollback = self.root / 'rollback'
        self.rollback.mkdir()

    def prepare(self):
        release.prepare(self.config, self.root / 'new-release', 'planner:new', self.rollback,
                        dict(web='old:web', worker='old:worker'))
        return json.loads((self.rollback / 'next.json').read_text()), json.loads((self.rollback / 'rollback.json').read_text())

    def test_preserves_installation_settings_and_env_references(self):
        new, _ = self.prepare()
        for name, original in self.before['services'].items():
            actual = new['services'][name]
            expected = copy.deepcopy(original)
            expected.update(image='planner:new', pull_policy='never')
            expected['build']['context'] = str(self.root / 'new-release')
            expected['environment']['VALUE'] = 'literal$$NOT_ENV'
            self.assertEqual(actual, expected)
        self.assertEqual(self.config, self.before)
        self.assertNotIn('test-only-secret', (self.rollback / 'next.json').read_text())

    def test_rollback_preserves_separate_images_and_environment_contents(self):
        _, rollback = self.prepare()
        self.env.write_text('changed later')
        for name in ('web', 'worker'):
            service = rollback['services'][name]
            self.assertEqual(service['image'], f'old:{name}')
            saved = Path(service['env_file'][0]['path'])
            self.assertIn('test-only-secret', saved.read_text())
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        for file in ('next.json', 'rollback.json'):
            self.assertEqual((self.rollback / file).stat().st_mode & 0o777, 0o600)

    def test_dollar_literals_in_nested_commands_are_protected(self):
        self.config['services']['worker']['command'] = ['sh', '-c', 'echo $HOME $$PID']
        new, _ = self.prepare()
        self.assertEqual(new['services']['worker']['command'][-1], 'echo $$HOME $$$$PID')

    def test_rejects_extra_services(self):
        self.config['services']['other-app'] = {}
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.rollback / 'next.json').exists())

    def test_rejects_unexpected_dockerfile(self):
        self.config['services']['web']['build']['dockerfile'] = 'other.Dockerfile'
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.rollback / 'next.json').exists())

    def test_missing_required_environment_stops_before_configuration_write(self):
        self.env.unlink()
        with self.assertRaises(FileNotFoundError):
            self.prepare()
        self.assertFalse((self.rollback / 'next.json').exists())

    def test_optional_absent_environment_and_plain_path_form(self):
        self.config['services']['web']['env_file'] = [str(self.env)]
        self.config['services']['worker']['env_file'] = [dict(path='/absent/optional.env', required=False)]
        new, rollback = self.prepare()
        self.assertEqual(new['services']['web']['env_file'], [str(self.env)])
        self.assertEqual(rollback['services']['worker']['env_file'], self.config['services']['worker']['env_file'])
        self.assertEqual(Path(rollback['services']['web']['env_file'][0]).read_text(), self.env.read_text())


class DeploymentSequenceTests(unittest.TestCase):
    def run_deployment(self, fail_stage='', change_code=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = root / 'repo'
        (repo / 'scripts').mkdir(parents=True)
        deploy_script = os.environ.get('PLANNER_DEPLOY_TEST_SCRIPT', 'deploy-v140.sh')
        for name in (deploy_script, 'prepare_v140_release.py'):
            shutil.copy2(SCRIPT.parent / name, repo / 'scripts' / name)
        backup = root / 'backups'
        backup.mkdir()
        restore = root / 'restore'
        script = repo / 'scripts' / deploy_script
        script.write_text(script.read_text().replace('/mnt/apps/weddingplannercouples', str(repo))
                          .replace('/mnt/apps_snaps_progs/weddingplannercouplesbup', str(backup))
                          .replace('/mnt/apps_snaps_progs/weddingplannercouples-restore-test', str(restore)))
        (repo / 'compose.yaml').write_text('{}')
        (repo / 'tracked-code.txt').write_text('original')
        def git(*args):
            subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'fixture')
        envfile = repo / 'control-centre.env'
        envfile.write_text('TEST_KEY=private-fixture-key')
        service = dict(image='old:release', build=dict(context='/old/snapshot', dockerfile='Dockerfile'),
                       env_file=[dict(path=str(envfile), required=True)])
        config = dict(name='weddingplannercouples', services=dict(web=copy.deepcopy(service), worker=copy.deepcopy(service)))
        original = json.dumps(config)
        (repo / 'compose.yaml').write_text(original)
        if change_code:
            (repo / 'tracked-code.txt').write_text('local change')
        binary = root / 'bin'
        binary.mkdir()
        fake = binary / 'docker'
        fake.write_text(r"""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['JOURNAL'], 'a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == 'compose':
    file = pathlib.Path(args[2])
    command = args[3:]
    if command == ['config', '--help']:
        print('--no-env-resolution')
    elif command == ['config', '--no-env-resolution', '--format', 'json']:
        print(file.read_text())
    elif command[:1] == ['ps'] and '-q' in command:
        print(command[-1] + '-container')
    elif command[:1] == ['exec'] and command[-1] == 'backup':
        if os.environ['FAIL_STAGE'] == 'backup':
            sys.exit(5)
        (pathlib.Path(os.environ['BACKUPS']) / 'planner-test.tar.gz').write_bytes(b'test archive')
    elif command[:1] == ['build'] and os.environ['FAIL_STAGE'] == 'build':
        sys.exit(6)
elif args[0] == 'inspect':
    print('true' if 'Running' in args[2] else 'sha256:previous-' + args[-1])
elif args[0] == 'run' and 'scripts/test_restore.py' in args and os.environ['FAIL_STAGE'] == 'restore':
    sys.exit(7)
""")
        fake.chmod(0o700)
        # This test runtime cannot chown; model install's directory/copy behavior.
        installer = binary / 'install'
        installer.write_text(r'''#!/usr/bin/env python3
import pathlib, shutil, sys
args=sys.argv[1:]
if '-d' in args:
    pathlib.Path(args[-1]).mkdir(parents=True, exist_ok=True)
else:
    shutil.copyfile(args[-2], args[-1])
    pathlib.Path(args[-1]).chmod(0o600)
''')
        installer.chmod(0o700)
        journal = root / 'journal'
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'], JOURNAL=str(journal),
                   FAIL_STAGE=fail_stage, BACKUPS=str(backup))
        result = subprocess.run(['bash', str(script)], cwd=repo, env=env, capture_output=True, text=True)
        calls = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
        return result, calls, repo, original, backup

    def test_success_builds_fresh_source_and_preserves_local_files(self):
        result, calls, repo, _, backup = self.run_deployment()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        current = json.loads((repo / 'compose.yaml').read_text())
        context = Path(current['services']['web']['build']['context'])
        self.assertTrue((context / 'tracked-code.txt').exists())
        self.assertFalse((context / 'control-centre.env').exists())
        self.assertEqual(current['services']['web']['env_file'][0]['path'], str(repo / 'control-centre.env'))
        self.assertTrue((repo / 'control-centre.env').exists())
        self.assertEqual(current['services']['web']['image'], current['services']['worker']['image'])
        self.assertIn('--no-build', next(c for c in calls if 'up' in c))
        self.assertEqual(len(list(backup.glob('before-*/rollback.json'))), 1)
        self.assertNotIn('private-fixture-key', result.stdout + result.stderr)

    def test_backup_build_and_restore_failures_do_not_restart_or_replace_compose(self):
        for stage in ('backup', 'build', 'restore'):
            with self.subTest(stage=stage):
                result, calls, repo, original, _ = self.run_deployment(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('1/5 Backing up', result.stdout)
                if stage == 'restore':
                    self.assertIn('3/5 Testing archive', result.stdout)
                    self.assertTrue(any('scripts/test_restore.py' in c for c in calls))
                self.assertEqual((repo / 'compose.yaml').read_text(), original)
                self.assertFalse(any('up' in c for c in calls))

    def test_local_code_edits_stop_before_docker(self):
        result, calls, repo, original, _ = self.run_deployment(change_code=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertEqual((repo / 'compose.yaml').read_text(), original)


if __name__ == '__main__':
    unittest.main()
