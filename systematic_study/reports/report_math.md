# Vellum Core: A Mathematical Note

## Abstract

This paper describes the mathematical structure of Vellum Core. The emphasis is on the algebraic statements encoded by the circuits, the interpretation of public and private variables, the role of rank-1 constraint systems, and the meaning of Groth16 proofs in this setting. Operational architecture is treated only insofar as it is necessary to interpret the proving model [1]-[9].

Two circuits are of particular interest. `AMLCheck` is a minimal multiplicative example. `BatchCreditCheck(N)` is the substantive construction: it encodes a batch relation over balances, limits, and an active prefix, and reduces that relation to algebraic constraints over a finite field. The core mathematical features are finite-field arithmetic, arithmetized integer comparison, canonical zero-padding, and multiplicative aggregation of row-wise validity [1]-[3].

## 1. Algebraic setting

The circuits are expressed in Circom and therefore operate over a finite field `F_p`. Signals are field elements; circuit semantics are not given by ordinary control flow, but by polynomial equalities. In this model, proving a statement means exhibiting a witness that satisfies all circuit constraints [4]-[6].

Circom documentation presents the essential constraint form as

`A * B + C = 0`,

where `A`, `B`, and `C` are linear combinations of signals. This gives rise to a rank-1 constraint system (R1CS). In standard zk-SNARK constructions, the R1CS is further transformed into an algebraic object suitable for proof generation; historically, the quadratic arithmetic program (QAP) view is the canonical bridge between constraints and proof systems [5], [8], [9].

The central implication is direct: Vellum Core does not prove general-purpose program execution as such. It proves that a collection of quadratic algebraic relations holds for a given assignment of public and private variables.

## 2. Witness and public data

The proving relation separates public values from private values. In the batch circuit [1]:

- `limits[N]` are public;
- `active_count` is public;
- `balances[N]` are private;
- all intermediate helper signals are private witness components.

Accordingly, a proof should be read as an existence statement:

> There exist private balances and intermediate values such that, together with the public limits and the public active count, all constraints of the circuit are satisfied.

The zero-knowledge property ensures that the witness itself is not revealed, only the validity of the statement.

## 3. Finite-field arithmetic and the absence of native order

A crucial mathematical point is that finite fields do not carry the ordinary ordering of the integers. Operations such as addition and multiplication are native; predicates such as `x > y` are not.

As a result, any comparison appearing in the circuit must be arithmetized. In Vellum Core this is done through `circomlib` comparators such as `GreaterThan(n)` and `LessThan(n)` [3], [7].

This has three consequences.

1. A comparison is not primitive; it is implemented as a subcircuit.
2. Its intended meaning is integer comparison within a prescribed bit range.
3. Its correctness therefore depends on bounded-range assumptions for the underlying values.

In the analyzed implementation [1]:

- `active_count` is checked with 16-bit comparators;
- `balances[i]` and `limits[i]` are compared with 32-bit comparators.

The intended mathematical semantics is thus not a field order, but an embedding of bounded nonnegative integers into `F_p`, together with an arithmetically enforced comparison relation.

## 4. Minimal example: `AMLCheck`

The circuit `AMLCheck` expresses the single relation [2]

`aml_score = amount * risk_weight`.

This is already a complete arithmetic statement. It requires one nonlinear multiplication constraint. Compiling the circuit yields:

- 1 constraint
- 4 wires
- 2 private inputs
- 1 output

The proof statement is correspondingly simple:

> There exist private values `amount` and `risk_weight` whose product equals the output `aml_score`.

This circuit serves as a minimal example of how an application-level statement is reduced to an algebraic identity.

## 5. The batch circuit `BatchCreditCheck(N)`

The principal construction is `BatchCreditCheck(N)`. In the implementation analyzed here, the main circuit is instantiated as [1]

`component main {public [limits, active_count]} = BatchCreditCheck(250);`

The circuit accepts:

- public `limits[0], ..., limits[N-1]`,
- public `active_count`,
- private `balances[0], ..., balances[N-1]`,

and produces:

- `all_valid`,
- `active_count_out`.

The design can be understood as a proof system for an active prefix of a fixed-length batch.

### 5.1 Active prefix condition

The circuit first constrains the public counter:

- `active_count > 0`
- `active_count <= N`

This enforces a nonempty active prefix inside the fixed batch.

For each index `i`, the circuit computes an indicator

`chi_i = 1` if `i < active_count`, and `0` otherwise.

This partitions the batch into:

- an active prefix `0, ..., active_count - 1`,
- an inactive padded suffix `active_count, ..., N - 1`.

### 5.2 Row-wise comparison

For each row, the circuit computes a comparison flag

`g_i = 1` if `balances[i] > limits[i]`, and `0` otherwise.

This should be interpreted carefully. The statement is not a native field inequality; it is an arithmetized integer inequality implemented through `GreaterThan(32)`. The intended claim is therefore:

> For each active row, the 32-bit integer represented by `balances[i]` is greater than the 32-bit integer represented by `limits[i]`.

### 5.3 Gated row validity

The circuit defines

`decision_valid_i = g_i * chi_i + (1 - chi_i)`.

This single algebraic expression merges the active and inactive cases:

- if `chi_i = 1`, then `decision_valid_i = g_i`;
- if `chi_i = 0`, then `decision_valid_i = 1`.

Inactive rows are therefore neutralized; active rows must satisfy the comparison.

### 5.4 Canonical zero-padding

Two additional constraints are imposed for every row:

`balances[i] * (1 - chi_i) = 0`

`limits[i] * (1 - chi_i) = 0`

These relations are mathematically significant. When `chi_i = 0`, they force

- `balances[i] = 0`,
- `limits[i] = 0`.

The inactive suffix is therefore not merely ignored; it is constrained to a canonical zero representation. This eliminates ambiguity in the encoding of shorter batches inside a fixed-size circuit.

### 5.5 Multiplicative aggregation

Global validity is accumulated through a product chain:

`c_0 = 1`

`c_{i+1} = c_i * decision_valid_i`

`all_valid = c_N`

Provided the row flags are Boolean, multiplication acts as conjunction:

- if every factor is `1`, the final product is `1`;
- if any factor is `0`, the final product is `0`.

Thus

`all_valid = Π_{i=0}^{N-1} decision_valid_i`,

which is equivalent to the statement that all active rows satisfy the row-wise comparison relation.

## 6. The induced NP statement

The batch circuit can be read as an NP relation. Given public values

- `limits[0], ..., limits[N-1]`,
- `active_count`,

the witness consists of

- `balances[0], ..., balances[N-1]`,
- all auxiliary internal signals,

such that:

1. `1 <= active_count <= N`;
2. for every `i < active_count`, `balances[i] > limits[i]`;
3. for every `i >= active_count`, `balances[i] = 0` and `limits[i] = 0`;
4. `active_count_out = active_count`;
5. `all_valid` equals the conjunction of all active row checks.

When `all_valid = 1`, the proof certifies that all active rows satisfy the encoded predicate.

## 7. Comparator semantics

The comparator construction is the most delicate mathematical point in the batch circuit [3], [7].

In `circomlib`, `LessThan(n)` is implemented by constraining the bit decomposition of [3]

`in[0] + 2^n - in[1]`

through `Num2Bits(n + 1)`. `GreaterThan(n)` is then obtained by swapping the inputs. This realizes bounded integer comparison algebraically.

The consequence is that the circuit’s ordering claims are valid only under the intended bounded interpretation of the inputs. For Vellum Core, that means:

- `active_count` is interpreted as a bounded nonnegative integer;
- `balances` and `limits` are interpreted as 32-bit-compatible nonnegative integers.

Without these range assumptions, the informal statement “the circuit proves `balance > limit`” is mathematically incomplete.

## 8. From Circom to Groth16

The proving pipeline follows the standard algebraic route:

1. Circom specifies signals and constraints.
2. The compiler emits an R1CS.
3. The proving system derives proving and verification relations from that constraint system.
4. Groth16 produces a succinct proof for a witness and a set of public signals [4]-[6], [8], [9].

R1CS is useful because each constraint has the canonical form

`<a, w> * <b, w> - <c, w> = 0`,

where `w` is the witness vector and `<., .>` denotes the inner product. This representation is compact, algebraically regular, and well suited to pairing-based SNARK constructions.

Groth16 is used here because it provides [8]:

- constant-size proofs (three group elements),
- compact verification dominated by a constant number of pairings,
- mature support in the Circom/SnarkJS toolchain.

The usual caveat remains important: proof size is constant, but total verification work is not completely independent of the number of public inputs, because public signals contribute to the linear combination inside verification. This matters in Vellum Core because `limits[N]` are public.

## 9. Constraint counts

The following figures were obtained by compiling the circuits with `circom --r1cs` and inspecting the resulting R1CS with `snarkjs r1cs info` for the circuits defined in [1] and [2].

For `BatchCreditCheck(250)`:

- curve: `bn-128`
- 13,032 wires
- 13,532 constraints
- 250 private inputs
- 251 public inputs
- 2 outputs

For `AMLCheck`:

- 4 wires
- 1 constraint
- 2 private inputs
- 1 output

These counts illustrate two structural facts:

1. `AMLCheck` is essentially a single multiplicative identity.
2. `BatchCreditCheck(N)` scales approximately linearly in `N`, because each additional row introduces comparison logic, padding constraints, and aggregation structure.

## 10. Interpretation of the proof statement

A Groth16 proof in this setting certifies the existence of private balances and auxiliary values satisfying the encoded algebraic relation. It does not, by itself, certify:

- the provenance of the private data,
- the economic significance of the predicate,
- the completeness of the underlying business model,
- or the validity of interpretations outside the assumed bit ranges.

The cryptographic guarantee is therefore precise but limited:

> The proof establishes correctness relative to the modeled relation, not correctness of the model itself.

## 11. Conclusion

Mathematically, Vellum Core is a concrete instance of a zk-SNARK system built from:

- finite-field arithmetic,
- R1CS-style circuit compilation,
- arithmetized integer comparison,
- multiplicative aggregation of row validity,
- and Groth16 proof generation and verification.

Its central batch circuit expresses a well-defined witness relation over a fixed-size array with an active prefix and canonical zero-padding. The resulting proof states that the private witness satisfies the encoded inequalities and padding conditions relative to the public inputs, without revealing the witness itself.

## References

[1] [batch_credit_check.circom](/Users/thilowilts/Code/VellumCore/circuits/batch_credit_check/batch_credit_check.circom)

[2] [aml_check.circom](/Users/thilowilts/Code/VellumCore/circuits/aml_check/aml_check.circom)

[3] `circomlib` comparator implementation at `/opt/homebrew/lib/node_modules/circomlib/circuits/comparators.circom`

[4] Circom Documentation, [Signals](https://docs.circom.io/circom-language/signals/)

[5] Circom Documentation, [Constraint Generation](https://docs.circom.io/circom-language/constraint-generation/)

[6] Circom Documentation, [The main Component](https://docs.circom.io/circom-language/the-main-component/)

[7] iden3, [circomlib repository](https://github.com/iden3/circomlib)

[8] Jens Groth, [On the Size of Pairing-based Non-interactive Arguments](https://eprint.iacr.org/2016/260), IACR ePrint 2016/260

[9] Bryan Parno, Craig Gentry, Jon Howell, Mariana Raykova, [Pinocchio: Nearly Practical Verifiable Computation](https://eprint.iacr.org/2013/279), IACR ePrint 2013/279
