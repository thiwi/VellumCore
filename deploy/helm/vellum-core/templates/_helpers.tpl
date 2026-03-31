{{- define "vellum-core.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "vellum-core.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "vellum-core.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "vellum-core.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ default (include "vellum-core.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
{{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{- define "vellum-core.commonEnv" -}}
- name: POLICY_PACKS_DIR
  value: /app/policy_packs
- name: CIRCUITS_DIR
  value: /app/circuits
- name: SHARED_ASSETS_DIR
  value: /shared_assets
- name: PROOF_OUTPUT_DIR
  value: /shared_assets/proofs
- name: SNARKJS_BIN
  value: snarkjs
- name: LOG_LEVEL
  value: {{ .Values.env.logLevel | quote }}
- name: DATABASE_URL
  value: {{ printf "postgresql+asyncpg://%s:%s@%s:%v/%s" .Values.externalDependencies.postgres.user .Values.externalDependencies.postgres.password .Values.externalDependencies.postgres.host .Values.externalDependencies.postgres.port .Values.externalDependencies.postgres.db | quote }}
- name: CELERY_BROKER_URL
  value: {{ printf "redis://%s:%v/%v" .Values.externalDependencies.redis.host 6379 .Values.externalDependencies.redis.brokerDb | quote }}
- name: CELERY_QUEUE
  value: {{ .Values.keda.queueName | quote }}
- name: REDIS_URL
  value: {{ printf "redis://%s:%v/%v" .Values.externalDependencies.redis.host 6379 .Values.externalDependencies.redis.nonceDb | quote }}
- name: VAULT_ADDR
  value: {{ .Values.externalDependencies.vault.addr | quote }}
- name: VAULT_TOKEN
  value: {{ .Values.externalDependencies.vault.token | quote }}
- name: VELLUM_JWT_KEY
  value: {{ .Values.externalDependencies.vault.jwtKey | quote }}
- name: VELLUM_AUDIT_KEY
  value: {{ .Values.externalDependencies.vault.auditKey | quote }}
- name: VELLUM_BANK_KEY
  value: {{ .Values.externalDependencies.vault.bankKey | quote }}
- name: VELLUM_DATA_KEY
  value: {{ .Values.externalDependencies.vault.dataKey | quote }}
- name: BANK_KEY_ID
  value: {{ .Values.env.bankKeyId | quote }}
- name: BANK_KEY_MAPPING_JSON
  value: {{ .Values.env.bankKeyMappingJson | quote }}
- name: SECURITY_PROFILE
  value: {{ .Values.env.securityProfile | quote }}
- name: JWT_ISSUER
  value: {{ .Values.env.jwtIssuer | quote }}
- name: JWT_AUDIENCE
  value: {{ .Values.env.jwtAudience | quote }}
- name: NONCE_WINDOW_SECONDS
  value: {{ .Values.env.nonceWindowSeconds | quote }}
- name: JWT_MAX_TTL_SECONDS
  value: {{ .Values.env.jwtMaxTtlSeconds | quote }}
- name: JWT_LEEWAY_SECONDS
  value: {{ .Values.env.jwtLeewaySeconds | quote }}
- name: METRICS_REQUIRE_AUTH
  value: {{ .Values.env.metricsRequireAuth | quote }}
- name: SUBMIT_RATE_LIMIT_PER_MINUTE
  value: {{ .Values.env.submitRateLimitPerMinute | quote }}
- name: MAX_SUBMIT_BODY_BYTES
  value: {{ .Values.env.maxSubmitBodyBytes | quote }}
- name: CELERY_TASK_SOFT_TIME_LIMIT_SECONDS
  value: {{ .Values.env.celerySoftTimeLimitSeconds | quote }}
- name: CELERY_TASK_TIME_LIMIT_SECONDS
  value: {{ .Values.env.celeryTimeLimitSeconds | quote }}
- name: CELERY_WORKER_MAX_TASKS_PER_CHILD
  value: {{ .Values.env.celeryWorkerMaxTasksPerChild | quote }}
- name: PROOF_JOB_MAX_ATTEMPTS
  value: {{ .Values.env.proofJobMaxAttempts | quote }}
- name: PROVER_MAX_PARALLEL_PROOFS
  value: {{ .Values.env.maxParallelProofs | quote }}
- name: VAULT_PUBLIC_KEY_CACHE_TTL_SECONDS
  value: {{ .Values.env.vaultPublicKeyCacheTtlSeconds | quote }}
- name: NATIVE_VERIFY_BASELINE_SECONDS
  value: {{ .Values.env.nativeVerifyBaselineSeconds | quote }}
- name: PROOF_PROVIDER_MODE
  value: {{ .Values.env.proofProviderMode | quote }}
- name: GRPC_PROVER_ENDPOINT
  value: {{ printf "%s:%v" (printf "%s-native-prover" (include "vellum-core.fullname" .)) .Values.service.nativeProver.port | quote }}
- name: GRPC_PROVER_TIMEOUT_SECONDS
  value: {{ .Values.env.grpcProverTimeoutSeconds | quote }}
- name: PROOF_SHADOW_MODE
  value: "false"
- name: PROOF_SHADOW_PROVIDER_MODE
  value: grpc
- name: JOB_RUNTIME_RETENTION_DAYS
  value: {{ .Values.env.jobRuntimeRetentionDays | quote }}
- name: FILE_ARCHIVE_AFTER_DAYS
  value: {{ .Values.env.fileArchiveAfterDays | quote }}
- name: MAINTENANCE_INTERVAL_SECONDS
  value: {{ .Values.env.maintenanceIntervalSeconds | quote }}
- name: MAINTENANCE_CYCLE_FILE_SCAN_LIMIT
  value: {{ .Values.env.maintenanceCycleFileScanLimit | quote }}
{{- end -}}
