# Firecracker provider usage

## Host and guest configuration

Set `MAGICMTN_FIRECRACKER_CONFIG` in the provider process environment to the absolute path of a private JSON file, for example:

```json
{
  "firecracker": "/usr/local/bin/firecracker",
  "state_dir": "/home/alice/.local/share/magicmtn/firecracker",
  "images": {"default-v1": {"kernel": "/home/alice/vms/vmlinux", "rootfs": "/home/alice/vms/default.ext4"}},
  "slots": [{
    "tap": "magic-tap0", "mac": "06:00:00:00:00:01", "guest_ip": "172.16.0.2",
    "ssh_key": "/home/alice/vms/id_ed25519", "known_hosts": "/home/alice/vms/known_hosts",
    "user": "root",
    "boot_args": "console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw ip=172.16.0.2::172.16.0.1:255.255.255.0::eth0:off"
  }]
}
```

Replace these paths and addresses with your prepared host configuration. Keep `state_dir` absolute and short enough for the VM's Unix API socket path. Use a separate state directory per host user and provider configuration; preserve it across runner restarts. Keep configuration, private keys, and VM state out of source control.

Prepare each TAP interface and any outbound routing/NAT on the host before use. Give each slot a distinct TAP interface, MAC address, and guest IP. Configure the guest's network, DNS, SSH authorized keys, and the corresponding trusted host key in `known_hosts`. The provider uses strict host key checking and does not enroll keys automatically. `user` defaults to `root` when omitted.

Map each exact OCI image reference to an image label from the configuration:

```sh
export MAGICMTN_FIRECRACKER_CONFIG=/home/alice/.config/magicmtn/firecracker.json
export MAGICMTN_FIRECRACKER_IMAGES='{"registry.example/sandbox@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef":"default-v1"}'
```

MagicMtn sends templates as `image:<OCI reference>|<session UUID>`. The provider looks up the image reference and starts the prepared kernel/rootfs; it does not pull that OCI image or verify the rootfs against its digest. The operator must ensure the prepared filesystem contains the matching workload. Preserve image mappings for sessions and releases still in use.

The guest needs a working SSH server, a shell, and `timeout` with support for `-k`. Include the MagicMtn sandbox agent and all of its dependencies for Pi sessions. Creation waits up to 60 seconds for successful SSH execution of `true`; it does not verify agent readiness or workspace permissions. Validate those separately in a real session.
