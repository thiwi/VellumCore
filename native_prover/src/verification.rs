use std::panic::AssertUnwindSafe;

use ark_bn254::Bn254;
use ark_groth16::{prepare_verifying_key, Groth16, PreparedVerifyingKey};
use serde_json::Value;
use tonic::Status;

use crate::parsing::{parse_proof, parse_public_inputs, parse_verification_key};

#[derive(Debug)]
pub struct CachedVerificationKey {
    pub prepared_candidates: Vec<PreparedVkCandidate>,
}

#[derive(Debug)]
pub struct PreparedVkCandidate {
    pub swap_coeffs: bool,
    pub prepared: PreparedVerifyingKey<Bn254>,
}

pub fn build_cached_verification_key(
    verification_key_json: &str,
) -> Result<CachedVerificationKey, Status> {
    let vk_value: Value = serde_json::from_str(verification_key_json)
        .map_err(|err| Status::invalid_argument(format!("verification_key JSON is invalid: {}", err)))?;

    let mut prepared_candidates = Vec::new();
    for swap_coeffs in [false, true] {
        if let Ok(vk) = parse_verification_key(&vk_value, swap_coeffs) {
            let prepared_attempt = std::panic::catch_unwind(AssertUnwindSafe(|| {
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

    Ok(CachedVerificationKey { prepared_candidates })
}

pub fn verify_native_proof(
    cached_key: &CachedVerificationKey,
    proof_json: &str,
    public_signals_json: &str,
) -> Result<bool, Status> {
    let proof_value: Value = serde_json::from_str(proof_json)
        .map_err(|err| Status::invalid_argument(format!("proof JSON is invalid: {}", err)))?;
    let public_signals_value: Value = serde_json::from_str(public_signals_json)
        .map_err(|err| Status::invalid_argument(format!("public_signals JSON is invalid: {}", err)))?;
    let public_inputs = parse_public_inputs(&public_signals_value)?;

    let mut parsed_any = false;
    for candidate in &cached_key.prepared_candidates {
        let proof = match parse_proof(&proof_value, candidate.swap_coeffs) {
            Ok(value) => value,
            Err(_) => continue,
        };
        parsed_any = true;
        let verification_attempt = std::panic::catch_unwind(AssertUnwindSafe(|| {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verify_native_proof_rejects_invalid_verification_key_json() {
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
