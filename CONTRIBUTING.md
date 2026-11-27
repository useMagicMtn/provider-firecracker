# Contributing

Preserve the sandbox lifecycle and execution contracts documented in the [README](README.md) and [usage guide](USAGE.md).

## Development setup

Use a Rust toolchain supporting edition 2024 and Python 3.11+ for development and packaging. The runtime uses only Python's standard library; there are no Python packages to install. Live VM operations require Linux, KVM, and the host prerequisites in [README.md](README.md). Unit tests can run without Firecracker or KVM, including on macOS.

Local development currently uses the SDK and provider framework from a sibling `magicmtn` checkout:

```text
src/
  magicmtn/
  provider-firecracker/
```

```sh
cp .cargo/config.toml.example .cargo/config.toml
cargo build --locked
```

Adjust the paths in the ignored `.cargo/config.toml` for your checkout layout. The manifest declares versioned SDK dependencies, but the current lockfile resolves them through local patches; use those patches for locked builds. A standalone release build needs compatible SDK crates and a lockfile resolved against its chosen dependency source. Do not silently update dependencies as part of unrelated changes.

## Architecture

- `src/main.rs` starts the persistent JSON RPC service and advertises sandbox capabilities.
- `src/lib.rs` implements `SandboxBackend` and launches Python once per operation. It embeds `src/runtime.py` in the binary, so rebuild after changing Python runtime code.
- `src/runtime.py` manages Firecracker, durable state, allocation locking, and SSH execution.
- `tests/test_runtime.py` checks lifecycle and bounded subprocess behavior with temporary state and fake processes.
- `package.sh` builds the executable and packages its manifest and license.

Provider discovery does not require Linux, Python, configuration, or KVM. VM operations require Linux. The Rust library and executable use the same runtime adapter.

## Lifecycle and execution

Allocation is serialized with `flock`; the lock spans each operation, including command execution. Each VM has a private state directory containing its copied root disk, API socket, console log, and process record. Process start identity and pidfd signals protect cleanup from PID reuse. Termination is idempotent and removes state only after confirmed cleanup; failed cleanup retains records for recovery.

A VM whose process has exited reports `stopped` until terminated. Its slot remains reserved while its record exists. A missing record reports `missing`. Do not delete state to free slots while a VM may still be alive. No automatic VM lifetime expiry is implemented by this adapter.

Commands preserve argument boundaries through shell quoting. Bounded execution accepts 1–30,000 ms and 1–1,048,576 output bytes shared across stdout and stderr. Plain `exec` uses 30 seconds and 16 KiB. The guest `timeout` command bounds remote execution, and the host kills and reaps SSH on its own deadline. SSH failure or timeout can still leave the remote outcome uncertain; inspect before retrying, and do not introduce automatic replay.

## Verification

```sh
cargo fmt --check
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
python3 -m unittest discover -s tests -v
```

The Python suite covers state cleanup, missing/stopped distinctions, PID reuse, path validation, output limits, and subprocess timeouts. These checks do not boot a VM. The Rust discovery integration test checks that image preparation is advertised without host configuration; `cargo test` also checks compilation and doc tests.

For lifecycle, networking, or execution changes, also validate on a prepared Linux/KVM host through the compiled RPC executable: create a VM, check status, execute literal arguments, exercise output and timeout limits, restart the provider and reconnect to saved state, then terminate and confirm the process, state directory, and slot are released. Exercise a real MagicMtn agent session when changing its guest requirements. Report live validation separately from unit checks.

## Packaging and releases

Build on the Linux architecture you intend to distribute:

```sh
./package.sh
magic provider install --file dist/firecracker-0.2.0-linux-x86_64.tar.gz
```

Use the archive matching your version and architecture. Packaging needs Python 3.11+ for `tomllib`. It produces `dist/firecracker-<version>-<os>-<arch>.tar.gz`, containing `provider`, `package.json`, and `LICENSE`. The manifest records protocol version 1 and the executable's SHA-256 checksum. Firecracker, Python, OpenSSH, kernels, root filesystems, keys, and host network configuration remain external prerequisites.

The packaging script can build on macOS for development, but VM operations remain Linux-only. Publish only verified Linux artifacts to the Registry. Before release, check provider discovery, archive contents, the executable checksum, and a live sandbox lifecycle. Use a new version and digest for changed released binaries, retain previous releases for existing session bindings, and preserve the Apache-2.0 license in distributions.
