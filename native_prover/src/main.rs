use ark_bn254::{Bn254, Fq, Fq2, Fr, G1Affine, G2Affine};
use ark_groth16::{prepare_verifying_key, Groth16, PreparedVerifyingKey, Proof, VerifyingKey};
use clap::Parser;
use serde_json::Value;
use std::collections::HashMap;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::fs;
use tokio::process::Command;
use tokio::sync::RwLock;
use tonic::{transport::Server, Request, Response, Status};
use tracing::info;

pub mod vellum_nativeprover {
    tonic::include_proto!("vellum.nativeprover");
}

use vellum_nativeprover::prover_server::{Prover, ProverServer};
use vellum_nativeprover::{
    GenerateProofRequest, GenerateProofResponse, VerifyProofRequest, VerifyProofResponse,
};

#[derive(Parser, Debug)]
#[command(name = "vellum-native-prover")]
struct Cli {
    #[arg(long, env = "NATIVE_PROVER_ADDR", default_value = "0.0.0.0:50051")]
    addr: String,
    #[arg(long, env = "SNARKJS_BIN", default_value = "snarkjs")]
    snarkjs_bin: String,
    #[arg(long, env = "NATIVE_GENERATE_BACKEND", default_value = "snarkjs")]
    native_generate_backend: String,
    #[arg(long, env = "RAPIDSNARK_BIN", default_value = "rapidsnark")]
    rapidsnark_bin: String,
    #[arg(long, env = "NATIVE_WITNESS_BACKEND", default_value = "snarkjs")]
    native_witness_backend: String,
    #[arg(long, env = "WITNESS_GEN_BIN", default_value = "witnesscalc")]
    witness_gen_bin: String,
}

#[derive(Clone, Debug)]
struct ProverService {
    snarkjs_bin: String,
    rapidsnark_bin: String,
    witness_gen_bin: String,
    generate_backend: GenerateBackend,
    witness_backend: WitnessBackend,
    verification_key_cache: Arc<RwLock<HashMap<String, Arc<CachedVerificationKey>>>>,
}

#[derive(Debug)]
struct CachedVerificationKey {
    prepared_candidates: Vec<PreparedVkCandidate>,
}

#[derive(Debug)]
struct PreparedVkCandidate {
    swap_coeffs: bool,
    prepared: PreparedVerifyingKey<Bn254>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GenerateBackend {
    Snarkjs,
    Rapidsnark,
}

impl GenerateBackend {
    fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_lowercase().as_str() {
            "snarkjs" => Ok(Self::Snarkjs),
            "rapidsnark" => Ok(Self::Rapidsnark),
            other => Err(format!(
                "unsupported NATIVE_GENERATE_BACKEND value: {} (expected snarkjs|rapidsnark)",
                other
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum WitnessBackend {
    Snarkjs,
    Binary,
}

impl WitnessBackend {
    fn parse(raw: &str) -> Result<Self, String> {
        match raw.trim().to_lowercase().as_str() {
            "snarkjs" => Ok(Self::Snarkjs),
            "binary" => Ok(Self::Binary),
            other => Err(format!(
                "unsupported NATIVE_WITNESS_BACKEND value: {} (expected snarkjs|binary)",
                other
            )),
        }
    }
}

#[tonic::async_trait]
impl Prover for ProverService {
    async fn generate_proof(
        &self,
        request: Request<GenerateProofRequest>,
    ) -> Result<Response<GenerateProofResponse>, Status> {
        let req = request.into_inner();
        ensure_json(&req.private_input_json, "private_input_json")?;

        let tmp = TempDir::new().map_err(internal_error)?;
        let input_path = tmp.path().join("input.json");
        let proof_path = tmp.path().join("proof.json");
        let public_path = tmp.path().join("public.json");

        fs::write(&input_path, req.private_input_json)
            .await
            .map_err(internal_error)?;

        match self.generate_backend {
            GenerateBackend::Snarkjs => {
                let output = run_command(
                    &self.snarkjs_bin,
                    &[
                        "groth16",
                        "fullprove",
                        path_arg(&input_path),
                        req.wasm_path.as_str(),
                        req.zkey_path.as_str(),
                        path_arg(&proof_path),
                        path_arg(&public_path),
                    ],
                )
                .await?;
                if !output.status.success() {
                    return Err(Status::internal(format!(
                        "fullprove failed: {}",
                        stderr_text(&output)
                    )));
                }
            }
            GenerateBackend::Rapidsnark => {
                let witness_path = tmp.path().join("witness.wtns");
                self.generate_witness(req.wasm_path.as_str(), &input_path, &witness_path)
                    .await?;

                let prove_output = run_command(
                    &self.rapidsnark_bin,
                    &[
                        req.zkey_path.as_str(),
                        path_arg(&witness_path),
                        path_arg(&proof_path),
                        path_arg(&public_path),
                    ],
                )
                .await?;
                if !prove_output.status.success() {
                    return Err(Status::internal(format!(
                        "rapidsnark prove failed: {}",
                        stderr_text(&prove_output)
                    )));
                }
            }
        }

        let proof_json = fs::read_to_string(&proof_path)
            .await
            .map_err(internal_error)?;
        let public_signals_json = fs::read_to_string(&public_path)
            .await
            .map_err(internal_error)?;
        ensure_json(&proof_json, "proof_json")?;
        ensure_json(&public_signals_json, "public_signals_json")?;

        Ok(Response::new(GenerateProofResponse {
            proof_json,
            public_signals_json,
        }))
    }

    async fn verify_proof(
        &self,
        request: Request<VerifyProofRequest>,
    ) -> Result<Response<VerifyProofResponse>, Status> {
        let req = request.into_inner();
        ensure_json(&req.proof_json, "proof_json")?;
        ensure_json(&req.public_signals_json, "public_signals_json")?;
        let cached_key = self
            .get_or_load_verification_key(req.verification_key_path.as_str())
            .await?;
        let valid = verify_native_proof(
            cached_key.as_ref(),
            req.proof_json.as_str(),
            req.public_signals_json.as_str(),
        )?;
        Ok(Response::new(VerifyProofResponse { valid }))
    }
}

impl ProverService {
    async fn get_or_load_verification_key(
        &self,
        verification_key_path: &str,
    ) -> Result<Arc<CachedVerificationKey>, Status> {
        {
            let cache = self.verification_key_cache.read().await;
            if let Some(cached) = cache.get(verification_key_path) {
                return Ok(Arc::clone(cached));
            }
        }

        let verification_key_raw = fs::read_to_string(verification_key_path)
            .await
            .map_err(internal_error)?;
        let parsed = build_cached_verification_key(verification_key_raw.as_str())?;

        let mut cache = self.verification_key_cache.write().await;
        let entry = cache
            .entry(verification_key_path.to_string())
            .or_insert_with(|| Arc::new(parsed));
        Ok(Arc::clone(entry))
    }

    async fn generate_witness(
        &self,
        wasm_path: &str,
        input_path: &PathBuf,
        witness_path: &PathBuf,
    ) -> Result<(), Status> {
        let output = match self.witness_backend {
            WitnessBackend::Snarkjs => {
                run_command(
                    &self.snarkjs_bin,
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
                    &self.witness_gen_bin,
                    &[wasm_path, path_arg(input_path), path_arg(witness_path)],
                )
                .await?
            }
        };
        if output.status.success() {
            return Ok(());
        }
        let reason = stderr_text(&output);
        match self.witness_backend {
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
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_target(false)
        .compact()
        .init();

    let cli = Cli::parse();
    let generate_backend = GenerateBackend::parse(cli.native_generate_backend.as_str())
        .map_err(|reason| std::io::Error::new(std::io::ErrorKind::InvalidInput, reason))?;
    let witness_backend = WitnessBackend::parse(cli.native_witness_backend.as_str())
        .map_err(|reason| std::io::Error::new(std::io::ErrorKind::InvalidInput, reason))?;
    let addr = cli.addr.parse()?;
    info!(addr = %cli.addr, "native_prover_startup");

    let service = ProverService {
        snarkjs_bin: cli.snarkjs_bin,
        rapidsnark_bin: cli.rapidsnark_bin,
        witness_gen_bin: cli.witness_gen_bin,
        generate_backend,
        witness_backend,
        verification_key_cache: Arc::new(RwLock::new(HashMap::new())),
    };

    Server::builder()
        .add_service(ProverServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}

fn build_cached_verification_key(
    verification_key_json: &str,
) -> Result<CachedVerificationKey, Status> {
    let vk_value: Value = serde_json::from_str(verification_key_json).map_err(|err| {
        Status::invalid_argument(format!("verification_key JSON is invalid: {}", err))
    })?;

    let mut prepared_candidates = Vec::new();
    for swap_coeffs in [false, true] {
        if let Ok(vk) = parse_verification_key(&vk_value, swap_coeffs) {
            let prepared_attempt = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                prepare_verifying_key(&vk)
            }));
            if let Ok(prepared) = prepared_attempt {
                prepared_candidates.push(PreparedVkCandidate {
                    swap_coeffs,
                    prepared,
                });
            }
        }
    }
    if prepared_candidates.is_empty() {
        return Err(Status::internal(
            "unable to parse verification_key into BN254 Groth16 structures",
        ));
    }
    Ok(CachedVerificationKey {
        prepared_candidates,
    })
}

fn verify_native_proof(
    cached_key: &CachedVerificationKey,
    proof_json: &str,
    public_signals_json: &str,
) -> Result<bool, Status> {
    let proof_value: Value = serde_json::from_str(proof_json)
        .map_err(|err| Status::invalid_argument(format!("proof JSON is invalid: {}", err)))?;
    let public_signals_value: Value = serde_json::from_str(public_signals_json).map_err(|err| {
        Status::invalid_argument(format!("public_signals JSON is invalid: {}", err))
    })?;
    let public_inputs = parse_public_inputs(&public_signals_value)?;

    let mut parsed_any = false;
    for candidate in &cached_key.prepared_candidates {
        let proof = match parse_proof(&proof_value, candidate.swap_coeffs) {
            Ok(value) => value,
            Err(_) => continue,
        };
        parsed_any = true;
        let verification_attempt = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            Groth16::<Bn254>::verify_proof(&candidate.prepared, &proof, &public_inputs)
        }));
        match verification_attempt {
            Ok(Ok(true)) => return Ok(true),
            Ok(Ok(false)) => continue,
            Ok(Err(_)) => continue,
            Err(_) => continue,
        }
    }

    if parsed_any {
        return Ok(false);
    }
    Err(Status::internal(
        "unable to parse proof/verification_key into BN254 Groth16 structures",
    ))
}

fn parse_verification_key(value: &Value, swap_coeffs: bool) -> Result<VerifyingKey<Bn254>, Status> {
    let alpha = parse_g1(get_field(value, "vk_alpha_1")?, "vk_alpha_1")?;
    let beta = parse_g2(get_field(value, "vk_beta_2")?, "vk_beta_2", swap_coeffs)?;
    let gamma = parse_g2(get_field(value, "vk_gamma_2")?, "vk_gamma_2", swap_coeffs)?;
    let delta = parse_g2(get_field(value, "vk_delta_2")?, "vk_delta_2", swap_coeffs)?;

    let gamma_abc_raw = value
        .get("IC")
        .or_else(|| value.get("ic"))
        .ok_or_else(|| Status::invalid_argument("verification key missing IC"))?;
    let gamma_abc_arr = as_array(gamma_abc_raw, "IC")?;
    let mut gamma_abc_g1 = Vec::with_capacity(gamma_abc_arr.len());
    for (index, point) in gamma_abc_arr.iter().enumerate() {
        gamma_abc_g1.push(parse_g1(point, format!("IC[{}]", index).as_str())?);
    }

    Ok(VerifyingKey {
        alpha_g1: alpha,
        beta_g2: beta,
        gamma_g2: gamma,
        delta_g2: delta,
        gamma_abc_g1,
    })
}

fn parse_proof(value: &Value, swap_coeffs: bool) -> Result<Proof<Bn254>, Status> {
    let a = parse_g1(get_field(value, "pi_a")?, "pi_a")?;
    let b = parse_g2(get_field(value, "pi_b")?, "pi_b", swap_coeffs)?;
    let c = parse_g1(get_field(value, "pi_c")?, "pi_c")?;
    Ok(Proof { a, b, c })
}

fn parse_public_inputs(value: &Value) -> Result<Vec<Fr>, Status> {
    let arr = as_array(value, "public_signals")?;
    let mut inputs = Vec::with_capacity(arr.len());
    for (index, entry) in arr.iter().enumerate() {
        inputs.push(parse_fr(
            entry,
            format!("public_signals[{}]", index).as_str(),
        )?);
    }
    Ok(inputs)
}

fn parse_g1(value: &Value, field_name: &str) -> Result<G1Affine, Status> {
    let arr = as_array(value, field_name)?;
    if arr.len() < 2 {
        return Err(Status::invalid_argument(format!(
            "{} must contain at least two coordinates",
            field_name
        )));
    }
    let x = parse_fq(&arr[0], format!("{}[0]", field_name).as_str())?;
    let y = parse_fq(&arr[1], format!("{}[1]", field_name).as_str())?;
    Ok(G1Affine::new_unchecked(x, y))
}

fn parse_g2(value: &Value, field_name: &str, swap_coeffs: bool) -> Result<G2Affine, Status> {
    let outer = as_array(value, field_name)?;
    if outer.len() < 2 {
        return Err(Status::invalid_argument(format!(
            "{} must contain x/y coordinates",
            field_name
        )));
    }

    let x_arr = as_array(&outer[0], format!("{}[0]", field_name).as_str())?;
    let y_arr = as_array(&outer[1], format!("{}[1]", field_name).as_str())?;
    if x_arr.len() < 2 || y_arr.len() < 2 {
        return Err(Status::invalid_argument(format!(
            "{} coordinates must contain two Fq elements",
            field_name
        )));
    }

    let x0 = parse_fq(&x_arr[0], format!("{}[0][0]", field_name).as_str())?;
    let x1 = parse_fq(&x_arr[1], format!("{}[0][1]", field_name).as_str())?;
    let y0 = parse_fq(&y_arr[0], format!("{}[1][0]", field_name).as_str())?;
    let y1 = parse_fq(&y_arr[1], format!("{}[1][1]", field_name).as_str())?;

    let x = if swap_coeffs {
        Fq2::new(x1, x0)
    } else {
        Fq2::new(x0, x1)
    };
    let y = if swap_coeffs {
        Fq2::new(y1, y0)
    } else {
        Fq2::new(y0, y1)
    };

    Ok(G2Affine::new_unchecked(x, y))
}

fn parse_fq(value: &Value, field_name: &str) -> Result<Fq, Status> {
    let raw = as_decimal_string(value, field_name)?;
    Fq::from_str(raw.as_str())
        .map_err(|_| Status::invalid_argument(format!("{} is not a valid Fq element", field_name)))
}

fn parse_fr(value: &Value, field_name: &str) -> Result<Fr, Status> {
    let raw = as_decimal_string(value, field_name)?;
    Fr::from_str(raw.as_str())
        .map_err(|_| Status::invalid_argument(format!("{} is not a valid Fr element", field_name)))
}

fn as_decimal_string<'a>(value: &'a Value, field_name: &str) -> Result<String, Status> {
    match value {
        Value::String(s) => Ok(s.clone()),
        Value::Number(n) => Ok(n.to_string()),
        _ => Err(Status::invalid_argument(format!(
            "{} must be a decimal string/number",
            field_name
        ))),
    }
}

fn get_field<'a>(value: &'a Value, field_name: &str) -> Result<&'a Value, Status> {
    value
        .get(field_name)
        .ok_or_else(|| Status::invalid_argument(format!("missing field: {}", field_name)))
}

fn as_array<'a>(value: &'a Value, field_name: &str) -> Result<&'a Vec<Value>, Status> {
    value
        .as_array()
        .ok_or_else(|| Status::invalid_argument(format!("{} must be an array", field_name)))
}

fn ensure_json(raw: &str, field_name: &str) -> Result<(), Status> {
    let _: Value = serde_json::from_str(raw).map_err(|err| {
        Status::invalid_argument(format!("{} is not valid JSON: {}", field_name, err))
    })?;
    Ok(())
}

fn internal_error(err: std::io::Error) -> Status {
    Status::internal(err.to_string())
}

async fn run_command(bin: &str, args: &[&str]) -> Result<std::process::Output, Status> {
    let output = Command::new(bin)
        .args(args)
        .output()
        .await
        .map_err(|err| Status::internal(format!("failed to execute command: {}", err)))?;
    Ok(output)
}

fn stderr_text(output: &std::process::Output) -> String {
    String::from_utf8_lossy(&output.stderr).trim().to_string()
}

fn path_arg(path: &PathBuf) -> &str {
    path.to_str().expect("temporary path must be valid UTF-8")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parse_generate_backend_accepts_supported_values() {
        assert_eq!(
            GenerateBackend::parse("snarkjs").expect("snarkjs should parse"),
            GenerateBackend::Snarkjs
        );
        assert_eq!(
            GenerateBackend::parse("RAPIDSNARK").expect("rapidsnark should parse"),
            GenerateBackend::Rapidsnark
        );
    }

    #[test]
    fn parse_generate_backend_rejects_unknown_values() {
        let err = GenerateBackend::parse("unknown").expect_err("unknown backend must fail");
        assert!(err.contains("unsupported NATIVE_GENERATE_BACKEND value"));
    }

    #[test]
    fn parse_witness_backend_accepts_supported_values() {
        assert_eq!(
            WitnessBackend::parse("snarkjs").expect("snarkjs witness should parse"),
            WitnessBackend::Snarkjs
        );
        assert_eq!(
            WitnessBackend::parse("BINARY").expect("binary witness should parse"),
            WitnessBackend::Binary
        );
    }

    #[test]
    fn parse_witness_backend_rejects_unknown_values() {
        let err = WitnessBackend::parse("unknown").expect_err("unknown witness backend must fail");
        assert!(err.contains("unsupported NATIVE_WITNESS_BACKEND value"));
    }

    #[test]
    fn parse_verification_key_accepts_ic_lowercase() {
        let vk = json!({
            "vk_alpha_1": ["0", "0", "1"],
            "vk_beta_2": [["0", "0"], ["0", "0"], ["1", "0"]],
            "vk_gamma_2": [["0", "0"], ["0", "0"], ["1", "0"]],
            "vk_delta_2": [["0", "0"], ["0", "0"], ["1", "0"]],
            "ic": [["0", "0", "1"]]
        });
        let parsed = parse_verification_key(&vk, false).expect("vk should parse");
        assert_eq!(parsed.gamma_abc_g1.len(), 1);
    }

    #[test]
    fn parse_public_inputs_rejects_non_array() {
        let err = parse_public_inputs(&json!({"bad": true}))
            .expect_err("non-array public signals must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn verify_native_proof_rejects_invalid_json() {
        let err = build_cached_verification_key("{bad").expect_err("invalid vk json must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn verify_native_proof_rejects_unusable_verification_key() {
        let err = build_cached_verification_key("{}").expect_err("vk without fields must fail");
        assert_eq!(err.code(), tonic::Code::Internal);
    }

    #[test]
    fn verify_native_proof_rejects_invalid_proof_json() {
        let cached = CachedVerificationKey {
            prepared_candidates: Vec::new(),
        };
        let err =
            verify_native_proof(&cached, "{bad", "[]").expect_err("invalid proof JSON must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }

    #[test]
    fn verify_native_proof_rejects_invalid_public_signals_json() {
        let cached = CachedVerificationKey {
            prepared_candidates: Vec::new(),
        };
        let err = verify_native_proof(&cached, "{}", "{bad")
            .expect_err("invalid public_signals JSON must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }
}
