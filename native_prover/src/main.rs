#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    vellum_native_prover::run().await
}
