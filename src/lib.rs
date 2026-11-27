//! Local Firecracker lifecycle. Host prerequisites are never installed automatically.
use anyhow::{Context, Result, ensure};
use magicmtn_sdk::{
    BoxFuture, ExecResult, ProviderSandbox, SandboxBackend, SandboxState, ScpDirection,
    image_registry::{Image, PreparedImage},
};
use serde_json::{Value, json};
use std::{path::Path, process::Stdio};
use tokio::{io::AsyncWriteExt, process::Command};
pub struct Firecracker;
async fn invoke(operation: Value) -> Result<Value> {
    ensure!(
        cfg!(target_os = "linux"),
        "Firecracker requires Linux with /dev/kvm"
    );
    let mut child = Command::new("python3")
        .args(["-c", include_str!("runtime.py")])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .context("Firecracker provider requires Python 3")?;
    child
        .stdin
        .take()
        .unwrap()
        .write_all(&serde_json::to_vec(&operation)?)
        .await?;
    let output = child.wait_with_output().await?;
    ensure!(
        output.status.success(),
        "Firecracker: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(serde_json::from_slice(&output.stdout)?)
}
impl SandboxBackend for Firecracker {
    fn prepare_image<'a>(
        &'a self,
        images: &'a std::collections::BTreeMap<String, Image>,
    ) -> BoxFuture<'a, PreparedImage> {
        Box::pin(async move {
            Ok(serde_json::from_value(
                invoke(json!({"op":"prepare_image", "images":images})).await?,
            )?)
        })
    }

    fn create<'a>(&'a self, template: &'a str) -> BoxFuture<'a, ProviderSandbox> {
        Box::pin(async move {
            Ok(serde_json::from_value(
                invoke(json!({"op":"create", "template":template})).await?,
            )?)
        })
    }
    fn status<'a>(&'a self, sandbox: &'a ProviderSandbox) -> BoxFuture<'a, SandboxState> {
        Box::pin(async move {
            Ok(serde_json::from_value(
                invoke(json!({"op":"status", "id":sandbox.provider_id})).await?,
            )?)
        })
    }
    fn terminate<'a>(&'a self, sandbox: &'a ProviderSandbox) -> BoxFuture<'a, ()> {
        Box::pin(async move {
            invoke(json!({"op":"terminate", "id":sandbox.provider_id})).await?;
            Ok(())
        })
    }
    fn exec<'a>(
        &'a self,
        sandbox: &'a ProviderSandbox,
        command: &'a str,
        args: &'a [String],
    ) -> BoxFuture<'a, String> {
        Box::pin(async move {
            let result = self
                .exec_bounded(sandbox, command, args, 30000, 16384)
                .await?;
            ensure!(
                !result.timed_out && result.exit_code == Some(0),
                "guest command failed: {}",
                result.stderr
            );
            Ok(result.stdout)
        })
    }
    fn exec_bounded<'a>(
        &'a self,
        sandbox: &'a ProviderSandbox,
        command: &'a str,
        args: &'a [String],
        timeout_ms: u64,
        max_output_bytes: usize,
    ) -> BoxFuture<'a, ExecResult> {
        Box::pin(async move {
            Ok(serde_json::from_value(invoke(json!({"op":"exec", "id":sandbox.provider_id, "command":command, "args":args, "timeout_ms":timeout_ms, "max_output_bytes":max_output_bytes})).await?)?)
        })
    }
    fn ssh<'a>(&'a self, _: &'a ProviderSandbox) -> BoxFuture<'a, ()> {
        Box::pin(async { anyhow::bail!("use bounded execution or the workspace terminal relay") })
    }
    fn scp<'a>(
        &'a self,
        _: &'a ProviderSandbox,
        _: &'a Path,
        _: &'a Path,
        _: ScpDirection,
    ) -> BoxFuture<'a, ()> {
        Box::pin(async { anyhow::bail!("use sandbox file tools") })
    }
}
