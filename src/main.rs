use magicmtn_provider_firecracker::Firecracker;
use magicmtn_sdk::plugin::{Capabilities, SandboxOperation::*};
#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    magicmtn_provider_framework::run_sandbox(
        "firecracker",
        env!("CARGO_PKG_VERSION"),
        Capabilities::sandbox(vec![
            PrepareImage,
            Create,
            Status,
            Terminate,
            Exec,
            ExecBounded,
        ]),
        Firecracker,
    )
    .await
}
