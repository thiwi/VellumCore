use std::collections::HashMap;
use std::sync::Arc;

use tempfile::TempDir;
use tokio::fs;
use tokio::sync::RwLock;
use tonic::{Request, Response, Status};

use crate::backend::{
    generate_witness, internal_error, run_rapidsnark_prove, run_snarkjs_fullprove,
    run_snarkjs_verify,
};
use crate::cli::{GenerateBackend, WitnessBackend};
use crate::parsing::ensure_json;
use crate::verification::{
    build_cached_verification_key, verify_native_proof, CachedVerificationKey,
};
use crate::vellum_nativeprover::prover_server::Prover;
use crate::vellum_nativeprover::{
    GenerateProofRequest, GenerateProofResponse, VerifyProofRequest, VerifyProofResponse,
};

#[derive(Clone, Debug)]
pub struct ProverService {
    pub snarkjs_bin: String,
    pub rapidsnark_bin: String,
    pub witness_gen_bin: String,
    pub generate_backend: GenerateBackend,
    pub witness_backend: WitnessBackend,
    pub verification_key_cache: Arc<RwLock<HashMap<String, Arc<CachedVerificationKey>>>>,
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
                run_snarkjs_fullprove(
                    &self.snarkjs_bin,
                    &input_path,
                    req.wasm_path.as_str(),
                    req.zkey_path.as_str(),
                    &proof_path,
                    &public_path,
                )
                .await?;
            }
            GenerateBackend::Rapidsnark => {
                let witness_path = tmp.path().join("witness.wtns");
                generate_witness(
                    self.witness_backend,
                    &self.snarkjs_bin,
                    &self.witness_gen_bin,
                    req.wasm_path.as_str(),
                    &input_path,
                    &witness_path,
                )
                .await?;

                run_rapidsnark_prove(
                    &self.rapidsnark_bin,
                    req.zkey_path.as_str(),
                    &witness_path,
                    &proof_path,
                    &public_path,
                )
                .await?;
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

        let native_valid = self
            .get_or_load_verification_key(req.verification_key_path.as_str())
            .await
            .and_then(|cached_key| {
                verify_native_proof(
                    cached_key.as_ref(),
                    req.proof_json.as_str(),
                    req.public_signals_json.as_str(),
                )
            })
            .unwrap_or(false);
        if native_valid {
            return Ok(Response::new(VerifyProofResponse { valid: true }));
        }

        let tmp = TempDir::new().map_err(internal_error)?;
        let proof_path = tmp.path().join("proof.json");
        let public_path = tmp.path().join("public.json");
        fs::write(&proof_path, req.proof_json)
            .await
            .map_err(internal_error)?;
        fs::write(&public_path, req.public_signals_json)
            .await
            .map_err(internal_error)?;

        let valid = run_snarkjs_verify(
            &self.snarkjs_bin,
            req.verification_key_path.as_str(),
            &public_path,
            &proof_path,
        )
        .await?;
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
}
