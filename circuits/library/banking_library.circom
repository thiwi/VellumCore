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

// Enforces 0 < active_count <= N for batch-style policies.
template ActiveCountBounds(N) {
    signal input active_count;
    signal output valid;

    component gt = GreaterThan(16);
    component lt = LessThan(16);

    gt.in[0] <== active_count;
    gt.in[1] <== 0;

    lt.in[0] <== active_count;
    lt.in[1] <== N + 1;

    valid <== gt.out * lt.out;
    valid === 1;
}

// Produces 1 iff index < active_count.
template ActiveIndexFlag16() {
    signal input active_count;
    signal input index;
    signal output is_active;

    component gt = GreaterThan(16);
    gt.in[0] <== active_count;
    gt.in[1] <== index;
    is_active <== gt.out;
    is_active * (is_active - 1) === 0;
}

template PrimitiveLessThan32() {
    signal input lhs;
    signal input rhs;
    signal output out;

    component cmp = LessThan(32);
    cmp.in[0] <== lhs;
    cmp.in[1] <== rhs;
    out <== cmp.out;
}

template PrimitiveGreaterThan32() {
    signal input lhs;
    signal input rhs;
    signal output out;

    component cmp = GreaterThan(32);
    cmp.in[0] <== lhs;
    cmp.in[1] <== rhs;
    out <== cmp.out;
}

template PrimitiveLessEqThan32() {
    signal input lhs;
    signal input rhs;
    signal output out;

    component cmp = LessEqThan(32);
    cmp.in[0] <== lhs;
    cmp.in[1] <== rhs;
    out <== cmp.out;
}

template PrimitiveGreaterEqThan32() {
    signal input lhs;
    signal input rhs;
    signal output out;

    component cmp = GreaterEqThan(32);
    cmp.in[0] <== lhs;
    cmp.in[1] <== rhs;
    out <== cmp.out;
}

template PrimitiveEqual() {
    signal input lhs;
    signal input rhs;
    signal output out;

    component cmp = IsEqual();
    cmp.in[0] <== lhs;
    cmp.in[1] <== rhs;
    out <== cmp.out;
}

// Enforces deterministic zero rows for inactive batch entries.
template ZeroPaddingInvariant() {
    signal input value;
    signal input is_active;
    signal output valid;

    is_active * (is_active - 1) === 0;
    value * (1 - is_active) === 0;
    valid <== 1;
}
