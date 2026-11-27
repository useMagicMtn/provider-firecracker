//! Discovery must advertise preparation without inspecting a host or starting Python.
use std::{
    io::Write,
    process::{Command, Stdio},
};

#[test]
fn preparation_is_discoverable_without_host_configuration() {
    let mut child = Command::new(env!("CARGO_BIN_EXE_magicmtn-provider-firecracker"))
        .env_clear()
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(b"{\"id\":1,\"protocol_version\":1,\"provider\":\"firecracker\",\"operation\":{\"name\":\"describe\"}}\n").unwrap();
    let result = child.wait_with_output().unwrap();
    assert!(result.status.success());
    let response: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(response["id"], 1);
    let capabilities = &response["outcome"]["ok"]["value"]["capabilities"]["sandbox_operations"];
    for operation in [
        "prepare_image",
        "create",
        "status",
        "terminate",
        "exec_bounded",
    ] {
        assert!(
            capabilities
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value == operation)
        );
    }
}
