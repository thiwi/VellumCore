use std::path::PathBuf;

use tokio::process::Command;
use tonic::Status;

use crate::cli::WitnessBackend;

pub fn internal_error(err: std::io::Error) -> Status {
    Status::internal(err.to_string())
}

pub async fn run_command(bin: &str, args: &[&str]) -> Result<std::process::Output, Status> {
    let output = Command::new(bin)
        .args(args)
        .output()
        .await
        .map_err(|err| Status::internal(format!("failed to execute command: {}", err)))?;
    Ok(output)
}

pub fn stderr_text(output: &std::process::Output) -> String {
    String::from_utf8_lossy(&output.stderr).trim().to_string()
}

pub fn path_arg(path: &PathBuf) -> &str {
    path.to_str().expect("temporary path must be valid UTF-8")
}

pub async fn run_snarkjs_fullprove(
    snarkjs_bin: &str,
    input_path: &PathBuf,
    wasm_path: &str,
    zkey_path: &str,
    proof_path: &PathBuf,
    public_path: &PathBuf,
) -> Result<(), Status> {
    let output = run_command(
        snarkjs_bin,
        &[
            "groth16",
            "fullprove",
            path_arg(input_path),
            wasm_path,
            zkey_path,
            path_arg(proof_path),
            path_arg(public_path),
        ],
    )
    .await?;
    if output.status.success() {
        return Ok(());
    }
    Err(Status::internal(format!(
        "fullprove failed: {}",
        stderr_text(&output)
    )))
}

pub async fn generate_witness(
    witness_backend: WitnessBackend,
    snarkjs_bin: &str,
    witness_gen_bin: &str,
    wasm_path: &str,
    input_path: &PathBuf,
    witness_path: &PathBuf,
) -> Result<(), Status> {
    let output = match witness_backend {
        WitnessBackend::Snarkjs => {
            run_command(
                snarkjs_bin,
                &[
                    "wtns",
                    "calculate",
                    wasm_path,
                    path_arg(input_path),
                    path_arg(witness_path),
                ],
            )
            .await?
        }
        WitnessBackend::Binary => {
            run_command(
                witness_gen_bin,
                &[wasm_path, path_arg(input_path), path_arg(witness_path)],
            )
            .await?
        }
    };
    if output.status.success() {
        return Ok(());
    }

    let reason = stderr_text(&output);
    match witness_backend {
        WitnessBackend::Snarkjs => Err(Status::internal(format!(
            "wtns calculate failed: {}",
            reason
        ))),
        WitnessBackend::Binary => Err(Status::internal(format!(
            "witness generator failed: {}",
            reason
        ))),
    }
}

pub async fn run_rapidsnark_prove(
    rapidsnark_bin: &str,
    zkey_path: &str,
    witness_path: &PathBuf,
    proof_path: &PathBuf,
    public_path: &PathBuf,
) -> Result<(), Status> {
    let output = run_command(
        rapidsnark_bin,
        &[
            zkey_path,
            path_arg(witness_path),
            path_arg(proof_path),
            path_arg(public_path),
        ],
    )
    .await?;
    if output.status.success() {
        return Ok(());
    }
    Err(Status::internal(format!(
        "rapidsnark prove failed: {}",
        stderr_text(&output)
    )))
}
