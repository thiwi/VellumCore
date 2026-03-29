use ark_bn254::{Fq, Fq2, Fr, G1Affine, G2Affine};
use serde_json::Value;
use std::str::FromStr;
use tonic::Status;

pub fn ensure_json(raw: &str, field_name: &str) -> Result<(), Status> {
    let _: Value = serde_json::from_str(raw)
        .map_err(|err| Status::invalid_argument(format!("{} is not valid JSON: {}", field_name, err)))?;
    Ok(())
}

pub fn parse_verification_key(value: &Value, swap_coeffs: bool) -> Result<ark_groth16::VerifyingKey<ark_bn254::Bn254>, Status> {
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

    Ok(ark_groth16::VerifyingKey {
        alpha_g1: alpha,
        beta_g2: beta,
        gamma_g2: gamma,
        delta_g2: delta,
        gamma_abc_g1,
    })
}

pub fn parse_proof(value: &Value, swap_coeffs: bool) -> Result<ark_groth16::Proof<ark_bn254::Bn254>, Status> {
    let a = parse_g1(get_field(value, "pi_a")?, "pi_a")?;
    let b = parse_g2(get_field(value, "pi_b")?, "pi_b", swap_coeffs)?;
    let c = parse_g1(get_field(value, "pi_c")?, "pi_c")?;
    Ok(ark_groth16::Proof { a, b, c })
}

pub fn parse_public_inputs(value: &Value) -> Result<Vec<Fr>, Status> {
    let arr = as_array(value, "public_signals")?;
    let mut inputs = Vec::with_capacity(arr.len());
    for (index, entry) in arr.iter().enumerate() {
        inputs.push(parse_fr(entry, format!("public_signals[{}]", index).as_str())?);
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

    let x = if swap_coeffs { Fq2::new(x1, x0) } else { Fq2::new(x0, x1) };
    let y = if swap_coeffs { Fq2::new(y1, y0) } else { Fq2::new(y0, y1) };

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

fn as_decimal_string(value: &Value, field_name: &str) -> Result<String, Status> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

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
    fn ensure_json_rejects_invalid_json() {
        let err = ensure_json("{bad", "proof_json").expect_err("invalid JSON must fail");
        assert_eq!(err.code(), tonic::Code::InvalidArgument);
    }
}
