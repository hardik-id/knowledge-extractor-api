#!/bin/sh
# make chart-check: lint, render and validate the chart (docs/deploy.md).
# Uses a local helm and kubeconform when there are any, their container images when not.
set -eu

HELM_IMAGE=alpine/helm:3.21.4
KUBECONFORM_IMAGE=ghcr.io/yannh/kubeconform:v0.7.0
# The Kubernetes version of the dev cluster, for the schemas.
KUBERNETES_VERSION=1.32.0

root=$(cd "$(dirname "$0")/../.." && pwd)
chart=deploy/helm/knowledge-extractor

run_helm() {
  if command -v helm >/dev/null 2>&1; then
    (cd "$root" && command helm "$@")
  else
    docker run --rm -v "$root":/work -w /work "$HELM_IMAGE" "$@"
  fi
}

run_kubeconform() {
  if command -v kubeconform >/dev/null 2>&1; then
    command kubeconform "$@"
  else
    docker run --rm -i "$KUBECONFORM_IMAGE" "$@"
  fi
}

# A Secret that exists only in the check: the chart needs a source and makes none here.
source_args="--set secrets.existingSecret=chart-check"

for values in "" "-f $chart/values-dev.yaml"; do
  label=${values:-defaults}
  echo "== lint: $label"
  # shellcheck disable=SC2086
  run_helm lint $chart $values $source_args --set config.DJANGO_ALLOWED_HOSTS=chart-check.example
  echo "== template and kubeconform (strict): $label"
  # shellcheck disable=SC2086
  run_helm template check $chart $values $source_args --set config.DJANGO_ALLOWED_HOSTS=chart-check.example \
    | run_kubeconform -strict -summary -kubernetes-version "$KUBERNETES_VERSION" -
done

# Key Vault on: the SecretProviderClass is a custom resource of the Secrets Store CSI driver. kubeconform
# has no schema for it without the driver's CRD (it is not in the Kubernetes schemas), so that kind is
# skipped; every other resource, with the volume the Key Vault adds to the pods, is checked strictly.
echo "== template and kubeconform (strict, SecretProviderClass skipped): values-dev.yaml with keyVault.enabled=true"
run_helm lint $chart -f $chart/values-dev.yaml --set keyVault.enabled=true
run_helm template check $chart -f $chart/values-dev.yaml --set keyVault.enabled=true \
  | run_kubeconform -strict -summary -skip SecretProviderClass -kubernetes-version "$KUBERNETES_VERSION" -

echo "== Key Vault on and the chart-made Secret off"
output=$(run_helm template check $chart -f $chart/values-dev.yaml --set keyVault.enabled=true)
case $output in
  *"kind: SecretProviderClass"*) ;;
  *) echo "FAIL: no SecretProviderClass with keyVault.enabled"; exit 1 ;;
esac
# secret.yaml renders nothing then: helm says so by failing to find output for it.
if run_helm template check $chart -f $chart/values-dev.yaml --set keyVault.enabled=true --show-only templates/secret.yaml >/dev/null 2>&1; then
  echo "FAIL: the chart made a Secret with keyVault.enabled"
  exit 1
fi
echo "ok"

echo "== a secret made by the chart, from values"
run_helm template check $chart -f $chart/values-dev.yaml \
  --set secrets.values.DJANGO_SECRET_KEY=x --set secrets.values.DATABASE_URL=x --set secrets.values.REDIS_URL=x \
  | run_kubeconform -strict -summary -kubernetes-version "$KUBERNETES_VERSION" -

echo "== no secret source: the chart must refuse"
if output=$(run_helm template check $chart -f $chart/values-dev.yaml 2>&1); then
  echo "FAIL: the chart rendered without a secret source"
  exit 1
fi
case $output in
  *"No secret source"*) echo "ok: $output" ;;
  *) echo "FAIL: unexpected message: $output"; exit 1 ;;
esac

echo "== no host names: the chart must refuse"
if output=$(run_helm template check $chart $source_args 2>&1); then
  echo "FAIL: the chart rendered without allowed hosts"
  exit 1
fi
case $output in
  *"DJANGO_ALLOWED_HOSTS is empty"*) echo "ok: $output" ;;
  *) echo "FAIL: unexpected message: $output"; exit 1 ;;
esac

echo "chart-check passed"
