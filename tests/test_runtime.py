import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).parents[1] / 'src/runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.id = str(uuid.uuid4())

    def call(self, op):
        return runtime.dispatch({'op': op, 'id': self.id}, {}, self.root)

    def test_missing_is_authoritative_and_cleanup_idempotent(self):
        self.assertEqual(self.call('status'), 'missing')
        self.assertIsNone(self.call('terminate'))
        self.assertIsNone(self.call('terminate'))

    def test_paths_cannot_escape_state_directory(self):
        self.id = '../../etc'
        with self.assertRaises(ValueError):
            self.call('terminate')

    def record(self):
        directory = self.root / self.id
        directory.mkdir()
        (directory / 'record.json').write_text(json.dumps({'pid': 123, 'start': '456', 'slot': {}}))
        return directory

    def test_stopped_is_not_missing(self):
        self.record()
        with patch.object(runtime, 'identity', return_value=None):
            self.assertEqual(self.call('status'), 'stopped')

    def test_cleanup_failure_retains_recoverable_state(self):
        directory = self.record()
        with patch.object(runtime, 'stop', side_effect=RuntimeError('busy')):
            with self.assertRaises(RuntimeError):
                self.call('terminate')
        self.assertTrue((directory / 'record.json').exists())

    def test_cleanup_removes_state_after_confirmed_stop(self):
        directory = self.record()
        with patch.object(runtime, 'stop') as stop:
            self.call('terminate')
            stop.assert_called_once()
        self.assertFalse(directory.exists())

    def test_pid_reuse_is_not_running(self):
        with patch.object(runtime, 'identity', return_value='different'):
            self.assertFalse(runtime.alive({'pid': 123, 'start': '456'}))

    def test_unprepared_image_never_launches_vm(self):
        with patch.object(runtime.os, 'access', return_value=True), patch.dict(runtime.os.environ, {'MAGICMTN_FIRECRACKER_IMAGES': '{}'}), patch.object(runtime.subprocess, 'Popen') as launch:
            with self.assertRaises(KeyError):
                runtime.dispatch({'op': 'create', 'template': 'image:repo@sha256:x'}, {'images': {}}, self.root)
            launch.assert_not_called()

    def ssh(self, script, timeout=.5, limit=32):
        real_popen = subprocess.Popen
        def launch(*args, **kwargs):
            return real_popen([sys.executable, '-c', script], **kwargs)
        record = {'slot': {'ssh_key': '/unused', 'known_hosts': '/unused', 'guest_ip': '127.0.0.1'}}
        with patch.object(runtime.subprocess, 'Popen', side_effect=launch):
            return runtime.ssh(record, ['true'], timeout, limit)

    def test_output_is_bounded_while_draining_both_streams(self):
        result = self.ssh("import sys; print('x'*100000); print('y'*100000, file=sys.stderr)")
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['stdout']) + len(result['stderr']), 32)
        self.assertEqual(result['exit_code'], 0)

    def test_timeout_kills_and_reaps_ssh(self):
        result = self.ssh('import time; time.sleep(10)', timeout=.05)
        self.assertTrue(result['timed_out'])
        self.assertIsNone(result['exit_code'])

    def test_guest_timeout_exit_is_reported(self):
        self.assertTrue(self.ssh('import sys; sys.exit(124)')['timed_out'])


if __name__ == '__main__':
    unittest.main()
