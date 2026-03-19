pragma circom 2.1.8;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";

// Proves min < value < max using 32-bit comparators.
template RangeProof32() {
    signal input value;
    signal input min;
    signal input max;
    signal output is_valid;

    component gt = GreaterThan(32);
    component lt = LessThan(32);

    gt.in[0] <== value;
    gt.in[1] <== min;

    lt.in[0] <== value;
    lt.in[1] <== max;

    is_valid <== gt.out * lt.out;
    is_valid === 1;
}

// Fixed-point helper for 2 decimal places. Example: 12.34 => 1234.
template FixedPointScale2() {
    signal input value_integer;
    signal output scaled_value;
    scaled_value <== value_integer * 100;
}

// Multiplication for 2-decimal fixed point values.
template FixedPointMul2() {
    signal input lhs_scaled;
    signal input rhs_scaled;
    signal output product_scaled;
    // Caller must treat this as fixed-point arithmetic in downstream checks.
    product_scaled <== lhs_scaled * rhs_scaled;
}

// Proves leaf inclusion in a Poseidon Merkle tree of fixed depth 10.
template MerkleInclusionPoseidonDepth10() {
    signal input leaf;
    signal input root;
    signal input pathElements[10];
    signal input pathIndices[10];
    signal output valid;

    signal hashes[11];
    signal left[10];
    signal right[10];
    component poseidons[10];

    hashes[0] <== leaf;

    for (var i = 0; i < 10; i++) {
        pathIndices[i] * (pathIndices[i] - 1) === 0;

        left[i] <== hashes[i] * (1 - pathIndices[i]) + pathElements[i] * pathIndices[i];
        right[i] <== hashes[i] * pathIndices[i] + pathElements[i] * (1 - pathIndices[i]);

        poseidons[i] = Poseidon(2);
        poseidons[i].inputs[0] <== left[i];
        poseidons[i].inputs[1] <== right[i];
        hashes[i + 1] <== poseidons[i].out;
    }

    hashes[10] === root;
    valid <== 1;
}

