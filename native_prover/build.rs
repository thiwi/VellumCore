fn main() {
    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .compile(&["../proto/vellum_prover.proto"], &["../proto"])
        .expect("failed to compile protobuf definitions");
}
