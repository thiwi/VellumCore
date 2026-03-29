pub mod backend;
pub mod cli;
pub mod parsing;
pub mod service;
pub mod verification;

pub mod vellum_nativeprover {
    tonic::include_proto!("vellum.nativeprover");
}

use clap::Parser;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tonic::transport::Server;
use tracing::info;

use crate::cli::{Cli, GenerateBackend, WitnessBackend};
use crate::service::ProverService;
use crate::verification::CachedVerificationKey;
use crate::vellum_nativeprover::prover_server::ProverServer;

pub async fn run() -> Result<(), Box<dyn std::error::Error>> {
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
        verification_key_cache: Arc::new(RwLock::new(HashMap::<
            String,
            Arc<CachedVerificationKey>,
        >::new())),
    };

    Server::builder()
        .add_service(ProverServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
