{{/* The chart name. */}}
{{- define "knowledge-extractor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* The release's name for resources: at most 63 characters (a DNS label). */}}
{{- define "knowledge-extractor.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "knowledge-extractor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Labels of every resource. */}}
{{- define "knowledge-extractor.labels" -}}
helm.sh/chart: {{ include "knowledge-extractor.chart" . }}
{{ include "knowledge-extractor.selectorLabels" . }}
app.kubernetes.io/version: {{ default .Chart.AppVersion .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "knowledge-extractor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "knowledge-extractor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* The ServiceAccount the api and the worker run as. */}}
{{- define "knowledge-extractor.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "knowledge-extractor.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "knowledge-extractor.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{/* The Secret the pods read: the named one, or the one this chart makes. */}}
{{- define "knowledge-extractor.secretName" -}}
{{- if .Values.keyVault.enabled }}
{{- default (printf "%s-secrets" (include "knowledge-extractor.fullname" .)) .Values.keyVault.secretName }}
{{- else if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "knowledge-extractor.fullname" .) }}
{{- end }}
{{- end }}

{{/* The Secret the migration Job reads: the named one, or its own hook copy of the chart-made one. */}}
{{- define "knowledge-extractor.migrateSecretName" -}}
{{- if .Values.keyVault.enabled }}
{{- include "knowledge-extractor.secretName" . }}
{{- else if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-migrate-secrets" (include "knowledge-extractor.fullname" .) }}
{{- end }}
{{- end }}

{{/* The host names the API answers to: config.DJANGO_ALLOWED_HOSTS when set by hand, else the Ingress host. */}}
{{- define "knowledge-extractor.allowedHosts" -}}
{{- if .Values.config.DJANGO_ALLOWED_HOSTS }}
{{- .Values.config.DJANGO_ALLOWED_HOSTS }}
{{- else if and .Values.ingress.enabled .Values.ingress.host }}
{{- .Values.ingress.host }}
{{- end }}
{{- end }}

{{/* The origins of the UI: config.CORS_ALLOWED_ORIGINS when set by hand, else the Ingress host over https (one origin for the UI and the API). */}}
{{- define "knowledge-extractor.corsOrigins" -}}
{{- if .Values.config.CORS_ALLOWED_ORIGINS }}
{{- .Values.config.CORS_ALLOWED_ORIGINS }}
{{- else if and .Values.ingress.enabled .Values.ingress.host }}
{{- printf "https://%s" .Values.ingress.host }}
{{- end }}
{{- end }}

{{/* The data of the ConfigMap: the same in the release's own copy and in the migration's hook copy. */}}
{{- define "knowledge-extractor.configData" -}}
{{- $config := deepCopy .Values.config }}
{{- $_ := set $config "DJANGO_ALLOWED_HOSTS" (include "knowledge-extractor.allowedHosts" .) }}
{{- $_ := set $config "CORS_ALLOWED_ORIGINS" (include "knowledge-extractor.corsOrigins" .) }}
{{- range $name, $value := $config }}
{{ $name }}: {{ $value | toString | quote }}
{{- end }}
{{- end }}

{{/* The data of the chart-made Secret: the same in the release's own copy and in the migration's hook copy. */}}
{{- define "knowledge-extractor.secretData" -}}
{{- range $key := splitList "," (include "knowledge-extractor.secretKeys" .) }}
{{- if not (include "knowledge-extractor.autoKey" (dict "root" $ "key" $key)) }}
{{ $key }}: {{ get $.Values.secrets.values $key | toString | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/* Secret keys needed by the settings: the variable names the application reads. */}}
{{- define "knowledge-extractor.secretKeys" -}}
{{- $keys := list "DJANGO_SECRET_KEY" "DATABASE_URL" "REDIS_URL" }}
{{- if and (eq (toString .Values.config.ASSISTANT_AGENT) "openai") (eq (toString .Values.config.LLM_PROVIDER) "openai") }}
{{- $keys = append $keys "OPENAI_API_KEY" }}
{{- end }}
{{- join "," $keys }}
{{- end }}

{{/*
Refuse to render when the settings or secrets are not usable. The messages
say what to set. Called once, from configmap.yaml (the migration's copies are rendered from the same values).
*/}}
{{- define "knowledge-extractor.validate" -}}
{{- if not (include "knowledge-extractor.allowedHosts" .) }}
{{- fail "config.DJANGO_ALLOWED_HOSTS is empty: set the host names the API answers to, comma separated, or enable the Ingress with ingress.host, from which it follows (values-dev.yaml has an example)." }}
{{- end }}
{{- if and .Values.ingress.enabled (not .Values.ingress.host) }}
{{- fail "ingress.enabled is true but ingress.host is empty: set the one host name of the UI and the API." }}
{{- end }}
{{- if and .Values.workloadIdentity.enabled (not .Values.workloadIdentity.clientId) }}
{{- fail "workloadIdentity.enabled is true but workloadIdentity.clientId is empty: set the client id of the user-assigned managed identity." }}
{{- end }}
{{- if and .Values.workloadIdentity.enabled (not .Values.serviceAccount.create) (not .Values.serviceAccount.name) }}
{{- fail "workloadIdentity.enabled needs serviceAccount.create=true, or serviceAccount.name naming an annotated ServiceAccount." }}
{{- end }}
{{- if .Values.keyVault.enabled }}
{{- if not .Values.keyVault.keyvaultName }}
{{- fail "keyVault.enabled is true but keyVault.keyvaultName is empty: set the name of the Azure Key Vault." }}
{{- end }}
{{- if not .Values.workloadIdentity.enabled }}
{{- fail "keyVault.enabled needs workloadIdentity.enabled=true: the driver signs in with the workload identity of the chart's ServiceAccount." }}
{{- end }}
{{- if not (include "knowledge-extractor.keyVaultClientId" .) }}
{{- fail "keyVault.enabled but no client id: set keyVault.clientId or workloadIdentity.clientId." }}
{{- end }}
{{- if not (include "knowledge-extractor.keyVaultTenantId" .) }}
{{- fail "keyVault.enabled but no tenant id: set keyVault.tenantId or workloadIdentity.tenantId." }}
{{- end }}
{{- range $key := splitList "," (include "knowledge-extractor.secretKeys" .) }}
{{- if not (get $.Values.keyVault.objects $key) }}
{{- fail (printf "keyVault.objects.%s is empty: set the name of that secret in the vault." $key) }}
{{- end }}
{{- end }}
{{- else if not .Values.secrets.existingSecret }}
{{- $missing := list }}
{{- range $key := splitList "," (include "knowledge-extractor.secretKeys" .) }}
{{- if and (not (get $.Values.secrets.values $key)) (not (include "knowledge-extractor.autoKey" (dict "root" $ "key" $key))) }}
{{- $missing = append $missing $key }}
{{- end }}
{{- end }}
{{- if $missing }}
{{- fail (printf "No secret source: set secrets.existingSecret to the name of a Secret that holds %s, or, for a first try in dev only, give secrets.values.<NAME> for each of: %s. Nothing secret belongs in a committed values file: use --set or --set-file." (include "knowledge-extractor.secretKeys" . | replace "," ", ") ($missing | join ", ")) }}
{{- end }}
{{- end }}
{{- end }}

{{/* Key Vault: the identity the driver signs in with. */}}
{{- define "knowledge-extractor.keyVaultClientId" -}}
{{- default .Values.workloadIdentity.clientId .Values.keyVault.clientId }}
{{- end }}
{{- define "knowledge-extractor.keyVaultTenantId" -}}
{{- default .Values.workloadIdentity.tenantId .Values.keyVault.tenantId }}
{{- end }}

{{/*
Secret keys the chart fills itself from the dev PostgreSQL or Redis: non-empty
("true") when enabled, not set by hand in secrets.values and not coming from
Key Vault. Called with (dict "root" $ "key" "DATABASE_URL").
*/}}
{{- define "knowledge-extractor.autoKey" -}}
{{- $v := .root.Values }}
{{- if and (not $v.keyVault.enabled) (not (get $v.secrets.values .key)) }}
{{- if and (eq .key "DATABASE_URL") $v.postgres.enabled }}true{{ end }}
{{- if and (eq .key "REDIS_URL") $v.redis.enabled }}true{{ end }}
{{- end }}
{{- end }}

{{/*
When the migration Job runs. Before the first install nothing of the release
exists, neither the dev PostgreSQL nor the ServiceAccount of the Key Vault
identity, so with either of them the hooks run after the install's resources
are created (the Job waits for the database).
*/}}
{{- define "knowledge-extractor.migrateHook" -}}
{{- if or .Values.postgres.enabled .Values.keyVault.enabled }}post-install,pre-upgrade{{ else }}pre-install,pre-upgrade{{ end }}
{{- end }}

{{/* Dev dependencies: names. */}}
{{- define "knowledge-extractor.postgresName" -}}
{{- printf "%s-postgres" (include "knowledge-extractor.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "knowledge-extractor.redisName" -}}
{{- printf "%s-redis" (include "knowledge-extractor.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
A password for a dev dependency: the one in values, else the one already in the
cluster (kept across upgrades), else a new random one (the first install).
Called with (dict "root" $ "name" <secret name> "key" <key> "value" <from values>).
*/}}
{{- define "knowledge-extractor.devPassword" -}}
{{- if .value }}
{{- .value }}
{{- else }}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace .name }}
{{- if and $existing $existing.data (get $existing.data .key) }}
{{- get $existing.data .key | b64dec }}
{{- else }}
{{- randAlphaNum 32 }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Environment of a pod that reads DATABASE_URL or REDIS_URL from the dev
PostgreSQL or Redis: the password from the dependency's Secret, then the URL
built with it (an explicit env entry wins over envFrom). Empty when off.
*/}}
{{- define "knowledge-extractor.dependencyEnv" -}}
{{- if include "knowledge-extractor.autoKey" (dict "root" . "key" "DATABASE_URL") }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "knowledge-extractor.postgresName" . }}
      key: POSTGRES_PASSWORD
- name: DATABASE_URL
  value: {{ printf "postgres://%s:$(POSTGRES_PASSWORD)@%s:5432/%s" .Values.postgres.user (include "knowledge-extractor.postgresName" .) .Values.postgres.database | quote }}
{{- end }}
{{- if include "knowledge-extractor.autoKey" (dict "root" . "key" "REDIS_URL") }}
- name: REDIS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "knowledge-extractor.redisName" . }}
      key: REDIS_PASSWORD
- name: REDIS_URL
  value: {{ printf "redis://:$(REDIS_PASSWORD)@%s:6379/0" (include "knowledge-extractor.redisName" .) | quote }}
{{- end }}
{{- end }}

{{/* The Key Vault volume and its mount: the driver syncs the Secret only while a pod mounts it. */}}
{{- define "knowledge-extractor.keyVaultVolume" -}}
- name: secrets-store
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: {{ include "knowledge-extractor.fullname" . }}
{{- end }}
{{- define "knowledge-extractor.keyVaultMount" -}}
- name: secrets-store
  mountPath: /mnt/secrets-store
  readOnly: true
{{- end }}
