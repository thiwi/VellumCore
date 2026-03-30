"""SDK-first example: submit evidence, run policy, export attestation."""

from __future__ import annotations

import asyncio

from vellum_core.api import FrameworkClient, PolicyRunRequest


async def main() -> None:
    framework = FrameworkClient.from_env()
    result = await framework.policy_engine.run(
        PolicyRunRequest(
            policy_id="lending_risk_v1",
            evidence={"type": "inline", "payload": {"balances": [120], "limits": [100]}},
            context={"tenant": "acme-bank", "workflow": "onboarding"},
        )
    )
    bundle = await framework.attestation_service.export(result.attestation_id)

    print(
        {
            "run_id": result.run_id,
            "decision": result.decision,
            "attestation_id": result.attestation_id,
            "policy_version": bundle.policy_version,
            "proof_hash": bundle.proof_hash,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
