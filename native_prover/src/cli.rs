use clap::Parser;

#[derive(Parser, Debug)]
#[command(name = "vellum-native-prover")]
pub struct Cli {
    #[arg(long, env = "NATIVE_PROVER_ADDR", default_value = "0.0.0.0:50051")]
    pub addr: String,
    #[arg(long, env = "SNARKJS_BIN", default_value = "snarkjs")]
    pub snarkjs_bin: String,
    #[arg(long, env = "NATIVE_GENERATE_BACKEND", default_value = "snarkjs")]
    pub native_generate_backend: String,
    #[arg(long, env = "RAPIDSNARK_BIN", default_value = "rapidsnark")]
    pub rapidsnark_bin: String,
    #[arg(long, env = "NATIVE_WITNESS_BACKEND", default_value = "snarkjs")]
    pub native_witness_backend: String,
    #[arg(long, env = "WITNESS_GEN_BIN", default_value = "witnesscalc")]
    pub witness_gen_bin: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GenerateBackend {
    Snarkjs,
    Rapidsnark,
}

impl GenerateBackend {
    pub fn parse(raw: &str) -> Result<Self, String> {
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
pub enum WitnessBackend {
    Snarkjs,
    Binary,
}

impl WitnessBackend {
    pub fn parse(raw: &str) -> Result<Self, String> {
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

#[cfg(test)]
mod tests {
    use super::{GenerateBackend, WitnessBackend};

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
}
