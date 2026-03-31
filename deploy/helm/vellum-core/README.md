# VellumCore Helm Chart

Vendor-neutrales Referenz-Deployment für `prover`, `worker`, `verifier`, `native-prover` und `maintenance`.

## Features

- `framework-init` als Helm Hook Job (`pre-install`, `pre-upgrade`)
- optionale Worker-Autoskalierung mit KEDA (`ScaledObject`)
- Security-Baseline (`PodSecurityContext`, `SecurityContext`, `NetworkPolicy`)
- optionales `ServiceMonitor`-Template für Prometheus Operator

## Quick Start

```bash
helm upgrade --install vellum-core ./deploy/helm/vellum-core \
  --set externalDependencies.postgres.host=<postgres-host> \
  --set externalDependencies.redis.host=<redis-host> \
  --set externalDependencies.vault.addr=https://<vault-host>:8200 \
  --set externalDependencies.vault.token=<vault-token>
```

## Wichtige Values

- `frameworkInit.setupCircuitIds`: Circuit-IDs für Artefakt-Bootstrap
- `keda.enabled`: Worker Queue Autoscaling aktivieren/deaktivieren
- `externalDependencies.*`: Managed Postgres/Redis/Vault Endpunkte
- `env.securityProfile`: `strict` (default) oder `dev`

