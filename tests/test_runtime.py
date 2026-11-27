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




class ImagePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kernel = self.root / 'vmlinux'
        self.kernel.write_bytes(b'prepared-kernel')
        self.rootfs = self.root / 'canonical.ext4'
        self.rootfs.write_bytes(b'\0' * 1080 + b'\x53\xef')
        self.image = {'repository': 'ghcr.io/usemagicmtn/canonical', 'digest': 'sha256:' + 'a' * 64}
        self.reference = self.image['repository'] + '@' + self.image['digest']
        self.config = {'images': {'canonical': {'reference': self.reference,
                       'platform': 'linux/amd64', 'kernel': str(self.kernel), 'rootfs': str(self.rootfs)}}}

    def prepare(self):
        with patch.object(runtime.platform, 'machine', return_value='x86_64'), patch.dict(runtime.os.environ, {'MAGICMTN_FIRECRACKER_IMAGES': '{}'}), patch.object(runtime.subprocess, 'Popen') as launch:
            result = runtime.dispatch({'op': 'prepare_image', 'images': {'linux/amd64': self.image}}, self.config, self.root)
            launch.assert_not_called()
            return result

    def test_preparation_returns_exact_digest_platform_and_launch_mapping(self):
        result = self.prepare()
        self.assertEqual(result['image'], self.image)
        self.assertEqual(result['platform'], 'linux/amd64')
        self.assertEqual(result['artifact'], 'canonical')
        self.assertEqual(json.loads(result['configuration']['MAGICMTN_FIRECRACKER_IMAGES']), {self.reference: 'canonical'})
        self.assertEqual(self.prepare(), result)

    def test_runtime_protocol_prepares_without_starting_a_vm(self):
        architecture = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}[runtime.platform.machine()]
        host_platform = 'linux/' + architecture
        config = dict(self.config, state_dir=str(self.root / 'state'))
        config['images']['canonical']['platform'] = host_platform
        config_file = self.root / 'firecracker.json'
        config_file.write_text(json.dumps(config))
        process = subprocess.run([sys.executable, str(Path(runtime.__file__))],
            input=json.dumps({'op': 'prepare_image', 'images': {host_platform: self.image}}),
            text=True, capture_output=True,
            env=dict(runtime.os.environ, MAGICMTN_FIRECRACKER_CONFIG=str(config_file), MAGICMTN_FIRECRACKER_IMAGES='{}'),
            timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['image'], self.image)
        self.assertEqual(result['platform'], host_platform)
        self.assertEqual(list((self.root / 'state').iterdir()), [self.root / 'state/.lock'])

    def test_existing_explicit_mapping_remains_supported(self):
        del self.config['images']['canonical']['reference']
        mapping = json.dumps({self.reference: 'canonical', 'retained-reference': 'retained'})
        with patch.object(runtime.platform, 'machine', return_value='x86_64'), patch.dict(runtime.os.environ, {'MAGICMTN_FIRECRACKER_IMAGES': mapping}):
            result = runtime.prepare_image({'linux/amd64': self.image}, self.config)
        self.assertEqual(json.loads(result['configuration']['MAGICMTN_FIRECRACKER_IMAGES'])['retained-reference'], 'retained')

    def test_unmapped_image_and_ambiguous_provenance_are_rejected(self):
        self.config['images']['other'] = dict(self.config['images']['canonical'])
        with self.assertRaises(ValueError):
            self.prepare()
        self.config['images'].clear()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_prepared_platform_and_files_are_validated(self):
        definition = self.config['images']['canonical']
        definition['platform'] = 'linux/arm64'
        with self.assertRaises(ValueError):
            self.prepare()
        definition['platform'] = 'linux/amd64'
        definition['kernel'] = 'relative/kernel'
        with self.assertRaises(ValueError):
            self.prepare()
        definition['kernel'] = str(self.kernel)
        self.rootfs.write_bytes(b'not-an-ext4-disk')
        with self.assertRaises(ValueError):
            self.prepare()
        self.rootfs.unlink()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_wrong_digest_and_missing_host_manifest_are_rejected(self):
        self.image['digest'] = 'sha256:' + 'b' * 64
        with self.assertRaises(ValueError):
            self.prepare()
        with patch.object(runtime.platform, 'machine', return_value='aarch64'):
            with self.assertRaises(ValueError):
                runtime.prepare_image({'linux/amd64': self.image}, self.config)

    def test_explicit_mapping_cannot_override_declared_provenance(self):
        self.config['images']['canonical']['reference'] = self.reference + 'different'
        with patch.object(runtime.platform, 'machine', return_value='x86_64'), patch.dict(runtime.os.environ, {'MAGICMTN_FIRECRACKER_IMAGES': json.dumps({self.reference: 'canonical'})}):
            with self.assertRaises(ValueError):
                runtime.prepare_image({'linux/amd64': self.image}, self.config)


if __name__ == '__main__':
    unittest.main()
