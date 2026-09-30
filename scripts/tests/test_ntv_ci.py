import contextlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('ntv_ci', Path(__file__).resolve().parents[1] / 'ntv-ci.py')
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.repo = self.root / 'repo'
        self.command('git', 'init', '--bare', '-b', 'main', str(self.remote))
        self.command('git', 'clone', str(self.remote), str(self.repo))
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.test')
        for name in (*CI.DATA_PATHS, 'README.md'):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('initial\n')
        self.git('add', '--all')
        self.git('commit', '-m', 'initial')
        self.git('push', '-u', 'origin', 'main')

    def command(self, *args, cwd=None):
        return subprocess.check_output(args, cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()

    def git(self, *args):
        return self.command('git', *args, cwd=self.repo)

    def publish(self, branch='main'):
        with contextlib.chdir(self.repo), contextlib.redirect_stdout(None):
            return CI.publish(branch)

    def test_push_only_generated_paths_and_no_empty_commit(self):
        initial = self.git('rev-parse', 'HEAD')
        self.assertFalse(self.publish())
        self.assertEqual(self.git('rev-parse', 'HEAD'), initial)
        (self.repo / CI.DATA_PATHS[0]).write_text('updated\n')
        (self.repo / 'README.md').write_text('unrelated\n')
        self.assertTrue(self.publish())
        head = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(head, initial)
        self.assertEqual(head, self.command('git', '--git-dir', str(self.remote), 'rev-parse', 'main'))
        self.assertEqual(self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'), CI.DATA_PATHS[0])
        self.assertEqual(self.git('show', 'HEAD:README.md'), 'initial')
        self.assertFalse(self.publish())

    def test_concurrent_default_branch_update_is_not_overwritten(self):
        other = self.root / 'other'
        self.command('git', 'clone', str(self.remote), str(other))
        for key, value in (('user.name', 'Other'), ('user.email', 'other@example.test')):
            self.command('git', 'config', key, value, cwd=other)
        (other / 'README.md').write_text('concurrent change\n')
        self.command('git', 'add', 'README.md', cwd=other)
        self.command('git', 'commit', '-m', 'concurrent', cwd=other)
        self.command('git', 'push', 'origin', 'main', cwd=other)
        remote_head = self.command('git', '--git-dir', str(self.remote), 'rev-parse', 'main')
        local_head = self.git('rev-parse', 'HEAD')
        (self.repo / CI.DATA_PATHS[0]).write_text('updated\n')
        with self.assertRaisesRegex(ValueError, 'advanced'):
            self.publish()
        self.assertEqual(self.git('rev-parse', 'HEAD'), local_head)
        self.assertEqual(self.command('git', '--git-dir', str(self.remote), 'rev-parse', 'main'), remote_head)

    def test_wrong_branch_and_unexpected_staging_are_rejected(self):
        self.git('switch', '-c', 'feature')
        with self.assertRaisesRegex(ValueError, 'Default branch'):
            self.publish()
        self.git('switch', 'main')
        (self.repo / 'README.md').write_text('unrelated\n')
        self.git('add', 'README.md')
        with self.assertRaisesRegex(ValueError, 'staged'):
            self.publish()
