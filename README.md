<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/logo-dark.svg">
    <img src=".github/assets/logo-light.svg" alt="MagicMtn logo" width="180" height="180">
  </picture>
</p>

# Firecracker provider for MagicMtn

Run MagicMtn sandboxes in local Linux microVMs with [Firecracker](https://github.com/firecracker-microvm/firecracker).

## Prerequisites

Use a Linux host with a user-installed Firecracker binary, read/write access to `/dev/kvm`, Python 3.9+ with `os.pidfd_open` and `signal.pidfd_send_signal`, and an OpenSSH client.

Prepare a compatible Linux kernel, an ext4 root filesystem with SSH and `timeout`, and one TAP network slot per concurrent VM. For MagicMtn Pi sessions, the guest also needs the MagicMtn sandbox agent and its dependencies. The provider does not install Firecracker, download or convert images, or configure host networking.

## Installation and configuration

Install from the MagicMtn Registry.

```sh
magic provider install firecracker
```

Set these variables in the environment of the process running the provider:

- `MAGICMTN_FIRECRACKER_CONFIG`: absolute path to a private JSON file describing Firecracker, prepared images, and network slots.
- `MAGICMTN_FIRECRACKER_IMAGES`: JSON map from exact OCI image references with digests to prepared image labels in that file.

See [the configuration example](USAGE.md#host-and-guest-configuration) for the file format and guest requirements. Set up the host and images before creating a sandbox. Start a sandbox from an OCI digest mapped in `MAGICMTN_FIRECRACKER_IMAGES`.

```sh
magic sandbox new --provider firecracker --image MAPPED_OCI_DIGEST_REFERENCE
magic sandbox exec SANDBOX_ID -- /bin/echo hello
magic sandbox terminate SANDBOX_ID --yes
```

Substitute your full mapped OCI image reference and the returned sandbox ID.

## Runtime behavior

The provider supports creation, status, termination, and bounded command execution. Each VM receives two vCPUs, 2 GiB of memory, and a private copy of its root disk. Interactive SSH and SCP operations are not advertised by the provider; command execution uses SSH internally.

Firecracker runs directly as the host user without a jailer. This configuration is intended for personal local workloads on a trusted host. Host routing, NAT, DNS, and isolation are operator responsibilities. Review Firecracker's [production host guidance](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md) before choosing a deployment environment.

Execution time and output are bounded, and guest SSH host keys are verified. A timeout does not prove every remote descendant stopped; inspect the guest before retrying work. VM state survives provider restarts, and sandboxes require explicit termination to release their disk and network slot.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development, testing, and packaging.

## License

[Apache License 2.0](LICENSE).
