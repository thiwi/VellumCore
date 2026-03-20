# Vellum Core: Practical Use in Financial and Crypto Environments

## Abstract

This paper examines Vellum Core from the perspective of financial institutions, market infrastructure providers, custodians, exchanges, counterparties, and audit functions. The focus is practical rather than mathematical. The central question is not how the proving system is constructed internally, but what type of operating model it enables, where its measurable benefits arise, and how it compares with more established approaches to verification and disclosure [1]-[10].

Vellum Core combines batch-oriented zero-knowledge proving with a reference operating stack for proof generation, verification, artifact management, audit logging, and monitoring. In practical terms, it allows one party to retain detailed underlying records while another party verifies a succinct claim about those records. This creates a different verification model from ordinary document exchange, row-level recomputation, or conventional attestation processes [1]-[8].

## 1. Executive overview

Vellum Core can be understood as an infrastructure layer for proving structured statements over sensitive datasets. A statement is encoded as a circuit, a proof is generated over a batch of records, and a verifier checks the resulting proof using public inputs and a verification key. The process is embedded in an operational flow that includes proof job management, artifact control, audit logging, and service observability [1]-[8].

For finance and crypto use cases, the main significance of this model lies in the separation between data possession and claim verification. One party may hold account-level or position-level data internally, while another party checks whether a defined condition has been satisfied without receiving the underlying rows in full. This pattern is relevant whenever confidentiality, external review, and repeatable verification are required simultaneously.

The measured performance profile of Vellum Core follows the usual structure of succinct proof systems. Proof generation is computationally expensive, while verification is comparatively stable and compact. The resulting benefit therefore appears primarily on the verifier side rather than as a universal reduction in total end-to-end computation [8]-[10].

## 2. Functional model

At a high level, Vellum Core follows a four-stage model.

1. A claim about a batch of records is formalized as a circuit.
2. A proving party generates a proof that the batch satisfies the claim.
3. A verifying party checks the proof against public inputs.
4. The operational lifecycle of the proof is recorded through signed audit events.

This structure is materially different from a conventional reporting workflow. In a conventional process, a counterparty, auditor, or regulator often receives underlying files, extracts rows, and reruns checks independently. In a proof-based process, the verifying party checks a cryptographic object that certifies satisfaction of the encoded relation [2]-[7].

The distinction is not merely computational. It affects disclosure boundaries, operational repetition, and the structure of the audit process itself.

## 3. Why this model matters in financial settings

Financial processes frequently require one institution to justify a claim to another institution without granting unrestricted access to its internal records. Examples include threshold checks, batch-level eligibility criteria, internal rule compliance, and periodic review processes involving third parties. In each of these cases, the organization holding the data and the organization verifying the claim may have different incentives, different confidentiality constraints, and different tolerances for operational burden.

Vellum Core addresses this tension by replacing full-data inspection with proof-based verification of a formalized statement. The underlying data remains under the control of the proving party. The verifying party receives the public inputs and the proof, not the complete private dataset [2], [4]-[8].

From a process perspective, this changes three things at once.

First, it changes the disclosure model. Instead of sharing full row-level evidence for each review cycle, the proving side discloses only what is needed for the proof relation and the verification procedure.

Second, it changes the repetition model. Once a verifying process is standardized around proof checking, the same workflow can be repeated across batches and review cycles without rebuilding the checking logic from scratch.

Third, it changes the audit model. A proof can become part of a broader signed and timestamped evidence chain rather than an isolated analytical output.

## 4. Benefits in practical use

The benefits of a system such as Vellum Core should be stated in operational rather than promotional terms. They arise from the structure of the workflow and from the measured asymmetry between proving and verification.

### 4.1 Data minimization

The most direct benefit is controlled disclosure. A proving institution can keep row-level balances, positions, or account attributes private while still demonstrating that a circuit-defined condition has been met. For regulated or commercially sensitive environments, this can reduce the amount of raw data circulated between internal teams, external auditors, counterparties, and technical operators [2], [4]-[8].

This does not eliminate the need for data governance, but it changes the boundary at which disclosure occurs. Instead of disclosing raw evidence by default, an institution can disclose a proof and the public values needed to interpret that proof.

### 4.2 Repeatable external verification

A second benefit is the standardization of repeated checks. Many financial controls are not one-off exercises; they recur across reporting periods, counterparties, or internal review cycles. Once the proving relation and the verification procedure are fixed, the verifying side can apply the same logic repeatedly without reconstructing the full analytical pipeline each time.

This can be relevant where external review is frequent or where the same kind of statement must be validated across many batches of records.

### 4.3 Lower verifier-side workload

The measured benchmark data indicates that verification remains comparatively stable as batch size increases, whereas native recomputation grows with the size of the dataset under review. This means that, in repeated review settings, the checking burden shifts away from the verifier and toward the proving side [9], [10].

That is a specific and important benefit. The system does not remove computational cost; it reallocates it. For use cases where the data holder is willing to absorb heavier computation in exchange for lighter external verification, the tradeoff may be structurally favorable.

### 4.4 Clearer separation of institutional roles

Traditional verification processes often blur the line between data custody, business interpretation, and technical validation. A proof-based system separates these roles more cleanly. One party owns the raw data. Another party verifies the claim. A third party, such as an auditor or regulator, may review the process and the audit trail without directly reproducing every internal calculation.

This separation can simplify responsibility boundaries, especially in multi-party environments.

### 4.5 Structured audit evidence

Vellum Core surrounds proof generation and verification with signed audit events and operational status tracking. In practical environments, this is significant because cryptographic proof alone is rarely enough. Institutions also need to know which artifacts were used, which service generated the proof, whether the process completed successfully, and how the resulting object fits into a larger control chain [3]-[7].

Accordingly, one benefit of the framework lies not only in the proof object itself, but in the fact that the proof can be embedded in a broader evidence trail.

## 5. Reference operating model

The reference deployment implements four visible service roles [3]-[7]:

- a prover service that accepts proof requests;
- a worker that resolves inputs and generates proofs asynchronously;
- a verifier service that validates proofs and exposes related endpoints;
- a web console for health checks, diagnostics, proof status, and verification flows.

This operating model is supported by:

- PostgreSQL for proof jobs and audit records;
- Redis for queueing and replay protection;
- Vault Transit for signing operations;
- SnarkJS and precompiled circuit artifacts for proof generation and verification.

The framework boundary is separate from the service boundary. The reusable layer is organized around `vellum_core.api`, `vellum_core.spi`, and `vellum_core.runtime`, while the service processes provide one deployable realization of that layer. This distinction is relevant for institutions that may wish to preserve the proving and verification logic while adapting storage, signing, job orchestration, or input adapters to internal standards [1]-[8].

## 6. Proof flow in operational terms

The batch flow can be summarized as follows.

1. A client submits either a batch directly or a source reference.
2. The request is normalized into a proof job.
3. The worker resolves the inputs, loads the required artifacts, and generates a Groth16 proof.
4. The resulting proof and metadata are stored.
5. The verifier checks the proof against the verification key and public signals.
6. The audit layer records the sequence of events associated with the proof lifecycle.

From a practical standpoint, the relevance of this structure lies in its repeatability. The same process can be used across recurring batches, and the same verification logic can be reused by multiple external or internal checking parties. This is one of the central differences between a proof-based workflow and an ad hoc data-room or spreadsheet process.

## 7. Observed performance profile

The benchmark dataset analyzed here compares native recomputation with proof-based verification for varying batch sizes at `ops=10000` [9], [10].

| N | Native Audit Time | Proving Time | Verification Time | Auditor Speedup | Realtime Speedup | Status |
|---|-------------------|--------------|-------------------|-----------------|------------------|--------|
| 100 | 166.24 ms | 1059.93 ms | 215.01 ms | 0.77x | 0.13x | native_faster |
| 250 | 405.91 ms | 1570.00 ms | 216.55 ms | 1.87x | 0.22x | vellum_advantage |
| 500 | 822.54 ms | 1592.39 ms | 207.68 ms | 3.96x | 0.44x | vellum_advantage |
| 750 | 1199.07 ms | 2583.67 ms | 214.13 ms | 5.60x | 0.42x | vellum_advantage |
| 1000 | 1621.91 ms | 2568.86 ms | 201.30 ms | 8.06x | 0.58x | vellum_advantage |

Several points follow from these measurements.

Verification time remains comparatively stable across the measured range. Native audit time increases with the number of rows under review. Proof generation remains materially more expensive than verification. The system therefore exhibits the characteristic asymmetry of succinct proof systems: expensive proving, relatively cheap checking [8]-[10].

For practical deployment, this implies that the case for adoption depends less on absolute wall-clock latency than on where verification effort sits in the operating model. If the main cost problem lies with repeated checking by auditors, counterparties, or external reviewers, the measured profile can be attractive. If the main cost problem lies with proof generation itself, the tradeoff is less favorable.

## 8. Comparison with existing approaches

The value of Vellum Core becomes clearer when it is compared with other established verification models [2]-[10].

### 8.1 Direct data sharing and native recomputation

The most common baseline is direct disclosure: the data holder sends files, tables, or exports to the verifying party, and the verifying party reruns the relevant checks. This approach has three properties.

First, it is easy to understand and operationally familiar. Second, it exposes the verifier to the underlying dataset. Third, the verifier-side workload grows with the size of the reviewed data.

Compared with this model, Vellum Core changes the disclosure boundary and reduces repeated verifier-side recomputation. The tradeoff is that the proving side must maintain circuit artifacts, proof infrastructure, and a more specialized technical stack [2]-[9].

### 8.2 Traditional attestations and signed reports

Another common approach is the signed report or attestation model. In that setting, one party signs a statement or report, and another party relies on the attestation together with organizational trust, contractual obligations, or audit procedures.

This approach is often simpler to operate, but it is weaker as a technical verification mechanism. A signed statement authenticates who made the claim; it does not cryptographically prove that the underlying dataset satisfies the claim.

Compared with a signed-report model, Vellum Core introduces a stronger technical guarantee about the encoded relation. The price of that stronger guarantee is higher implementation complexity and higher proving cost [3]-[8].

### 8.3 Sampling-based audit processes

In some financial settings, audit evidence is gathered through sampling, manual inspection, and procedural controls rather than exhaustive technical verification. Sampling can be appropriate where complete recomputation is too expensive or unnecessary, but it does not offer deterministic coverage of every included row.

By contrast, a batch proof certifies the full encoded relation over the entire batch included in the witness. This is a substantial difference. The proof system replaces selective inspection of rows with exhaustive verification of the encoded predicate, while preserving privacy for the private inputs [2], [8].

### 8.4 Merkle-tree commitments and proof-of-reserves style systems

In the crypto sector, Merkle-tree commitments are a common mechanism for proving inclusion or summarizing balances. These systems are useful for demonstrating that a particular account or record is included in a committed set, or that a set structure is consistent with a published root.

However, Merkle proofs and proof-of-reserves style constructions answer a narrower class of questions. They are well suited to inclusion, membership, or aggregate commitment integrity, but less suited to proving arbitrary batch predicates such as rule-based comparisons, threshold relations, or structured constraints across a full set of rows.

Compared with such systems, Vellum Core is more expressive at the predicate level, since the circuit can encode application-specific relations. The tradeoff is again complexity: Merkle systems are often simpler, narrower, and cheaper to operate [2], [8].

### 8.5 Generic zk-SNARK development stacks

It is also useful to distinguish Vellum Core from generic proving toolchains. Circom, SnarkJS, and related libraries provide the cryptographic and circuit-level substrate, but they do not by themselves define an institutional workflow for proof jobs, audit trails, service health, or operational diagnostics.

Vellum Core adds a structured application and operations layer around the proving toolchain. In that sense, it should be compared not only with cryptographic libraries, but with end-to-end verification processes [1]-[8].

## 9. Implications for different stakeholders

### 9.1 Financial institutions

For banks, lenders, administrators, and custodians, the framework is most relevant when a claim must be validated repeatedly by another party, but the underlying dataset should remain private. The main practical implications are:

- reduced routine disclosure of raw row-level data;
- reusable verification logic across review cycles;
- stronger separation between data custody and claim checking;
- a structured audit trail around proof production and verification.

These properties are particularly relevant in recurring control environments, outsourced review arrangements, and cases where confidential client or position data should not be distributed more broadly than necessary.

### 9.2 Auditors, counterparties, and regulators

For external reviewers, the main effect is a change in verification method. Instead of receiving complete underlying files and rerunning the full check, the reviewer verifies a compact proof against public inputs. This does not eliminate the need for model review or procedural oversight, but it can reduce repeated computational and operational burden once the proving relation is accepted.

### 9.3 Crypto market participants

For exchanges, custodians, protocol operators, and crypto service providers, the framework is relevant in situations where internal state must be rendered externally verifiable without disclosing all account-level or wallet-level detail. This can be useful in partner reporting, selected transparency disclosures, and recurring internal control processes with external stakeholders.

## 10. Practical limitations

Several limitations remain important in any realistic assessment.

### 10.1 Proving cost

Proof generation is the dominant cost in the measured runs. This is not an implementation accident; it follows the standard economics of succinct proof systems. Institutions considering deployment must decide whether verifier-side savings justify prover-side computation and operational complexity [8]-[10].

### 10.2 Fixed circuit arity

The batch circuit uses a fixed-size structure with an active count and zero-padding. This is a standard circuit design choice, but it requires explicit management of circuit size, artifact generation, and batch encoding.

### 10.3 Toolchain dependence

The implemented path is tied to Circom, SnarkJS, and Groth16. Interfaces exist for extension, but the measured and supported flow is specific to that proving stack [1]-[8].

### 10.4 Scope of guarantees

The proof establishes correctness relative to the encoded relation. It does not independently establish the provenance, completeness, valuation, or business interpretation of the underlying data. Governance, model validation, and data controls remain separate obligations [2], [8].

### 10.5 Integration scope

The reusable layer is organized as a Python framework. Institutions seeking a language-neutral boundary, a fully standardized external protocol, or a cross-organizational interoperability layer would require additional abstraction beyond the current implementation [1], [8].

## 11. Conclusion

Vellum Core is best interpreted as a proof-oriented verification framework for batch statements over sensitive data. Its practical significance lies in enabling a different verification structure: one party can retain private records, another party can verify a formally defined claim, and the operational lifecycle can be recorded through audit and service controls.

The main benefits are most visible where verifier-side effort, repeated review, and controlled disclosure are central concerns. The main costs are most visible in proof generation, circuit management, and operational complexity. Relative to direct data sharing, attestations, sampling-based review, and narrower cryptographic commitment systems, Vellum Core offers a different point in the tradeoff space: stronger formal verification of application-specific batch predicates, with higher implementation and proving overhead [2]-[10].

## References

[1] [README.md](/Users/thilowilts/Code/VellumCore/README.md)

[2] [batch_credit_check.circom](/Users/thilowilts/Code/VellumCore/circuits/batch_credit_check/batch_credit_check.circom)

[3] [prover_service.py](/Users/thilowilts/Code/VellumCore/prover_service.py)

[4] [worker.py](/Users/thilowilts/Code/VellumCore/worker.py)

[5] [verifier_service.py](/Users/thilowilts/Code/VellumCore/verifier_service.py)

[6] [dashboard_service.py](/Users/thilowilts/Code/VellumCore/dashboard_service.py)

[7] [docs/REFERENCE_SERVICES.md](/Users/thilowilts/Code/VellumCore/docs/REFERENCE_SERVICES.md)

[8] [docs/SDK.md](/Users/thilowilts/Code/VellumCore/docs/SDK.md)

[9] [study_results/results_batch_100.json](/Users/thilowilts/Code/VellumCore/systematic_study/study_results/results_batch_100.json), [study_results/results_batch_250.json](/Users/thilowilts/Code/VellumCore/systematic_study/study_results/results_batch_250.json), [study_results/results_batch_500.json](/Users/thilowilts/Code/VellumCore/systematic_study/study_results/results_batch_500.json), [study_results/results_batch_750.json](/Users/thilowilts/Code/VellumCore/systematic_study/study_results/results_batch_750.json)

[10] [study_results/results_batch_1000.json](/Users/thilowilts/Code/VellumCore/systematic_study/study_results/results_batch_1000.json)
