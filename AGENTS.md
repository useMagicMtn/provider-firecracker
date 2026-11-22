# Agent Development Guide

## Coding style

Use the [Google Rust Guide](https://google.github.io/styleguide/rustguide.html). Keep Python changes consistent with the existing standard-library runtime.

## Setup and commands

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, configuration, runtime behavior, and release checks. Locked local builds use a sibling `magicmtn` SDK checkout and `.cargo/config.toml` copied from the checked-in example.

- Build: `cargo build --locked`
- Rust compilation and doc tests: `cargo test --locked`
- Python runtime tests: `python3 -m unittest discover -s tests -v`
- Formatting: `cargo fmt --check` (apply with `cargo fmt`)
- Lint: `cargo clippy --locked --all-targets -- -D warnings`
- Package: `./package.sh`

Run checks relevant to the change. Runtime changes need Rust and Python checks. Unit tests require no Firecracker, KVM, or network setup; report Linux VM integration separately. Do not modify host networking or start VMs as part of routine checks.

## Repository structure

- `src/main.rs`: sandbox RPC entry point and capability advertisement.
- `src/lib.rs`: SDK trait implementation and embedded Python subprocess invocation.
- `src/runtime.py`: Firecracker lifecycle, durable state, allocation lock, and SSH execution. Rebuild Rust after editing this embedded file.
- `tests/test_runtime.py`: lifecycle and bounded subprocess tests.
- `package.sh`: archive and executable checksum manifest generation.
- `README.md`: public overview and installation; `CONTRIBUTING.md`: development and operational details.

## Compatibility and runtime changes

- Preserve creation, status, termination, exec, and bounded exec capabilities. SSH and SCP trait methods are required unsupported-operation implementations, not dead code.
- Keep discovery independent of runtime prerequisites and configuration.
- Preserve durable state layout, UUID path validation, process start identity checks, pidfd signaling, and the allocation lock. Release a slot only after confirmed process cleanup; retain recoverable state on cleanup failure.
- Preserve literal command arguments, strict SSH host key checks, bounded output, guest timeouts, and host SSH cleanup. A timeout leaves the remote outcome uncertain; do not add automatic retries.
- Do not silently change guest users, prepared image mappings, machine resources, or advertised capabilities. Do not add automatic host setup or image downloads.
- Keep `Cargo.lock` stable unless changing dependencies intentionally. Do not commit `.cargo/config.toml`, `target/`, `dist/`, Python bytecode, private keys, VM state, or local host configuration.
- Preserve the Apache-2.0 license. Released binary changes need new versions and digests; preserve existing releases and session bindings.
- GitHub Actions CI is intentionally absent for now. Do not add workflows unless requested.
