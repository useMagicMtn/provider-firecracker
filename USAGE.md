# Firecracker provider usage

## Host and guest configuration

Set `MAGICMTN_FIRECRACKER_CONFIG` in the provider process environment to the absolute path of a private JSON file, for example:

```json
{
  "firecracker": "/usr/local/bin/firecracker",
  "state_dir": "/home/alice/.local/share/magicmtn/firecracker",
  "images": {"canonical": {
    "kernel": "/home/alice/vms/vmlinux",
    "rootfs": "/home/alice/vms/canonical.ext4",
    "reference": "ghcr.io/usemagicmtn/canonical@sha256:YOUR_CANONICAL_MANIFEST_DIGEST",
    "platform": "linux/amd64"
  }},
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

## Prepare Canonical

Read the Canonical manifests for your installation:

```sh
magic --local images list --format json
```

Set `images.canonical.reference` to the Canonical repository and digest for your Linux host's architecture, joined as `REPOSITORY@DIGEST`. Set `platform` to the corresponding `linux/amd64` or `linux/arm64` value. Use the kernel and ext4 root filesystem you prepared from that Canonical image. Include Python 3, Pi, `/opt/magicmtn/runtime`, and a writable `/computer` directory in the guest, along with SSH and `timeout`.

Export the configuration path before starting MagicMtn:

```sh
export MAGICMTN_FIRECRACKER_CONFIG="$HOME/.config/magicmtn/firecracker.json"
magic server start
```

In another terminal, prepare the default image:

```sh
magic images prepare canonical --provider firecracker
```

Preparation selects the host platform, validates the configured image reference, readable kernel, and ext4 filesystem, and returns the mapping MagicMtn saves for new sandboxes. Preparation reads the existing host configuration; prepare the kernel, root filesystem, SSH keys, and network slots before running it. Keep each prepared kernel and root filesystem unchanged while its image mapping is in use.

## Explicit image mappings

You can also map exact OCI image references to image labels in the provider environment:

```sh
export MAGICMTN_FIRECRACKER_CONFIG=/home/alice/.config/magicmtn/firecracker.json
export MAGICMTN_FIRECRACKER_IMAGES='{"registry.example/sandbox@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef":"canonical"}'
```

MagicMtn sends templates as `image:<OCI reference>|<session UUID>`. The provider looks up the image reference and starts the prepared kernel/rootfs; it does not pull that OCI image or verify the rootfs against its digest. The operator must ensure the prepared filesystem contains the matching workload. Preserve image mappings for sessions and releases still in use.

The guest needs a working SSH server, a shell, and `timeout` with support for `-k`. Include the MagicMtn sandbox agent and all of its dependencies for Pi sessions. Creation waits up to 60 seconds for successful SSH execution of `true`; it does not verify agent readiness or workspace permissions. Validate those separately in a real session.
