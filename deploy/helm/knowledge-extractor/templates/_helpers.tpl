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
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "knowledge-extractor.fullname" .) }}
{{- end }}
{{- end }}

{{/* The Secret the migration Job reads: the named one, or its own hook copy of the chart-made one. */}}
{{- define "knowledge-extractor.migrateSecretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-migrate-secrets" (include "knowledge-extractor.fullname" .) }}
{{- end }}
{{- end }}

{{/* The data of the ConfigMap: the same in the release's own copy and in the migration's hook copy. */}}
{{- define "knowledge-extractor.configData" -}}
{{- range $name, $value := .Values.config }}
{{ $name }}: {{ $value | toString | quote }}
{{- end }}
{{- end }}

{{/* The data of the chart-made Secret: the same in the release's own copy and in the migration's hook copy. */}}
{{- define "knowledge-extractor.secretData" -}}
{{- range $key := splitList "," (include "knowledge-extractor.secretKeys" .) }}
{{ $key }}: {{ get $.Values.secrets.values $key | toString | quote }}
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
{{- if not .Values.config.DJANGO_ALLOWED_HOSTS }}
{{- fail "config.DJANGO_ALLOWED_HOSTS is empty: set the host names the API answers to, comma separated (values-dev.yaml has an example)." }}
{{- end }}
{{- if and .Values.workloadIdentity.enabled (not .Values.workloadIdentity.clientId) }}
{{- fail "workloadIdentity.enabled is true but workloadIdentity.clientId is empty: set the client id of the user-assigned managed identity." }}
{{- end }}
{{- if and .Values.workloadIdentity.enabled (not .Values.serviceAccount.create) (not .Values.serviceAccount.name) }}
{{- fail "workloadIdentity.enabled needs serviceAccount.create=true, or serviceAccount.name naming an annotated ServiceAccount." }}
{{- end }}
{{- if not .Values.secrets.existingSecret }}
{{- $missing := list }}
{{- range $key := splitList "," (include "knowledge-extractor.secretKeys" .) }}
{{- if not (get $.Values.secrets.values $key) }}
{{- $missing = append $missing $key }}
{{- end }}
{{- end }}
{{- if $missing }}
{{- fail (printf "No secret source: set secrets.existingSecret to the name of a Secret that holds %s, or, for a first try in dev only, give secrets.values.<NAME> for each of: %s. Nothing secret belongs in a committed values file: use --set or --set-file." (include "knowledge-extractor.secretKeys" . | replace "," ", ") ($missing | join ", ")) }}
{{- end }}
{{- end }}
{{- end }}
