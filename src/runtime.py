"""One invocation per RPC; durable state and an allocation lock span runner restarts."""
import fcntl
import http.client
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid


def identity(pid):
    try:
        # comm may contain spaces and parentheses.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except FileNotFoundError:
        return None


def alive(record):
    return identity(record['pid']) == record['start']


def stop(record):
    # pidfd avoids signalling a recycled PID between inspection and signalling.
    try:
        fd = os.pidfd_open(record['pid'])
    except ProcessLookupError:
        return
    try:
        if alive(record):
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            if not select.select([fd], [], [], 5)[0]:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
                if not select.select([fd], [], [], 5)[0]:
                    raise RuntimeError('VM did not stop; retain state for cleanup')
    finally:
        os.close(fd)


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(5)
        self.sock.connect(self.host)


def api(path, route, body):
    conn = UnixHTTP(str(path))
    try:
        conn.request('PUT', route, json.dumps(body), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        if response.status != 204:
            raise RuntimeError(f'Firecracker API {route}: {response.status}: {data!r}')
    finally:
        conn.close()


def ssh(record, argv, timeout, limit):
    slot = record['slot']
    command = ['ssh', '-F', '/dev/null', '-i', slot['ssh_key'], '-o', 'IdentitiesOnly=yes',
               '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile=' + slot['known_hosts'],
               '--', slot.get('user', 'root') + '@' + slot['guest_ip'], shlex.join(argv)]
    start = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = bytearray(), bytearray()
    streams = {child.stdout: bytearray(), child.stderr: bytearray()}
    truncated = False
    timed_out = False
    try:
        while (streams or child.poll() is None) and time.monotonic() - start < timeout:
            ready, _, _ = select.select(list(streams), [], [], min(.1, timeout))
            for stream in ready:
                chunk = os.read(stream.fileno(), 4096)
                if not chunk:
                    streams.pop(stream)
                    continue
                target = out if stream == child.stdout else err
                keep = max(0, limit - len(out) - len(err))
                target.extend(chunk[:keep])
                truncated |= len(chunk) > keep
        timed_out = bool(streams) or child.poll() is None
    finally:
        if timed_out:
            child.kill()
        child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    return {'stdout': out.decode(errors='replace'), 'stderr': err.decode(errors='replace'),
            'exit_code': None if timed_out else child.returncode, 'timed_out': timed_out or child.returncode in (124, 137),
            'truncated': truncated, 'elapsed_ms': int((time.monotonic() - start) * 1000)}


def dispatch(request, config, root):
    op = request['op']
    if op == 'create':
        if not os.access('/dev/kvm', os.R_OK | os.W_OK):
            raise RuntimeError('install Firecracker and grant this user access to /dev/kvm first')
        template = request['template'].removeprefix('image:').split('|', 1)[0]
        mapping = json.loads(os.environ.get('MAGICMTN_FIRECRACKER_IMAGES', '{}'))
        image = config['images'][mapping[template]]
        used = {json.loads(p.read_text())['slot']['tap'] for p in root.glob('*/record.json')}
        slot = next((s for s in config['slots'] if s['tap'] not in used), None)
        if slot is None:
            raise RuntimeError('no free prepared network slots; clean up existing sandboxes')
        directory = root / str(uuid.uuid4())
        directory.mkdir(mode=0o700)
        record = None
        try:
            shutil.copyfile(image['rootfs'], directory / 'rootfs.ext4')
            sock = directory / 'api.sock'
            with (directory / 'console.log').open('wb') as log:
                child = subprocess.Popen([config['firecracker'], '--api-sock', str(sock)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            record = {'pid': child.pid, 'start': identity(child.pid), 'slot': slot}
            if record['start'] is None:
                raise RuntimeError('Firecracker exited during launch')
            (directory / 'record.json').write_text(json.dumps(record))
            for _ in range(100):
                if sock.exists():
                    break
                if not alive(record):
                    raise RuntimeError('Firecracker exited during launch')
                time.sleep(.05)
            api(sock, '/machine-config', {'vcpu_count': 2, 'mem_size_mib': 2048})
            api(sock, '/boot-source', {'kernel_image_path': image['kernel'], 'boot_args': slot['boot_args']})
            api(sock, '/drives/rootfs', {'drive_id': 'rootfs', 'path_on_host': str(directory / 'rootfs.ext4'), 'is_root_device': True, 'is_read_only': False})
            api(sock, '/network-interfaces/eth0', {'iface_id': 'eth0', 'host_dev_name': slot['tap'], 'guest_mac': slot['mac']})
            api(sock, '/actions', {'action_type': 'InstanceStart'})
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if not alive(record):
                    raise RuntimeError('VM exited before SSH became ready')
                if ssh(record, ['true'], 5, 1024)['exit_code'] == 0:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('guest SSH did not become ready; check network and known_hosts')
            return {'provider_id': directory.name, 'status': 'running', 'create_time_ms': int(time.time()*1000), 'metadata': {'image': template}}
        except BaseException:
            if record is not None:
                stop(record)
            shutil.rmtree(directory)
            raise
    directory = root / str(uuid.UUID(request['id']))
    path = directory / 'record.json'
    if not path.exists():
        if op == 'status':
            return 'missing'
        if op == 'terminate':
            return None
        raise RuntimeError('sandbox missing')
    record = json.loads(path.read_text())
    if op == 'status':
        return 'running' if alive(record) else 'stopped'
    if op == 'terminate':
        stop(record)
        shutil.rmtree(directory)
        return None
    if op == 'exec':
        if not alive(record):
            raise RuntimeError('sandbox is stopped')
        timeout = request['timeout_ms']
        limit = request['max_output_bytes']
        if not 1 <= timeout <= 30000 or not 1 <= limit <= 1048576:
            raise ValueError('invalid execution limits')
        # Guest timeout also bounds the remote process after an SSH disconnect.
        return ssh(record, ['timeout', '-k', '1', str(timeout/1000), request['command'], *request['args']], timeout/1000 + 1, limit)
    raise ValueError('unknown operation')


def main():
    os.umask(0o077)
    config = json.loads(Path(os.environ['MAGICMTN_FIRECRACKER_CONFIG']).read_text())
    root = Path(config['state_dir'])
    if not root.is_absolute():
        raise ValueError('state_dir must be absolute')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        print(json.dumps(dispatch(json.load(sys.stdin), config, root)))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
